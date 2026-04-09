---
phase: 10-cron-wiring-web-control-panel
verified: 2026-04-09T00:00:00Z
status: gaps_found
score: 8/9 must-haves verified
gaps:
  - truth: "GET /api/cron/jobs returns a JSON-serializable list of cron jobs"
    status: failed
    reason: "routes/cron.py returns raw CronJob dataclass instances via JSONResponse. Python's json.dumps cannot serialize dataclasses — the endpoint raises a 500 TypeError at runtime whenever real CronJob objects exist in app.state.cron_service. Tests pass only because they mock cron_service.list() with plain dicts."
    artifacts:
      - path: "workspace/sci_fi_dashboard/routes/cron.py"
        issue: "Line 26: `\"jobs\": jobs` where jobs is list[CronJob] dataclasses — not JSON-serializable. Missing dataclasses.asdict() conversion."
    missing:
      - "Import `from dataclasses import asdict` in routes/cron.py"
      - "Change `\"jobs\": jobs` to `\"jobs\": [asdict(j) for j in jobs]` on line 26"
      - "Add a test in test_cron_routes.py that passes real CronJob instances (not plain dicts) to cron_service.list() to prevent regression"
---

# Phase 10: Cron Wiring + Web Control Panel Verification Report

**Phase Goal:** CronService is wired to `persona_chat()` so scheduled jobs actually run with isolated agent contexts. The dashboard becomes a real-time interactive control panel — sessions, cron jobs, model routing decisions, memory stats — observable and controllable from a browser.
**Verified:** 2026-04-09
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | CronService from cron/ package is initialized in api_gateway.py lifespan | VERIFIED | `api_gateway.py:237` imports `from sci_fi_dashboard.cron import CronService`; no remaining reference to `cron_service.py` import |
| 2 | Each cron job execution uses a unique session_key (cron-{job_id}-{uuid}) | VERIFIED | `cron/service.py:351` generates `session_key = f"cron-{job.id}-{uuid.uuid4().hex[:8]}"` in `_run_payload()`; `isolated_agent.py` passes it directly to `execute_fn` |
| 3 | Cron job execution flows through persona_chat() via the execute_fn adapter | VERIFIED | `api_gateway.py:241-260` defines `_cron_execute_fn` that constructs a `ChatRequest(session_key=session_key)` and calls `persona_chat(req, "the_creator")` |
| 4 | Cron jobs respect configurable timeout via asyncio.wait_for wrapping | VERIFIED | `api_gateway.py:250-253` wraps `persona_chat()` in `asyncio.wait_for(timeout=timeout_s)`; `isolated_agent.py:51` passes `payload.timeout_seconds` as kwarg |
| 5 | Cron job start/done/error events appear in the SSE pipeline stream | VERIFIED | `cron/service.py:261-267` emits `cron.job_start`; lines `288-296` emit `cron.job_done`; lines `310-317` emit `cron.job_error`. All guarded in `try/except`. |
| 6 | Non-loopback requests to /dashboard return 403 | VERIFIED | `middleware.py:122-136` defines `LoopbackOnlyMiddleware` checking `request.client.host` against `frozenset({"127.0.0.1", "::1", "localhost"})`; registered in `api_gateway.py:376` |
| 7 | GET /api/cron/jobs returns a JSON-serializable list of cron jobs | FAILED | `routes/cron.py:26` returns `"jobs": jobs` where `jobs` is `list[CronJob]` dataclasses from `cron/service.py`. `json.dumps` cannot serialize dataclasses. Confirmed with `python -c "json.dumps({'jobs': [job]})"` → `TypeError: Object of type CronJob is not JSON serializable`. Tests pass because they mock with plain dicts. |
| 8 | Dashboard has 4 panels (sessions, cron, memory, routing) with auto-refresh and SSE handlers | VERIFIED | `index.html` contains `id="panel-sessions"`, `id="panel-cron"`, `id="panel-memory"`, `id="panel-routing"`. `synapse.js` has `refreshSessions()`, `refreshCronJobs()`, `refreshMemoryStats()`, cron SSE handlers, and DOMContentLoaded wiring with `setInterval` |
| 9 | Dashboard uses vanilla JS + Tailwind CDN only (no npm build step) | VERIFIED | Grep of `index.html` and `synapse.js` confirms zero `node_modules`, zero `require()`, zero npm package imports. Test `test_dashboard_no_npm_references` validates this. |

