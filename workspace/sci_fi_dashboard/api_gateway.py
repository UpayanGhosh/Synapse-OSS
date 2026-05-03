"""
Synapse Gateway -- The Soul + Brain Assembly Line

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
import threading
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
from sci_fi_dashboard.observability import apply_logging_config
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
    playground,
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


class _NoopProactiveMCPClient:
    async def call_tool(self, *_args, **_kwargs) -> str:
        return "[]"


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
    apply_logging_config(deps._synapse_cfg)
    print("[Synapse] Booting gateway...")
    ensure_bridge_db()
    worker_task = asyncio.create_task(gentle_worker_loop())

    # Start channel adapters
    await deps.channel_registry.start_all()

    # Wire retry queue into WhatsApp channel
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel
    from gateway.retry_queue import RetryQueue

    wa_ch = deps.channel_registry.get("whatsapp")
    if isinstance(wa_ch, WhatsAppChannel):
        _retry_queue = RetryQueue(data_root=deps._synapse_cfg.data_root)
        wa_ch._retry_queue = _retry_queue
        await _retry_queue.start(wa_ch)
        app.state.retry_queue = _retry_queue
        print("[INFO] WhatsApp retry queue started.")

    # Phase 16 BRIDGE-02/03: Bridge /health poller with gated restart
    app.state.bridge_health_poller = None
    try:
        if (
            isinstance(wa_ch, WhatsAppChannel)
            and hasattr(wa_ch, "_supervisor")
            and wa_ch._supervisor is not None
        ):
            from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller
            from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_poller_emitter

            bridge_cfg = getattr(deps._synapse_cfg, "bridge", None) or {}
            poller = BridgeHealthPoller(
                channel=wa_ch,
                supervisor=wa_ch._supervisor,
                interval_s=float(bridge_cfg.get("healthPollIntervalSeconds", 30.0)),
                failures_before_restart=int(bridge_cfg.get("healthFailuresBeforeRestart", 3)),
                timeout_s=float(bridge_cfg.get("healthPollTimeoutSeconds", 5.0)),
                grace_window_s=float(bridge_cfg.get("healthGraceWindowSeconds", 60.0)),
                emitter=_get_poller_emitter(),
            )
            wa_ch._bridge_health_poller = poller  # surfaces in get_status as bridge_health
            await poller.start()
            app.state.bridge_health_poller = poller
            logger.info(
                "[BRIDGE_HEALTH] Poller started (interval=%ss, threshold=%d)",
                bridge_cfg.get("healthPollIntervalSeconds", 30),
                bridge_cfg.get("healthFailuresBeforeRestart", 3),
            )
    except Exception as _poller_exc:
        logger.warning("[BRIDGE_HEALTH] Poller init failed (non-fatal): %s", _poller_exc)
        app.state.bridge_health_poller = None

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

            # Claude-Code-like toolkit (bash_exec, edit_file, grep, glob, edit_synapse_config,
            # list_directory). Owner-gated and Sentinel-gated by factory; safe to register
            # unconditionally — non-owner sessions see only read-type tools.
            try:
                from sci_fi_dashboard.tool_sysops import register_sysops_tools

                register_sysops_tools(deps.tool_registry, deps.memory_engine, deps.WORKSPACE_ROOT)
                deps._tool_logger.info("sysops tools registered")
            except Exception as exc:
                deps._tool_logger.warning("sysops registration failed: %s", exc)

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
    deps._proactive_engine = None
    if _mcp_config.proactive.enabled:
        proactive_client = app.state.mcp_client or _NoopProactiveMCPClient()
        app.state.proactive_engine = ProactiveAwarenessEngine(
            proactive_client, _mcp_config.proactive
        )
        await app.state.proactive_engine.start()
        deps._proactive_engine = app.state.proactive_engine
        logger.info(
            "[PROACTIVE] Engine started (%s)",
            "mcp" if app.state.mcp_client else "memory-only",
        )

    # CronService — proactive scheduled messages (wired to persona_chat via execute_fn)
    app.state.cron_service = None
    try:
        from sci_fi_dashboard.chat_pipeline import persona_chat
        from sci_fi_dashboard.cron import CronService
        from sci_fi_dashboard.schemas import ChatRequest

        async def _cron_execute_fn(message: str, session_key: str, **kwargs) -> str:
            """Adapter: CronService execute_fn -> persona_chat()."""
            timeout_s = float(kwargs.pop("timeout_seconds", 300))
            channel_id = str(kwargs.pop("channel_id", "") or "")
            user_id = str(kwargs.pop("user_id", "") or "the_creator")
            req = ChatRequest(
                message=message,
                session_key=session_key,
                user_id=user_id,
                channel_id=channel_id or None,
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
        deps.cron_service = app.state.cron_service
        await app.state.cron_service.start()
        logger.info("[CRON] CronService (cron/) started")
    except Exception as _cron_exc:
        deps.cron_service = None
        logger.warning("[CRON] CronService init failed (non-fatal): %s", _cron_exc)

    # Phase 16 HEART-01..05: Heartbeat runner — scheduled outbound pings
    app.state.heartbeat_runner = None
    try:
        heartbeat_cfg = getattr(deps._synapse_cfg, "heartbeat", None) or {}
        if heartbeat_cfg.get("enabled", False):
            from sci_fi_dashboard.chat_pipeline import persona_chat
            from sci_fi_dashboard.gateway.heartbeat_runner import HeartbeatRunner
            from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_heartbeat_emitter
            from sci_fi_dashboard.schemas import ChatRequest

            async def _heartbeat_reply_adapter(prompt: str) -> str:
                """Adapter: heartbeat prompt -> persona_chat -> LLM reply text.

                Uses session_key="heartbeat" so heartbeat cycles never appear
                in user-visible conversation history.
                """
                req = ChatRequest(
                    message=prompt,
                    session_key="heartbeat",
                    user_id="the_creator",
                )
                try:
                    result = await asyncio.wait_for(
                        persona_chat(req, "the_creator"),
                        timeout=60.0,
                    )
                except TimeoutError:
                    logger.warning("[HEARTBEAT] persona_chat timed out after 60s")
                    return ""
                raw = str(result.get("reply", "") if isinstance(result, dict) else (result or ""))
                # Strip pipeline metadata footer (--- **Context Usage:**...) before
                # strip_heartbeat_token sees the reply, otherwise HEARTBEAT_OK residue
                # causes the runner to forward the footer to WhatsApp.
                sep = raw.find("\n\n---\n")
                return raw[:sep] if sep != -1 else raw

            app.state.heartbeat_runner = HeartbeatRunner(
                channel_registry=deps.channel_registry,
                cfg=deps._synapse_cfg,
                get_reply_fn=_heartbeat_reply_adapter,
                emitter=_get_heartbeat_emitter(),
                interval_s=float(heartbeat_cfg.get("interval_s", 1800)),
                channel_name="whatsapp",
            )
            await app.state.heartbeat_runner.start()
            logger.info(
                "[HEARTBEAT] Runner started (interval=%ss, recipients=%d)",
                heartbeat_cfg.get("interval_s", 1800),
                len(heartbeat_cfg.get("recipients", [])),
            )
        else:
            logger.info("[HEARTBEAT] Disabled (heartbeat.enabled=false in synapse.json)")
    except Exception as _heart_exc:
        logger.warning("[HEARTBEAT] Runner init failed (non-fatal): %s", _heart_exc)
        app.state.heartbeat_runner = None

    # GentleWorker — thermal-guarded proactive check-ins (PROA-01/02/03/04)
    app.state.gentle_worker = None
    try:
        from sci_fi_dashboard.gentle_worker import GentleWorker

        app.state.gentle_worker = GentleWorker(
            graph=deps.brain,
            cron_service=app.state.cron_service,
            proactive_engine=deps._proactive_engine,
            channel_registry=deps.channel_registry,
        )
        # Capture the main event loop so heavy_task_proactive_checkin can
        # hop into it via asyncio.run_coroutine_threadsafe (PROA-02 safety).
        app.state.gentle_worker._event_loop = asyncio.get_running_loop()
        app.state.gentle_worker_thread = threading.Thread(
            target=app.state.gentle_worker.start,
            daemon=True,
            name="gentle-worker",
        )
        app.state.gentle_worker_thread.start()
        logger.info("[GentleWorker] Started in background thread")
    except Exception as _gw_exc:
        logger.warning("[GentleWorker] init failed (non-fatal): %s", _gw_exc)
        app.state.gentle_worker = None

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
            seeded = SkillRegistry.seed_bundled_skills(_skills_dir)
            if seeded:
                logger.info("[Skills] Seeded %d bundled skill(s)", seeded)

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

    # Phase 3 (auto-flush): Background scanner for idle/oversized sessions.
    # Runs as a FastAPI lifespan task so flush cadence follows gateway uptime,
    # not battery/CPU state (intentionally NOT inside gentle_worker_loop).
    from sci_fi_dashboard.auto_flush import SessionAutoFlusher  # noqa: PLC0415
    from sci_fi_dashboard.pipeline_helpers import _handle_new_command  # noqa: PLC0415

    _auto_flush_cfg = deps._synapse_cfg.session_auto_flush
    _flusher = SessionAutoFlusher(
        data_root=deps._synapse_cfg.data_root,
        agent_ids=list(deps.sbs_registry.keys()),
        handle_new_command=_handle_new_command,
        idle_threshold=_auto_flush_cfg.idle_seconds,
        count_threshold=_auto_flush_cfg.message_count,
        min_messages=_auto_flush_cfg.min_messages,
        check_interval=_auto_flush_cfg.check_interval_seconds,
    )
    if _auto_flush_cfg.enabled:
        await _flusher.start()
    else:
        logger.info("[AutoFlush] Disabled via config (session.auto_flush_enabled=false)")
    app.state.auto_flusher = _flusher

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

    if hasattr(app.state, "gentle_worker") and app.state.gentle_worker is not None:
        app.state.gentle_worker.is_running = False
        # Thread is daemon — will exit with process; no join needed

    worker_task.cancel()
    if hasattr(app.state, "proactive_engine") and app.state.proactive_engine:
        await app.state.proactive_engine.stop()
    if hasattr(app.state, "cron_service") and app.state.cron_service:
        await app.state.cron_service.stop()
    if hasattr(app.state, "mcp_client") and app.state.mcp_client:
        await app.state.mcp_client.disconnect_all()
    if hasattr(app.state, "retry_queue"):
        await app.state.retry_queue.stop()
    # Phase 16: stop heartbeat runner + bridge health poller BEFORE channel_registry.stop_all
    if hasattr(app.state, "auto_flusher") and app.state.auto_flusher is not None:
        with suppress(Exception):
            await app.state.auto_flusher.stop()
    if hasattr(app.state, "heartbeat_runner") and app.state.heartbeat_runner is not None:
        with suppress(Exception):
            await app.state.heartbeat_runner.stop()
    if hasattr(app.state, "bridge_health_poller") and app.state.bridge_health_poller is not None:
        with suppress(Exception):
            await app.state.bridge_health_poller.stop()
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
app.include_router(playground.router)

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
