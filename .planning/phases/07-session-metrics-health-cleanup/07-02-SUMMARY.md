---
phase: 07-session-metrics-health-cleanup
plan: "02"
subsystem: session-metrics
tags: [sessions, api, sqlite, state, camelCase, SESS-02, SESS-03]
dependency_graph:
  requires: [07-01]
  provides: [GET /api/sessions, state.py SQLite sessions read]
  affects: [workspace/sci_fi_dashboard/api_gateway.py, workspace/sci_fi_dashboard/state.py]
tech_stack:
  added: []
  patterns: [lazy-import-inside-try, camelCase-mapping, sqlite3-row-factory]
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/sci_fi_dashboard/state.py
decisions:
  - "GET /api/sessions returns [] on any exception rather than raising — graceful degradation for dashboard consumers"
  - "state.py uses conn.close() explicitly (not context manager) to mirror plan spec inside try block"
  - "contextTokens hardcoded to 1048576 in /api/sessions response — sessions table has no context column; matches state.py default"
metrics:
  duration_minutes: 10
  completed_date: "2026-03-03"
  tasks_completed: 2
  files_modified: 2
---

# Phase 7 Plan 2: Sessions API Endpoint and State.py SQLite Read Summary

**One-liner:** GET /api/sessions FastAPI endpoint + state.py SQLite sessions read replacing subprocess placeholder, satisfying SESS-02 and SESS-03.

## Objective

Expose the sessions table (created in plan 07-01) via a new GET /api/sessions FastAPI endpoint returning camelCase JSON, and replace the empty placeholder block in state.py with a real SQLite read from memory.db.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add GET /api/sessions route to api_gateway.py | 16842d7 | workspace/sci_fi_dashboard/api_gateway.py |
| 2 | Replace placeholder in state.py with SQLite read | c93fc9e | workspace/sci_fi_dashboard/state.py |

## What Was Built

### Task 1: GET /api/sessions endpoint (api_gateway.py)

Added a synchronous FastAPI route after the `/health` route and before the channel layer section:

```python
@app.get("/api/sessions")
def get_sessions():
    """SESS-02: Return session token usage matching openclaw sessions list --json schema."""
    import sqlite3  # noqa: PLC0415
    from sci_fi_dashboard.db import DB_PATH  # noqa: PLC0415

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, model, input_tokens, output_tokens, total_tokens, created_at "
                "FROM sessions ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [
            {
                "sessionId": r["session_id"],
                "model": r["model"],
                "inputTokens": r["input_tokens"],
                "outputTokens": r["output_tokens"],
                "totalTokens": r["total_tokens"],
                "contextTokens": 1048576,
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    except Exception:
        return []
```

Key design choices:
- Synchronous route (not `async def`) — blocking sqlite3 is fine for lightweight health-adjacent endpoint
- Explicit camelCase mapping in list comprehension — never returns sqlite3.Row directly
- Lazy imports inside handler — consistent with DB_PATH monkeypatching pattern
- Returns `[]` on any exception including missing table or unreadable DB

### Task 2: SQLite read in state.py (state.py)

Replaced the empty sessions placeholder in `DashboardState.update_stats()`:

```python
# Fetch real API usage
try:
    import sqlite3  # noqa: PLC0415
    from sci_fi_dashboard.db import DB_PATH  # noqa: PLC0415 — lazy import avoids circular

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT input_tokens, output_tokens, total_tokens "
        "FROM sessions ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    self.active_sessions = len(rows)
    self.total_tokens_in = sum(r["input_tokens"] for r in rows)
    self.total_tokens_out = sum(r["output_tokens"] for r in rows)
except Exception:
    pass
```

Key design choices:
- Imports inside `try:` block — preserves monkeypatching compatibility for SYNAPSE_HOME tests
- `conn.close()` explicit (not context manager) — consistent with plan spec
- Reads `input_tokens`/`output_tokens` column names directly (snake_case from DB)
- No subprocess calls; fault-tolerant via existing `except Exception: pass` guard

## Verification

Both files parse cleanly with `ast.parse()`. The following test suites pass:

- `tests/test_config.py` — 7 tests
- `tests/test_queue.py` — 14 tests
- `tests/test_llm_router.py` — 20 tests
- `tests/test_smoke.py` — 25 tests
- `tests/test_flood.py` — 7 tests
- `tests/test_dedup.py` — 8 tests

Total: 81 tests passing.

## Deviations from Plan

None — plan executed exactly as written.

## Requirements Satisfied

- SESS-02: GET /api/sessions returns JSON list with camelCase field names (inputTokens, outputTokens, totalTokens, sessionId, contextTokens)
- SESS-03: state.py update_stats() populates total_tokens_in and total_tokens_out from sessions table without shelling out

## Self-Check: PASSED
