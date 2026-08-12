# Phase 2 — Fix vector-path failure in `_ingest_session_background`

## TL;DR
Diagnose and root-cause-fix the silent failure that prevents `MemoryEngine.add_memory` from writing `documents` rows when called from the `_ingest_session_background` asyncio task — using the diagnostic surface from Phase 1.

## Goal
After this phase, every successful `/new` produces at least one new `documents` row with `filename='session'` and a corresponding `vec_items` row (and LanceDB upsert when configured). The `ingest_failures` table records `phase='completed'`, not `phase='vector'`, on a healthy run. No silent failures, no try/except band-aids — the actual exception that Phase 1 surfaced is fixed at its source.

## Severity & Effort
- **Severity:** P1+ (silent data loss; chat ingestion has been broken for ~2 months — the entire post-bulk-import history exists only in JSONL transcripts, not in semantic memory)
- **Effort:** M (~3 hr — diagnosis 1 hr, fix 1 hr, verification 1 hr)
- **Blocks:** Phase 3 (auto-flush would amplify the failure if it lands first)
- **Blocked by:** Phase 1 (need the captured exception)

## Why this matters (with evidence)

Per **E1.1**, `documents` has 10,383 rows post-cleanup, but 99.6% of them are the WhatsApp bulk import from 2026-02. Day-to-day chat has produced ~30-50 rows total since then, and only 5 of them have `filename='session'`. The most recent `session` doc is from 2026-04-25 00:51 — before today's 56-message session (E1.6) and before the failed 06:20 `/new` (E1.7).

The path is wired correctly on paper: `pipeline_helpers.py:325-332` schedules `_ingest_session_background` as a fire-and-forget task, and that function calls `deps.memory_engine.add_memory(content=text, category="session", hemisphere=hemisphere)` at `session_ingest.py:142-146`. `add_memory` itself (`memory_engine.py:368-432`) is `@with_retry(retries=5, delay=0.1)`, opens a connection, inserts into `documents`, generates an embedding, writes to `vec_items` and LanceDB, and commits. There is no obvious bug in static reading. Yet runtime behaviour is silent failure.

E1.7 confirms the asymmetry: KG path succeeded (178 triples), vector path failed. Both paths run inside the same coroutine, on the same event loop, with the same `memory_db_path`. The thing that differs is what `add_memory` touches that the KG branch does not:

- `BACKUP_FILE` (`memory_engine.py:80`) — `os.path.join(WORKSPACE_ROOT, "_archived_memories", "persistent_log.jsonl")`. Resolves to `D:\Shorty\Synapse-OSS\workspace\_archived_memories\persistent_log.jsonl`. The directory was cleaned during the 2026-04-26 pollution sweep (ROADMAP §"What was JUST DONE": "65 → 47 lines"). Could be a stale handle, a race with the cleanup, or a Windows path/permissions issue when called from the background task.
- `get_db_connection()` (`memory_engine.py:379`) — goes through `DatabaseManager._ensure_db()` (`db.py:184`) which has a `threading.Lock`. The KG branch in `session_ingest.py` uses `sqlite3.connect(memory_db_path)` directly (line 158), bypassing the manager. Possible deadlock or initialization-time bug when called from a background asyncio task running on a non-main thread.
- Embedding via `self.get_embedding(content)` (`memory_engine.py:392`) — typically Ollama on `http://localhost:11434`. If Ollama is down, `embedding` is `None`, and the code path at `memory_engine.py:425-426` logs `[WARN] Embedding failed for doc {doc_id}; queued for later processing` but does NOT raise. The doc is still inserted with `processed=0`. This means an Ollama outage cannot explain the missing `documents` rows — the row would still exist. Whatever fails happens **before** the embedding step or aborts the whole transaction silently.
- LanceDB upsert (`memory_engine.py:407-422`) — wrapped in its own `try/except`, swallowed. Cannot block the doc insert.
- The outer `try/except` at `memory_engine.py:371`/`:431` returns `{"error": str(e)}` on any exception. **This is the real swallow surface.** `add_memory` does not raise on most errors — it returns an error dict that the caller has to inspect. `session_ingest.py:142-147` does not inspect the return value.

That last point is critical: **`session_ingest.py` thinks it succeeded** when `add_memory` quietly returns `{"error": "..."}` because the `try/except` at line 148 only catches actual raises, not error returns. So `ingested_vec += 1` increments and the summary log claims success. The `/new` archived → KG-only outcome described in E1.7 is consistent with `add_memory` returning an error dict that nobody checks.

