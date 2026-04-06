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

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.conv_kg_extractor import run_batch_extraction
from sci_fi_dashboard.schemas import ChatRequest
from synapse_config import SynapseConfig

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

    from synapse_config import SynapseConfig as _SC

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
        payload.get("via")
        or payload.get("delivery")
        or payload.get("payload", {}).get("via")
        or ""
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

        continuation = await call_gemini_flash(
            new_history, temperature=0.7, max_tokens=2000
        )

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
# Async Gateway Processing Pipeline
# ---------------------------------------------------------------------------


async def process_message_pipeline(
    user_msg: str, chat_id: str, mcp_context: str = ""
) -> str:
    from sci_fi_dashboard.chat_pipeline import persona_chat

    target = deps._resolve_target(chat_id)

    chat_req = ChatRequest(
        message=user_msg,
        user_id=chat_id,
        session_type="safe",
    )
    result = await persona_chat(chat_req, target, None, mcp_context=mcp_context)
    return result.get("reply", "")


async def on_batch_ready(
    chat_id: str, combined_message: str, metadata: dict
):
    from gateway.queue import MessageTask

    is_group = metadata.get("is_group", False)
    chat_type = "group" if is_group else "direct"
    session_key = (
        f"{metadata.get('channel_id', 'whatsapp')}:{chat_type}:{chat_id}"
    )
    task = MessageTask(
        task_id=str(uuid.uuid4()),
        chat_id=chat_id,
        user_message=combined_message,
        message_id=metadata.get("message_id", ""),
        sender_name=metadata.get("sender_name", ""),
        channel_id=metadata.get("channel_id", "whatsapp"),
        is_group=is_group,
        session_key=session_key,
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
                                entities_json_path=str(
                                    Path(__file__).parent / "entities.json"
                                ),
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
