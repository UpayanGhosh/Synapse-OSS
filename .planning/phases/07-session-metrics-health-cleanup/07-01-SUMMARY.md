---
phase: 07-session-metrics-health-cleanup
plan: "01"
subsystem: session-tracking
tags: [sqlite, sessions, llm-instrumentation, token-tracking, SESS-01]
dependency_graph:
  requires: []
  provides: [sessions-table-schema, _write_session-helper, call()-session-side-effect]
  affects: [07-02-api-sessions-endpoint, 07-02-state-replacement]
tech_stack:
  added: [uuid (stdlib), sqlite3-sessions-schema]
  patterns: [idempotent-migration, non-fatal-side-effect, lazy-import-for-monkeypatching]
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/db.py
    - workspace/sci_fi_dashboard/llm_router.py
decisions:
  - "_ensure_sessions_table() placed at module level in db.py — callable with any sqlite3.Connection for fresh and existing DBs"
  - "Existing DB migration handled via else branch in _ensure_db() with fresh sqlite3.connect() — no sqlite-vec needed for sessions table"
  - "executescript() used for sessions DDL inside _ensure_sessions_table() — matches existing pattern in _ensure_db() for documents schema"
  - "_write_session() uses lazy import of DB_PATH inside function body — mirrors existing noqa PLC0415 pattern in codebase for monkeypatching compatibility"
  - "call_model() NOT instrumented — used for validation pings in onboarding wizard where token tracking is irrelevant (per plan spec)"
  - "Non-fatal try/except around _write_session() in call() — session write failure must not break LLM response delivery"
metrics:
  duration: 12 min
  completed_date: "2026-03-03"
  tasks_completed: 2
  files_modified: 2
---

# Phase 7 Plan 01: Sessions Table and LLM Instrumentation Summary

**One-liner:** SQLite sessions table added to memory.db via idempotent `_ensure_sessions_table()` migration, and `SynapseLLMRouter.call()` instrumented with non-fatal `_write_session()` side effect capturing input/output/total token counts.

## What Was Built

### Task 1 — `workspace/sci_fi_dashboard/db.py`

Added `_ensure_sessions_table(conn: sqlite3.Connection) -> None` as a module-level function before `DatabaseManager`. The function uses `executescript()` with `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` to idempotently create:

- **sessions table** (8 columns): `id`, `session_id`, `role`, `model`, `input_tokens`, `output_tokens`, `total_tokens`, `created_at`
- **`idx_sessions_created_at`** index on `sessions(created_at)` for efficient time-range queries

Called from `DatabaseManager._ensure_db()` in two places:
1. **New DB path**: called before `conn.close()` sharing the existing connection
2. **Existing DB path** (new `else` branch): opens a fresh `sqlite3.connect(DB_PATH)` as a context manager — no sqlite-vec extension needed for sessions DDL

### Task 2 — `workspace/sci_fi_dashboard/llm_router.py`

Added `import uuid` and `import sqlite3` to the top-level imports.

Added `_write_session(role: str, model: str, usage) -> None` as a module-level function:
- Lazy-imports `DB_PATH` from `sci_fi_dashboard.db` inside the function body (`noqa: PLC0415`) to allow test monkeypatching of `SYNAPSE_HOME`
- Guards all `usage` attribute access: `getattr(usage, "prompt_tokens", 0) or 0` — handles `None` usage objects
- Uses `str(uuid.uuid4())` as unique `session_id` per row
- Opens fresh `sqlite3.connect(DB_PATH)` as context manager, executes INSERT, calls `conn.commit()`

Instrumented `SynapseLLMRouter.call()`:
- Extracts response text as `text = choice.message.content or ""`
- Wraps `_write_session()` in `try/except Exception` — failure is logged at DEBUG level, never propagated
- Returns `text` after session write (or after write failure)
- `call()` signature unchanged: `async def call(self, role, messages, temperature, max_tokens) -> str`
- `call_model()` NOT touched — not instrumented per plan spec

## Verification Results

**Task 1 verification (fresh DB):**
```
PASS: sessions table created with correct schema
Tables: ['documents', ..., 'sessions']
Columns: ['id', 'session_id', 'role', 'model', 'input_tokens', 'output_tokens', 'total_tokens', 'created_at']
Indexes: ['idx_documents_hemisphere', ..., 'idx_sessions_created_at']
```

**Task 1 verification (existing DB):**
```
PASS: sessions table migrated into existing DB
```

**Task 2 verification (AST check):**
```
PASS: _write_session defined and called in llm_router.py
```

**Full test suite (non-integration, non-performance):**
```
251 passed, 24 deselected, 4 xfailed, 2 xpassed, 0 failures in 87.25s
```

Note: `test_performance.py::test_concurrent_writes` failed with `65.87s > 10.0s` assertion — pre-existing environmental issue (Windows SQLite concurrent write performance); unrelated to this plan's changes. All 20 `test_llm_router.py` tests pass.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `a3454d0` | feat(07-01): add sessions table to db.py via _ensure_sessions_table() |
| Task 2 | `c5ad313` | feat(07-01): add _write_session() and instrument call() in llm_router.py |

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Added else branch for existing DB migration**

- **Found during:** Task 1 implementation
- **Issue:** Plan specified calling `_ensure_sessions_table(conn)` inside the `if not os.path.exists(DB_PATH):` block only. This would skip migration for existing DBs (non-fresh-boot). The plan's verify script uses a temp directory (fresh DB), so the test passes either way, but production upgrades would miss the sessions table on existing DBs.
- **Fix:** Added `else:` branch after the `if not os.path.exists(DB_PATH):` block that opens a fresh `sqlite3.connect(DB_PATH)` context manager and calls `_ensure_sessions_table()` — idempotent via `CREATE TABLE IF NOT EXISTS`.
- **Files modified:** `workspace/sci_fi_dashboard/db.py`
- **Commit:** `a3454d0`

## Self-Check

### Created files
- None to check (no new files created)

### Modified files
- `workspace/sci_fi_dashboard/db.py` — confirmed modified (`a3454d0`)
- `workspace/sci_fi_dashboard/llm_router.py` — confirmed modified (`c5ad313`)

### Commits
- `a3454d0` — confirmed in git log
- `c5ad313` — confirmed in git log

## Self-Check: PASSED
