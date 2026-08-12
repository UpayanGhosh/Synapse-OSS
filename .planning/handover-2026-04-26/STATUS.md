# Phase 2 Status — Fix Vector Path Failure

Branch: `fix/phase-2-fix-vector-path-failure`
Date: 2026-04-26

## Phase 1 Telemetry State

`ingest_failures` table had **zero pre-existing rows** at Phase 2 start. The gateway had not
run with Phase 1 in place, so no telemetry was available to guide root-cause diagnosis. All
fixes in Phase 2 are code-audit-driven (defensive), not telemetry-driven.

## Tasks Completed

| Task | SHA | Status |
|------|-----|--------|
| 2.1 — Read Phase 1 telemetry | — | CONFIRMED EMPTY |
| 2.2 — Return-value check + telemetry | e95c6d2 | DONE |
| 2.3 — Defensive root-cause fix | e95c6d2 | DONE |
| 2.4 — CLAUDE.md footgun doc | 447bb4d | DONE |
| 2.5 — Unit tests (3 cases) | 58870e3 | DONE — 3/3 pass |
| 2.6 — Integration smoke | — | DEFERRED (see below) |
| 2.7 — This STATUS.md | current | DONE |

## Defensive Fix Applied — Task 2.3 Candidate (a): BACKUP_FILE path refactor

**Root cause candidate addressed**: The module-level `BACKUP_FILE` constant resolved to
`workspace/_archived_memories/persistent_log.jsonl` under the repo root. On 2026-04-26
this directory was cleaned, and on Windows a missing parent directory + asyncio background
task timing can produce a silent `FileNotFoundError` that is caught by `add_memory`'s
outer `except Exception` and returned as `{"error": str(e)}` — which callers never checked.

**Fix applied**:
- Replaced `BACKUP_FILE` constant with `_resolve_backup_path()` that resolves under
  `~/.synapse/workspace/_archived_memories/persistent_log.jsonl` via `SynapseConfig.data_root`
- Moved `os.makedirs` + `Path.touch()` into `MemoryEngine.__init__` so the directory and
  file are pre-created once at gateway startup; any `OSError` surfaces immediately as a
  `[WARN]` print rather than silently failing the first `add_memory` call
- `add_memory` now uses `self._backup_file` (instance attribute) instead of the module global

**Candidates NOT applied**:
- **(b) Extension-load**: `add_memory` already uses `get_db_connection()` which goes through
  `DatabaseManager._ensure_db()` (threading.Lock + sqlite_vec load). No change needed.
- **(c) Ollama**: already wrapped at `memory_engine.py:425-426` — doc inserted with
  `processed=0` even on embed failure.
- **(d) LanceDB**: already wrapped in its own try/except at `memory_engine.py:421`.

## Return-Value Check Applied — Task 2.2

`_ingest_session_background` now:
1. Captures `add_memory()` return value
2. On raised exception → calls `_record_ingest_failure(phase='vector')` then `continue`
3. On `{"error": ...}` return → wraps in `RuntimeError`, calls `_record_ingest_failure(phase='vector')` then `continue`
4. Only increments `ingested_vec` on confirmed success
5. Fixed off-by-one: `batch_index` now uses `i+1` (1-based) consistently

## Residual Risk

**If the BACKUP_FILE path race was not the actual root cause**: Phase 1 telemetry will now
capture the real exception type and message in `ingest_failures` after the next gateway run.
Query:
```sql
SELECT phase, exception_type, exception_msg, traceback
FROM ingest_failures
WHERE phase = 'vector'
ORDER BY created_at DESC LIMIT 10;
```
Use `synapse memory memory-health` CLI or `GET /memory_health` endpoint. A follow-up phase
will tighten the fix once real exception data is available.

## Scope Boundaries — What Phase 2 Does NOT Do

- **No auto-flush** of the 56 unflushed messages in session `cecb9c73` — that is Phase 3.
- **No backfill** of the ~30-50 lost sessions from 2026-02-13 onward. Historical chat content
  exists only in JSONL transcripts, not in `documents`. These sessions can be manually
  re-ingested via `_ingest_session_background` once the vector path is confirmed healthy,
  but this is explicitly out of scope for Phase 2.
- **No `kg_processed` / `atomic_facts` changes** — Phase 4.
- **No `add_memory` refactor to raise** — too many callers; documented as footgun in
  CLAUDE.md gotcha 11 instead.
- **No new `/memory_health` metrics** — Phase 1 surface is sufficient.

## Integration Smoke Recipe (run manually after gateway restart)

```bash
before=$(python -c "
import sqlite3, pathlib
db = pathlib.Path.home() / '.synapse/workspace/db/memory.db'
print(sqlite3.connect(str(db)).execute(\"SELECT COUNT(*) FROM documents WHERE filename='session'\").fetchone()[0])
")
curl -s -X POST \
  -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "/new"}' \
  http://127.0.0.1:8000/chat/the_creator
# wait ~10s for background ingestion
sleep 10
after=$(python -c "
import sqlite3, pathlib
db = pathlib.Path.home() / '.synapse/workspace/db/memory.db'
print(sqlite3.connect(str(db)).execute(\"SELECT COUNT(*) FROM documents WHERE filename='session'\").fetchone()[0])
")
echo "before=$before after=$after"
# Expect after > before
# Also check: synapse memory memory-health
```
