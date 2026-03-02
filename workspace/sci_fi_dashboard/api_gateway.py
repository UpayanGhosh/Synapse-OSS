"""
Antigravity Gateway v2 -- The Soul + Brain Assembly Line

Routes:
  POST /chat/the_creator   -- Chat as Synapse talking to user_nickname (brother mode)
  POST /chat/the_partner   -- Chat as Synapse talking to the_partner_name (caring PA mode)
  POST /chat          -- Generic fallback (original Banglish persona)
  POST /persona/rebuild -- Re-parse chat logs and rebuild persona profiles
  GET  /persona/status  -- Profile stats and embedding mode
  POST /ingest         -- Ingest a fact into the knowledge graph
  POST /add            -- Unstructured memory -> LLM -> triple extraction
  POST /query          -- Query the knowledge graph
  GET  /health         -- System health
"""

import asyncio
import json
import os
import socket
import sqlite3
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import psutil
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel

# from celery import Celery  # REMOVED -- using async workers
from rich import print

# Add current directory + workspace root to path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)
if WORKSPACE_ROOT not in sys.path:
    sys.path.append(WORKSPACE_ROOT)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def validate_env() -> None:
    """Validate required and optional env keys. Uses SynapseConfig for path resolution."""
    from synapse_config import SynapseConfig  # noqa: PLC0415

    cfg = SynapseConfig.load()
    print(f"[INFO] Synapse data root: {cfg.data_root}")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        print("[WARN] GEMINI_API_KEY not set — direct Gemini routing disabled (configure in synapse.json for Phase 2)")

    if not os.environ.get("GROQ_API_KEY", "").strip():
        print("[WARN] GROQ_API_KEY not set -- voice transcription disabled")
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("[WARN] OPENROUTER_API_KEY not set -- fallback model routing disabled")
    if not os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip():
        print("[WARN] WHATSAPP_BRIDGE_TOKEN not set -- WhatsApp bridge unauthenticated")

    ollama_on = _port_open("localhost", 11434)
    qdrant_on = _port_open("localhost", 6333)
    groq_on = bool(os.environ.get("GROQ_API_KEY", "").strip())
    openrouter_on = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    whatsapp_on = bool(os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip())

    print("[INFO] Feature availability:")
    print(f"   Ollama         {'[ON]' if ollama_on else '[--]'}  local embedding + The Vault")
    print(f"   Qdrant         {'[ON]' if qdrant_on else '[--]'}  vector search")
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


# send_via_cli() removed — Phase 4 replaces with Baileys HTTP bridge


async def continue_conversation(target: str, messages: list[dict], last_reply: str):
    """
    Background task to generate and send the rest of the message.
    """
    print(f"[REFRESH] [AUTO-CONTINUE] Handling cut-off response for {target}...")

    # 1. Update History
    # We clone messages to avoid mutating the original reference if reused
    new_history = [m.copy() for m in messages]
    new_history.append({"role": "assistant", "content": last_reply})
    new_history.append(
        {
            "role": "user",
            "content": "You were cut off. Continue exactly from where you stopped. Do not repeat what you already said. Just write the rest.",
        }
    )

    # 2. Call Model (Gemini Flash for speed/cost)
    # We use a larger token limit here since it's async push
    try:
        continuation = await call_gemini_flash(new_history, temperature=0.7, max_tokens=2000)

        # 3. Check emptiness
        if not continuation.strip():
            print("[WARN] Continuation was empty.")
            return

        # 4. Clean up (sometimes models repeat the last sentence)
        # For now, just send it.

        # 5. Send continuation — Phase 4 will implement Baileys HTTP bridge here
        print(f"[AUTO-CONTINUE] Continuation ready ({len(continuation)} chars). "
              "WhatsApp send skipped until Phase 4 Baileys bridge is implemented.")

        # 6. Recursive Check? (If this one is ALSO cut off?)
        # For now, let's limit to one continuation to avoid infinite loops.

    except Exception as e:
        print(f"[ERROR] [AUTO-CONTINUE] Failed: {e}")


from sci_fi_dashboard.conflict_resolver import ConflictManager  # noqa: E402
from sci_fi_dashboard.dual_cognition import DualCognitionEngine  # noqa: E402
from sci_fi_dashboard.emotional_trajectory import EmotionalTrajectory  # noqa: E402
from sci_fi_dashboard.memory_engine import MemoryEngine  # noqa: E402
from sci_fi_dashboard.retriever import (  # noqa: E402
    get_db_stats,
    query_memories,
)
from sci_fi_dashboard.sbs.orchestrator import SBSOrchestrator  # noqa: E402
from sci_fi_dashboard.smart_entity import EntityGate  # noqa: E402
from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402
from sci_fi_dashboard.toxic_scorer_lazy import LazyToxicScorer  # noqa: E402

