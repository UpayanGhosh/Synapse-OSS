# Phase 10: Cron Wiring + Web Control Panel — Research

**Researched:** 2026-04-09
**Domain:** Asyncio scheduler wiring, FastAPI SSE, vanilla JS dashboard, loopback security
**Confidence:** HIGH

---

## Summary

Phase 10 has two tightly coupled halves: wiring the existing `CronService` (in `sci_fi_dashboard/cron/`) to `persona_chat()` so scheduled jobs actually run through the full pipeline, and extending the existing dashboard (`static/dashboard/`) with panels for sessions, cron jobs, memory stats, and model routing decisions.

The most important discovery is that the **cron infrastructure is already ~85% built**. `sci_fi_dashboard/cron/` (8 files: `service.py`, `isolated_agent.py`, `store.py`, `schedule.py`, `delivery.py`, `run_log.py`, `alerting.py`, `stagger.py`, `types.py`) exists and is fully designed. However `api_gateway.py` still imports and instantiates the **old** `cron_service.py` (top-level file), not the new `cron/` package. The new `CronService` requires an `execute_fn` parameter — a callable `(message, session_key, **kwargs) -> str` — which is not yet wired to `persona_chat()`. This is the primary gap for CRON-01 through CRON-04.

For the dashboard half, the existing `static/dashboard/index.html` (1867 lines) and `synapse.js` (1075 lines) already implement the SSE pipeline visualization, chat input bar (`POST /pipeline/send`), and node animation. What is **missing** is: active sessions panel (DASH-02), cron jobs panel (DASH-02), memory stats panel (DASH-02), model routing decisions panel (DASH-02), and loopback-only enforcement (DASH-04). The `GET /pipeline/events` SSE stream already works and already connects to `PipelineEventEmitter`. The cron module just needs to emit events to that same emitter to appear in the dashboard. There is no API route for cron CRUD yet (needed for DASH-02 job listing).

**Primary recommendation:** Wire new `cron/CronService` into `api_gateway.py` lifespan with an `execute_fn` adapter over `persona_chat()`, add a `GET /api/cron/jobs` route backed by the existing `CronService`, add a `LoopbackOnlyMiddleware` for dashboard routes, and extend the dashboard HTML/JS with four new panels — all without touching the existing SSE stream or breaking the pipeline visualization.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CRON-01 | Each cron job runs in an isolated agent context with separate memory | `cron/isolated_agent.py` + `SessionTarget.ISOLATED` already implement this; gap is `execute_fn` must create a fresh `ChatRequest` with a unique `session_key` |
| CRON-02 | CronService execute_fn is wired to persona_chat() in gateway lifespan | `api_gateway.py` currently imports old `cron_service.py`; must be replaced with `from sci_fi_dashboard.cron import CronService` + execute_fn adapter |
| CRON-03 | Isolated agents get recent memory context injected as system prefix | `run_isolated_agent()` already accepts `light_context` kwarg; `MemoryEngine.query()` can be called with the cron payload as query text before the `persona_chat()` call |
| CRON-04 | Cron jobs have configurable timeout and cleanup on failure | `CronPayload.timeout_seconds` (default 300) + `CronFailureAlert` + `RunLog` already implemented; `asyncio.wait_for()` wrapping the `execute_fn` call is the missing piece |
| DASH-01 | Dashboard shows real-time pipeline events via SSE | `GET /pipeline/events` SSE stream already works; cron job execution must call `get_emitter().emit("cron.job_start", ...)` and `cron.job_done` to appear in dashboard |
| DASH-02 | Dashboard displays active sessions, memory stats, and model routing decisions | `GET /api/sessions` already exists; `get_db_stats()` in `retriever.py` returns memory stats; `GET /api/cron/jobs` needs to be created; dashboard HTML panels need extending |
| DASH-03 | User can send messages from the dashboard (existing pipeline/send endpoint) | Already fully implemented: `POST /pipeline/send` in `routes/pipeline.py`, wired in dashboard JS |
| DASH-04 | Dashboard is loopback-only with session token auth | `api_gateway.py` binds to `127.0.0.1` by default via `API_BIND_HOST`; need a `LoopbackOnlyMiddleware` that returns 403 for non-loopback requests to `/dashboard` and `/static/dashboard/` |
| DASH-05 | Dashboard uses vanilla JS + Tailwind (no React build step) | Existing dashboard uses Tailwind CDN + vanilla JS — requirement is already met; must NOT add npm/node_modules to the new panels |

