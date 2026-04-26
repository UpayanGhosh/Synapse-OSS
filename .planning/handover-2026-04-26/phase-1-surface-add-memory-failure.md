# Phase 1 — Surface silent `add_memory` failure

## TL;DR
Make the silent `add_memory` failure inside `_ingest_session_background` user-visible via a persisted failure record, an HTTP `/memory_health` endpoint, and a `synapse_cli memory-health` subcommand — so Phase 2 has the real exception to fix.

## Goal
Today the user has no way to know whether their last `/new` actually wrote anything to `documents`. Per E1.7, the 06:20 archive on 2026-04-25 succeeded at the JSONL level but silently failed the vector path. After this phase: the failure is captured in `memory.db`, surfaced via `GET /memory_health`, and queryable from the CLI. We do **not** fix the root cause here — that is Phase 2's job.

## Severity & Effort
- **Severity:** P1 (silent data loss; user-visible reliability gap)
- **Effort:** S (~1 hr)
- **Blocks:** Phase 2 (Phase 2 needs the captured exception to know what to fix)
- **Blocked by:** None

## Why this matters (with evidence)

The chat → memory pipeline has three writers: vector (`documents` + `vec_items` + LanceDB), KG (`entity_links`), and the session token-counter (`sessions` table). Per **E1.5**, the `sessions` table is alive — five fresh rows from 2026-04-26 with sane token counts. Per **E1.4**, `entity_links` is alive — 178 triples written in the past 7 days. But per **E1.1**, only 5 rows ever exist with `filename='session'`, and the most recent one is from 2026-04-25 00:51. The vector path for normal day-to-day chat ingestion is dead.

This dead path is invisible to the user. `_ingest_session_background` runs as a fire-and-forget `asyncio.create_task()` from `pipeline_helpers.py:325-332` (`_handle_new_command`), and on failure it lands in this swallow:

```python
# workspace/sci_fi_dashboard/session_ingest.py:140-149
# ── 1. Vector ingestion ──
try:
    deps.memory_engine.add_memory(
        content=text,
        category="session",
        hemisphere=hemisphere,
    )
    ingested_vec += 1
except Exception as exc:
    log.error("[session_ingest] vector batch %d/%d failed: %s", i + 1, len(batches), exc)
```

`log.error` writes a line to the gateway log. That's it. The user sees `"Session archived! I'll remember everything. Starting fresh now."` (`pipeline_helpers.py:348`) and walks away. Per **E1.7**, this is exactly what happened on 2026-04-25 06:20 — JSONL archived, KG path produced 178 triples, vector path silently produced nothing. There is currently no way for a user to tell from the bot's surface that ingestion failed.

The existing `/health` endpoint (`workspace/sci_fi_dashboard/routes/health.py:20-51`) returns `memory_ok: bool(get_db_stats())` — which is `True` whenever the DB has any rows at all, so it has been reporting `True` through every silent failure of the past two months. Insufficient signal.

This phase doesn't fix the bug. It makes the bug observable. The diagnostic surface is the prerequisite for Phase 2's root-cause fix and for the OSS sign-off criterion ("documents table grows organically as user chats — no manual /new required for ingestion to fire").

## Current state — what's there now

**Where the swallow happens** — `workspace/sci_fi_dashboard/session_ingest.py:148`:

```python
except Exception as exc:
    log.error("[session_ingest] vector batch %d/%d failed: %s", i + 1, len(batches), exc)
```

The `exc` is logged but never persisted. The KG branch directly below it (`session_ingest.py:185-186`) does the same swallow.

**Where the user is told it succeeded** — `workspace/sci_fi_dashboard/pipeline_helpers.py:348`:

```python
return "Session archived! I'll remember everything. Starting fresh now."
```

This string is returned regardless of whether `_ingest_session_background` later succeeds or fails — the task is fired and forgotten at line 325.

**What exists for diagnostics today**:
- `GET /health` (`routes/health.py:20-51`) — boolean `memory_ok` derived from `get_db_stats()`, no temporal info.
- `synapse_cli` (`workspace/synapse_cli.py`) — Typer app with `whatsapp` and `antigravity` subcommand groups; no `memory` subcommand.
- `memory_diary` table (`db.py:79-92`) — has `dominant_mood TEXT` column, suitable for piggybacking failure markers if we choose that route.

**Counters that already exist in `_ingest_session_background`** (lines 134-135):

```python
ingested_vec = 0
ingested_kg = 0
```

These are calculated and logged at line 198-204 but never persisted. The terminal log line `"[session_ingest] done: %d/%d vec batches, %d KG triples — session %s"` is the only place they appear.