# --- Singletons (Optimized v3) ---
brain = SQLiteGraph()
gate = EntityGate(entities_file="entities.json")
conflicts = ConflictManager(conflicts_file="conflicts.json")
toxic_scorer = LazyToxicScorer(idle_timeout=30.0)
emotional_trajectory = EmotionalTrajectory()
memory_engine = MemoryEngine(graph_store=brain, keyword_processor=gate)
dual_cognition = DualCognitionEngine(
    memory_engine=memory_engine,
    graph=brain,
    toxic_scorer=toxic_scorer,
    emotional_trajectory=emotional_trajectory,
)

# --- Async Gateway Components ---
import uuid  # noqa: E402

from gateway.dedup import MessageDeduplicator  # noqa: E402
from gateway.flood import FloodGate  # noqa: E402
from gateway.queue import MessageTask, TaskQueue  # noqa: E402
from gateway.worker import MessageWorker  # noqa: E402
from channels.base import ChannelMessage  # noqa: E402
from channels.registry import ChannelRegistry  # noqa: E402
from channels.stub import StubChannel  # noqa: E402
from channels.whatsapp import WhatsAppChannel  # noqa: E402

task_queue = TaskQueue(max_size=100)
dedup = MessageDeduplicator(window_seconds=300)
flood = FloodGate(batch_window_seconds=3.0)

# Channel registry — all adapters register here; lifespan calls start_all()
channel_registry = ChannelRegistry()
# Phase 4: Real WhatsApp bridge via Baileys Node.js microservice (WA-02)
channel_registry.register(WhatsAppChannel(
    bridge_port=int(os.environ.get("BRIDGE_PORT", "5010")),
    python_webhook_url=os.environ.get(
        "PYTHON_WEBHOOK_URL",
        "http://127.0.0.1:8000/channels/whatsapp/webhook",
    ),
))
channel_registry.register(StubChannel(channel_id="stub"))      # test/demo channel

# --- Sentinel (File Governance) ---
from sbs.sentinel.tools import init_sentinel  # noqa: E402

init_sentinel(project_root=Path(__file__).parent)  # noqa: E402

# --- SBS Orchestrator (Phase 1) ---
SBS_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synapse_data")