</phase_requirements>

---

## Standard Stack

### Core (already in project — no new installs needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `croniter` | already in use | Cron expression parsing + next-run calculation | Used in `cron/schedule.py`; already validates and computes next fires |
| `zoneinfo` | stdlib (Python 3.9+) | IANA timezone support | Used in `cron/schedule.py` for TZ-aware cron expressions |
| FastAPI / Starlette | `>=0.104.0` | SSE streaming, middleware | Project standard; `StreamingResponse` used in `routes/pipeline.py` |
| Tailwind CDN | via `<script src="https://cdn.tailwindcss.com">` | Dashboard styling | Already in `index.html`; DASH-05 explicitly requires this (no build step) |
| asyncio | stdlib | Timer loop, task isolation | All cron loops and `persona_chat()` are asyncio-native |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` | already in requirements | Webhook delivery for cron | Optional; `cron/delivery.py` already guards with `if httpx is None` |
| `pytest-asyncio` | already in tests | Async test support | Already used in `test_cron_service.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Tailwind CDN | Local Tailwind CSS | Local requires build step — DASH-05 explicitly forbids this |
| Custom SSE keep-alive | `asyncio.wait_for(timeout=25.0)` | Already implemented in `pipeline.py` — do not change |
| `asyncio.wait_for` for cron timeout | Custom signal-based timeout | `asyncio.wait_for` is already the pattern used for `dual_cognition_timeout` in the gateway |

**Installation:** None required. All dependencies already present.

---

## Architecture Patterns

### Recommended Structure for Phase 10 Changes

```
workspace/sci_fi_dashboard/
├── api_gateway.py              # CHANGE: replace cron_service import, add execute_fn adapter
├── cron/                       # EXISTING — do not restructure
│   ├── service.py              # EXISTING — already has full CRUD + timer loop
│   ├── isolated_agent.py       # EXISTING — isolated session execution
│   └── ...                     # 7 other files — no changes needed
├── middleware.py               # CHANGE: add LoopbackOnlyMiddleware
├── routes/
│   ├── pipeline.py             # EXISTING — SSE stream + /pipeline/send (no changes needed)
│   ├── cron.py                 # NEW: GET /api/cron/jobs, POST /api/cron/run/{id}
│   └── ...
└── static/dashboard/
    ├── index.html              # CHANGE: add 4 new panels (sessions, cron, memory, routing)
    └── synapse.js              # CHANGE: add panel data-fetch + SSE handlers for cron events
```

### Pattern 1: execute_fn Adapter in api_gateway.py lifespan

**What:** A thin async wrapper that adapts `persona_chat()` to the signature `(message: str, session_key: str, **kwargs) -> str` expected by `CronService`.

**When to use:** In the lifespan `async with` block, after `persona_chat` is available via `deps`.

**Example:**
```python
# In api_gateway.py lifespan, AFTER deps are initialized:
from sci_fi_dashboard.cron import CronService
from sci_fi_dashboard.schemas import ChatRequest

async def _cron_execute_fn(message: str, session_key: str, **kwargs) -> str:
    """Adapter: CronService execute_fn → persona_chat()"""
    timeout = kwargs.pop("timeout_seconds", 300)
    req = ChatRequest(
        message=message,
        session_key=session_key,  # isolated session per job (CRON-01)
        user_id="the_creator",
    )
    try:
        result = await asyncio.wait_for(
            deps.persona_chat(req, "the_creator"),
            timeout=float(timeout),
        )
    except asyncio.TimeoutError:
        logger.warning("[Cron] execute_fn timed out after %ss (session=%s)", timeout, session_key)
        raise
    if isinstance(result, dict):
        return result.get("reply", "")
    return str(result)

app.state.cron_service = CronService(
    agent_id="the_creator",
    data_root=str(deps._synapse_cfg.data_root),
    execute_fn=_cron_execute_fn,
    channel_registry=deps.channel_registry,
)
await app.state.cron_service.start()
```