**Score:** 8/9 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `workspace/sci_fi_dashboard/schemas.py` | ChatRequest with session_key field | VERIFIED | Line 11: `session_key: str \| None = None` with comment noting cron isolation purpose |
| `workspace/sci_fi_dashboard/api_gateway.py` | CronService wired via execute_fn adapter | VERIFIED | Lines 234-271: `from sci_fi_dashboard.cron import CronService`, `_cron_execute_fn` adapter, `asyncio.wait_for`, `CronService(execute_fn=_cron_execute_fn)` |
| `workspace/sci_fi_dashboard/cron/service.py` | SSE event emission on job start/done/error | VERIFIED | Lines 259-267 (start), 287-296 (done), 309-317 (error) — all guarded by `try/except` |
| `workspace/sci_fi_dashboard/middleware.py` | LoopbackOnlyMiddleware class | VERIFIED | Lines 122-136 with `LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})` and `_DASHBOARD_PREFIXES` |
| `workspace/sci_fi_dashboard/routes/cron.py` | Cron API routes (list, run) | STUB/BUG | File exists with correct routes and auth. Bug: `"jobs": jobs` returns non-serializable dataclasses. Route structure is correct; serialization is broken. |
| `workspace/sci_fi_dashboard/static/dashboard/index.html` | Four new dashboard panels | VERIFIED | All four panel IDs present; 2-column Tailwind grid; no npm artifacts |
| `workspace/sci_fi_dashboard/static/dashboard/synapse.js` | Panel data-fetch functions and cron SSE handlers | VERIFIED | `refreshSessions()`, `refreshCronJobs()`, `refreshMemoryStats()`, `wirePanelEvents()`, cron SSE handlers all present |
| `workspace/tests/test_cron_wiring.py` | Cron execute_fn, session isolation, timeout, SSE tests | VERIFIED | 12 tests covering CRON-01 through CRON-04 and DASH-01 |
| `workspace/tests/test_loopback_middleware.py` | LoopbackOnlyMiddleware unit tests | VERIFIED | 7 tests including IPv4, IPv6, external IP 403, non-dashboard bypass, direct dispatch |
| `workspace/tests/test_cron_routes.py` | Cron API route tests | PARTIAL | 10 tests present but mock `cron_service.list()` with plain dicts — does not catch the dataclass serialization bug |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `api_gateway.py` | `cron/service.py` | `CronService(execute_fn=_cron_execute_fn)` | WIRED | `api_gateway.py:262-267` passes `execute_fn=_cron_execute_fn` |
| `api_gateway.py` | `chat_pipeline.py` | `_cron_execute_fn` calls `persona_chat()` | WIRED | `api_gateway.py:239,251`: `from sci_fi_dashboard.chat_pipeline import persona_chat` then `await asyncio.wait_for(persona_chat(req, "the_creator"), ...)` |
| `cron/service.py` | `pipeline_emitter.py` | `get_emitter().emit()` for SSE events | WIRED | Three lazy-import calls at lines 260-266, 288-295, 310-316 — correct guard pattern |
| `api_gateway.py` | `middleware.py` | `app.add_middleware(LoopbackOnlyMiddleware)` | WIRED | `api_gateway.py:31,376`: imported and registered |
| `api_gateway.py` | `routes/cron.py` | `app.include_router(cron_routes.router)` | WIRED | `api_gateway.py:379-390`: imported and router included |
| `routes/cron.py` | `cron/service.py` | `request.app.state.cron_service.list()` | WIRED (broken) | `routes/cron.py:24` calls `svc.list()` correctly, but serialization of the returned dataclasses fails at `JSONResponse` |
| `synapse.js` | `/api/sessions` | `fetch('/api/sessions', ...)` | WIRED | `synapse.js:1211`: `fetch('/api/sessions', { headers })` |
| `synapse.js` | `/api/cron/jobs` | `fetch('/api/cron/jobs', ...)` | WIRED | `synapse.js:1258`: `fetch('/api/cron/jobs', { headers })` |
| `synapse.js` | `/persona/status` | `fetch('/persona/status', ...)` for memory stats | WIRED | `synapse.js:1311`: correct adaptation from plan's `/persona/summary` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| CRON-01 | 10-01, 10-04 | Each cron job runs in an isolated agent context with separate memory | SATISFIED | `session_key = f"cron-{job.id}-{uuid.uuid4().hex[:8]}"` in `_run_payload()`; `ChatRequest.session_key` field added |
| CRON-02 | 10-01, 10-04 | CronService execute_fn is wired to persona_chat() in gateway lifespan | SATISFIED | `_cron_execute_fn` adapter in `api_gateway.py` lifespan wraps `persona_chat()` |
| CRON-03 | 10-01, 10-04 | Isolated agents get recent memory context injected as system prefix | SATISFIED | `session_key` flows into `persona_chat()` which calls `MemoryEngine.query()` using that key (design-level, existing pipeline behavior) |
| CRON-04 | 10-01, 10-04 | Cron jobs have configurable timeout and cleanup on failure | SATISFIED | `asyncio.wait_for(timeout=timeout_s)` in `_cron_execute_fn`; `timeout_seconds` from `CronPayload.timeout_seconds` via kwargs |
| DASH-01 | 10-01, 10-04 | Dashboard shows real-time pipeline events via SSE | SATISFIED | `cron.job_start/done/error` added to SSE stream in `cron/service.py`; `synapse.js` handlers registered for these events |
| DASH-02 | 10-02, 10-03, 10-04 | Dashboard displays active sessions, memory stats, and model routing decisions | BLOCKED | GET `/api/cron/jobs` route raises 500 when real `CronJob` objects are returned (dataclass serialization bug). Sessions panel (fetches `/api/sessions`) and memory panel (fetches `/persona/status`) are unaffected. |
| DASH-03 | 10-03 | User can send messages from the dashboard | SATISFIED | `/pipeline/send` confirmed in `routes/pipeline.py`; `chat-input` and `chat-send` in `index.html`; `sendChat()` function in dashboard JS |
| DASH-04 | 10-02, 10-04 | Dashboard is loopback-only with session token auth | SATISFIED | `LoopbackOnlyMiddleware` restricts `/dashboard` and `/static/dashboard`; cron routes require `_require_gateway_auth` |
| DASH-05 | 10-03, 10-04 | Dashboard uses vanilla JS + Tailwind (no React build step) | SATISFIED | Zero npm/node_modules in dashboard files; Tailwind CDN only |