def _load_personas_config() -> dict:
    """Load persona definitions from workspace/personas.yaml, with a built-in fallback."""
    cfg_path = Path(WORKSPACE_ROOT) / "personas.yaml"
    if cfg_path.exists():
        try:
            import yaml

            with open(cfg_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "personas" in data:
                return data
        except Exception as exc:
            print(f"[WARN] Could not load personas.yaml: {exc}. Using built-in defaults.")
    # Fallback: two default personas
    return {
        "personas": [
            {
                "id": "the_creator",
                "display_name": "Primary User",
                "description": "Chat as Synapse -> primary user (Bro Mode)",
                "whatsapp_phones": [],
                "whatsapp_keywords": [],
            },
            {
                "id": "the_partner",
                "display_name": "Partner",
                "description": "Chat as Synapse -> partner (Caring PA Mode)",
                "whatsapp_phones": [],
                "whatsapp_keywords": [],
            },
        ],
        "default_persona": "the_creator",
    }


PERSONAS_CONFIG = _load_personas_config()
sbs_registry: dict[str, SBSOrchestrator] = {
    p["id"]: SBSOrchestrator(os.path.join(SBS_DATA_DIR, p["id"]))
    for p in PERSONAS_CONFIG["personas"]
}


def _resolve_target(raw_target: str) -> str:
    """Map a raw chat_id / phone number / keyword to a persona ID."""
    t = raw_target.lower()
    for p in PERSONAS_CONFIG["personas"]:
        if any(phone in t for phone in p.get("whatsapp_phones", [])):
            return p["id"]
        if any(kw in t for kw in p.get("whatsapp_keywords", [])):
            return p["id"]
    return PERSONAS_CONFIG.get("default_persona", "the_creator")


def get_sbs_for_target(target: str) -> SBSOrchestrator:
    return sbs_registry.get(target, sbs_registry[PERSONAS_CONFIG["default_persona"]])


# --- Environment ---
from utils.env_loader import load_env_file  # noqa: E402

load_env_file(anchor=Path(__file__))  # noqa: E402
validate_env()  # ENV-01, ENV-02, ENV-03 -- hard-fail or warn before singletons

from synapse_config import SynapseConfig  # noqa: E402
from sci_fi_dashboard.llm_router import SynapseLLMRouter  # noqa: E402

# --- LLM Client (Phase 2: litellm via SynapseLLMRouter) ---
# Model strings come from synapse.json model_mappings — no hardcoded strings here.
_synapse_cfg = SynapseConfig.load()
synapse_llm_router = SynapseLLMRouter(_synapse_cfg)

_model_mappings = _synapse_cfg.model_mappings
_llm_arch = f"litellm/SynapseLLMRouter ({len(_model_mappings)} roles configured)"
print(
    f"[BOT] LLM Architecture ({_llm_arch}): \n"
    + "\n".join(
        f"   {role}: {cfg.get('model', '?')} (fallback: {cfg.get('fallback', 'none')})"
        for role, cfg in _model_mappings.items()
    )
)

# REDIS_URL removed -- no Redis dependency
BRIDGE_DB_PATH = Path(__file__).resolve().with_name("whatsapp_bridge.db")
# bridge_queue REMOVED -- Celery no longer needed
# WhatsApp messages handled by gateway.worker.MessageWorker (async)

# --- Persona Profiles Layer Migrated to SBS ---
# SBS handles loading persona profiles natively internally.


# --- Schemas ---


class ChatRequest(BaseModel):
    message: str
    history: list = []
    user_id: str | None = None
    session_type: str | None = None  # safe or spicy override


class MemoryItem(BaseModel):
    content: str
    category: str = "general"


class QueryItem(BaseModel):
    text: str


class WhatsAppEnqueueRequest(BaseModel):
    message_id: str
    from_phone: str
    to_phone: str | None = None
    conversation_id: str | None = None
    text: str
    timestamp: str | None = None
    channel: str = "whatsapp"


class WhatsAppLoopTestRequest(BaseModel):
    target: str = "+10000000000"
    message: str = "local-loop-test"
    dry_run: bool = True
    timeout_sec: float = 20.0


# --- LLM Call ---
# from toxic_scorer import toxic_scorer # REPLACED by LazyToxicScorer above

# --- Remote LLM Clients ---

WINDOWS_PC_IP = os.environ.get("WINDOWS_PC_IP", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def call_local_spicy(prompt: str) -> str:
    """LOCAL_SPICY (The Vault): routes to 'vault' role in model_mappings."""
    print("[HOT] Calling LOCAL_SPICY (The Vault) via SynapseLLMRouter 'vault' role...")
    messages = [{"role": "user", "content": prompt}]
    return await synapse_llm_router.call("vault", messages, temperature=0.8, max_tokens=2000)


async def call_or_fallback(prompt: str) -> str:
    """OR_FALLBACK: casual role via SynapseLLMRouter (openrouter fallback handled by Router)."""
    print("[REFRESH] Calling OR_FALLBACK via SynapseLLMRouter...")
    messages = [{"role": "user", "content": prompt}]
    return await synapse_llm_router.call("casual", messages)


async def call_gemini_flash(input_messages: list, temperature: float = 0.7, max_tokens: int = 500) -> str:
    """AG_CASUAL / TRAFFIC COP: routes to 'casual' role in model_mappings."""
    return await synapse_llm_router.call("casual", input_messages, temperature, max_tokens)


async def call_ag_code(messages: list) -> str:
    """AG_CODE (The Hacker): routes to 'code' role in model_mappings."""
    print("[CMD] Routing to THE HACKER (code role)...")
    return await synapse_llm_router.call("code", messages, temperature=0.2, max_tokens=1000)


async def call_ag_oracle(messages: list) -> str:
    """AG_ORACLE (The Architect): routes to 'analysis' role in model_mappings."""
    print("[BLDG] Calling The Architect (analysis role)...")
    return await synapse_llm_router.call("analysis", messages, temperature=0.7, max_tokens=1500)


async def call_ag_review(messages: list) -> str:
    """AG_REVIEW (The Philosopher): routes to 'review' role in model_mappings."""
    print("[THINK] Calling The Philosopher (review role)...")
    return await synapse_llm_router.call("review", messages, temperature=0.7, max_tokens=1500)


async def translate_banglish(text: str) -> str:
    """
    Translate Banglish -> English via SynapseLLMRouter (translate role → Llama 3 via OpenRouter).
    """
    messages = [
        {
            "role": "system",
            "content": "You are a translator. Translate Romanized Bengali (Banglish) to English. OUTPUT ONLY ENGLISH.",
        },
        {"role": "user", "content": text},
    ]
    try:
        return await synapse_llm_router.call("translate", messages)
    except Exception as e:
        print(f"[WARN] Translation failed: {e}")
        return text


# --- Routing Logic ---


async def route_traffic_cop(user_message: str) -> str:
    """
    TRAFFIC COP: Classifies message as CASUAL, CODING, ANALYSIS, or REVIEW.
    """
    system = "Classify this message. Reply with EXACTLY ONE WORD: CASUAL, CODING, ANALYSIS, or REVIEW.\n\n- CODING: Write code, debug, script, API, python.\n- ANALYSIS (Synthesis/Data): Summarize logs, explain history, deep dive, data aggregation. (Use Gemini Pro Context).\n- REVIEW (Critique/Judgment): Grade this, find flaws, audit, critique logic, opinion. (Use Claude Opus nuance).\n- CASUAL: Chat, greetings, daily life, simple questions."
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]
    try:
        # Use Flash for speed; Increase tokens for thinking
        resp = await call_gemini_flash(messages, temperature=0.0, max_tokens=100)
        decision = resp.strip().upper()
        # Clean up punctuation
        import re

        decision = re.sub(r"[^A-Z]", "", decision)
        print(f"[SIGNAL] Traffic Cop: {decision}")
        return decision
    except Exception:
        return "CASUAL"


# --- Persona Chat Handler (MoA Version) ---


async def persona_chat(
    request: ChatRequest,
    target: str,
    background_tasks: BackgroundTasks | None = None,
):
    user_msg = request.message
    print(f"[MAIL] [{target.upper()}] Inbound: {user_msg[:80]}...")

    # 1. Memory Retrieval (Phoenix v3 Unified Engine)
    try:
        env_session = os.environ.get("SESSION_TYPE", "safe")
        session_mode = request.session_type or env_session
        if session_mode not in ["safe", "spicy"]:
            session_mode = "safe"

        # Using the new MemoryEngine for hybrid search + graph context
        mem_response = memory_engine.query(user_msg, limit=5)

        # Format results for the prompt
        results_list = mem_response.get("results", [])
        formatted_facts = "\n".join(
            [f"* {r['content']} (Source: {r['source']})" for r in results_list]
        )
        graph_ctx = mem_response.get("graph_context", "")

        memory_context = f"{formatted_facts}\n\n{graph_ctx}"
        retrieval_method = mem_response.get("tier", "standard")
    except Exception as e:
        print(f"[WARN] Memory Engine Error: {e}")
        memory_context = "(Memory retrieval unavailable)"
        retrieval_method = "failed"

    # 2. Toxicity Check (Auto-Switch to Spicy?)
    # If user explicitly requested "safe", we respect it unless toxicity is extreme?
    # For now, we respect the explicitly passed `request.session_type`.
    # But if `session_type` is None, we could use toxicity to auto-switch.

    toxicity = toxic_scorer.score(user_msg)
    if toxicity > 0.8 and session_mode == "safe":
        print(
            f"[WARN] High Toxicity ({toxicity:.2f}) detected in Safe Mode. Remaining Safe (Architectural Decision)."
        )
        # Optional: Auto-switch to vault? User said "Zero cloud leakage".
        # If toxic, maybe we SHOULD switch to vault?
        # For now, sticking to requested mode to avoid surprises.

    # 2.5 DUAL COGNITION: Think before speaking
    try:
        cognitive_merge = await dual_cognition.think(
            user_message=user_msg,
            chat_id=request.user_id or "default",
            conversation_history=request.history,
            target=target,
            llm_fn=call_gemini_flash,  # Use the fast model for thinking
        )

        cognitive_context = dual_cognition.build_cognitive_context(cognitive_merge)

        print(
            f"[MEM] Cognitive State: {cognitive_merge.tension_type} (tension={cognitive_merge.tension_level:.2f})"
        )
        print(f"[THOUGHT] Inner thought: {cognitive_merge.inner_monologue[:100]}")

    except Exception as e:
        print(f"[WARN] Dual cognition failed: {e}")
        cognitive_context = ""

    # 3. Assemble System Prompt
    sbs_orchestrator = get_sbs_for_target(target)

    # Log user message here via orchestrator
    user_log = sbs_orchestrator.on_message("user", user_msg, request.user_id or "default")
    user_msg_id = user_log.get("msg_id")

    base_instructions = "You are Synapse. Follow the persona profile below precisely."
    system_prompt = sbs_orchestrator.get_system_prompt(base_instructions)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": f"--- RETRIEVED MEMORIES ---\n{memory_context}\n--- END MEMORIES ---",
        },
    ]
    if cognitive_context:
        messages.append({"role": "system", "content": cognitive_context})
    messages.extend(request.history)
    messages.append({"role": "user", "content": user_msg})

    if session_mode == "spicy":
        # === THE VAULT (Local Stheno) ===
        print("[HOT] Routing to THE VAULT (Local Stheno)")
        # Translate first? Stheno understands Banglish moderately well, but translation helps RAG.
        # But for "Authentic" spicy chat, we might want raw Banglish.
        # Let's keep raw for Stheno to maintain flavor, unless requested otherwise.

        full_prompt = f"{system_prompt}\n\nUser: {user_msg}\n\nSynapse:"
        try:
            reply = await call_local_spicy(full_prompt)
            model_used = "The Vault (Stheno)"
        except Exception as e:
            print(f"[WARN] Vault failed: {e}. Falling back to OpenRouter.")
            reply = await call_or_fallback(full_prompt)
            model_used = "The Vault (OpenRouter Fallback)"

    else:
        # === SAFE HEMISPHERE (MoA Routing) ===
        # 1. Traffic Cop
        classification = await route_traffic_cop(user_msg)

        if "CODING" in classification:
            # === THE HACKER (Claude Sonnet 4.5) ===
            print("[CMD] Routing to THE HACKER (Claude Sonnet 4.5)")
            reply = await call_ag_code(messages)
            model_used = "The Hacker (Sonnet 4.5 [Placeholder])"

        elif "ANALYSIS" in classification:
            # === THE ARCHITECT (Gemini 3 Pro) ===
            print("[BLDG] Routing to THE ARCHITECT (Gemini 3 Pro)")
            reply = await call_ag_oracle(messages)
            model_used = "The Architect (Gemini 3 Pro)"

        elif "REVIEW" in classification:
            # === THE PHILOSOPHER (Claude Opus 4.6) ===
            print("[THINK] Routing to THE PHILOSOPHER (Claude Opus 4.6)")
            reply = await call_ag_review(messages)
            model_used = "The Philosopher (Opus 4.6 [Placeholder])"

        else:
            # === AG_CASUAL (Gemini Flash) ===
            print("[GREEN] Routing to AG_CASUAL (Gemini Flash)")
            reply = await call_gemini_flash(messages, temperature=0.85)
            model_used = "Traffic Cop / Casual (Gemini Flash)"

    # --- Programmatic Footer Injection (Memory Check) ---
    # We inject this here to ensure it ALWAYS appears, rather than relying on LLM hallucination.

    # Estimate tokens (rough char count / 4)
    out_tokens = len(reply) // 4
    in_tokens = sum(len(m.get("content", "")) for m in messages) // 4
    total_tokens = in_tokens + out_tokens

    # Context Usage (Mocked max for now, or based on model)
    max_context = 1_000_000  # 1M for Gemini Flash
    usage_pct = (total_tokens / max_context) * 100

    stats_footer = f"\n\n---\n**Context Usage:** {total_tokens // 1000}k / {max_context // 1000000}m ({usage_pct:.2f}%)\n**Model:** {model_used}\n**Turn Total Tokens:** {total_tokens:,}\n**Response Time:** [Calc in Node]"

    final_reply = reply + stats_footer
    print(f"[SPARK] [{target.upper()}] Response via {model_used}: {final_reply[:60]}...")

    # Log assistant message
    sbs_orchestrator = get_sbs_for_target(target)
    sbs_orchestrator.on_message(
        "assistant", reply, request.user_id or "default", response_to=user_msg_id
    )

    # --- AUTO-CONTINUE LOGIC ---
    # Check for cut-off (no terminal punctuation)
    # Punctuation marks that end a sentence/thought
    terminals = [".", "!", "?", '"', "'", ")", "]", "}"]
    # Only check if length is significant (> 50 chars) to avoid false positives on short replies
    is_long = len(reply) > 50
    cleaned_reply = reply.strip()
    ends_with_terminal = any(cleaned_reply.endswith(t) for t in terminals)

    if is_long and not ends_with_terminal:
        print("[CUT] DETECTED CUT-OFF! Triggering Auto-Continue...")
        if background_tasks:
            # We must pass the RAW messages (without the user's last msg? No, messages already has it)
            background_tasks.add_task(continue_conversation, request.user_id, messages, reply)
        else:
            print("[WARN] No BackgroundTasks object available. Using asyncio.create_task.")
            asyncio.create_task(continue_conversation(request.user_id, messages, reply))

    return {
        "reply": final_reply,
        "persona": f"synapse_{target}",
        "memory_method": retrieval_method,
        "model": model_used,
    }


