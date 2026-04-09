---
phase: 10-cron-wiring-web-control-panel
plan: 02
subsystem: api
tags: [fastapi, middleware, starlette, cron, dashboard, security]

# Dependency graph
requires:
  - phase: 10-01
    provides: CronService lifecycle in app.state.cron_service
provides:
  - LoopbackOnlyMiddleware protecting /dashboard and /static/dashboard routes (403 for non-loopback)
  - GET /api/cron/jobs endpoint returning all registered jobs with gateway auth
  - POST /api/cron/jobs/{id}/run endpoint for force-running jobs with gateway auth
  - list() and run() methods added to CronService (cron_service.py)
affects:
  - 10-03-dashboard-ui (consumes /api/cron/jobs for DASH-02 panels)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - LoopbackOnlyMiddleware pattern: Starlette BaseHTTPMiddleware checking request.client.host against frozenset of loopback addresses
    - Cron route pattern: APIRouter with Depends(_require_gateway_auth), graceful None-check on app.state.cron_service

key-files:
  created:
    - workspace/sci_fi_dashboard/routes/cron.py
  modified:
    - workspace/sci_fi_dashboard/middleware.py
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/sci_fi_dashboard/cron_service.py

key-decisions:
  - "LoopbackOnlyMiddleware registered after BodySizeLimitMiddleware — Starlette LIFO order means it runs before body-size check, rejecting non-local clients before body is read"
  - "CronService.list() reads all jobs (including disabled) by default — routes/cron.py exposes all jobs so dashboard can show disabled ones with toggle UI"
  - "CronService.run() raises KeyError on missing job_id so routes/cron.py can return clean 404 (vs previous pattern of returning error dict)"
  - "routes/cron.py serializes jobs as plain dicts (not dataclass asdict) — cron_service.py stores jobs as JSON dicts, not dataclasses"

patterns-established:
  - "Loopback guard pattern: check any(path.startswith(p) for p in PREFIXES) then check client.host against LOOPBACK_HOSTS frozenset"
  - "Cron API pattern: getattr(request.app.state, 'cron_service', None) null-check before use; return 503 if not running"

requirements-completed: [DASH-02, DASH-04]

# Metrics
duration: 8min
completed: 2026-04-09
---

# Phase 10 Plan 02: Cron Middleware + API Routes Summary

**LoopbackOnlyMiddleware (DASH-04) + /api/cron/jobs endpoints (DASH-02) wired into FastAPI gateway with gateway auth enforcement**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-09T13:52:00Z
- **Completed:** 2026-04-09T13:54:36Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `LoopbackOnlyMiddleware` to `middleware.py` — returns 403 for any non-loopback IP hitting `/dashboard` or `/static/dashboard`
- IPv6 `::1` and `localhost` hostname included in allowed set (defense against varied loopback representations)
- Created `routes/cron.py` with `GET /api/cron/jobs` and `POST /api/cron/jobs/{id}/run`, both gated by `_require_gateway_auth`
- Added `list()` and `run()` methods to `CronService` so routes have a clean API to call

## Task Commits

Each task was committed atomically:

1. **Task 1: LoopbackOnlyMiddleware + api_gateway registration** - `c53d6be` (feat)
2. **Task 2: Cron API routes + CronService list/run methods** - `0f17687` (feat)

**Plan metadata:** (docs commit — see final commit below)

## Files Created/Modified
- `workspace/sci_fi_dashboard/middleware.py` - Added `LoopbackOnlyMiddleware` class + `LOOPBACK_HOSTS`/`_DASHBOARD_PREFIXES` constants
- `workspace/sci_fi_dashboard/api_gateway.py` - Import + register `LoopbackOnlyMiddleware`; import + include `cron_routes.router`
- `workspace/sci_fi_dashboard/routes/cron.py` - New file: `GET /api/cron/jobs` + `POST /api/cron/jobs/{id}/run`
- `workspace/sci_fi_dashboard/cron_service.py` - Added `list()`, `_load_all_jobs()`, and `run()` methods to `CronService`

## Decisions Made
- `LoopbackOnlyMiddleware` registered after `BodySizeLimitMiddleware` — Starlette LIFO order means loopback check runs first (before body is read), which is the correct order
- `CronService.list()` returns all jobs (enabled + disabled) by default — dashboard needs to show disabled jobs so users can toggle them
- `CronService.run()` raises `KeyError` when job not found — allows the route to return a clean 404 instead of embedding error strings in 200 responses
- Jobs serialized as plain dicts (not `dataclasses.asdict`) because `cron_service.py` stores jobs as JSON dicts loaded directly from file

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CronService missing list() and run() methods**
- **Found during:** Task 2 (routes/cron.py creation)
- **Issue:** Plan referenced `svc.list()` and `svc.run(job_id, mode="force")` on `app.state.cron_service`, but the actual `CronService` in `cron_service.py` (the one wired in `api_gateway.py`) had neither method — only `start()`, `stop()`, `reload()`
- **Fix:** Added `list()` (reads all jobs from disk), `_load_all_jobs()` (reads including disabled), and `run()` (force-fires a job by job_id) to `CronService` in `cron_service.py`
- **Files modified:** `workspace/sci_fi_dashboard/cron_service.py`
- **Verification:** `python -c "from sci_fi_dashboard.routes.cron import router; print('OK')"` passes
- **Committed in:** `0f17687` (Task 2 commit)

**2. [Rule 1 - Bug] Plain dict serialization instead of dataclasses.asdict()**
- **Found during:** Task 2 (routes/cron.py creation)
- **Issue:** Plan's routes/cron.py template used `asdict(j) for j in jobs` (dataclass pattern from `cron/service.py`), but `cron_service.py` CronService stores jobs as plain JSON dicts (not dataclasses)
- **Fix:** Routes/cron.py serializes jobs directly (no asdict import needed) — `"jobs": jobs` where jobs is already a list of dicts
- **Files modified:** `workspace/sci_fi_dashboard/routes/cron.py`
- **Verification:** Routes import cleanly and return correct JSON structure
- **Committed in:** `0f17687` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2x Rule 1 — bugs caused by plan referencing wrong CronService interface)
**Impact on plan:** Both fixes required for correctness. The plan referenced `cron/service.py` interface but the gateway uses `cron_service.py`. No scope creep.

## Issues Encountered
- Plan's context showed `cron/service.py` interface (`CronService.list()` returning `list[CronJob]` dataclasses), but `api_gateway.py` imports from `sci_fi_dashboard.cron_service` (the flat-file JSON-based service). Fixed by adding list/run methods to the correct module.

## Next Phase Readiness
- Dashboard UI (Plan 03) can now fetch `/api/cron/jobs` with gateway token to render DASH-02 panels
- `/dashboard` route protected from external access (DASH-04)
- Both requirements DASH-02 and DASH-04 satisfied

---
*Phase: 10-cron-wiring-web-control-panel*
*Completed: 2026-04-09*
