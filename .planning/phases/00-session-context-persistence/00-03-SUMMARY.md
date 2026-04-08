---
phase: 00-session-context-persistence
plan: "03"
subsystem: sessions-api
tags: [sessions, session-store, file-based, multiuser, reset-endpoint]
dependency_graph:
  requires:
    - "00-01"
  provides:
    - GET /api/sessions using SessionStore (file-based JSON)
    - POST /api/sessions/{key}/reset with transcript archival and cache invalidation
    - SessionStore.delete() method for session rotation
  affects:
    - workspace/sci_fi_dashboard/routes/sessions.py
    - workspace/sci_fi_dashboard/multiuser/session_store.py
tech_stack:
  added: []
  patterns:
    - async FastAPI route with lazy imports (avoids circular deps at module load)
    - Iterate sbs_registry to scan all agents' session stores
    - delete()+update() pattern for session_id rotation on reset
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/routes/sessions.py
    - workspace/sci_fi_dashboard/multiuser/session_store.py
decisions:
  - GET /sessions scans sbs_registry (all persona agent IDs) to return sessions from all agents
  - Float epoch (updatedAtEpoch) used for sort key — avoids TypeError on mixed types
  - delete() + update() required for session_id rotation — _merge_entry() preserves session_id once set
  - SessionStore.delete() added in this plan (was planned for 00-02) to unblock reset endpoint
metrics:
  duration: "~7 minutes"
  completed: "2026-04-07T05:53:11Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 00 Plan 03: Sessions API Rewrite Summary

**One-liner:** Rewrote GET /sessions to use SessionStore file-based JSON (not SQLite token-usage table) and added POST /sessions/{key}/reset with transcript archival, session_id rotation, and cache invalidation.

## What Was Built

Replaced the incorrect SQLite-based `GET /sessions` implementation (which read from the token-usage `sessions` table — Research Pitfall 4) with a correct file-based implementation backed by `SessionStore`.

1. **GET /sessions** — now async, iterates over `deps.sbs_registry` to scan all persona agents' SessionStore files at `~/.synapse/state/agents/<agent_id>/sessions/sessions.json`. Returns camelCase JSON list sorted by `updatedAtEpoch` descending.

2. **POST /sessions/{key}/reset** — new endpoint that: archives the transcript file (renames to `.deleted.<epoch_ms>`), calls `store.delete()` + `store.update()` to rotate the session_id (fresh UUID), and invalidates the `conversation_cache` entry.

3. **SessionStore.delete()** — added async `delete()` and synchronous `_delete_sync()` methods to `session_store.py` using the same filelock + asyncio.Lock + atomic write pattern as `update()`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite GET /sessions + add POST /sessions/{key}/reset | 1202b08 | workspace/sci_fi_dashboard/routes/sessions.py, workspace/sci_fi_dashboard/multiuser/session_store.py |
| 2 | Verify sessions endpoints are importable and registered | (no new commit — already registered) | workspace/sci_fi_dashboard/api_gateway.py (verified) |

## Decisions Made

- **Float sort key for updatedAt**: `updatedAtEpoch` (raw float) is used as the sort key rather than the ISO string `updatedAt` — prevents `TypeError: '<' not supported between instances of 'float' and 'NoneType'` when `updated_at` is 0.0.
- **Lazy imports inside route handlers**: `SynapseConfig`, `SessionStore`, `_deps` are imported inside the function body to avoid circular import issues at module load time.
- **delete() + update() for reset**: `_merge_entry()` preserves `session_id` once set — a plain `update()` cannot change it. The `delete()` removes the entry first so `update()` creates a fresh UUID.
- **SessionStore.delete() added here**: The plan noted this as "added by Plan 00-02 Task 0" but 00-02 is a parallel wave executing separately. Since the reset endpoint is in this plan and requires `delete()`, it was added as a Rule 2 deviation.

## Deviations from Plan

### Auto-added Missing Critical Functionality

**1. [Rule 2 - Missing Dependency] Added SessionStore.delete() method**
- **Found during:** Task 1 implementation
- **Issue:** `reset_session` calls `store.delete(session_key)` but the method did not exist in session_store.py (plan listed it as "added by Plan 00-02 Task 0", which executes in a separate worktree)
- **Fix:** Added `async def delete()` + `def _delete_sync()` to `SessionStore` in `session_store.py`. Uses same locking pattern (asyncio.Lock + filelock + atomic write) as the existing `update()` method. Invalidates LRU cache entry on deletion.
- **Files modified:** `workspace/sci_fi_dashboard/multiuser/session_store.py`
- **Commit:** 1202b08

## Known Stubs

None. Both endpoints are concrete implementations that read real disk data.

## Threat Flags

No new trust boundaries introduced beyond what is documented in the plan's threat model.

Security mitigations applied:
- T-00-07 (path traversal via session_key): session_key is used as a dict key lookup, not as a filesystem path — no traversal possible.
- T-00-09 (unauthenticated session reset): Both `GET /api/sessions` and `POST /api/sessions/{key}/reset` have `dependencies=[Depends(_require_gateway_auth)]`.

## Self-Check: PASSED

Files verified:
- `workspace/sci_fi_dashboard/routes/sessions.py` — contains `SessionStore` import, no `sqlite3`, async `get_sessions` and `reset_session`, `_require_gateway_auth` on both endpoints, `HTTPException(404)` on not found
- `workspace/sci_fi_dashboard/multiuser/session_store.py` — contains `async def delete()` and `def _delete_sync()` with correct locking pattern

Routes verified:
- `python -c "from sci_fi_dashboard.routes.sessions import router; print([r.path for r in router.routes])"` returned `['/api/sessions', '/api/sessions/{session_key}/reset']`

Commit verified:
- `1202b08`: feat(00-03): rewrite sessions.py to use SessionStore + add delete method
