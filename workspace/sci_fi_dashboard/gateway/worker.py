import asyncio
import contextlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime

from sci_fi_dashboard.observability import get_child_logger
from sci_fi_dashboard.observability.context import _run_id_ctx, set_run_id

from .queue import MessageTask, TaskQueue
from .sender import (
    WhatsAppSender,  # kept for backwards-compat constructor param; Phase 4 removes it
)

logger = logging.getLogger(__name__)
_log = get_child_logger("gateway.worker")

# ChannelRegistry imported lazily to avoid circular imports at module load time


def _split_long_message(text: str, chunk_size: int = 4000) -> list[str]:
    """Split a long message at natural break points for any channel."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        for sep in ["\n\n", "\n", " "]:
            bp = text.rfind(sep, 0, chunk_size)
            if bp != -1:
                break
        else:
            bp = chunk_size
        chunks.append(text[:bp])
        text = text[bp:].lstrip()
    return chunks


class MessageWorker:
    """
    Background worker pulling from the task queue.
    Dispatches outbound messages via ChannelRegistry (CHAN-07) — no channel-specific branching.
    """

    def __init__(
        self,
        queue: TaskQueue,
        process_fn: Callable[..., Awaitable[str]],  # (msg, chat_id[, mcp_context]) → str
        num_workers: int = 2,
        sender: WhatsAppSender | None = None,  # deprecated; kept for compat
        channel_registry=None,  # ChannelRegistry — preferred dispatch path
        mcp_client=None,  # SynapseMCPClient — optional MCP context gathering
        retry_queue=None,
        inbox_store=None,
        inbox_replay: Callable[[dict], None] | None = None,
        max_processing_attempts: int = 3,
        processing_retry_delay_seconds: float = 5.0,
        inbox_poll_seconds: float = 1.0,
        personal_memory_service=None,
    ):
        self.queue = queue
        self.sender = sender  # fallback if no channel_registry or channel not found
        self.channel_registry = channel_registry
        self.mcp_client = mcp_client
        self.retry_queue = retry_queue
        self.personal_memory_service = personal_memory_service
        if retry_queue is not None and personal_memory_service is not None:
            personal_memory_service.retry_queue = retry_queue
            retry_queue.set_delivery_observer(personal_memory_service.mark_assistant_delivery)
        self.inbox_store = inbox_store
        self.inbox_replay = inbox_replay
        self.max_processing_attempts = max(1, max_processing_attempts)
        self.processing_retry_delay_seconds = max(0.0, processing_retry_delay_seconds)
        self.inbox_poll_seconds = max(0.01, inbox_poll_seconds)
        self._inbox_poller: asyncio.Task | None = None
        replay_owner = getattr(inbox_replay, "__self__", None)
        if replay_owner is not None and hasattr(replay_owner, "set_failure_callback"):
            replay_owner.set_failure_callback(self._record_batch_enqueue_failure)
        self.process_fn = process_fn
        # Detect whether process_fn accepts mcp_context as a 3rd positional arg.
        # Allows old 2-arg consumers to keep working without modification.
        try:
            _sig = inspect.signature(process_fn)
            _params = list(_sig.parameters.values())
            _positional = [
                p
                for p in _params
                if p.kind
                in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            _has_varargs = any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in _params)
            _has_varkw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in _params)
            _kw_names = {p.name for p in _params if p.kind is inspect.Parameter.KEYWORD_ONLY}
            _param_names = {p.name for p in _params}
            self._process_fn_accepts_mcp = _has_varargs or len(_positional) >= 3
            self._process_fn_accepts_mcp_keyword = (
                not self._process_fn_accepts_mcp and "mcp_context" in _param_names
            )
            self._process_fn_accepts_channel_metadata = _has_varkw or {
                "channel_id",
                "is_group",
            }.issubset(_kw_names)
            self._process_fn_accepts_source_key = _has_varkw or "source_message_key" in _param_names
            self._process_fn_accepts_received_at = _has_varkw or "source_received_at" in _param_names
            self._process_fn_accepts_person_origin = _has_varkw or "person_origin" in _param_names
            self._process_fn_accepts_api_auth = _has_varkw or "api_authenticated" in _param_names
        except (ValueError, TypeError):
            self._process_fn_accepts_mcp = False
            self._process_fn_accepts_mcp_keyword = False
            self._process_fn_accepts_channel_metadata = False
            self._process_fn_accepts_source_key = False
            self._process_fn_accepts_received_at = False
            self._process_fn_accepts_person_origin = False
            self._process_fn_accepts_api_auth = False
        self.num_workers = num_workers
        self._workers: list[asyncio.Task] = []
        self._running = False

        # PER-CHAT GENERATION TRACKING
        self._chat_generations: dict[tuple[str, str], int] = {}
        self._gen_lock = asyncio.Lock()

    def _get_channel(self, task):
        """
        Resolve the channel adapter for a task via ChannelRegistry.
        Returns the channel if found, None otherwise.
        No WhatsApp-specific branching — registry dispatch only (CHAN-07).
        """
        if self.channel_registry is None:
            return None
        channel_id = getattr(task, "channel_id", None) or "whatsapp"
        channel = self.channel_registry.get(channel_id)
        if channel is None:
            logger.warning("No channel registered for '%s' -- task will fail", channel_id)
        return channel

    async def start(self):
        if self._running:
            return
        if self.inbox_store is not None:
            self.inbox_store.recover_processing()
        self._running = True
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"msg-worker-{i}")
            self._workers.append(task)
        if self.inbox_store is not None and self.inbox_replay is not None:
            self._inbox_poller = asyncio.create_task(
                self._poll_inbox(), name="inbox-retry-poller"
            )
        logger.info("Started %d workers", self.num_workers)

    async def stop(self):
        self._running = False
        if self._inbox_poller is not None:
            self._inbox_poller.cancel()
            await asyncio.gather(self._inbox_poller, return_exceptions=True)
            self._inbox_poller = None
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("All workers stopped")

    async def _poll_inbox(self) -> None:
        assert self.inbox_store is not None and self.inbox_replay is not None
        while self._running:
            try:
                for entry in self.inbox_store.claim_due():
                    try:
                        self.inbox_replay(entry)
                    except Exception as exc:
                        logger.error("Inbox replay failed for row %s: %s", entry["id"], exc)
                        self.inbox_store.mark_failed(
                            [entry["id"]],
                            max_attempts=self.max_processing_attempts,
                            retry_delay_seconds=self.processing_retry_delay_seconds,
                            error=type(exc).__name__,
                            terminal_message_key=f"inbox-error:{entry['id']}",
                        )
                for notice in self.inbox_store.claim_terminal_notices():
                    ids = notice["inbox_ids"]
                    if self.retry_queue is None:
                        self.inbox_store.release_terminal_notice(ids)
                        continue
                    try:
                        entry_id = await self.retry_queue.enqueue_outbound(
                            channel_id=notice["channel_id"],
                            chat_id=notice["chat_id"],
                            text="I hit a glitch on my side and couldn't finish that request. Please try again.",
                            message_key=notice["terminal_message_key"],
                            owner_id=f"{notice['channel_id']}:{notice['chat_id']}",
                        )
                        self.inbox_store.mark_dead_letter(ids)
                        await self.retry_queue.attempt_now(entry_id)
                    except Exception:
                        self.inbox_store.release_terminal_notice(ids)
                        logger.exception("Could not commit terminal inbox notice")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Inbox retry poll failed")
            await asyncio.sleep(self.inbox_poll_seconds)

    def _record_processing_failure(self, task: MessageTask, error: Exception | str) -> bool:
        if self.inbox_store is None or not task.inbox_ids:
            return False
        self.inbox_store.mark_failed(
            task.inbox_ids,
            max_attempts=self.max_processing_attempts,
            retry_delay_seconds=self.processing_retry_delay_seconds,
            error=type(error).__name__ if isinstance(error, Exception) else error,
            terminal_message_key=f"inbox-error:{task.task_id}",
        )
        return True

    def _record_batch_enqueue_failure(self, metadata: dict, error: Exception) -> None:
        """Return a claimed envelope to durable retry if batch enqueue fails."""
        if self.inbox_store is None:
            return
        ids = list(dict.fromkeys(metadata.get("inbox_ids") or []))
        if not ids:
            return
        if not metadata.get("inbox_claimed") and not self.inbox_store.claim(ids):
            return
        self.inbox_store.mark_failed(
            ids,
            max_attempts=self.max_processing_attempts,
            retry_delay_seconds=self.processing_retry_delay_seconds,
            error=type(error).__name__,
            terminal_message_key=f"inbox-error:{','.join(map(str, sorted(ids)))}",
        )

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                task = await self.queue.dequeue()
                await self._handle_task(task, worker_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Worker-%d loop error: %s", worker_id, e, exc_info=True)
                await asyncio.sleep(1)

    async def _handle_task(self, task: MessageTask, worker_id: int):
        _ctx_token = set_run_id(task.run_id) if task.run_id else None
        try:
            if self.inbox_store is not None and task.inbox_ids and not task.inbox_claimed:
                if not self.inbox_store.claim(task.inbox_ids):
                    self.queue.supersede(task)
                    return
                task.inbox_claimed = True
            chat_id = task.chat_id
            generation_key = (task.channel_id, chat_id)
            start_time = time.time()

            async with self._gen_lock:
                current = self._chat_generations.get(generation_key, 0)
                new_gen = current + 1
                self._chat_generations[generation_key] = new_gen
                task.generation = new_gen

            _log.info(
                "worker_processing",
                extra={
                    "worker_id": worker_id,
                    "generation": task.generation,
                    "chat_id": chat_id,
                    "sender_name": task.sender_name,
                    "msg_preview": task.user_message[:40],
                },
            )

            channel = self._get_channel(task)

            typing_task = None
            try:
                # STEP 1: Mark read (blue ticks)
                if task.message_id and channel:
                    await channel.mark_read(chat_id, task.message_id)
                elif task.message_id and self.sender:
                    await self.sender.send_seen(chat_id, task.message_id)

                # STEP 2: Typing indicator
                typing_task = asyncio.create_task(self._keep_typing(chat_id, channel))

                # STEP 4: The actual pipeline (SBS + RAG + LLM)
                # Note: mcp_context populated here by external MCP tool calls (not memory —
                # persona_chat queries memory directly via the singleton MemoryEngine).
                kwargs = {}
                if self._process_fn_accepts_channel_metadata:
                    kwargs.update(channel_id=task.channel_id, is_group=task.is_group)
                if self._process_fn_accepts_source_key:
                    kwargs["source_message_key"] = task.task_id
                if self._process_fn_accepts_received_at:
                    receipt = (
                        self.inbox_store.received_at(task.inbox_ids)
                        if self.inbox_store is not None and task.inbox_ids
                        else None
                    )
                    kwargs["source_received_at"] = receipt or datetime.now(UTC).isoformat()
                if self._process_fn_accepts_person_origin:
                    kwargs["person_origin"] = task.person_origin
                if self._process_fn_accepts_api_auth:
                    kwargs["api_authenticated"] = task.api_authenticated
                if self._process_fn_accepts_mcp:
                    response = await self.process_fn(
                        task.user_message,
                        chat_id,
                        task.mcp_context,
                        **kwargs,
                    )
                elif self._process_fn_accepts_mcp_keyword:
                    response = await self.process_fn(
                        task.user_message,
                        chat_id,
                        mcp_context=task.mcp_context,
                        **kwargs,
                    )
                else:
                    response = await self.process_fn(task.user_message, chat_id, **kwargs)

                from sci_fi_dashboard.personal_memory import PersonalizedReply

                personalized = response if isinstance(response, PersonalizedReply) else None
                if personalized is not None:
                    response = personalized.text

                # STEP 5: Stop typing
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

                # STEP 6: Check if still the latest generation before sending
                async with self._gen_lock:
                    latest_gen = self._chat_generations.get(generation_key, task.generation)

                if task.generation != latest_gen:
                    self.queue.supersede(task)
                    if self.inbox_store is not None:
                        self.inbox_store.mark_completed(task.inbox_ids)
                    logger.info(
                        "Worker-%d gen=%d superseded by gen=%d for chat %s, dropping",
                        worker_id,
                        task.generation,
                        latest_gen,
                        chat_id,
                    )
                    return

                # STEP 6: Send response via ChannelRegistry (CHAN-07: no WA-specific branching)
                if response and response.strip():
                    if self.retry_queue is not None:
                        chunks = _split_long_message(response, chunk_size=4000)
                        group_key = f"reply:{task.task_id}"
                        entry_ids = [
                            await self.retry_queue.enqueue_outbound(
                                channel_id=task.channel_id,
                                chat_id=chat_id,
                                text=chunk,
                                message_key=f"{group_key}:{index}",
                                owner_id=f"{task.channel_id}:{chat_id}",
                                group_key=group_key,
                                sequence=index,
                                personal_context_json=(
                                    json.dumps(asdict(personalized.person_context), sort_keys=True)
                                    if personalized is not None else None
                                ),
                                parent_episode_id=(
                                    personalized.source_episode_id if personalized is not None else None
                                ),
                            )
                            for index, chunk in enumerate(chunks)
                        ]
                        if personalized is not None and self.personal_memory_service is not None:
                            for entry_id in entry_ids:
                                try:
                                    committed = await self.retry_queue.get_entry(entry_id)
                                    if committed is None:
                                        continue
                                    created = datetime.fromisoformat(committed["created_at"])
                                    self.personal_memory_service.record_assistant_reply(
                                        personalized.person_context,
                                        source_episode_id=personalized.source_episode_id,
                                        source_message_id=committed["message_key"],
                                        content=committed["text"],
                                        occurred_at=created.replace(tzinfo=UTC),
                                        delivery_state="pending",
                                    )
                                except Exception:
                                    logger.warning("Assistant memory projection deferred after outbox commit")
                        # All reply chunks are committed before the inbox is
                        # closed. Recovery then retries transport, not the LLM.
                        if self.inbox_store is not None:
                            self.inbox_store.mark_completed(task.inbox_ids)
                        states = [await self.retry_queue.attempt_now(eid) for eid in entry_ids]
                        success = all(state == "accepted" for state in states)
                    elif channel:
                        # Split long messages — channels may have their own limits; 4000 chars is safe
                        chunks = _split_long_message(response, chunk_size=4000)
                        success = True
                        for i, chunk in enumerate(chunks):
                            ok = await channel.send(chat_id, chunk)
                            if not ok:
                                logger.warning(
                                    "Worker-%d channel.send() failed on chunk %d",
                                    worker_id,
                                    i + 1,
                                )
                                success = False
                                # Enqueue failed chunk into retry queue if available
                                retry_queue = getattr(channel, "_retry_queue", None)
                                if retry_queue is not None:
                                    await retry_queue.enqueue(
                                        channel_id=channel.channel_id,
                                        chat_id=chat_id,
                                        text=chunk,
                                        error="send() returned False",
                                    )
                                break
                            if i < len(chunks) - 1:
                                await asyncio.sleep(0.8)
                    elif self.sender:
                        success = await self.sender.send_long_message(
                            target=chat_id, message=response
                        )
                    else:
                        logger.warning(
                            "Worker-%d no channel or sender -- dropping response", worker_id
                        )
                        success = False

                    processing_time_ms = int((time.time() - start_time) * 1000)
                    if success or self.retry_queue is not None:
                        self.queue.complete(task, response)
                        logger.info(
                            "Worker-%d gen=%d response committed in %dms",
                            worker_id,
                            task.generation,
                            processing_time_ms,
                        )
                        if self.inbox_store is not None and self.retry_queue is None:
                            self.inbox_store.mark_completed(task.inbox_ids)
                    else:
                        self.queue.fail(task, "Send failed")
                        self._record_processing_failure(task, "SendFailed")
                else:
                    self.queue.fail(task, "Empty LLM response")
                    self._record_processing_failure(task, "EmptyResponse")

            except Exception as e:
                error_msg = str(e)

                async with self._gen_lock:
                    latest_gen = self._chat_generations.get(generation_key, task.generation)

                if task.generation != latest_gen:
                    self.queue.supersede(task)
                    if self.inbox_store is not None:
                        self.inbox_store.mark_completed(task.inbox_ids)
                    logger.info(
                        "Worker-%d gen=%d error after superseded by gen=%d for %s, dropping",
                        worker_id,
                        task.generation,
                        latest_gen,
                        chat_id,
                    )
                    return

                self.queue.fail(task, error_msg)
                logger.error("Worker-%d task failed: %s", worker_id, error_msg, exc_info=True)

                if not self._record_processing_failure(task, e):
                    # Legacy non-durable callers retain their immediate notice.
                    warn_msg = "I hit a glitch on my side. Try once more in a moment."
                    if channel:
                        await channel.send(chat_id, warn_msg)
                    elif self.sender:
                        await self.sender.send_text(chat_id, warn_msg)

            finally:
                if typing_task is not None and not typing_task.done():
                    typing_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await typing_task

        finally:
            if _ctx_token is not None:
                _run_id_ctx.reset(_ctx_token)

    async def _keep_typing(self, chat_id: str, channel=None):
        """Resend typing indicator every 4s to keep it alive."""
        try:
            while True:
                if channel:
                    await channel.send_typing(chat_id)
                elif self.sender:
                    await self.sender.send_typing(chat_id)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