## Target state — what it should do after

After this phase:

1. **Persisted failure record.** When `add_memory` raises inside `_ingest_session_background`, an `ingest_failures` row is written to `memory.db` capturing: `created_at`, `session_key`, `agent_id`, `archived_path`, `batch_index`, `total_batches`, `phase` (`'vector' | 'kg' | 'load'`), `exception_type`, `exception_msg`, `traceback` (truncated to 4 KB).
2. **Persisted success record.** On a clean run, write a single summary row capturing `ingested_vec`, `ingested_kg`, `total_batches`, `session_key` so success has the same observability surface as failure. (Same table, `phase='completed'`, `exception_*` NULL.)
3. **`GET /memory_health` endpoint.** Returns JSON:
   ```json
   {
     "last_doc_added_at": "2026-04-25T00:51:12+00:00",
     "last_kg_extraction_at": "2026-04-25T23:23:23+00:00",
     "last_ingest_completed_at": "2026-04-26T01:02:03+00:00",
     "last_ingest_failure_at": "2026-04-25T06:20:14+00:00",
     "pending_session_message_count": 56,
     "recent_failures": [
       {"created_at": "...", "session_key": "...", "phase": "vector",
        "exception_type": "ConnectionError", "exception_msg": "..."}
     ]
   }
   ```
4. **`synapse_cli memory-health` subcommand.** Pretty-prints the same payload (Rich table). Exits non-zero if `last_ingest_failure_at` is newer than `last_ingest_completed_at`.

The `memory_diary` table is **not** the right home for this — it is a daily-summary surface (one row per day per user) and would require schema overload to be useful. A dedicated `ingest_failures` table is cheaper and cleaner.

## Tasks (ordered)