# --- Async Gateway Processing Pipeline ---


async def process_message_pipeline(user_msg: str, chat_id: str) -> str:
    target = _resolve_target(chat_id)

    chat_req = ChatRequest(
        message=user_msg,
        user_id=chat_id,
        session_type="safe",  # default
    )
    result = await persona_chat(chat_req, target, None)
    return result.get("reply", "")


async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
    task = MessageTask(
        task_id=str(uuid.uuid4()),
        chat_id=chat_id,
        user_message=combined_message,
        message_id=metadata.get("message_id", ""),
        sender_name=metadata.get("sender_name", ""),
        channel_id=metadata.get("channel_id", "whatsapp"),   # NEW: propagate channel_id
    )
    await task_queue.enqueue(task)


flood.set_callback(on_batch_ready)


# --- Background Worker ---


async def gentle_worker_loop():
    """Background maintenance loop."""
    print("[WORKER] Gentle Worker: running.")
    while True:
        try:
            battery = psutil.sensors_battery()
            is_plugged = battery.power_plugged if battery else True
            cpu_load = psutil.cpu_percent(interval=None)

            if is_plugged and cpu_load < 20.0:
                brain.prune_graph()
                conflicts.prune_conflicts()
                await asyncio.sleep(600)
            else:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[WARN] Worker: {e}")
            await asyncio.sleep(60)