**Critical detail:** The old `cron_service.py` (top-level) must be replaced — not added alongside. Both cannot be instantiated simultaneously or you get duplicate timer loops.

### Pattern 2: Session Key Isolation (CRON-01 + CRON-02)

**What:** Each job execution uses `session_key = f"cron-{job.id}-{uuid.hex[:8]}"` — already computed by `cron/service.py → _run_payload()`. The `session_key` flows into `ChatRequest` to prevent history contamination.

**When to use:** Always for `SessionTarget.ISOLATED` jobs (the default for cron).

**Key insight:** `persona_chat()` uses `request.session_key` (or `"default"` fallback) to key the conversation history cache via `deps.conversation_cache`. Passing a unique `session_key` per cron execution gives each job its own isolated memory slice automatically — no special memory isolation code needed beyond using the correct key.

### Pattern 3: Cron SSE Emission for DASH-01

**What:** Cron job execution emits events to `PipelineEventEmitter` so the dashboard updates in real time.

**When to use:** In `cron/service.py → _execute_job()`, call `get_emitter().emit(...)` before and after the payload runs.

**Example:**
```python
# In cron/service.py _execute_job():
from sci_fi_dashboard.pipeline_emitter import get_emitter

get_emitter().emit("cron.job_start", {
    "job_id": job.id, "job_name": job.name
})
# ... run payload ...
get_emitter().emit("cron.job_done", {
    "job_id": job.id, "status": result["status"],
    "duration_ms": job.state.last_duration_ms,
})
```

### Pattern 4: LoopbackOnlyMiddleware (DASH-04)

**What:** Starlette middleware that inspects `request.client.host` and returns 403 for any dashboard route accessed from a non-loopback address.

**When to use:** Applied to `/dashboard` and `/static/dashboard/` paths only (not all API routes, which are already protected by `_require_gateway_auth`).

**Example:**
```python
# In middleware.py:
LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost"}

class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    """Return 403 for dashboard routes accessed from non-loopback addresses."""

    PROTECTED_PREFIXES = ("/dashboard", "/static/dashboard")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.PROTECTED_PREFIXES):
            host = request.client.host if request.client else ""
            if host not in LOOPBACK_IPS:
                return JSONResponse(
                    {"detail": "Dashboard access is restricted to localhost"},
                    status_code=403,
                )
        return await call_next(request)
```

### Pattern 5: Dashboard Panels (DASH-02) — Vanilla JS Fetch

**What:** New panels in `index.html` fetch data from existing endpoints on DOMContentLoaded and refresh periodically.

**When to use:** For sessions, memory stats, cron jobs, model routing — none of these need SSE; they are snapshots fetched via `fetch()`.

**Example:**
```javascript
// Fetch sessions on load and every 30s
async function refreshSessions() {
  const res = await fetch('/api/sessions');
  const data = await res.json();
  // render data into #panel-sessions
}
setInterval(refreshSessions, 30_000);
document.addEventListener('DOMContentLoaded', refreshSessions);
```

**Endpoints to hit:**
- `GET /api/sessions` — already exists (sessions.py), returns `[{sessionKey, agentId, updatedAt, compactionCount}]`
- `GET /pipeline/state` — already exists (pipeline.py), returns `{status, queue, sbs_profile}`
- `GET /api/cron/jobs` — NEW, must be created in `routes/cron.py`
- `GET /health` — already exists, includes memory_ok bool
- `GET /persona/summary` — already exists (persona.py), includes `get_db_stats()` data

### Anti-Patterns to Avoid

