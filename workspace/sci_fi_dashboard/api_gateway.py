"""
Antigravity Gateway v2 -- The Soul + Brain Assembly Line

Thin orchestrator: app creation, lifespan, middleware, router includes.
All business logic lives in dedicated modules:
  - _deps.py           : shared singleton registry
  - schemas.py         : Pydantic request models
  - middleware.py       : auth, rate limiting, body size
  - llm_wrappers.py    : LLM call helpers, traffic cop
  - chat_pipeline.py   : persona_chat() core
  - pipeline_helpers.py: message pipeline, background workers
  - whatsapp_bridge.py : bridge SQLite store
  - channel_setup.py   : optional channel registration
  - routes/            : FastAPI APIRouter modules
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path as _Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.channel_setup import register_optional_channels
from sci_fi_dashboard.middleware import BodySizeLimitMiddleware, LoopbackOnlyMiddleware
from sci_fi_dashboard.pipeline_helpers import (
    gentle_worker_loop,
    process_message_pipeline,
)

# Route modules
from sci_fi_dashboard.routes import (
    agents as agents_routes,
)
from sci_fi_dashboard.routes import (
    chat,
    health,
    knowledge,
    persona,
    sessions,
    websocket,
    whatsapp,
)
from sci_fi_dashboard.routes import (
    pipeline as pipeline_routes,
)
from sci_fi_dashboard.whatsapp_bridge import ensure_bridge_db

logger = logging.getLogger(__name__)

# Register optional channels (Telegram/Discord/Slack) if tokens configured
register_optional_channels()


# ---------------------------------------------------------------------------
# App Lifecycle
# ---------------------------------------------------------------------------

# --- Embedding Provider Status ---
try:
    from sci_fi_dashboard.embedding import get_provider as _get_emb_provider  # noqa: E402

    _emb_provider = _get_emb_provider()
    if _emb_provider:
        _info = _emb_provider.info()
        logger.info(
            "[Embedding] Provider: %s | Model: %s | Dims: %s",
            _info.name,
            _info.model,
            _info.dimensions,
        )
    else:
        logger.warning("[Embedding] No provider available -- semantic search disabled")
except Exception as _emb_exc:
    logger.warning("[Embedding] Provider init failed: %s", _emb_exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[MEM] Booting Antigravity Gateway v2...")
    ensure_bridge_db()
    worker_task = asyncio.create_task(gentle_worker_loop())

    # Start channel adapters
    await deps.channel_registry.start_all()

    # Wire retry queue into WhatsApp channel
    from channels.whatsapp import WhatsAppChannel
    from gateway.retry_queue import RetryQueue

    wa_ch = deps.channel_registry.get("whatsapp")
    if isinstance(wa_ch, WhatsAppChannel):
        _retry_queue = RetryQueue(data_root=deps._synapse_cfg.data_root)
        wa_ch._retry_queue = _retry_queue
        await _retry_queue.start(wa_ch)
        app.state.retry_queue = _retry_queue
        print("[INFO] WhatsApp retry queue started.")

    from gateway.worker import MessageWorker

    app.state.worker = MessageWorker(
        queue=deps.task_queue,
        channel_registry=deps.channel_registry,
        process_fn=process_message_pipeline,
        num_workers=2,
    )
    await app.state.worker.start()
    print("[INFO] Async Gateway Pipeline started.")

    # Phase 3: Initialize ToolRegistry
    if deps._TOOL_REGISTRY_AVAILABLE:
        try:
            from sci_fi_dashboard.tool_registry import (
                ToolRegistry,
                register_builtin_tools,
            )

            deps.tool_registry = ToolRegistry()
            register_builtin_tools(deps.tool_registry, deps.memory_engine, deps.WORKSPACE_ROOT)
            deps._tool_logger.info("ToolRegistry initialized")
        except Exception as exc:
            deps._tool_logger.warning("ToolRegistry init failed (non-fatal): %s", exc)
            deps.tool_registry = None
    else:
        deps._tool_logger.info("tool_registry module not available -- tool execution loop disabled")

    # Phase 4: Initialize safety pipeline
    if deps._TOOL_SAFETY_AVAILABLE:
        try:
            from sci_fi_dashboard.tool_safety import (
                ToolAuditLogger,
                ToolHookRunner,
            )

            deps.hook_runner = ToolHookRunner()
            audit_dir = str(deps._synapse_cfg.data_root / "audit")
            deps.audit_logger = ToolAuditLogger(audit_dir)

            async def _audit_hook(tool_name, args, result, duration_ms):
                if deps.audit_logger:
                    deps.audit_logger.log_tool_call(
                        tool_name=tool_name,
                        args=args,
                        result_content=result.get("content", ""),
                        is_error=result.get("is_error", False),
                        duration_ms=duration_ms,
                        sender_id="unknown",
                        chat_id="unknown",
                    )

            deps.hook_runner.register_after(_audit_hook)
            deps._tool_logger.info("Tool safety pipeline initialized")
        except Exception as exc:
            deps._tool_logger.warning("Tool safety init failed (non-fatal): %s", exc)
    else:
        deps._tool_logger.info("tool_safety module not available -- safety pipeline disabled")

    # Initialize SessionActorQueue
    from gateway.session_actor import SessionActorQueue

    app.state.session_actor_queue = SessionActorQueue()

    # Initialize AgentRegistry + SubAgentRunner (Phase 3: SubAgent System)
    from sci_fi_dashboard.subagent import AgentRegistry
    from sci_fi_dashboard.subagent.runner import SubAgentRunner

    deps.agent_registry = AgentRegistry()
    deps.agent_runner = SubAgentRunner(
        registry=deps.agent_registry,
        channel_registry=deps.channel_registry,
        llm_router=deps.synapse_llm_router,
    )
    logger.info("[SubAgent] SubAgent system initialized (registry + runner)")

    # Initialize models catalog
    from models_catalog import ensure_models_catalog

    catalog_path, action = ensure_models_catalog(deps._synapse_cfg)
    print(f"[INFO] Models catalog: {catalog_path} ({action})")

    # Initialize GatewayWebSocket
    from gateway.ws_server import GatewayWebSocket

    app.state.gateway_ws = GatewayWebSocket(
        config=deps._synapse_cfg,
        task_queue=deps.task_queue,
        channel_registry=deps.channel_registry,
        models_catalog_path=catalog_path,
    )

    # MCP Client Initialization
    from mcp_client import SynapseMCPClient
    from mcp_config import load_mcp_config

    _mcp_config = load_mcp_config(deps._synapse_cfg.mcp)
    app.state.mcp_client = None
    if _mcp_config.enabled:
        app.state.mcp_client = SynapseMCPClient()
        await app.state.mcp_client.connect_all(_mcp_config)
        logger.info(
            "[MCP] Connected. Available tools: %d",
            len(app.state.mcp_client.list_all_tools()),
        )
        app.state.worker.mcp_client = app.state.mcp_client

    # Proactive Awareness Engine
    from proactive_engine import ProactiveAwarenessEngine

    app.state.proactive_engine = None
    if _mcp_config.enabled and _mcp_config.proactive.enabled and app.state.mcp_client:
        app.state.proactive_engine = ProactiveAwarenessEngine(
            app.state.mcp_client, _mcp_config.proactive
        )
        await app.state.proactive_engine.start()
        deps._proactive_engine = app.state.proactive_engine
        logger.info("[PROACTIVE] Engine started")

    # CronService — proactive scheduled messages (wired to persona_chat via execute_fn)
    app.state.cron_service = None
    try:
        from sci_fi_dashboard.chat_pipeline import persona_chat
        from sci_fi_dashboard.cron import CronService
        from sci_fi_dashboard.schemas import ChatRequest

        async def _cron_execute_fn(message: str, session_key: str, **kwargs) -> str:
            """Adapter: CronService execute_fn -> persona_chat()."""
            timeout_s = float(kwargs.pop("timeout_seconds", 300))
            req = ChatRequest(
                message=message,
                session_key=session_key,
                user_id="the_creator",
            )
            try:
                result = await asyncio.wait_for(
                    persona_chat(req, "the_creator"),
                    timeout=timeout_s,
                )
            except TimeoutError:
                logger.warning(
                    "[Cron] Job timed out (session=%s, timeout=%ss)",
                    session_key,
                    timeout_s,
                )
                raise
            return result.get("reply", "") if isinstance(result, dict) else str(result or "")

        app.state.cron_service = CronService(
            agent_id="the_creator",
            data_root=str(deps._synapse_cfg.data_root),
            execute_fn=_cron_execute_fn,
            channel_registry=deps.channel_registry,
        )
        await app.state.cron_service.start()
        logger.info("[CRON] CronService (cron/) started")
    except Exception as _cron_exc:
        logger.warning("[CRON] CronService init failed (non-fatal): %s", _cron_exc)

    # DiaryEngine — generates diary entries on session archive
    try:
        deps.init_diary_engine()
    except Exception as _diary_exc:
        logger.warning("[Diary] DiaryEngine init failed (non-fatal): %s", _diary_exc)

    # Phase 1 (v2.0): Skill Architecture
    if deps._SKILL_SYSTEM_AVAILABLE:
        try:
            from sci_fi_dashboard.skills.registry import SkillRegistry
            from sci_fi_dashboard.skills.router import SkillRouter
            from sci_fi_dashboard.skills.watcher import SkillWatcher

            _skills_dir = deps._synapse_cfg.data_root / "skills"
            _skills_dir.mkdir(parents=True, exist_ok=True)

            deps.skill_registry = SkillRegistry(_skills_dir)
            deps.skill_router = SkillRouter()
            deps.skill_router.update_skills(deps.skill_registry.list_skills())

            # Wire hot-reload: when watcher triggers reload, also update router embeddings
            _original_reload = deps.skill_registry.reload

            def _reload_with_router_update():
                _original_reload()
                if deps.skill_router is not None:
                    deps.skill_router.update_skills(deps.skill_registry.list_skills())

            deps.skill_registry.reload = _reload_with_router_update

            deps.skill_watcher = SkillWatcher(
                skills_dir=_skills_dir,
                registry=deps.skill_registry,
                debounce_seconds=2.0,
            )
            deps.skill_watcher.start()

            _skill_count = len(deps.skill_registry.list_skills())
            logger.info(
                "[Skills] Skill system initialized: %d skill(s) loaded from %s",
                _skill_count,
                _skills_dir,
            )
        except Exception as exc:
            logger.warning("[Skills] Skill system init failed (non-fatal): %s", exc)
            deps.skill_registry = None
            deps.skill_router = None
            deps.skill_watcher = None
    else:
        logger.info("[Skills] skills module not available -- skill system disabled")

    yield

    # --- Shutdown ---
    print("[STOP] Shutting down...")

    # Stop skill watcher
    if deps.skill_watcher is not None:
        with suppress(Exception):
            deps.skill_watcher.stop()

    deps.brain.save_graph()

    for persona_id, sbs in deps.sbs_registry.items():
        try:
            sbs.profile_mgr.snapshot_version()
            print(f"[SBS] Shutdown snapshot saved for {persona_id}")
        except Exception as e:
            print(f"[SBS] Shutdown snapshot failed for {persona_id}: {e}")

    worker_task.cancel()
    if hasattr(app.state, "proactive_engine") and app.state.proactive_engine:
        await app.state.proactive_engine.stop()
    if hasattr(app.state, "cron_service") and app.state.cron_service:
        await app.state.cron_service.stop()
    if hasattr(app.state, "mcp_client") and app.state.mcp_client:
        await app.state.mcp_client.disconnect_all()
    if hasattr(app.state, "retry_queue"):
        await app.state.retry_queue.stop()
    await deps.channel_registry.stop_all()
    if hasattr(app.state, "worker"):
        await app.state.worker.stop()
    with suppress(asyncio.CancelledError):
        await worker_task


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)

# CORS
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(LoopbackOnlyMiddleware)

# Include routers
from sci_fi_dashboard.routes import cron as cron_routes  # noqa: E402

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(whatsapp.router)
app.include_router(persona.router)
app.include_router(knowledge.router)
app.include_router(sessions.router)
app.include_router(websocket.router)
app.include_router(pipeline_routes.router)
app.include_router(agents_routes.router)
app.include_router(cron_routes.router)

# Dashboard static files
_static_dir = _Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# TTS outbound media files (OGG voice notes served to Baileys bridge)
from synapse_config import resolve_data_root as _resolve_data_root  # noqa: E402

_tts_media_dir = _resolve_data_root() / "state" / "media" / "tts_outbound"
_tts_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media/tts_outbound", StaticFiles(directory=str(_tts_media_dir)), name="tts_outbound")

# Image generation outbound media files (PNG images served to Baileys bridge)
_img_gen_media_dir = _resolve_data_root() / "state" / "media" / "image_gen_outbound"
_img_gen_media_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/media/image_gen_outbound",
    StaticFiles(directory=str(_img_gen_media_dir)),
    name="image_gen_outbound",
)


@app.get("/dashboard")
async def dashboard():
    return RedirectResponse(url="/static/dashboard/index.html")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BIND_HOST = os.environ.get("API_BIND_HOST", "127.0.0.1")
    uvicorn.run(app, host=BIND_HOST, port=8000)