# --- WhatsApp Bridge Store ---


def normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(ch for ch in str(raw) if ch.isdigit())


def validate_bridge_token(request: Request) -> None:
    bridge_token = os.environ.get("WHATSAPP_BRIDGE_TOKEN")
    if bridge_token:
        provided = request.headers.get("x-bridge-token")
        if provided != bridge_token:
            raise HTTPException(status_code=401, detail="Invalid bridge token")


def validate_api_key(request: Request) -> None:
    """Validates the API key for protected endpoints."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        provided = request.headers.get("x-api-key")
        if provided != api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")


def ensure_bridge_db() -> None:
    BRIDGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbound_messages (
                message_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                from_phone TEXT NOT NULL,
                to_phone TEXT,
                conversation_id TEXT,
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                reply TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.commit()


def get_inbound_message(message_id: str) -> dict[str, Any] | None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM inbound_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    return dict(row) if row else None


def insert_inbound_message(
    *,
    message_id: str,
    channel: str,
    from_phone: str,
    to_phone: str | None,
    conversation_id: str | None,
    text: str,
    status: str,
) -> None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO inbound_messages
            (message_id, channel, from_phone, to_phone, conversation_id, text, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (message_id, channel, from_phone, to_phone, conversation_id, text, status),
        )
        conn.commit()


def update_inbound_message(
    message_id: str,
    *,
    status: str | None = None,
    task_id: str | None = None,
    reply: str | None = None,
    error: str | None = None,
) -> None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute(
            """
            UPDATE inbound_messages
            SET status = COALESCE(?, status),
                task_id = COALESCE(?, task_id),
                reply = COALESCE(?, reply),
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
            """,
            (status, task_id, reply, error, message_id),
        )
        conn.commit()


# --- App Lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[MEM] Booting Antigravity Gateway v2...")
    ensure_bridge_db()
    worker_task = asyncio.create_task(gentle_worker_loop())

    # Start channel adapters — all within uvicorn's event loop (asyncio.create_task inside)
    await channel_registry.start_all()

    app.state.worker = MessageWorker(
        queue=task_queue,
        channel_registry=channel_registry,  # WA-02: WhatsAppChannel handles all dispatch
        process_fn=process_message_pipeline,
        num_workers=2,
    )
    await app.state.worker.start()
    print("[INFO] Async Gateway Pipeline started.")

    yield

    print("[STOP] Shutting down...")
    brain.save_graph()
    worker_task.cancel()
    await channel_registry.stop_all()   # NEW: stop all channels before worker
    if hasattr(app.state, "worker"):
        await app.state.worker.stop()
    with suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(lifespan=lifespan)

# --- CORS Configuration ---
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ===========================================
#  ROUTES
# ===========================================


@app.get("/")
def root():
    return {"status": "online", "soul": "operational", "version": "v2.0"}


@app.get("/health")
def health():
    return {
        "graph_nodes": brain.number_of_nodes(),
        "graph_edges": brain.number_of_edges(),
        "toxic_model_loaded": toxic_scorer.is_loaded(),
        "memory_db": get_db_stats(),
        "pending_conflicts": len(
            [c for c in conflicts.pending_conflicts if c["status"] == "pending"]
        ),
        "model": SynapseConfig.load().model_mappings.get("casual", {}).get("model", "unset"),
        "architecture": {
            "casual": SynapseConfig.load().model_mappings.get("casual", {}).get("model", "unset"),
            "code": SynapseConfig.load().model_mappings.get("code", {}).get("model", "unset"),
            "analysis": SynapseConfig.load().model_mappings.get("analysis", {}).get("model", "unset"),
            "review": SynapseConfig.load().model_mappings.get("review", {}).get("model", "unset"),
        },
    }


# --- Channel Abstraction Layer Routes ---


@app.post("/channels/{channel_id}/webhook")
async def unified_webhook(channel_id: str, request: Request):
    """
    CHAN-04: Unified inbound webhook for all channels.
    Validates channel is registered, normalizes payload to ChannelMessage,
    feeds FloodGate pipeline with channel_id in metadata.
    """
    channel = channel_registry.get(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not registered")

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    msg: ChannelMessage = await channel.receive(raw)

    if dedup.is_duplicate(msg.message_id or raw.get("message_id", "")):
        return {"status": "skipped", "reason": "duplicate", "accepted": True}

    await flood.incoming(
        chat_id=msg.chat_id,
        message=msg.text,
        metadata={
            "message_id": msg.message_id,
            "sender_name": msg.sender_name,
            "channel_id": msg.channel_id,    # CRITICAL: must be in metadata for on_batch_ready
        },
    )
    return {"status": "queued", "accepted": True, "task_queue_depth": task_queue.pending_count}


@app.post("/whatsapp/enqueue")
async def whatsapp_enqueue_shim(request: Request):
    """
    CHAN-05: Backwards-compatible shim. Delegates to unified_webhook with channel_id='whatsapp'.
    Existing webhook configurations do NOT need to change.
    """
    return await unified_webhook("whatsapp", request)


# --- WhatsApp Async Bridge ---
# NOTE: /whatsapp/enqueue replaces the previously disabled Celery-based endpoint.
# Messages now handled by FloodGate + TaskQueue in gateway/ via unified_webhook above.


@app.get("/whatsapp/jobs/{message_id}")
def whatsapp_job_status(message_id: str):
    row = get_inbound_message(message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


@app.post("/whatsapp/loop-test")
async def whatsapp_loop_test(payload: WhatsAppLoopTestRequest, request: Request):
    """
    Validate outbound loop path from Python -> WhatsApp bridge.
    Phase 4 will implement Baileys bridge. Currently returns 501.
    Uses --dry-run by default to avoid sending real messages.
    """
    validate_bridge_token(request)

    target = normalize_phone(payload.target)
    if not target:
        raise HTTPException(status_code=400, detail="target is required")

    raise HTTPException(
        status_code=501,
        detail="WhatsApp send via CLI not available — Phase 4 will implement Baileys bridge",
    )


# --- OpenAI Compatibility Layer ---


class OpenAIRequest(BaseModel):
    model: str = "default"
    messages: list[dict]
    temperature: float | None = 0.7
    max_tokens: int | None = 500
    user: str | None = "the_creator"


@app.post("/chat")
@app.post("/v1/chat/completions")
async def chat_webhook(request: Request):
    validate_api_key(request)
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "reason": "invalid_json"}

    messages = body.get("messages", [])
    if not messages:
        if "message" in body:
            user_msg = body["message"]
        else:
            return {"status": "error", "reason": "no_messages"}
    else:
        user_msg = None
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break

    if not user_msg:
        return {"status": "skipped", "reason": "no_user_message"}

    chat_id = (
        body.get("chat_id")
        or body.get("from")
        or body.get("user")
        or request.headers.get("X-Chat-Id", "")
        or body.get("user_id", "")
    )
    message_id = body.get("message_id", str(uuid.uuid4()))
    sender_name = body.get("sender_name", chat_id)
    is_from_me = body.get("fromMe", False)

    if is_from_me:
        return {"status": "skipped", "reason": "own_message"}

    if not str(user_msg).strip():
        return {"status": "skipped", "reason": "empty"}

    if dedup.is_duplicate(message_id):
        # We pretend it queued but do not actually queue
        return {"status": "skipped", "reason": "duplicate", "accepted": True}

    await flood.incoming(
        chat_id=chat_id,
        message=user_msg,
        metadata={
            "message_id": message_id,
            "sender_name": sender_name,
        },
    )

    return {
        "status": "queued",
        "accepted": True,
        "task_queue_depth": task_queue.pending_count,
    }


# --- Persona Chat Endpoints (dynamically registered from personas.yaml) ---


def _make_persona_handler(persona_id: str):
    async def handler(
        request: ChatRequest, background_tasks: BackgroundTasks, http_request: Request
    ):
        validate_api_key(http_request)
        return await persona_chat(request, persona_id, background_tasks)

    handler.__name__ = f"chat_{persona_id}"
    return handler


for _p in PERSONAS_CONFIG["personas"]:
    app.add_api_route(
        f"/chat/{_p['id']}",
        _make_persona_handler(_p["id"]),
        methods=["POST"],
        summary=_p.get("description", f"Chat as {_p['id']}"),
    )


@app.get("/gateway/status")
async def gateway_status():
    return {
        "queue": task_queue.get_stats(),
        "workers": app.state.worker.num_workers if hasattr(app.state, "worker") else 0,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


# --- Persona Management ---


@app.post("/persona/rebuild")
async def rebuild_personas(request: Request):
    """Rebuild all persona profiles using SBS."""
    validate_api_key(request)
    try:
        for sbs in sbs_registry.values():
            sbs.force_batch(full_rebuild=True)
        return {"status": "rebuilt", "personas": list(sbs_registry.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@app.get("/persona/status")
def persona_status():
    """Show current persona profile stats from SBS."""
    stats = {pid: sbs.get_profile_summary() for pid, sbs in sbs_registry.items()}
    db = get_db_stats()
    return {"profiles": stats, "memory_db": db}


@app.get("/sbs/status")
def sbs_status():
    """Show live SBS stats for sci-fi dashboard."""
    stats = {pid: sbs.get_profile_summary() for pid, sbs in sbs_registry.items()}
    return {"profiles": stats}


# --- Memory Endpoints (preserved from v1) ---


@app.post("/ingest")
def ingest_fact(
    subject: str,
    relation: str,
    object_entity: str,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Ingest a structured fact into the knowledge graph."""
    validate_api_key(request)
    brain.add_node(subject)
    brain.add_node(object_entity)
    brain.add_relation(subject, relation, object_entity)
    background_tasks.add_task(brain.save_graph)
    return {
        "status": "received",
        "fact": f"{subject} --[{relation}]--> {object_entity}",
    }