- **Importing `cron_service.py` (top-level) and `cron/service.py` simultaneously** — this creates two independent timer loops. The old top-level file must be completely replaced in `api_gateway.py`.
- **Calling `persona_chat()` from cron without a session_key** — without a unique `session_key`, the cron call lands in the default session, contaminating real conversation history.
- **Blocking the asyncio event loop in cron** — `_fire_job()` must `await` the execute_fn. If execute_fn is sync, wrap in `asyncio.get_event_loop().run_in_executor()`. In practice, `persona_chat()` is async, so this is already safe.
- **Adding a second memory query inside the execute_fn adapter** — the CLAUDE.md gotcha #10 explicitly says memory is queried once in `persona_chat()` and shared via `pre_cached_memory`. Do not add a pre-cron memory query.
- **Using npm/node_modules for dashboard panels** — DASH-05 is explicit. CDN only.
- **Applying LoopbackOnlyMiddleware to all routes** — API endpoints (WhatsApp webhook, `/chat/`) are called from external services (Telegram, etc.). Only dashboard routes need loopback restriction.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cron expression parsing | Custom regex parser | `croniter.is_valid()` + `croniter.get_next()` | Already in `cron/schedule.py`; edge cases (Vixie cron vs POSIX) handled |
| Job persistence | Custom JSON writer | `CronStore.save()` (atomic via `os.replace`) | Already handles crash safety; existing format |
| Job state tracking | Custom dict | `CronJobState` dataclass + `RunLog.append()` | Already tracks `consecutive_errors`, `last_delivery_status`, `last_failure_alert_at_ms` |
| SSE reconnect in browser | Custom polling | `SSEClient` class already in `synapse.js` | Already handles exponential backoff; just add new event handlers |
| Loopback IP check | Custom inet_aton | `request.client.host in {"127.0.0.1", "::1"}` | Starlette already normalizes the client host |
| Memory stats | Custom SQLite query | `get_db_stats()` in `retriever.py` | Returns `{atomic_facts, documents, entity_links, relationship_memories, roasts, gift_ideas}` |
| Session listing | Custom file scan | `GET /api/sessions` already exists | Returns paginated sessions across all agents |

**Key insight:** ~85% of this phase is wiring, not building. The cron infrastructure, the SSE emitter, the session API, the memory stats function, and the dashboard skeleton all exist. The work is replacing one import, adding one middleware, one new API route, one execute_fn adapter, and HTML/JS for four panels.

---

## Common Pitfalls

### Pitfall 1: Old cron_service.py vs new cron/ package co-existence
**What goes wrong:** Both `cron_service.py` (top-level) and `cron/service.py` define a `CronService`. If `api_gateway.py` imports both, two timer loops run. Jobs fire twice. Memory state diverges.
**Why it happens:** The new package was built as a replacement but `api_gateway.py` was not updated to use it.
**How to avoid:** Replace `from sci_fi_dashboard.cron_service import CronService` with `from sci_fi_dashboard.cron import CronService` in `api_gateway.py`. The old `cron_service.py` is not deleted (it may be used in tests or docs) but must not be instantiated.
**Warning signs:** Log shows `[CRON] CronService started` twice; jobs deliver duplicate messages.

### Pitfall 2: Missing session_key in ChatRequest loses isolation
**What goes wrong:** If `ChatRequest(message=payload)` is constructed without `session_key`, `persona_chat()` uses `getattr(request, "session_key", None) or "default"`. The cron job's turn lands in the main user session — it appears in conversation history, responds to context from real chats.
**Why it happens:** `ChatRequest` has `session_key` as an optional field; it's easy to miss.
**How to avoid:** Always pass `session_key=session_key` where `session_key = f"cron-{job.id}-{uuid4().hex[:8]}"`. This is already computed in `cron/service.py._run_payload()` — the adapter must accept and forward it.
**Warning signs:** Cron replies appear in the user's chat history; user sees duplicate or out-of-place messages.

### Pitfall 3: asyncio.wait_for timeout raises CancelledError propagation
**What goes wrong:** `asyncio.wait_for(coro, timeout=N)` raises `asyncio.TimeoutError` on expiry, but in Python 3.11+ this is a subclass of `TimeoutError`. If the `_execute_job` exception handler only catches `Exception`, it catches `TimeoutError` and logs `job.state.last_run_status = "error"` correctly. However, `asyncio.CancelledError` (raised if the entire service is stopped mid-flight) is a `BaseException` in Python 3.8+, not `Exception`. The `_execute_job` handler in `cron/service.py` already catches `Exception` and `BaseException` separately — do not widen or narrow this.
**Why it happens:** Python asyncio cancellation hierarchy changed in 3.8.
**How to avoid:** Keep the existing `try/except Exception` in `_execute_job` as-is. In the execute_fn adapter, let `asyncio.TimeoutError` propagate naturally.
**Warning signs:** Service hangs on shutdown; jobs don't clean up after cancel.

