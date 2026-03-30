import asyncio
import contextlib
import time
import traceback

from .queue import MessageTask, TaskQueue
from .sender import (
    WhatsAppSender,  # kept for backwards-compat constructor param; Phase 4 removes it
)

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
        process_fn,
        num_workers: int = 2,
        sender: WhatsAppSender | None = None,  # deprecated; kept for compat
        channel_registry=None,  # ChannelRegistry — preferred dispatch path
    ):
        self.queue = queue
        self.sender = sender  # fallback if no channel_registry or channel not found
        self.channel_registry = channel_registry
        self.process_fn = process_fn
        self.num_workers = num_workers
        self._workers: list[asyncio.Task] = []
        self._running = False

        # PER-CHAT GENERATION TRACKING
        self._chat_generations: dict[str, int] = {}
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
            print(f"[WORKER] No channel registered for '{channel_id}' — task will fail")
        return channel

    async def start(self):
        self._running = True
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i), name=f"msg-worker-{i}")
            self._workers.append(task)
        print(f"[WORKER] Started {self.num_workers} workers.")

    async def stop(self):
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        print("[WORKER] All workers stopped.")

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                task = await self.queue.dequeue()
                await self._handle_task(task, worker_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WORKER-{worker_id}] Loop error: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def _handle_task(self, task: MessageTask, worker_id: int):
        chat_id = task.chat_id
        start_time = time.time()

        async with self._gen_lock:
            current = self._chat_generations.get(chat_id, 0)
            new_gen = current + 1
            self._chat_generations[chat_id] = new_gen
            task.generation = new_gen

        print(
            f"[WORKER-{worker_id}] gen={task.generation} Processing: "
            f'"{task.user_message[:60]}..." from {task.sender_name}'
        )

        channel = self._get_channel(task)

        try:
            # STEP 1: Mark read (blue ticks)
            if task.message_id and channel:
                await channel.mark_read(chat_id, task.message_id)
            elif task.message_id and self.sender:
                await self.sender.send_seen(chat_id, task.message_id)

            # STEP 2: Typing indicator
            typing_task = asyncio.create_task(self._keep_typing(chat_id, channel))

            # STEP 3: The actual pipeline (SBS + RAG + LLM)
            response = await self.process_fn(task.user_message, chat_id)

            # STEP 4: Stop typing
            typing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing_task

            # STEP 5: Check if still the latest generation before sending
            async with self._gen_lock:
                latest_gen = self._chat_generations.get(chat_id, task.generation)

            if task.generation != latest_gen:
                self.queue.supersede(task)
                print(
                    f"[WORKER-{worker_id}] gen={task.generation} superseded by "
                    f"gen={latest_gen} for chat {chat_id}. Dropping response silently."
                )
                return

            # STEP 6: Send response via ChannelRegistry (CHAN-07: no WA-specific branching)
            if response and response.strip():
                if channel:
                    # Split long messages — channels may have their own limits; 4000 chars is safe
                    chunks = _split_long_message(response, chunk_size=4000)
                    success = True
                    for i, chunk in enumerate(chunks):
                        ok = await channel.send(chat_id, chunk)
                        if not ok:
                            print(f"[WORKER-{worker_id}] channel.send() failed on chunk {i+1}")
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
                    success = await self.sender.send_long_message(target=chat_id, message=response)
                else:
                    print(f"[WORKER-{worker_id}] No channel or sender — dropping response")
                    success = False

                processing_time_ms = int((time.time() - start_time) * 1000)
                if success:
                    self.queue.complete(task, response)
                    print(
                        f"[WORKER-{worker_id}] gen={task.generation} Delivered in "
                        f"{processing_time_ms}ms"
                    )
                else:
                    self.queue.fail(task, "Send failed")
            else:
                self.queue.fail(task, "Empty LLM response")

        except Exception as e:
            error_msg = str(e)

            async with self._gen_lock:
                latest_gen = self._chat_generations.get(chat_id, task.generation)

            if task.generation != latest_gen:
                self.queue.supersede(task)
                print(
                    f"[WORKER-{worker_id}] gen={task.generation} error after superseded by "
                    f"gen={latest_gen} for {chat_id}. Dropping silently."
                )
                return

            self.queue.fail(task, error_msg)
            print(f"[WORKER-{worker_id}] Task failed: {error_msg}")
            traceback.print_exc()

            # Notify user of error
            warn_msg = "[WARN] A technical glitch occurred. Please try again. [WRENCH]"
            if channel:
                await channel.send(chat_id, warn_msg)
            elif self.sender:
                await self.sender.send_text(chat_id, warn_msg)

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