- [ ] **Task 1.1** — Add the `ingest_failures` table migration. Files: `workspace/sci_fi_dashboard/db.py`. Add a new helper `_ensure_ingest_failures_table(conn)` modeled on `_ensure_jarvis_tables` (`db.py:45-114`) and call it from both `_ensure_db()` (`db.py:255-256`) and the existing-DB migration block (`db.py:262-266`). Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS ingest_failures (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      session_key     TEXT,
      agent_id        TEXT,
      archived_path   TEXT,
      batch_index     INTEGER,
      total_batches   INTEGER,
      phase           TEXT NOT NULL,           -- 'load' | 'vector' | 'kg' | 'completed'
      exception_type  TEXT,
      exception_msg   TEXT,
      traceback       TEXT,
      ingested_vec    INTEGER,                 -- only set when phase='completed'
      ingested_kg     INTEGER                  -- only set when phase='completed'
  );
  CREATE INDEX IF NOT EXISTS idx_ingest_failures_created_at
      ON ingest_failures(created_at);
  CREATE INDEX IF NOT EXISTS idx_ingest_failures_phase
      ON ingest_failures(phase);
  ```

- [ ] **Task 1.2** — Wire failure capture in `_ingest_session_background`. Files: `workspace/sci_fi_dashboard/session_ingest.py`. Three call sites:
  - `session_ingest.py:90-92` (transcript load failure → `phase='load'`)
  - `session_ingest.py:148-149` (vector batch → `phase='vector'`)
  - `session_ingest.py:185-186` (KG batch → `phase='kg'`)

  Add a helper `_record_ingest_failure(memory_db_path, *, phase, session_key, agent_id, archived_path, batch_index, total_batches, exc)` that opens its own short-lived `sqlite3.connect(memory_db_path)` (matching the pattern at `session_ingest.py:158`), inserts a row, and never raises (wrap the insert in `try/except` and downgrade to `log.warning` on insert failure — we cannot have telemetry-write blow up the ingest path).

- [ ] **Task 1.3** — Wire success capture. Files: `workspace/sci_fi_dashboard/session_ingest.py`. After the final summary log at `session_ingest.py:198-204`, insert a `phase='completed'` row carrying `ingested_vec` and `ingested_kg`.

- [ ] **Task 1.4** — Add the `/memory_health` route. Files: `workspace/sci_fi_dashboard/routes/health.py`. New handler in the existing `router`. Queries (use `get_db_connection()` from `db.py:338`):
  ```sql
  SELECT MAX(created_at) FROM documents;
  SELECT MAX(created_at) FROM entity_links;
  SELECT MAX(created_at) FROM ingest_failures WHERE phase = 'completed';
  SELECT MAX(created_at) FROM ingest_failures WHERE phase IN ('load','vector','kg');
  SELECT created_at, session_key, phase, exception_type, exception_msg
      FROM ingest_failures WHERE phase != 'completed'
      ORDER BY created_at DESC LIMIT 10;
  ```
  For `pending_session_message_count`, count lines across all `*.jsonl` files under `~/.synapse/state/agents/*/sessions/` that are NOT `*.deleted.*`. Use `SynapseConfig.load().data_root` to anchor the path.

  Apply `Depends(_require_gateway_auth)` matching the `/gateway/status` pattern at `routes/health.py:54` so this is not anonymous (it leaks timestamps and exception messages).

- [ ] **Task 1.5** — Add the CLI subcommand. Files: `workspace/synapse_cli.py`. New typer group `memory_app = typer.Typer(name="memory", help="Memory pipeline diagnostics")` modeled on the existing `wa_app` (`synapse_cli.py:27-28`). One command: `memory-health` (Typer infers from method name `memory_health`) that:
  - reads `~/.synapse/synapse.json → gateway.token` (via `SynapseConfig.load()`) for the auth header
  - hits `http://127.0.0.1:{port}/memory_health` with `httpx`
  - pretty-prints with `rich.table.Table`
  - exits with code `1` if `last_ingest_failure_at > last_ingest_completed_at`

- [ ] **Task 1.6** — Tests. Files: create `workspace/tests/test_memory_health.py` if missing. Three tests:
  1. `test_ingest_failure_persisted_to_db` — patch `deps.memory_engine.add_memory` to raise `RuntimeError("boom")`, run `_ingest_session_background` against a tmp transcript, assert one `ingest_failures` row with `phase='vector'` and `exception_type='RuntimeError'`.
  2. `test_memory_health_endpoint_shape` — TestClient on the FastAPI app, populate one row in each of `documents`, `entity_links`, `ingest_failures`, hit `/memory_health` with auth, assert all 6 keys present.
  3. `test_memory_health_endpoint_requires_auth` — same call without `Authorization` header → 401.

  Per ROADMAP §"Don't re-introduce test pollution": new tests MUST mock `MemoryEngine.add_memory` per the canonical pattern at `workspace/tests/pipeline/conftest.py:296-300`. The first test patches `add_memory` to raise, which already satisfies this.

- [ ] **Task 1.7** — Update CLAUDE.md "Configuration → Critical Gotchas" with a one-liner that the `/memory_health` endpoint is the canonical health probe for the ingestion pipeline.

## Dependencies
- **Hard:** None.
- **Soft:** None.
- **Provides:** Phase 2 reads `ingest_failures` rows to learn what `add_memory` is actually raising. Phase 3's auto-flush trigger reads `pending_session_message_count` from this endpoint.

## Success criteria (must all be true before claiming done)
- [ ] `ingest_failures` table exists in a fresh OSS install (verify via `sqlite3 ~/.synapse/workspace/db/memory.db ".schema ingest_failures"`).
- [ ] Existing dev DB picks up the table on first boot after the change (verify on `~/.synapse/workspace/db/memory.db` — same `.schema` query).
- [ ] Forcing a failure (e.g. monkeypatch `MemoryEngine.add_memory` to raise) writes one `phase='vector'` row.
- [ ] A clean `/new` writes one `phase='completed'` row with non-zero `ingested_vec` and `ingested_kg`.
- [ ] `curl -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" http://127.0.0.1:8000/memory_health` returns all 6 keys.
- [ ] `python workspace/synapse_cli.py memory health-check` (or whatever Typer routes to) exits 0 on healthy DB and 1 after an injected failure.
- [ ] All three new tests pass via `cd workspace && pytest tests/test_memory_health.py -v`.
- [ ] No new `MagicMock` strings appear in `documents.content` after the test run (regression guard from E1.8).

## Verification recipe (how Codex proves it works)

```bash
# 0. Branch from develop
git checkout develop
git checkout -b fix/phase-1-surface-add-memory-failure

# 1. Migration applies on existing DB
python -c "from workspace.sci_fi_dashboard.db import get_db_connection; \
  c = get_db_connection(); \
  print(c.execute('SELECT name FROM sqlite_master WHERE name=\"ingest_failures\"').fetchone())"
# expected: ('ingest_failures',)

# 2. Run the new tests
cd workspace && pytest tests/test_memory_health.py -v

# 3. End-to-end smoke (gateway must be running)
curl -s -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  http://127.0.0.1:8000/memory_health | python -m json.tool

# 4. Trigger a real failure (kill Ollama, then /new). Verify ingest_failures row appears.
ollama stop  # or kill the process
curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "/new"}' http://127.0.0.1:8000/chat/the_creator
sleep 5
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT phase, exception_type, exception_msg FROM ingest_failures ORDER BY created_at DESC LIMIT 1;"

# 5. Pollution regression guard
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%';"
# expected: 0

# 6. CLI command
python workspace/synapse_cli.py memory health-check
# Should print a pretty table with the 6 fields.

# 7. Lint
ruff check workspace/sci_fi_dashboard/db.py \
  workspace/sci_fi_dashboard/session_ingest.py \
  workspace/sci_fi_dashboard/routes/health.py \
  workspace/synapse_cli.py \
  workspace/tests/test_memory_health.py
black --check workspace/
```

## Risks & gotchas

- **Auth on `/memory_health`** — exception messages can contain file paths or partial content. Wire `Depends(_require_gateway_auth)` (see `routes/health.py:54`); do not leave it anonymous.
- **Telemetry write must not crash ingest** — wrap the `INSERT INTO ingest_failures` in its own `try/except` so a corrupt DB or schema drift cannot turn an ingest hiccup into a complete loss. Downgrade to `log.warning` on insert failure.
- **Connection lifecycle** — `_ingest_session_background` already opens its own `sqlite3.connect(memory_db_path)` at line 158 for the KG branch. Reuse the same pattern; do **not** call `get_db_connection()` from the background task because that goes through `DatabaseManager._ensure_db()` which has a global lock and is unnecessary overhead per-batch.
- **Index growth** — `ingest_failures` is unbounded. Phase 1 leaves it that way; document a future TTL prune in CLAUDE.md and let the gentle worker (`gentle_worker.py`) handle it later. Do not add a prune in this phase.
- **Windows cp1252 in CLI output** — the CLI prints exception messages that may contain emoji from WhatsApp transcripts. Wrap with the `safe()` helper from `EVIDENCE.md` lines 21-24 before printing, or use Rich (which handles encoding correctly).
- **Existing dev DB is 226 MB** — running the migration is fast, but back up first per ROADMAP §"Tools & environment notes". Backup is already at `~/.synapse/workspace/db/memory.db.bak_1777166450`; an additional pre-migration copy is cheap insurance.

## Out of scope (DO NOT do these in this phase)

- Fixing the actual `add_memory` failure. That is Phase 2.
- Auto-firing `_ingest_session_background` on idle/threshold. That is Phase 3.
- Touching `atomic_facts` or `kg_processed`. That is Phase 4.
- Adding a UI surface in the dashboard for `ingest_failures`. JSON endpoint + CLI is sufficient for the diagnostic loop.
- Pruning old `ingest_failures` rows. Future work.
- Pulling the same data into the existing `/health` endpoint. Keep the surfaces separate so OSS users with no gateway token still get the binary `/health`.

## Evidence references

- **E1.1** (documents composition) — only 5 rows ever exist with `filename='session'`, last one 2026-04-25 00:51. Confirms vector path is rarely producing.
- **E1.4** (entity_links alive) — 178 triples in past 7 days. KG path is healthy; vector path is not.
- **E1.5** (sessions table tracks tokens not content) — chat content is missing from `documents` even when token-counter rows exist.
- **E1.7** (last `/new` archived but vector-path failed) — direct evidence of silent failure on 2026-04-25 06:20. The KG path produced triples; the vector path did not, and the user got no signal.
- **E7** (sqlite query recipes) — recipes 1, 3, 4 become the basis of the `/memory_health` queries.

> **Note:** EVIDENCE.md does not yet have a section explicitly listing `BACKUP_FILE` (memory_engine.py:80, `_archived_memories/persistent_log.jsonl`) as a diagnostic input. If the file exists and is readable from the gateway process, a future revision could add `last_backup_jsonl_append_at` to `/memory_health`. Out of scope for Phase 1.

## Files touched (expected)

- `workspace/sci_fi_dashboard/db.py` — add `_ensure_ingest_failures_table` helper + wire it into `_ensure_db()` and the migration block.
- `workspace/sci_fi_dashboard/session_ingest.py` — wire `_record_ingest_failure` at the three swallow sites + the success site.
- `workspace/sci_fi_dashboard/routes/health.py` — add `/memory_health` handler.
- `workspace/synapse_cli.py` — add `memory` typer subgroup with `health-check` command.
- `workspace/tests/test_memory_health.py` — new file with three tests.
- `CLAUDE.md` — one-liner under "Critical Gotchas" or a new "Diagnostics" subsection pointing at `/memory_health`.