### Pitfall 4: Dashboard loopback check for IPv6 ::1
**What goes wrong:** A user accesses the dashboard via `http://localhost/` which may resolve to `::1` (IPv6 loopback) instead of `127.0.0.1`. Checking only for `"127.0.0.1"` blocks legitimate local access.
**Why it happens:** Modern OSes prefer IPv6 for `localhost`.
**How to avoid:** Check `host in {"127.0.0.1", "::1", "localhost"}`. The string `"localhost"` itself can appear if Starlette resolves the hostname — include it defensively.
**Warning signs:** User reports 403 when accessing `http://localhost:8000/dashboard`.

### Pitfall 5: /pipeline/send has no auth — not a bug, by design
**What goes wrong:** A reviewer or developer adds `Depends(_require_gateway_auth)` to `POST /pipeline/send`, breaking dashboard chat for users without tokens.
**Why it happens:** The endpoint is deliberately open for local-dev use; it is only safe because the entire server binds to `127.0.0.1`.
**How to avoid:** Do not add auth to `/pipeline/send`. The loopback binding (`API_BIND_HOST=127.0.0.1`) is the security boundary. The `LoopbackOnlyMiddleware` adds a defense-in-depth check at the HTTP layer.
**Warning signs:** Dashboard chat input stops working after "security hardening."

### Pitfall 6: CronService.start() called before deps.persona_chat is available
**What goes wrong:** If `CronService.start()` is called early in the lifespan, and a job has a very short schedule (e.g., `every_ms: 1000` for testing), `_catch_up_missed_jobs()` may invoke `execute_fn` before `deps.persona_chat` / `deps.memory_engine` are fully initialized.
**Why it happens:** `lifespan()` initializes components in sequence; `persona_chat` depends on `MemoryEngine`, `SynapseLLMRouter`, etc.
**How to avoid:** Initialize CronService after all core deps are initialized (after the SubAgent and GatewayWebSocket blocks, as the existing `cron_service.py` init already is). Add a guard in the execute_fn adapter: `if not hasattr(deps, 'persona_chat') or deps.persona_chat is None: raise RuntimeError("pipeline not ready")`.
**Warning signs:** `AttributeError` or `NoneType` errors in cron logs on startup.

---

## Code Examples

### CRON-02: Replacing the lifespan CronService init

```python
# api_gateway.py — IN lifespan(), AFTER SubAgent init, REPLACE the existing cron block:

# REMOVE:
#   from sci_fi_dashboard.cron_service import CronService
#   app.state.cron_service = CronService(channel_registry=deps.channel_registry)
#   await app.state.cron_service.start()

# ADD:
app.state.cron_service = None
try:
    from sci_fi_dashboard.cron import CronService
    from sci_fi_dashboard.schemas import ChatRequest

    async def _cron_execute_fn(message: str, session_key: str, **kwargs) -> str:
        timeout_s = float(kwargs.get("timeout_seconds", 300))
        req = ChatRequest(message=message, session_key=session_key, user_id="the_creator")
        try:
            result = await asyncio.wait_for(
                deps.persona_chat(req, "the_creator"), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            logger.warning("[Cron] Job timed out (session=%s, timeout=%ss)", session_key, timeout_s)
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
```

### DASH-04: LoopbackOnlyMiddleware

```python
# middleware.py — add after BodySizeLimitMiddleware:

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_DASHBOARD_PREFIXES = ("/dashboard", "/static/dashboard")


class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    """Restrict /dashboard and /static/dashboard/ to loopback-only access."""

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in _DASHBOARD_PREFIXES):
            client_host = request.client.host if request.client else ""
            if client_host not in LOOPBACK_HOSTS:
                return JSONResponse(
                    {"detail": "Dashboard restricted to localhost"},
                    status_code=403,
                )
        return await call_next(request)
```

