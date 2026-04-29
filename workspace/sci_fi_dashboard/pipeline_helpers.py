"""Gateway processing pipeline, background workers, and utility functions."""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from pathlib import Path

import psutil
from synapse_config import SynapseConfig

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.conv_kg_extractor import run_batch_extraction
from sci_fi_dashboard.multiuser.session_key import build_session_key
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.session_ingest import _ingest_session_background

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_databases() -> dict:
    """HLTH-01: Check existence of each SQLite database file."""
    from sci_fi_dashboard.db import DB_PATH as MEMORY_DB
    from sci_fi_dashboard.sqlite_graph import DB_PATH as GRAPH_DB

    result = {
        "memory_db": {
            "status": "ok" if os.path.exists(MEMORY_DB) else "missing",
            "path": MEMORY_DB,
        },
        "knowledge_graph_db": {
            "status": "ok" if os.path.exists(GRAPH_DB) else "missing",
            "path": GRAPH_DB,
        },
    }
    try:
        from sci_fi_dashboard.emotional_trajectory import DB_PATH as TRAJ_DB

        result["emotional_trajectory_db"] = {
            "status": "ok" if os.path.exists(TRAJ_DB) else "missing",
            "path": TRAJ_DB,
        }
    except ImportError:
        result["emotional_trajectory_db"] = {"status": "not_installed"}
    return result


def _check_llm_provider() -> dict:
    """HLTH-01: Report LLM provider configuration status."""
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    casual_model = cfg.model_mappings.get("casual", {}).get("model", "")
    if not casual_model:
        return {"status": "unconfigured", "model": None}
    if "ollama" in casual_model:
        reachable = _port_open("localhost", 11434)
        return {
            "status": "ok" if reachable else "down",
            "provider": "ollama",
            "model": casual_model,
        }
    has_providers = bool(cfg.providers)
    return {
        "status": "configured" if has_providers else "unconfigured",
        "provider": "cloud",
        "model": casual_model,
    }


def validate_env() -> None:
    """Validate required and optional env keys."""
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    print(f"[INFO] Synapse data root: {cfg.data_root}")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        print(
            "[WARN] GEMINI_API_KEY not set -- direct Gemini routing disabled "
            "(configure in synapse.json for Phase 2)"
        )

    if not os.environ.get("GROQ_API_KEY", "").strip():
        print("[WARN] GROQ_API_KEY not set -- voice transcription disabled")
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("[WARN] OPENROUTER_API_KEY not set -- fallback model routing disabled")
    if not os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip():
        print("[WARN] WHATSAPP_BRIDGE_TOKEN not set -- WhatsApp bridge unauthenticated")

    from synapse_config import SynapseConfig as _SC  # noqa: N814

    ollama_on = _port_open("localhost", 11434)
    lance_dir = _SC.load().db_dir / "lancedb"
    lance_on = lance_dir.exists()
    groq_on = bool(os.environ.get("GROQ_API_KEY", "").strip())
    openrouter_on = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    whatsapp_on = bool(os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip())

    print("[INFO] Feature availability:")
    print(f"   Ollama         {'[ON]' if ollama_on else '[--]'}  local embedding + The Vault")
    print(f"   LanceDB        {'[ON]' if lance_on else '[--]'}  vector search (embedded)")
    print(f"   Groq           {'[ON]' if groq_on else '[--]'}  voice transcription")
    print(f"   OpenRouter     {'[ON]' if openrouter_on else '[--]'}  fallback model routing")
    print(f"   WhatsApp       {'[ON]' if whatsapp_on else '[--]'}  bridge authentication")


def _extract_cli_send_route(raw_stdout: str) -> str:
    raw = (raw_stdout or "").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return (
        payload.get("via") or payload.get("delivery") or payload.get("payload", {}).get("via") or ""
    )


# ---------------------------------------------------------------------------
# Auto-Continue Background Task
# ---------------------------------------------------------------------------