@app.post("/add")
async def add_memory(item: MemoryItem, background_tasks: BackgroundTasks, request: Request):
    """Unstructured memory -> LLM -> triple extraction -> graph."""
    validate_api_key(request)
    print(f"[ADD] Ingesting: {item.content[:60]}...")

    try:
        messages = [
            {
                "role": "system",
                "content": 'Extract the core fact as a triple. JSON format: {"s": "Subject", "r": "Relation", "o": "Object"}. No other text.',
            },
            {"role": "user", "content": item.content},
        ]
        extraction = await call_gemini_flash(messages, temperature=0.1, max_tokens=1000)
        extraction = extraction.strip()

        import ast

        data = None
        if "{" in extraction and "}" in extraction:
            start = extraction.find("{")
            end = extraction.rfind("}") + 1
            json_str = extraction[start:end]
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                with suppress(Exception):
                    data = ast.literal_eval(json_str)

        if data:
            s, r, o = data.get("s"), data.get("r"), data.get("o")
            if s and r and o:
                brain.add_node(s)
                brain.add_node(o)
                brain.add_relation(s, r, o)
                background_tasks.add_task(brain.save_graph)
                return {"status": "memorized", "triple": f"{s} -[{r}]-> {o}"}

    except Exception as e:
        print(f"[WARN] Extraction Error: {e}")

    return {"status": "failed_extraction", "content": item.content}


@app.post("/query")
async def query_memory(item: QueryItem, request: Request):
    """Query knowledge graph + vector memory."""
    validate_api_key(request)
    print(f"[SEARCH] Query: {item.text}")

    # Graph search
    graph_results = []
    try:
        tokens = item.text.split()
        for token in tokens:
            if brain.graph.has_node(token):
                graph_results.append(token)
                for n in brain.graph.neighbors(token):
                    graph_results.append(f"{token} -> {n}")
    except Exception:
        pass

    # Vector search
    memory_results = {}
    with suppress(Exception):
        memory_results = query_memories(item.text, limit=3)

    return {
        "graph": graph_results,
        "memory": memory_results,
        "graph_count": len(graph_results),
    }


if __name__ == "__main__":
    import uvicorn

    BIND_HOST = os.environ.get("API_BIND_HOST", "0.0.0.0")
    uvicorn.run(app, host=BIND_HOST, port=8000)