```python
# api_gateway.py — add after BodySizeLimitMiddleware:
from sci_fi_dashboard.middleware import LoopbackOnlyMiddleware
app.add_middleware(LoopbackOnlyMiddleware)
```

### DASH-01: Cron SSE events in cron/service.py

```python
# cron/service.py — in _execute_job(), surround the payload run:
try:
    from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter
    _get_emitter().emit("cron.job_start", {"job_id": job.id, "job_name": job.name})
except Exception:
    pass  # emitter is optional — never let it block cron

output = await self._run_payload(job)

try:
    _get_emitter().emit("cron.job_done", {
        "job_id": job.id,
        "status": "ok",
        "duration_ms": int((time.monotonic() - start_mono) * 1000),
    })
except Exception:
    pass
```

### DASH-02: New cron routes

```python
# routes/cron.py — new file:
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sci_fi_dashboard.middleware import _require_gateway_auth

router = APIRouter()


@router.get("/api/cron/jobs", dependencies=[Depends(_require_gateway_auth)])
async def list_cron_jobs(request: Request):
    from dataclasses import asdict
    svc = getattr(request.app.state, "cron_service", None)
    if svc is None:
        return JSONResponse({"jobs": [], "error": "CronService not running"})
    return JSONResponse({
        "jobs": [asdict(j) for j in svc.list()]
    })


@router.post("/api/cron/jobs/{job_id}/run", dependencies=[Depends(_require_gateway_auth)])
async def run_cron_job(job_id: str, request: Request):
    svc = getattr(request.app.state, "cron_service", None)
    if svc is None:
        raise HTTPException(503, "CronService not running")
    result = await svc.run(job_id, mode="force")
    return JSONResponse(result)
```

### ChatRequest session_key field check

```python
# Verify ChatRequest accepts session_key — from schemas.py (confirm field exists):
# If not present, must add: session_key: Optional[str] = None
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `cron_service.py` (top-level, fires via old ChatRequest) | `cron/` package with full CRUD, typed dataclasses, isolated sessions | Already built, not yet wired | Phase 10 completes the wire-up |
| No loopback enforcement (server trusts `API_BIND_HOST`) | `LoopbackOnlyMiddleware` at HTTP layer | Phase 10 | Defense-in-depth — protects against misconfigured reverse proxy |
| Static pipeline dashboard (no cron/sessions visibility) | Extended dashboard with 4 new panels | Phase 10 | Makes system state observable |

**Deprecated/outdated:**
- `cron_service.py` (top-level): deprecated by `cron/` package. Remove instantiation from `api_gateway.py` but keep the file for now to avoid breaking any tests that might import it.

---

## Open Questions

1. **Does `ChatRequest` have a `session_key` field?**
   - What we know: `persona_chat()` uses `getattr(request, "session_key", None) or "default"` — so it handles missing field gracefully.
   - What's unclear: Whether `ChatRequest` in `schemas.py` declares `session_key: Optional[str] = None` explicitly.
   - Recommendation: Verify in `schemas.py` before the execute_fn adapter is written. If missing, add it as an optional field — this is a one-liner addition with no blast radius.

2. **Should the dashboard require a session token (DASH-04)?**
   - What we know: DASH-04 says "session token auth" but the success criterion only tests loopback enforcement (not token checking).
   - What's unclear: Whether `x-api-key` token should be required for dashboard access from localhost, or if loopback binding alone suffices.
   - Recommendation: Implement loopback middleware (satisfies the success criterion) and leave token auth as a config option via `gateway.token`. The existing `_require_gateway_auth` dependency already handles the API routes.

3. **Memory stats for DASH-02: which stats to show?**
   - What we know: `get_db_stats()` returns `{atomic_facts, documents, entity_links, relationship_memories, roasts, gift_ideas}`. `retriever.py` also has LanceDB stats.
   - What's unclear: Whether the planner wants a compact summary (3 numbers) or the full breakdown.
   - Recommendation: Show `documents`, `atomic_facts`, `entity_links` as the primary three — compact enough for a panel row.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `workspace/tests/pytest.ini` |
| Quick run command | `cd workspace && pytest tests/test_cron_service.py tests/test_cron_store.py tests/test_cron_schedule.py -v` |
| Full suite command | `cd workspace && pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CRON-01 | Two simultaneous jobs use distinct session keys | unit | `pytest tests/test_cron_service.py -k "isolated" -x` | Partial — need `test_isolated_sessions` |
| CRON-02 | execute_fn receives message + session_key from cron | unit | `pytest tests/test_cron_service.py -k "execute_fn" -x` | Partial — `test_cron_service.py` has mock execute_fn tests |
| CRON-03 | Isolated agent receives recent memory context | unit | `pytest tests/test_cron_service.py -k "light_context" -x` | Not yet |
| CRON-04 | Job timeout triggers error state + cleanup | unit | `pytest tests/test_cron_service.py -k "timeout" -x` | Not yet |
| DASH-01 | Cron execution emits cron.job_start SSE event | unit | `pytest tests/test_pipeline_emitter.py -k "cron" -x` | Not yet — emitter not tested |
| DASH-02 | GET /api/cron/jobs returns job list | integration | `pytest tests/test_api_gateway.py -k "cron_jobs" -x` | Not yet |
| DASH-03 | POST /pipeline/send returns reply | integration | `pytest tests/test_api_gateway.py -k "pipeline_send" -x` | Likely partial |
| DASH-04 | Non-loopback GET /dashboard returns 403 | integration | `pytest tests/test_api_gateway.py -k "loopback" -x` | Not yet |
| DASH-05 | Dashboard HTML has no npm/node_modules references | smoke | `pytest tests/test_smoke.py -k "dashboard" -x` | Partial — smoke tests exist |