This phase fixes both: identifies the actual exception (via Phase 1 telemetry once we additionally capture error-dict returns), then fixes the root cause.

## Current state — what's there now

**The swallow surface in `add_memory`** — `workspace/sci_fi_dashboard/memory_engine.py:367-432`:

```python
@with_retry(retries=5, delay=0.1)
def add_memory(
    self, content: str, category: str = "direct_entry", hemisphere: str = "safe"
) -> dict:
    try:
        # Backup
        os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)
        ...
        conn = get_db_connection()
        cursor = conn.cursor()
        ...
        cursor.execute("INSERT INTO documents ...", (...))
        doc_id = cursor.lastrowid
        embedding = self.get_embedding(content)
        if embedding is not None:
            ...
            cursor.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
        else:
            print(f"[WARN] Embedding failed for doc {doc_id}; queued for later processing")
        conn.commit()
        conn.close()
        return {"status": "stored", "id": doc_id, "embedded": embedding is not None}
    except Exception as e:
        return {"error": str(e)}
```

`@with_retry(retries=5, delay=0.1)` (`memory_engine.py:36-56`) only retries on `sqlite3.OperationalError` with `"locked"` in its string. Any other exception falls through to the outer `try/except` and returns `{"error": str(e)}`.

**The non-checking caller** — `workspace/sci_fi_dashboard/session_ingest.py:140-149`:

```python
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

The return value is discarded. `ingested_vec` always increments unless an exception leaks through `add_memory`'s outer try.

**The KG branch by contrast** — `session_ingest.py:158`:

```python
conn = sqlite3.connect(memory_db_path)
try:
    _ensure_entity_links(conn)
    for triple, confidence in validated:
        ...