**All 9 requirements from phase plans accounted for.** No orphaned requirements found in REQUIREMENTS.md — all CRON-01 through CRON-04 and DASH-01 through DASH-05 are mapped to Phase 10 and verified above.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `workspace/sci_fi_dashboard/routes/cron.py` | 25-27 | `"jobs": jobs` where `jobs` is `list[CronJob]` dataclasses — not JSON-serializable | Blocker | GET `/api/cron/jobs` will raise `TypeError: Object of type CronJob is not JSON serializable` at runtime when any cron jobs are registered. This makes DASH-02 non-functional for the cron jobs panel. |
| `workspace/tests/test_cron_routes.py` | 77-78 | `test_list_cron_jobs_with_data` mocks return value as plain dicts, hiding the serialization bug | Warning | Test gives false confidence — passes while the real endpoint fails |

---

### Human Verification Required

#### 1. Cron Job Round-Trip

**Test:** Define a cron job in `synapse.json` using the `cron/` package format, start the gateway, and wait for the scheduled time (or use POST `/api/cron/jobs/{id}/run`).
**Expected:** The user receives a proactive message; the conversation log shows a cron-originated entry with a `cron-{id}-{hex}` session key distinct from regular chat sessions.
**Why human:** Requires a live gateway + real LLM call; end-to-end pipeline behavior cannot be verified by static analysis.

#### 2. Cron Jobs Panel in Dashboard

**Test:** After fixing the serialization bug (gap above), open `http://127.0.0.1:8000/dashboard` and verify the cron panel renders jobs.
**Expected:** Panel shows job names, schedules, last-run status, and next-run times; cron SSE events cause the panel to update without page refresh.
**Why human:** Visual rendering and SSE live-update behavior require browser interaction.

#### 3. Dashboard Chat (DASH-03 Regression)

**Test:** Open `http://127.0.0.1:8000/dashboard`, type a message in the chat input, and press Send.
**Expected:** Reply appears in the dashboard reply area; the existing pipeline visualization shows the request flowing through.
**Why human:** Interactive browser behavior.

---

### Gaps Summary

One gap blocks full goal achievement:

**DASH-02 cron panel is non-functional at runtime.** `routes/cron.py` calls `svc.list()` on `app.state.cron_service`, which is a `CronService` from `cron/service.py` that returns `list[CronJob]` dataclass instances. The route then does `JSONResponse({"jobs": jobs, ...})` where `jobs` contains these dataclass objects. Python's `json.dumps` (used by `JSONResponse`) cannot serialize dataclasses and raises `TypeError: Object of type CronJob is not JSON serializable`.

The fix is minimal: import `from dataclasses import asdict` and change line 26 from `"jobs": jobs` to `"jobs": [asdict(j) for j in jobs]`. The companion fix is updating `test_list_cron_jobs_with_data` to pass real `CronJob` instances rather than plain dicts, so the test actually catches this path.

This bug was introduced by a plan deviation: Plan 02 SUMMARY noted it dropped `asdict` because "cron_service.py stores jobs as plain JSON dicts" — but that decision was based on the old `cron_service.py` (flat-file JSON store), not the new `cron/service.py` (dataclass store) that Plan 01 wired into the gateway. The executor applied the wrong serialization strategy for the wired class.

All other must-haves are fully verified: cron wiring to `persona_chat()`, session isolation, timeout, SSE emission, loopback middleware, dashboard panels (sessions/memory/routing), chat input, and npm-free compliance.

---

_Verified: 2026-04-09_
_Verifier: Claude (gsd-verifier)_