### Sampling Rate
- **Per task commit:** `cd workspace && pytest tests/test_cron_service.py tests/test_cron_store.py -v`
- **Per wave merge:** `cd workspace && pytest tests/ -v -m "unit or integration"`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cron_isolated_agent.py` — covers CRON-01 (session key isolation), CRON-03 (light_context injection)
- [ ] `tests/test_cron_timeout.py` — covers CRON-04 (timeout + failure state)
- [ ] `tests/test_pipeline_emitter.py` — covers DASH-01 (cron SSE events)
- [ ] `tests/test_loopback_middleware.py` — covers DASH-04 (non-loopback 403)
- [ ] `tests/test_cron_routes.py` — covers DASH-02 (GET /api/cron/jobs)

---

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection — `cron/service.py`, `cron/isolated_agent.py`, `cron/types.py`, `cron/store.py`, `cron/schedule.py`, `cron/delivery.py`, `cron/run_log.py`, `cron/alerting.py` — full implementation reviewed
- `api_gateway.py` lifespan — confirmed current CronService import is old top-level module
- `routes/pipeline.py` — confirmed `GET /pipeline/events` SSE and `POST /pipeline/send` are working
- `pipeline_emitter.py` — confirmed `PipelineEventEmitter` singleton, `emit()` method, subscriber queue
- `middleware.py` — confirmed `BodySizeLimitMiddleware` pattern for new middleware
- `routes/sessions.py` — confirmed `GET /api/sessions` exists and returns correct format
- `retriever.py:303` — confirmed `get_db_stats()` function signature and return shape
- `static/dashboard/index.html` + `synapse.js` — confirmed existing SSE client, chat input, Tailwind CDN setup

### Secondary (MEDIUM confidence)

- `REQUIREMENTS.md` CRON-01 through DASH-05 — exact requirement text used for test mapping
- `STATE.md` decisions block — confirmed Phase 10 design choices (BackgroundTask pattern, Vault isolation, etc.)

### Tertiary (LOW confidence)

- None. All findings are from direct codebase inspection at HIGH confidence.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already present in codebase
- Architecture: HIGH — patterns verified against actual code in `cron/`, `pipeline.py`, `middleware.py`
- Pitfalls: HIGH — identified from concrete code inspection (old vs new CronService, session_key path, asyncio cancel behavior)
- Test mapping: MEDIUM — existing test files confirmed, gap tests identified but not yet written

**Research date:** 2026-04-09
**Valid until:** 2026-06-09 (stable domain — FastAPI, asyncio, Tailwind CDN patterns are unlikely to shift)