```

Direct `sqlite3.connect`, no `DatabaseManager`, no extension load (KG only writes to `entity_links`, doesn't need `vec0`). This is why E1.4 shows it working.

## Target state — what it should do after

1. `_ingest_session_background` checks `add_memory`'s return value. If it has an `"error"` key, the failure is recorded via Phase 1's `_record_ingest_failure` with `phase='vector'` and the exception string. `ingested_vec` only increments on `{"status": "stored", ...}`.
2. The actual root cause Phase 1 surfaced is fixed. Likely candidates ranked by suspicion:
   - **(a) `BACKUP_FILE` path race** — Windows `os.makedirs` + `open(..., "a")` from a background asyncio task, possibly racing with the 2026-04-26 cleanup. Fix: replace `BACKUP_FILE` derivation with `SynapseConfig.load().data_root / "workspace" / "_archived_memories" / "persistent_log.jsonl"` so it lives under `~/.synapse/` and not under repo root, and pre-create the directory once at gateway startup instead of on every call.
   - **(b) `get_db_connection()` from a background task** — `DatabaseManager._init_lock` is a `threading.Lock` (`db.py:181`). On Windows, `sqlite-vec` extension load (`db.py:303`) can fail intermittently. Fix: switch `add_memory` to the same `sqlite3.connect(memory_db_path)` pattern the KG branch uses, since `add_memory` does not need vector-extension features for the `INSERT INTO documents` and `INSERT INTO vec_items` calls — `vec_items` is a `vec0` virtual table that requires the extension. So if the connection comes via `get_db_connection`, the extension loads; if it comes via plain `sqlite3.connect`, the `vec_items` insert fails. **Verify** which path is actually loaded.
   - **(c) Ollama embedding fail bypassing the doc insert** — already handled (the doc is inserted with `processed=0`) so this should NOT cause missing rows. If E1.1 shows missing rows, this is not the cause. Confirm by checking whether any rows have `processed=0` and `embedding_model='nomic-embed-text'`.
   - **(d) LanceDB upsert path race** — already wrapped in its own try/except (line 421), should not surface.
3. A unit test exists at `workspace/tests/test_session_ingest.py` (create if absent) that runs `_ingest_session_background` end-to-end against a `tmp_path` `memory.db` and asserts at least one `documents` row was created with `filename='session'`.
4. An integration smoke produces a real `documents` row with `filename='session'` against the dev DB after a `/new`.
5. `ingest_failures` shows `phase='completed'` for the run, not `phase='vector'`.

## Tasks (ordered)

- [ ] **Task 2.1** — Read Phase 1's `ingest_failures` output. Files: query `~/.synapse/workspace/db/memory.db`. Run:
  ```bash
  sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT created_at, phase, exception_type, exception_msg, traceback
     FROM ingest_failures
     WHERE phase != 'completed'
     ORDER BY created_at DESC LIMIT 5;"
  ```
  If no rows exist (because Phase 1 ran clean since landing), force one by triggering a `/new` with conditions that should fail (e.g. Ollama down). Capture the full exception. **This is the single most important step in the phase — every downstream task depends on it.**

- [ ] **Task 2.2** — Add return-value check + telemetry. Files: `workspace/sci_fi_dashboard/session_ingest.py:140-149`. Replace the bare call with:
  ```python
  try:
      result = deps.memory_engine.add_memory(
          content=text,
          category="session",
          hemisphere=hemisphere,
      )
  except Exception as exc:
      _record_ingest_failure(
          memory_db_path, phase="vector", session_key=session_key,
          agent_id=agent_id, archived_path=str(archived_path),
          batch_index=i + 1, total_batches=len(batches), exc=exc,
      )
      log.error("[session_ingest] vector batch %d/%d raised: %s", i + 1, len(batches), exc)
      continue
  if isinstance(result, dict) and "error" in result:
      _record_ingest_failure(
          memory_db_path, phase="vector", session_key=session_key,
          agent_id=agent_id, archived_path=str(archived_path),
          batch_index=i + 1, total_batches=len(batches),
          exc=RuntimeError(result["error"]),
      )
      log.error("[session_ingest] vector batch %d/%d returned error: %s",
                i + 1, len(batches), result["error"])
      continue
  ingested_vec += 1
  ```
  This change alone catches every `{"error": ...}` return and feeds it to Phase 1's telemetry. **This is the highest-leverage line in the phase.**

- [ ] **Task 2.3** — Apply the root-cause fix Phase 1's evidence points to. Decision tree based on what `exception_type` Phase 1 captured:
  - **If `FileNotFoundError` or `PermissionError` on `BACKUP_FILE`** — fix candidate (a). Refactor `BACKUP_FILE` derivation in `memory_engine.py:80` to:
    ```python
    def _resolve_backup_path() -> str:
        cfg = SynapseConfig.load()
        return str(cfg.data_root / "workspace" / "_archived_memories" / "persistent_log.jsonl")
    ```
    Move the `os.makedirs(..., exist_ok=True)` out of `add_memory` and into `MemoryEngine.__init__` (`memory_engine.py:89`) so it runs once.
  - **If `sqlite3.OperationalError` with `"no such module: vec0"` or extension-related** — fix candidate (b). The `add_memory` connection path is loading without the extension. Either ensure `get_db_connection` is the only entry point and trace why it's misbehaving, OR explicitly call `sqlite_vec.load(conn)` in `add_memory` after the connect. Prefer the former — single source of truth.
  - **If `sqlite3.OperationalError` with `"database is locked"`** — `with_retry` should have handled this. Bump `retries` from 5 to 10 and `delay` from 0.1 to 0.25 (`memory_engine.py:367`). Investigate WAL checkpoint contention; consider `PRAGMA wal_autocheckpoint=100`.
  - **If `httpx.ConnectError` or similar Ollama failure** — confirms candidate (c). Per `memory_engine.py:425-426`, the doc *should* still be inserted. If it's not, the order is wrong: the embedding call must come AFTER `cursor.execute("INSERT INTO documents ...")` (line 382) — which it does. So this should never be the cause of a missing row. Re-read `add_memory` carefully for ordering bugs.
  - **If `sqlite3.OperationalError: cannot rollback - no transaction is active`** — connection re-use issue. The fix is to ensure each call to `add_memory` opens and closes its own connection (it does, `memory_engine.py:379`/`:429`). Investigate whether `with_retry` is replaying a closed connection.
  - **Anything else** — debug the specific exception. Do not add try/except — the goal is to identify and fix, not to silence.

- [ ] **Task 2.4** — Update CLAUDE.md "Critical Gotchas" with a new entry: `add_memory returns {"error": str}, does not raise — callers MUST check return value`. This is a footgun that bit us once; document it.

- [ ] **Task 2.5** — Unit test. Files: `workspace/tests/test_session_ingest.py` (create if missing). Test cases:
  1. `test_session_ingest_writes_documents_row` — set up a tmp `memory.db` via monkeypatching `SYNAPSE_HOME` to a `tmp_path`, write a fixture transcript with 5 user/assistant turns to a tmp path, instantiate a real (or partially-mocked) `MemoryEngine`, call `_ingest_session_background` directly, assert a `documents` row with `filename='session'` exists.
  2. `test_session_ingest_records_vector_failure` — same setup but mock `add_memory` to return `{"error": "boom"}`. Assert one `ingest_failures` row with `phase='vector'`.
  3. `test_session_ingest_records_vector_exception` — mock `add_memory` to raise. Assert one `ingest_failures` row with `phase='vector'` and the right `exception_type`.

  Per ROADMAP §"Don't re-introduce test pollution", any test that does NOT explicitly want to test the real write path MUST mock `add_memory`. The first test above intentionally uses the real path against a tmp DB; the latter two mock.

- [ ] **Task 2.6** — Integration smoke. Files: none (manual script). Run a real `/new` against the dev gateway and confirm a `documents` row appears:
  ```bash
  before=$(sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*) FROM documents WHERE filename='session';")
  curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"message": "/new"}' http://127.0.0.1:8000/chat/the_creator
  sleep 10  # allow background task to drain (BATCH_SLEEP_S=1.0 × N batches)
  after=$(sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*) FROM documents WHERE filename='session';")
  echo "before=$before after=$after"  # expect after > before
  ```

- [ ] **Task 2.7** — Backfill check. Files: query only. After the fix lands, do NOT attempt to re-ingest the historical lost JSONLs — that's a separate decision. Document in `STATUS.md` (per ROADMAP execution rule 5) what's been lost and link to E1.7.

## Dependencies
- **Hard:** Phase 1 (need `ingest_failures` telemetry to identify the root cause).
- **Soft:** None.
- **Provides:** Phase 3 can safely auto-trigger `_ingest_session_background` knowing it actually writes documents.

## Success criteria (must all be true before claiming done)
- [ ] Phase 1's `ingest_failures` table shows at least one `phase='completed'` row for a real `/new` run (verify via SQL).
- [ ] No `phase='vector'` rows are produced for a healthy run (Ollama up, disk writable, etc.).
- [ ] `documents` table grows by at least one row per `/new` (smoke from Task 2.6).
- [ ] `vec_items` table grows in lockstep with `documents` for the new rows (sanity check that the vector path is end-to-end).
- [ ] Three new tests pass via `cd workspace && pytest tests/test_session_ingest.py -v`.
- [ ] `pytest tests/ -m unit` passes (no regressions).
- [ ] `pytest tests/ -m integration` passes if Ollama is available (skip otherwise).
- [ ] No `MagicMock` or `<Mock` strings in `documents.content` (regression guard from E1.8).
- [ ] CLAUDE.md updated with the `add_memory returns dict, does not raise` footgun.
- [ ] STATUS.md in `.planning/handover-2026-04-26/` documents what was lost (the historical chat content from 2026-02-13 onward) and that backfill is not in scope.

## Verification recipe (how Codex proves it works)

```bash
# 0. Branch
git checkout develop
git checkout -b fix/phase-2-fix-vector-path-failure
# Phase 1 must be merged first — verify:
sqlite3 ~/.synapse/workspace/db/memory.db ".schema ingest_failures" | head -1
# expected: CREATE TABLE ingest_failures (...