async def continue_conversation(
    target: str,
    messages: list[dict],
    last_reply: str,
    channel_id: str = "whatsapp",
):
    """H-10: Background task to generate continuation and send it via the channel."""
    print(f"[REFRESH] [AUTO-CONTINUE] Handling cut-off response for {target}...")

    new_history = [m.copy() for m in messages]
    new_history.append({"role": "assistant", "content": last_reply})
    new_history.append(
        {
            "role": "user",
            "content": (
                "You were cut off. Continue exactly from where you stopped. "
                "Do not repeat what you already said. Just write the rest."
            ),
        }
    )

    try:
        from sci_fi_dashboard.llm_wrappers import call_gemini_flash

        continuation = await call_gemini_flash(new_history, temperature=0.7, max_tokens=2000)

        if not continuation.strip():
            print("[WARN] Continuation was empty.")
            return

        channel = deps.channel_registry.get(channel_id)
        if channel is not None:
            try:
                await channel.send(target, continuation)
                print(
                    f"[AUTO-CONTINUE] Sent continuation ({len(continuation)} chars) "
                    f"via {channel_id}"
                )
            except Exception as send_err:
                print(f"[WARN] [AUTO-CONTINUE] Channel send failed: {send_err}")
        else:
            print(
                f"[AUTO-CONTINUE] Continuation ready ({len(continuation)} chars) "
                f"but channel '{channel_id}' not available."
            )

    except Exception as e:
        print(f"[ERROR] [AUTO-CONTINUE] Failed: {e}")


# ---------------------------------------------------------------------------
# LLM Adapter for Compaction (bridges SynapseLLMRouter → compaction contract)
# ---------------------------------------------------------------------------


