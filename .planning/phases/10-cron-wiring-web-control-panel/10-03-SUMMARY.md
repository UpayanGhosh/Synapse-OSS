---
phase: 10-cron-wiring-web-control-panel
plan: 03
subsystem: ui
tags: [dashboard, tailwind, vanilla-js, sse, cron, sessions, memory, routing]

# Dependency graph
requires:
  - phase: 10-01
    provides: cron SSE events (cron.job_start/done/error) on /pipeline/events
  - phase: 10-02
    provides: GET /api/cron/jobs endpoint with gateway auth
provides:
  - Dashboard sessions panel (panel-sessions) with auto-refresh every 30s
  - Dashboard cron jobs panel (panel-cron) with SSE-triggered refresh on cron events
  - Dashboard memory stats panel (panel-memory) with 3 stat cards (documents/facts/links)
  - Dashboard routing decisions panel (panel-routing) SSE-populated from llm.route events
  - Helper functions: relativeTime(), formatSchedule(), statusBadge(), roleBadge()
affects:
  - phase-11-realtime-voice-streaming (dashboard base established)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Vanilla JS panel pattern: fetch + innerHTML rendering with no framework dependency
    - SSE panel refresh pattern: cron.job_done/error triggers immediate refreshCronJobs()
    - Gateway token pattern: _getGatewayToken() reads from window.SYNAPSE_TOKEN or meta[name=synapse-token]
    - Routing decisions pattern: llm.route SSE event captured to build last-10 routing history list

key-files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/static/dashboard/index.html
    - workspace/sci_fi_dashboard/static/dashboard/synapse.js

key-decisions:
  - "Used /persona/status instead of /persona/summary — /persona/status is the actual endpoint with memory_db stats"
  - "Routing decisions panel driven by llm.route SSE event (not pipeline.run_done) — llm.route is what carries role+model in current codebase"
  - "pipeline.run_done handler added as future-proof fallback — registered in allTypes for forward compatibility"
  - "SSEClient allTypes array extended with cron.* and pipeline.run_done to ensure EventSource registers those event types before handlers fire"
  - "formatSchedule() handles both cron/service.py CronSchedule objects AND cron_service.py legacy schedule strings"

patterns-established:
  - "Panel data pattern: fetch on DOMContentLoaded + setInterval for periodic refresh; manual refresh via button"
  - "_getGatewayToken() reads from window.SYNAPSE_TOKEN or meta[name=synapse-token] — consistent auth token injection point"

requirements-completed: [DASH-02, DASH-03, DASH-05]

# Metrics
duration: 12min
completed: 2026-04-09
---

# Phase 10 Plan 03: Dashboard UI Panels Summary

**Four monitoring panels added to dashboard (sessions, cron, memory, routing) with vanilla JS polling + cron SSE event handlers — no npm, Tailwind CDN only**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-09T13:59:30Z
- **Completed:** 2026-04-09T14:11:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added four new monitoring panels to index.html in a 2-column Tailwind grid below the pipeline visualization — sessions table, cron jobs table, memory stat cards, and routing decisions list
- Extended synapse.js with `refreshSessions()`, `refreshCronJobs()`, `refreshMemoryStats()`, and `wirePanelEvents()` — all vanilla fetch(), no frameworks
- Added cron SSE event handlers (`cron.job_start/done/error`) that update the pipeline status indicator and trigger `refreshCronJobs()` for live state refresh
- Routing decisions panel populated via `llm.route` SSE events (role+model), showing last 10 routing decisions with colored role badges
- Chat input (DASH-03) verified intact — no regression

## Task Commits

Each task was committed atomically:

1. **Task 1: Add four data panels to index.html** - `e48f78b` (feat)
2. **Task 2: Add panel data-fetch functions and cron SSE handlers to synapse.js** - `086c41c` (feat)

**Plan metadata:** (docs commit — see final commit below)

## Files Created/Modified

- `workspace/sci_fi_dashboard/static/dashboard/index.html` - Added panels-container div with 4 panels (panel-sessions, panel-cron, panel-memory, panel-routing) between pipeline visualization and chat input
- `workspace/sci_fi_dashboard/static/dashboard/synapse.js` - Added 375 lines: panel fetch functions, SSE handlers, helper utilities, wirePanelEvents(), DOMContentLoaded wiring

## Decisions Made

- **Used `/persona/status` not `/persona/summary`**: The plan referenced `/persona/summary` but the actual FastAPI route registered is `GET /persona/status` (in `routes/persona.py`). Fixed during implementation.
- **Routing decisions via `llm.route` not `pipeline.run_done`**: Current codebase emits `llm.route` with role+model fields; `pipeline.run_done` doesn't exist yet. Added `pipeline.run_done` handler as forward-compatible fallback.
- **SSEClient allTypes extension**: Cron events needed to be in the `allTypes` array so `EventSource.addEventListener` is called for them before `onEvent` handlers fire.
- **formatSchedule() dual format**: Handles both `cron/service.py` CronSchedule objects (with `kind`/`every_ms`/`expr` fields) and `cron_service.py` legacy schedule strings (`"every_8h"`, `"every_day_at_08:00"`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used correct endpoint /persona/status instead of /persona/summary**
- **Found during:** Task 2 (refreshMemoryStats implementation)
- **Issue:** Plan specified fetching `/persona/summary` but the actual endpoint is `GET /persona/status` in `routes/persona.py`; `/persona/summary` would return 404
- **Fix:** `refreshMemoryStats()` fetches `/persona/status` and reads `data.memory_db` for the stats
- **Files modified:** `workspace/sci_fi_dashboard/static/dashboard/synapse.js`
- **Verification:** grep confirms `persona/status` in synapse.js, routes/persona.py confirms endpoint name
- **Committed in:** `086c41c` (Task 2 commit)

**2. [Rule 1 - Bug] Routing decisions driven by llm.route (not pipeline.run_done)**
- **Found during:** Task 2 (wirePanelEvents implementation)
- **Issue:** Plan said "Listen for `pipeline.run_done` events" but current codebase emits `llm.route` with role+model, not `pipeline.run_done`
- **Fix:** Primary routing decisions handler on `llm.route`; `pipeline.run_done` handler added as future-proof fallback
- **Files modified:** `workspace/sci_fi_dashboard/static/dashboard/synapse.js`
- **Verification:** `llm.route` handler in wireEvents() already surfaced role+model; confirmed in existing synapse.js handlers
- **Committed in:** `086c41c` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2x Rule 1 — bugs from plan referencing non-existent endpoint and non-existent SSE event)
**Impact on plan:** Both fixes required for correctness. The endpoint and event type differences are pre-existing codebase facts.

## Issues Encountered

- The verification script needed `encoding='utf-8'` — the HTML file contains non-ASCII bytes (cp1252 default failed). Added explicit UTF-8 encoding to all Python verification commands.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DASH-02 (sessions + cron panels), DASH-03 (chat input intact), DASH-05 (Tailwind CDN only) all satisfied
- Dashboard at `http://127.0.0.1:8000/dashboard` shows all 4 data panels with auto-refresh
- Phase 10 complete — all plans (01, 02, 03) executed
- Phase 11 (Realtime Voice Streaming) can proceed: dashboard WebSocket infrastructure established

---
*Phase: 10-cron-wiring-web-control-panel*
*Completed: 2026-04-09*