# 1. Capture the actual failure first (this is the diagnostic)
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT created_at, phase, exception_type, exception_msg, substr(traceback, 1, 500)
   FROM ingest_failures
   WHERE phase != 'completed'
   ORDER BY created_at DESC LIMIT 1;"
# If empty: trigger a /new with Ollama down to force a failure, then re-query.

# 2. Apply the root-cause fix (depends on what Step 1 surfaced).
#    No generic command — read Task 2.3 decision tree.

# 3. Run unit tests
cd workspace && pytest tests/test_session_ingest.py -v

# 4. Restart gateway with the fix
# (kill the running uvicorn first — see CLAUDE.md "Critical Gotchas" #4)
pkill -f "uvicorn api_gateway" || true
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload &
sleep 5

# 5. Integration smoke
before=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE filename='session';")
curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "/new"}' http://127.0.0.1:8000/chat/the_creator
sleep 15
after=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE filename='session';")
echo "documents.session: before=$before after=$after"
test "$after" -gt "$before" || echo "FAIL: vector path still broken"

# 6. Vector + LanceDB sanity
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT id, filename, processed, length(content) FROM documents
   WHERE filename='session' ORDER BY id DESC LIMIT 3;"
# Expect: most recent rows have processed=1 (embedding succeeded)

# 7. Telemetry sanity
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT phase, COUNT(*) FROM ingest_failures
   WHERE created_at > datetime('now','-1 hour')
   GROUP BY phase;"
# Expect: phase='completed' present, phase='vector' absent or zero.

# 8. Pollution regression
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%';"
# expected: 0

# 9. Lint
ruff check workspace/sci_fi_dashboard/memory_engine.py \
  workspace/sci_fi_dashboard/session_ingest.py \
  workspace/tests/test_session_ingest.py