class _LLMClientAdapter:
    """Adapter: exposes acompletion(messages=[...]) using SynapseLLMRouter._do_call().

    compaction.py requires: await llm_client.acompletion(messages=[...])
    returning an object with .choices[0].message.content (plain string).

    SynapseLLMRouter._do_call(role, messages) returns the raw litellm response
    which already has that shape. We use the "casual" role for compaction summaries.
    """

    def __init__(self, router) -> None:
        self._router = router

    async def acompletion(self, messages: list[dict], **kwargs):
        """Forward to SynapseLLMRouter._do_call with role='casual'.

        Passes max_tokens=2000 (not the _do_call default of 1000) so that
        compaction summaries of large conversations are not truncated.
        """
        max_tokens = kwargs.get("max_tokens", 2000)
        return await self._router._do_call("casual", messages, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Async Gateway Processing Pipeline
# ---------------------------------------------------------------------------

# Module-level set prevents GC of fire-and-forget background tasks (Research Pitfall 6).
_background_tasks: set[asyncio.Task] = set()

# GC anchor for session ingestion background tasks (/new command)
_session_ingest_tasks: set[asyncio.Task] = set()

# GC anchor for diary generation background tasks (/new command)
_diary_tasks: set[asyncio.Task] = set()


async def _send_voice_note(reply: str, chat_id: str) -> None:
    """Background task: synthesize TTS, save to media store, deliver via WhatsApp."""
    try:
        from sci_fi_dashboard.media.store import save_media_buffer
        from sci_fi_dashboard.tts import TTSEngine

        engine = TTSEngine()
        ogg_bytes = await engine.synthesize(reply)
        if not ogg_bytes:
            return  # TTS disabled, text too long, ffmpeg missing, or synthesis failed

        # Save OGG to media store for bridge to fetch
        saved = save_media_buffer(
            ogg_bytes,
            content_type="audio/ogg",
            subdir="tts_outbound",
        )

        # Build local URL for bridge to fetch
        audio_url = f"http://127.0.0.1:8000/media/tts_outbound/{saved.path.name}"

        # Deliver via WhatsApp channel
        wa_channel = deps.channel_registry.get("whatsapp")
        if wa_channel and hasattr(wa_channel, "send_voice_note"):
            await wa_channel.send_voice_note(chat_id, audio_url)
        else:
            logger.warning("TTS: WhatsApp channel not available for voice note delivery")
    except Exception:
        logger.exception("TTS background task failed for chat_id=%s", chat_id)


async def _generate_diary_background(
    archived_path: Path,
    agent_id: str,
    session_key: str,
) -> None:
    """Background coroutine: generate a diary entry from an archived session transcript."""
    try:
        from sci_fi_dashboard.multiuser.transcript import load_messages

        messages = await load_messages(archived_path)
        if not messages:
            return
        await deps.diary_engine.generate_entry(
            session_id=session_key,
            user_id=agent_id,
            messages=messages,
        )
        logger.info("[Diary] Entry generated for session %s", session_key)
    except Exception:
        logger.warning(
            "[Diary] Background diary generation failed for %s", session_key, exc_info=True
        )


async def _handle_new_command(
    session_key: str,
    agent_id: str,
    data_root: "Path",
    session_store,
    hemisphere: str = "safe",
) -> str:
    """Archive current transcript, fire full memory-loop ingestion, rotate session ID.

    The old JSONL is renamed (not deleted).
    Background task runs vector + KG ingestion on the archived transcript.
    Returns confirmation immediately — callers must NOT call the LLM.
    """
    from sci_fi_dashboard.multiuser.transcript import archive_transcript, transcript_path

    entry = await session_store.get(session_key)
    archived_path = None

    if entry is not None:
        old_path = transcript_path(entry, data_root, agent_id)
        archived_path = await archive_transcript(old_path) if old_path.exists() else None

    # Clear in-memory cache
    deps.conversation_cache.invalidate(session_key)

    # Rotate session ID → new JSONL on next message
    # CRITICAL: delete() first — _merge_entry() never overwrites session_id via update()
    await session_store.delete(session_key)
    await session_store.update(session_key, {"compaction_count": 0})

    # Fire-and-forget: full memory loop (vector + KG) in background
    if archived_path is not None:
        task = asyncio.create_task(
            _ingest_session_background(
                archived_path=archived_path,
                agent_id=agent_id,
                session_key=session_key,
                hemisphere=hemisphere,
            )
        )
        _session_ingest_tasks.add(task)
        task.add_done_callback(_session_ingest_tasks.discard)

        # Fire-and-forget: diary entry generation (independent of ingest)
        if deps.diary_engine is not None:
            diary_task = asyncio.create_task(
                _generate_diary_background(
                    archived_path=archived_path,
                    agent_id=agent_id,
                    session_key=session_key,
                )
            )
            _diary_tasks.add(diary_task)
            diary_task.add_done_callback(_diary_tasks.discard)

    return "Session archived! I'll remember everything. Starting fresh now."


async def process_message_pipeline(
    user_msg: str, chat_id: str, mcp_context: str = "", *, is_group: bool = False
) -> str:
    """Process one inbound message through the full session-aware pipeline.

    The ``is_group`` keyword-only parameter defaults to False so the existing
    3-arg call ``process_fn(task.user_message, chat_id, task.mcp_context)`` from
    MessageWorker continues to work unchanged (Research Pitfall 3 / D-04, D-06).
    """
    # Deferred imports to avoid circular dependencies at module load time.
    from sci_fi_dashboard.chat_pipeline import persona_chat
    from sci_fi_dashboard.multiuser.compaction import compact_session, estimate_tokens
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import (
        append_message,
        load_messages,
        transcript_path,
    )

    # ------------------------------------------------------------------
    # Step 1: Resolve target persona and load config
    # ------------------------------------------------------------------
    target = deps._resolve_target(chat_id)
    cfg = SynapseConfig.load()
    data_root = cfg.data_root  # ~/.synapse/ — NOT cfg.db_dir.parent (Research Pitfall 1)
    session_cfg = getattr(cfg, "session", {}) or {}
    dm_scope = session_cfg.get("dmScope", "per-channel-peer")
    identity_links = session_cfg.get("identityLinks", {})

    # ------------------------------------------------------------------
    # Step 2: Build session key (per D-04, D-05, D-06, D-07)
    # ------------------------------------------------------------------
    session_key = build_session_key(
        agent_id=target,
        channel="whatsapp",
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id="whatsapp",
        dm_scope=dm_scope,
        main_key="whatsapp:dm",
        identity_links=identity_links,
    )
    logger.debug("session_key_built")

    # ------------------------------------------------------------------
    # Step 2b: Sub-agent spawn detection (Phase 3)
    # ------------------------------------------------------------------
    from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

    # TODO(multi-channel): channel_id is hardcoded to "whatsapp" because
    # process_message_pipeline() does not receive channel_id from its caller.
    # When a second channel gains pipeline access, thread channel_id from
    # MessageTask through process_message_pipeline's signature instead.
    spawn_reply = await maybe_spawn_agent(
        user_msg=user_msg,
        chat_id=chat_id,
        channel_id="whatsapp",
        session_key=session_key,
    )
    if spawn_reply is not None:
        return spawn_reply  # Short-circuit: agent spawned, return acknowledgment as str

    # ------------------------------------------------------------------
    # Step 3: Get or create session entry (per D-18 corrected, D-19)
    # ------------------------------------------------------------------
    store = SessionStore(agent_id=target, data_root=data_root)
    entry = await store.get(session_key)
    if entry is None:
        entry = await store.update(session_key, {})

    t_path = transcript_path(entry, data_root, target)

    # ------------------------------------------------------------------
    # /new command: archive session + full memory loop + rotate session
    # ------------------------------------------------------------------
    if user_msg.strip().lower() == "/new":
        return await _handle_new_command(
            session_key=session_key,
            agent_id=target,
            data_root=data_root,
            session_store=store,
        )

    # ------------------------------------------------------------------
    # Step 4: Load history with cache (per D-10, D-13, Research Pitfall 7)
    # ------------------------------------------------------------------
    channels_cfg = (
        cfg.channels if hasattr(cfg, "channels") and isinstance(cfg.channels, dict) else {}
    )
    history_limit = int(channels_cfg.get("whatsapp", {}).get("dmHistoryLimit", 50))

    messages = deps.conversation_cache.get(session_key)
    if messages is None:
        messages = await load_messages(t_path, limit=history_limit)
        deps.conversation_cache.put(session_key, messages)  # put() BEFORE append() calls

    # ------------------------------------------------------------------
    # Step 5: Capture user turn first, then call persona_chat with timeout
    # ------------------------------------------------------------------
    history_for_llm = list(messages)
    user_dict = {"role": "user", "content": user_msg}
    await append_message(t_path, user_dict)
    deps.conversation_cache.append(session_key, user_dict)

    raw_timeout = session_cfg.get("chat_timeout_seconds", 90.0)
    try:
        chat_timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        chat_timeout_seconds = 90.0

    chat_req = ChatRequest(
        message=user_msg,
        user_id=chat_id,
        session_type="safe",
        history=history_for_llm,
    )
    try:
        result = await asyncio.wait_for(
            persona_chat(chat_req, target, None, mcp_context=mcp_context),
            timeout=chat_timeout_seconds,
        )
        reply = result.get("reply", "")
    except TimeoutError:
        logger.warning("persona_chat timed out after %.2fs for %s", chat_timeout_seconds, session_key)
        reply = (
            "I saved your message, but I timed out while generating a reply. "
            "Please try again."
        )
    except Exception:
        logger.exception("persona_chat failed for %s", session_key)
        reply = (
            "I saved your message, but hit an error while generating a reply. "
            "Please try again."
        )

    # ------------------------------------------------------------------
    # Step 6: Fire-and-forget assistant append + compaction (per D-11, D-12, D-14-D-17)
    # ------------------------------------------------------------------
    asst_dict = {"role": "assistant", "content": reply}

    async def _save_and_compact():
        try:
            await append_message(t_path, asst_dict)
            deps.conversation_cache.append(session_key, asst_dict)

            # Compaction pre-gate (D-14: 60% threshold, D-17: 32k safe default)
            cached = deps.conversation_cache.get(session_key) or []
            ctx_window = 32_000
            if estimate_tokens(cached) > int(ctx_window * 0.6):
                await compact_session(
                    transcript_path=t_path,
                    context_window_tokens=ctx_window,
                    llm_client=_LLMClientAdapter(deps.synapse_llm_router),
                    agent_id=target,
                    session_key=session_key,
                    store_path=store._path,
                )
                deps.conversation_cache.invalidate(session_key)
        except Exception:
            logger.exception("Background save/compact failed for %s", session_key)

    task = asyncio.create_task(_save_and_compact())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # ------------------------------------------------------------------
    # Step 7: TTS voice note (fire-and-forget, mutually exclusive with auto-continue)
    # ------------------------------------------------------------------
    # Only trigger TTS when:
    # 1. The reply exists and is non-empty
    # 2. Auto-continue was NOT triggered for this reply (check: reply ends with terminal punct)
    # 3. TTS is enabled in config (default: True)
    # Note: Channel is implicitly WhatsApp — process_message_pipeline is WhatsApp-only.
    _tts_cfg = cfg.tts if hasattr(cfg, "tts") else {}
    _tts_enabled = _tts_cfg.get("enabled", True) if _tts_cfg else True
    _terminals = (".", "!", "?", '"', "'", ")", "]", "}")
    _reply_stripped = reply.strip()
    _ends_terminal = bool(_reply_stripped) and _reply_stripped[-1] in _terminals

    if reply and _tts_enabled and _ends_terminal:
        tts_task = asyncio.create_task(_send_voice_note(reply, chat_id))
        _background_tasks.add(tts_task)
        tts_task.add_done_callback(_background_tasks.discard)

    return reply


async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
    from gateway.queue import MessageTask

    is_group = metadata.get("is_group", False)
    channel_id = metadata.get("channel_id", "whatsapp")

    # WA-FIX-04: use canonical build_session_key so on_batch_ready and
    # process_message_pipeline agree on one session-key shape.
    cfg = SynapseConfig.load()
    session_cfg = getattr(cfg, "session", {}) or {}
    target = deps._resolve_target(chat_id)
    session_key = build_session_key(
        agent_id=target,
        channel=channel_id,
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id=channel_id,
        dm_scope=session_cfg.get("dmScope", "per-channel-peer"),
        main_key="whatsapp:dm",
        identity_links=session_cfg.get("identityLinks", {}),
    )
    task = MessageTask(
        task_id=str(uuid.uuid4()),
        chat_id=chat_id,
        user_message=combined_message,
        message_id=metadata.get("message_id", ""),
        sender_name=metadata.get("sender_name", ""),
        channel_id=channel_id,
        is_group=is_group,
        session_key=session_key,
        run_id=metadata.get("run_id"),
    )
    await deps.task_queue.enqueue(task)


# ---------------------------------------------------------------------------
# Background Worker
# ---------------------------------------------------------------------------


async def gentle_worker_loop():
    """Background maintenance loop."""
    print("[WORKER] Gentle Worker: running.")
    _kg_tick = 0
    _kg_last_time = time.time()
    while True:
        try:
            battery = psutil.sensors_battery()
            is_plugged = battery.power_plugged if battery else True
            cpu_load = psutil.cpu_percent(interval=None)

            if is_plugged and cpu_load < 20.0:
                deps.brain.prune_graph()
                deps.conflicts.prune_conflicts()

                # KG extraction every 2 cycles (~20 min) or 30-min fallback
                _kg_tick += 1
                if _kg_tick >= 2 or (time.time() - _kg_last_time) >= 1800:
                    _kg_tick = 0
                    _kg_last_time = time.time()
                    try:
                        cfg = SynapseConfig.load()
                        for pid, sbs in deps.sbs_registry.items():
                            await run_batch_extraction(
                                persona_id=pid,
                                sbs_data_dir=str(sbs.data_dir),
                                llm_router=deps.synapse_llm_router,
                                graph=deps.brain,
                                memory_db_path=str(cfg.db_dir / "memory.db"),
                                entities_json_path=str(Path(__file__).parent / "entities.json"),
                                min_messages=cfg.kg_extraction.min_messages,
                                kg_role=cfg.kg_extraction.kg_role,
                            )
                    except Exception as e:
                        logger.warning("[WARN] KG extraction failed: %s", e)

                await asyncio.sleep(600)
            else:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except (KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception as e:
            print(f"[WARN] Worker: {e}")
            await asyncio.sleep(60)


# Wire flood callback -- must happen after on_batch_ready is defined
deps.flood.set_callback(on_batch_ready)