black --check workspace/
```

## Risks & gotchas

- **Don't reach for try/except as the fix.** The brief is explicit: "Don't just add try/except — fix the actual bug." The Task 2.2 return-value check is telemetry, not a fix. The fix is in Task 2.3 and addresses the actual exception.
- **`@with_retry` only catches `sqlite3.OperationalError` with `"locked"` in the message** (`memory_engine.py:42-52`). It does NOT retry on connection failures, extension-load failures, or `IntegrityError`. Don't assume retry coverage you don't have.
- **The `_archived_memories/persistent_log.jsonl` file** — was cleaned during 2026-04-26 (ROADMAP "What was JUST DONE": "65 → 47 lines"). If Phase 1 captures a `FileNotFoundError` for this path, the cleanup may have removed the file and `os.makedirs` is creating the dir but `open(..., "a")` is racing. Mitigation: pre-create file (touch) in `MemoryEngine.__init__`.
- **Windows + asyncio + threading.Lock.** The `DatabaseManager._init_lock` is a thread lock, but background asyncio tasks all run on the event-loop thread (single-threaded). It should be uncontended, but `_ensure_db()` calls `sqlite_vec.load(conn)` which opens a DLL/shared library — that can fail on Windows if the loader path is unstable. The fix isn't to remove the lock; it's to ensure `_ensure_db()` runs once at gateway startup so the background path never re-enters it cold.
- **LanceDB upsert can fail silently** (`memory_engine.py:421` — already wrapped). Phase 2 does not need to harden it; if the LanceDB upsert is the actual cause, surface it via the same return-dict check.
- **Test isolation**. Per ROADMAP execution rule 7, any new test importing chat-pipeline code MUST mock `add_memory`. The `test_session_ingest_writes_documents_row` test uses a real `add_memory` against a tmp DB, which is allowed because it's pointed at `tmp_path` not the prod DB. The other two tests mock as required.
- **Backups before destructive verification**. ROADMAP "Tools & environment notes" mandates a `.bak_<timestamp>` copy before destructive DB action. Verification commands above are read-only or write-only-to-correct-place; no destructive ops needed.
- **The 56 unflushed messages in cecb9c73 (E1.6)** — Phase 2 does not flush them automatically. Phase 3 owns auto-flush. The user can manually `/new` once Phase 2 lands to recover today's session into `documents`; that's a one-time bootstrap, not part of the phase.

## Out of scope (DO NOT do these in this phase)

- Auto-flush triggers. Phase 3.
- Backfilling the lost ~30-50 chat sessions from 2026-02-13 onward. Separate decision; document in STATUS.md but do not attempt.
- Touching `kg_processed` or `atomic_facts`. Phase 4.
- Refactoring `add_memory` to raise instead of return-dict. That would ripple through every caller (`grep -n "memory_engine.add_memory" workspace/`); too risky for this phase. Document the footgun in CLAUDE.md (Task 2.4) and leave the surface alone.
- Adding a new metric to `/memory_health`. Phase 1's surface is enough.
- Tuning Ollama `num_ctx` or VRAM. Different scope.

## Evidence references

- **E1.1** (documents composition) — only 5 `filename='session'` rows ever; latest is 2026-04-25 00:51. Direct evidence the vector path is mostly producing nothing.
- **E1.4** (entity_links alive) — KG path works; vector path doesn't. The asymmetry isolates the bug to `add_memory` or its caller, not to the asyncio plumbing.
- **E1.5** (sessions table token-only) — confirms the chat content gap.
- **E1.7** (06:20 archive failed silent) — directly cites `session_ingest.py:148` as the swallow site and notes the KG/vector asymmetry.
- **E1.8** (pollution forensics) — confirms `add_memory` writes to prod DB when called for real, so the function itself is wired correctly. The failure is environmental, not structural.
- **E8** (code paths index) — `memory_engine.py:368-432` and `session_ingest.py:47-200` are the two files this phase touches.

## Files touched (expected)

- `workspace/sci_fi_dashboard/session_ingest.py` — return-value check + telemetry calls (Task 2.2).
- `workspace/sci_fi_dashboard/memory_engine.py` — root-cause fix (Task 2.3 — exact change depends on Phase 1's diagnostic output; one of: `BACKUP_FILE` rework, `get_db_connection` audit, retry tuning, or extension-load fix).
- `workspace/tests/test_session_ingest.py` — three new tests (create file).
- `CLAUDE.md` — new gotcha entry (Task 2.4): `add_memory returns dict, does not raise`.
- `.planning/handover-2026-04-26/STATUS.md` — document scope of historical loss (Task 2.7).
