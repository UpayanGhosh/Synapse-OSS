# Phase 4 — Deprecate `atomic_facts` + wire `kg_processed=1` at runtime

## TL;DR
Pure cleanup. Drop the `atomic_facts` family of tables (dead since 2026-02-13, 72% NULL on key columns) and wire `kg_processed=1` into the runtime KG-extraction path so the flag actually advances on real usage instead of sitting at 0 across the entire DB.

## Goal
After this phase: `atomic_facts`, `atomic_facts_vec`, and any companion artifacts are gone. The `documents.kg_processed` column truthfully reflects whether KG extraction has run on a row. Retrieval queries that previously fanned out to `atomic_facts` are reduced to the `documents` + `entity_links` path, simplifying maintenance and shrinking the schema surface that OSS users have to understand.

## Severity & Effort
- **Severity:** P3 (cleanup; not blocking but defers debt and confuses readers of CLAUDE.md schema docs)
- **Effort:** S (~1 hr — migration 15 min, query removal 20 min, runtime flag wiring 15 min, tests + docs 10 min)
- **Blocks:** Nothing on the critical path.
- **Blocked by:** None. Independent of Phases 1-3.

## Why this matters (with evidence)

Per **E1.3**, `atomic_facts` has 740 rows total, the most recent of which was inserted on 2026-02-13 21:43:33. Nothing has been added in over two months. Of those 740 rows: **529 (72%) have `entity IS NULL AND category IS NULL`** — the two columns that exist specifically to make atomic facts useful for retrieval. The table is functionally a free-text dump of WhatsApp content with broken metadata.

Per **E1.4**, the working KG surface has migrated entirely to `entity_links`: 794 total rows, 178 added in the past 7 days, all freshly tagged with subject/relation/object/confidence. This is where new structured knowledge lives. `atomic_facts` is a stranded prior generation of the schema.

Per **E1.2**, `documents.kg_processed = 0` for ALL 10,383 rows. The flag is never advanced at runtime. The only place it ever gets set to 1 is in `workspace/scripts/personal/kg_bulk_extract.py:750`:

```python
cur.execute("UPDATE documents SET kg_processed = 1 WHERE id = ?", (doc_id,))
```

That's a manual personal script the user has not run on the current DB. The runtime KG path — `_ingest_session_background` (`session_ingest.py`) and `conv_kg_extractor.py` — extracts triples and writes them to `entity_links` (`session_ingest.py:172-179` and `conv_kg_extractor.py:803`) but **never** marks the source documents as processed. So if any future code uses `kg_processed` as a filter (e.g. "only extract on rows where kg_processed=0 to avoid duplicate work"), it will reprocess every row every time.

The two issues are linked: `atomic_facts` is the shadow of an old retrieval design that included a `kg_processed` flag to gate periodic re-extraction. The runtime now uses `entity_links` directly, but the flag wiring was never updated to match. Cleaning up both at once is one atomic phase.

This phase recommends **Option A — pure deprecation** of `atomic_facts`. The brief lists Option B (revive) but the data is conclusive: 72% NULL metadata, two months of zero writes, retrieval already moved on. Reviving would require backfilling 740 rows with subject/category extraction that the current pipeline doesn't produce.

## Current state — what's there now

**Schema definition** — `workspace/sci_fi_dashboard/db.py:102-113`:

```sql
CREATE TABLE IF NOT EXISTS atomic_facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity          TEXT,
    content         TEXT NOT NULL,
    category        TEXT,
    source_doc_id   INTEGER,
    unix_timestamp  INTEGER,
    embedding_model TEXT DEFAULT 'nomic-embed-text',
    embedding_version TEXT DEFAULT 'ollama-v1',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Created inside `_ensure_jarvis_tables` (called from both fresh-DB init at `db.py:255` and existing-DB migration at `db.py:265`).

**Companion virtual table** — `workspace/scripts/update_memory_schema.py:42-52`:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS atomic_facts_vec USING vec0(
    fact_id integer primary key,
    embedding float[384]
);
```

Created by a manual one-shot script. Not currently created by `db.py` runtime, so on a fresh OSS install today this virtual table may not exist at all. Confirm via:

```bash
sqlite3 ~/.synapse/workspace/db/memory.db ".tables atomic_facts_vec"
```

**Migration touching `atomic_facts`** — `workspace/sci_fi_dashboard/db.py:144-152`:

```python
# Same migration for atomic_facts table (may not exist on all deployments)
cursor = conn.execute("PRAGMA table_info(atomic_facts)")
columns = {row[1] for row in cursor.fetchall()}
if columns and "embedding_model" not in columns:
    conn.execute(
        "ALTER TABLE atomic_facts ADD COLUMN embedding_model TEXT DEFAULT 'nomic-embed-text'"
    )
    conn.execute(
        "ALTER TABLE atomic_facts ADD COLUMN embedding_version TEXT DEFAULT 'ollama-v1'"
    )
```

Defensively wrapped (`if columns and ...`), so if the table is dropped, this code becomes a no-op. Safe to leave OR safe to delete; deletion is preferred.

**Runtime read sites** — these are the queries to remove:

- `workspace/sci_fi_dashboard/retriever.py:82-116` — `atomic_facts_vec MATCH` query, fans out to `atomic_facts` for entity/category/content lookup. Wrapped in `try/except Exception as e: print(f"[WARN] atomic_facts_vec query failed: {e}")` so it already silently degrades when the table is missing.
- `workspace/sci_fi_dashboard/retriever.py:312-315` — `SELECT COUNT(*) FROM atomic_facts` for `get_db_stats()`. Defensively wrapped.
- `workspace/sci_fi_dashboard/static/dashboard/synapse.js:1316` — `_setMemStat('mem-stat-atomic-facts', db.atomic_facts ?? null);` — the dashboard tile that shows `atomic_facts` count. Becomes vestigial.
- `workspace/finish_facts.py` — standalone script that bulk-fills `atomic_facts_vec` embeddings. Will become an obsolete script.
- `workspace/scripts/migrate_to_lancedb.py:120-199` — function `migrate_atomic_facts` that migrates `atomic_facts_vec` into LanceDB. Already handles the "table not found" case (`migrate_to_lancedb.py:127`); just becomes a no-op after deprecation.
- `workspace/scripts/nightly_ingest.py:30, 40, 58, 77, 80` — uses `atomic_facts` for an old nightly ingest design. Likely already orphaned; verify via `git log --oneline -- workspace/scripts/nightly_ingest.py` for last touch.
- `workspace/scripts/update_memory_schema.py:29-52` — the schema-creation script. Becomes obsolete.

**The `kg_processed=1` write site that should fire at runtime but doesn't** — `workspace/sci_fi_dashboard/session_ingest.py:151-186`. After triples are written to `entity_links` (line 172), no `UPDATE documents SET kg_processed = 1 WHERE id = ?` is issued. The same gap exists in the periodic extractor — `workspace/sci_fi_dashboard/conv_kg_extractor.py:795-813`:

```python
conn = sqlite3.connect(memory_db_path)
try:
    _ensure_entity_links(conn)
    for triple, confidence in validated_triples:
        ...
        _write_triple_to_entity_links(...)
    conn.commit()
finally:
    conn.close()
```

The periodic path also forgets to set `kg_processed`. Both paths must be fixed.

The bulk script `workspace/scripts/personal/kg_bulk_extract.py:750` is the only place the flag advances today, and it does so per-doc inside its own batch loop:

```python
cur.execute("UPDATE documents SET kg_processed = 1 WHERE id = ?", (doc_id,))
```

That pattern is the correct shape; the runtime needs to do the same.

## Target state — what it should do after

1. **`atomic_facts` and `atomic_facts_vec` dropped** from a fresh DB and any existing DB. The `_ensure_jarvis_tables` schema in `db.py` no longer creates the table. The migration in `db.py:144-152` is removed.
2. **All read sites** for `atomic_facts` are removed:
   - `retriever.py:82-116` — atomic_facts_vec branch deleted; `use_atomic` parameter removed (or kept and made a no-op if it has external callers).
   - `retriever.py:312-315` — `atomic_facts` count removed from `get_db_stats()`.
   - `static/dashboard/synapse.js:1316` — atomic_facts tile removed; layout reflows.
   - `workspace/finish_facts.py` — deleted (or moved under `workspace/scripts/_obsolete/` with a note).
   - `workspace/scripts/nightly_ingest.py` — deleted (or moved to `_obsolete/`).
   - `workspace/scripts/update_memory_schema.py` — deleted.
   - `workspace/scripts/migrate_to_lancedb.py` — `migrate_atomic_facts` function deleted; main entry no longer calls it.
3. **`kg_processed=1` wired at runtime** in two places:
   - `session_ingest.py` — after the `_write_triple_to_entity_links` loop succeeds, mark the source as processed. Caveat: the source for `_ingest_session_background` is the *batch text*, not a `documents.id`, because the vector ingestion in step 1 (`session_ingest.py:142`) creates fresh `documents` rows with new IDs. So the right pattern is: `add_memory` returns the inserted `doc_id`, and Phase 2's return-value check (Task 2.2) gives us a clean handle to it. After KG extraction, `UPDATE documents SET kg_processed = 1 WHERE id = ?` for that doc_id.
   - `conv_kg_extractor.py:795-813` — same pattern. The periodic extractor already iterates per-doc; just add the `UPDATE` after `conn.commit()`.
4. **Migration script** that drops the tables idempotently for existing DBs.
5. **CLAUDE.md** updated: schema section no longer mentions `atomic_facts`. The "Memory (Hybrid RAG)" section explicitly states the retrieval surface is `documents` + `entity_links` only.
6. **Tests:** new tests confirm `kg_processed=1` is set after a KG-extraction run; old tests that referenced `atomic_facts` are updated or removed.

## Tasks (ordered)

- [ ] **Task 4.0** — **Stop and ask the user before deleting `atomic_facts`.** Per the brief: "ask user before deletion is irreversible." The DB has 740 rows; even if the metadata is mostly NULL, the `content` column has free-text user data. Confirm:
  > "Going to drop `atomic_facts` (740 rows, 72% NULL metadata, last write 2026-02-13) and `atomic_facts_vec`. Backup at `~/.synapse/workspace/db/memory.db.bak_<timestamp>` will be created first. OK to proceed?"
  Also explicitly recommend Option A (deprecate) over Option B (revive) and ask for confirmation.

- [ ] **Task 4.1** — Pre-migration backup. Files: shell command. Per ROADMAP §"Tools & environment notes":
  ```bash
  cp ~/.synapse/workspace/db/memory.db \
     ~/.synapse/workspace/db/memory.db.bak_phase4_$(date +%s)
  ```
  Verify the backup is non-zero and readable.

- [ ] **Task 4.2** — Add the drop migration. Files: `workspace/sci_fi_dashboard/db.py`. Add a helper `_drop_atomic_facts_artifacts(conn)`:
  ```python
  def _drop_atomic_facts_artifacts(conn: sqlite3.Connection) -> None:
      """Phase 4 — drop the deprecated atomic_facts surface.

      Idempotent: safe to call multiple times. Drops both the regular and
      virtual tables. Logged so first-boot operators see the change.
      """
      for stmt in (
          "DROP TABLE IF EXISTS atomic_facts_vec",
          "DROP TABLE IF EXISTS atomic_facts",
      ):
          try:
              conn.execute(stmt)
          except sqlite3.OperationalError as exc:
              print(f"[WARN] atomic_facts cleanup: {exc}")
      conn.commit()
  ```
  Wire it into both code paths in `_ensure_db()`:
  - Fresh DB block (`db.py:215-258`): no-op for fresh DBs (CREATE statements are removed in Task 4.3, so DROP IF EXISTS is harmless).
  - Existing DB block (`db.py:260-267`): call after `_ensure_kg_processed_column(_mig)`.

- [ ] **Task 4.3** — Remove `atomic_facts` from schema creation. Files: `workspace/sci_fi_dashboard/db.py`.
  - Delete lines 102-113 (the `CREATE TABLE atomic_facts` block) inside `_ensure_jarvis_tables`.
  - Delete lines 144-152 (the `atomic_facts` migration block) inside `_ensure_embedding_metadata`.

- [ ] **Task 4.4** — Remove `atomic_facts` query paths. Files:
  - `workspace/sci_fi_dashboard/retriever.py`:
    - Delete the `atomic_facts_vec` branch at lines 82-116. Also remove the `use_atomic` parameter from the function signature if it has no external callers; otherwise leave the parameter but make the body a no-op for one release cycle and add a `DeprecationWarning`. Verify callers via:
      ```bash
      grep -rn "use_atomic" workspace/
      ```
    - Delete the `atomic_facts` count at lines 312-315 of `get_db_stats()`. Update any consumers of the returned dict.
  - `workspace/sci_fi_dashboard/static/dashboard/synapse.js`:
    - Delete line 1316 (`_setMemStat('mem-stat-atomic-facts', ...)`).
    - Find and delete the corresponding HTML tile in the dashboard template (search the static directory for `mem-stat-atomic-facts`).

- [ ] **Task 4.5** — Wire `kg_processed=1` in runtime. Files:
  - `workspace/sci_fi_dashboard/session_ingest.py` — after the `for triple, confidence in validated:` loop completes (line 179) and before `conn.commit()` (line 180), add:
    ```python
    # Mark the source document as KG-processed so periodic extractors don't re-run on it
    if vec_doc_id is not None:
        conn.execute(
            "UPDATE documents SET kg_processed = 1 WHERE id = ?",
            (vec_doc_id,),
        )
    ```
    Where `vec_doc_id` comes from Phase 2's return-value check (Task 2.2). If Phase 2 hasn't landed yet, capture the `doc_id` from `add_memory`'s returned `{"status": "stored", "id": doc_id}` and pass it down.

  - `workspace/sci_fi_dashboard/conv_kg_extractor.py` — after the loop at lines 799-810 commits successfully, add:
    ```python
    cur = conn.cursor()
    cur.execute(
        "UPDATE documents SET kg_processed = 1 WHERE id = ?",
        (doc_id,),
    )
    conn.commit()
    ```
    `doc_id` should already be in scope at that point — verify via reading lines ~750-810 of the file.

- [ ] **Task 4.6** — Remove or relocate obsolete scripts. Files:
  - Move to `workspace/scripts/_obsolete/` with a one-line README explaining why:
    - `workspace/finish_facts.py`
    - `workspace/scripts/nightly_ingest.py`
    - `workspace/scripts/update_memory_schema.py`
  - Strip `migrate_atomic_facts` from `workspace/scripts/migrate_to_lancedb.py` (delete lines 120-199 and the call at line 251). Leave the rest of the script intact.
  - Document in CLAUDE.md that these scripts are gone.

- [ ] **Task 4.7** — Update CLAUDE.md schema docs. Files: `D:/Shorty/Synapse-OSS/CLAUDE.md`. Search for any mention of `atomic_facts`:
  ```bash
  grep -n "atomic_facts" CLAUDE.md
  ```
  Remove. Update the "Memory (Hybrid RAG)" section to state explicitly: "Retrieval queries `documents` (vector + FTS) and `entity_links` (KG triples). The legacy `atomic_facts` table was removed in Phase 4 (handover-2026-04-26)."

- [ ] **Task 4.8** — Tests.
  - **Update**: `workspace/tests/test_schema_migration.py` — remove any `atomic_facts` assertions; add an assertion that the table does NOT exist after migration on an existing DB:
    ```python
    def test_atomic_facts_dropped_on_migration(tmp_path, monkeypatch):
        # set up DB with atomic_facts present, run migration, assert it's gone
    ```
  - **Update**: `workspace/tests/test_retriever.py` — remove `atomic_facts` test cases. Add an assertion that retrieval still returns the `documents` results without the atomic facts surface.
  - **New**: `workspace/tests/test_kg_processed_flag.py` — two tests:
    1. `test_session_ingest_marks_kg_processed` — run `_ingest_session_background` end-to-end against a tmp DB with KG extraction enabled (mock the LLM to return one valid triple); assert the inserted `documents` row has `kg_processed = 1` after the function returns.
    2. `test_conv_kg_extractor_marks_kg_processed` — run the periodic extractor against a fixture doc with `kg_processed = 0`; assert it flips to 1.

  Per ROADMAP execution rule 7, mock `add_memory` in any test that reaches the chat-pipeline import path. The first test above does want the real `add_memory` to fire (it's testing end-to-end behaviour against a tmp DB), which is allowed because it's a `tmp_path` DB, not the prod one. The second test mocks at the extractor level.

- [ ] **Task 4.9** — Verify post-migration. Files: shell. Run:
  ```bash
  sqlite3 ~/.synapse/workspace/db/memory.db ".tables" | grep atomic
  # expected: no output
  sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*), SUM(kg_processed) FROM documents;"
  # SUM(kg_processed) was 0 before; after Phase 4 + a /new, should be > 0 for newly-extracted docs.
  ```

## Dependencies
- **Hard:** None.
- **Soft:** Phase 2 strongly preferred — its Task 2.2 return-value check makes capturing the new `doc_id` for `kg_processed` wiring much cleaner. If Phase 2 is not merged, this phase still works but Task 4.5 needs an inline tweak to extract `doc_id` from `add_memory`'s return.
- **Provides:** Cleaner schema for OSS users; CLAUDE.md schema section is shorter; `kg_processed` flag becomes meaningful so future scripts can use it as a filter.

## Success criteria (must all be true before claiming done)
- [ ] User has explicitly approved the deprecation (Task 4.0).
- [ ] Pre-migration backup exists at `memory.db.bak_phase4_*` (Task 4.1).
- [ ] `atomic_facts` and `atomic_facts_vec` do NOT exist after the migration runs on the dev DB (verify via `.tables`).
- [ ] Fresh OSS DB never creates either table (verify via `SYNAPSE_HOME=/tmp/synapse_test python -c "from sci_fi_dashboard.db import DatabaseManager; DatabaseManager.get_connection()" && sqlite3 /tmp/synapse_test/workspace/db/memory.db ".tables"`).
- [ ] All `atomic_facts` query paths removed from runtime code (Task 4.4); `grep -n "atomic_facts" workspace/sci_fi_dashboard/` returns only obsolete-folder paths or zero matches.
- [ ] `kg_processed = 1` is set after a real `/new` run (Task 4.5 wired). Verify:
  ```bash
  sqlite3 ~/.synapse/workspace/db/memory.db \
    "SELECT COUNT(*) FROM documents WHERE kg_processed = 1;"
  # expect: > 0 after at least one /new since this phase merged
  ```
- [ ] Obsolete scripts moved to `_obsolete/` (Task 4.6).
- [ ] CLAUDE.md no longer references `atomic_facts` (Task 4.7).
- [ ] All updated and new tests pass via `cd workspace && pytest tests/test_schema_migration.py tests/test_retriever.py tests/test_kg_processed_flag.py -v`.
- [ ] No new pollution; `SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%'` is 0.
- [ ] `pytest tests/ -m unit` and `pytest tests/ -m integration` pass.
- [ ] Dashboard tile for `atomic_facts` is gone; UI doesn't error (smoke-test by loading `http://127.0.0.1:8000/dashboard`).

## Verification recipe (how Codex proves it works)

```bash
# 0. Branch from develop. Get user approval first (Task 4.0).
git checkout develop
git checkout -b fix/phase-4-deprecate-atomic-facts

# 1. Backup
cp ~/.synapse/workspace/db/memory.db \
   ~/.synapse/workspace/db/memory.db.bak_phase4_$(date +%s)
ls -la ~/.synapse/workspace/db/memory.db.bak_phase4_*

# 2. Confirm starting state
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT name FROM sqlite_master WHERE name LIKE 'atomic_facts%';"
# expected: atomic_facts (and possibly atomic_facts_vec)
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE kg_processed = 1;"
# expected: 0 (per E1.2)

# 3. Apply Tasks 4.2 - 4.7

# 4. Run unit tests
cd workspace && pytest tests/test_schema_migration.py tests/test_retriever.py \
  tests/test_kg_processed_flag.py -v

# 5. Restart gateway so the migration runs on the dev DB
pkill -f "uvicorn api_gateway" || true
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload &
sleep 5

# 6. Verify migration applied
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT name FROM sqlite_master WHERE name LIKE 'atomic_facts%';"
# expected: empty
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
# verify no surprise drops elsewhere

# 7. End-to-end: /new + kg_processed advancement
before=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE kg_processed = 1;")
curl -s -X POST -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "/new"}' http://127.0.0.1:8000/chat/the_creator
sleep 15
after=$(sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE kg_processed = 1;")
echo "kg_processed=1 rows: before=$before after=$after"
test "$after" -gt "$before" || echo "FAIL: kg_processed not advancing"

# 8. Fresh-install verification
rm -rf /tmp/synapse_phase4_test
SYNAPSE_HOME=/tmp/synapse_phase4_test python -c "
from sci_fi_dashboard.db import DatabaseManager
DatabaseManager.get_connection()
"
sqlite3 /tmp/synapse_phase4_test/workspace/db/memory.db \
  ".tables" | tr ' ' '\n' | grep atomic
# expected: empty

# 9. Dashboard smoke
curl -s http://127.0.0.1:8000/dashboard | grep -i atomic
# expected: empty

# 10. Pollution regression
sqlite3 ~/.synapse/workspace/db/memory.db \
  "SELECT COUNT(*) FROM documents WHERE content LIKE '%MagicMock%';"
# expected: 0

# 11. Lint
ruff check workspace/sci_fi_dashboard/db.py \
  workspace/sci_fi_dashboard/retriever.py \
  workspace/sci_fi_dashboard/session_ingest.py \
  workspace/sci_fi_dashboard/conv_kg_extractor.py \
  workspace/scripts/migrate_to_lancedb.py \
  workspace/tests/test_schema_migration.py \
  workspace/tests/test_retriever.py \
  workspace/tests/test_kg_processed_flag.py
black --check workspace/
```

## Risks & gotchas

- **Irreversible** — once dropped, the 740 `atomic_facts` rows are gone unless restored from backup. The mandatory pre-migration backup mitigates this. Per ROADMAP, two backups already exist (`memory.db.bak_1777166450` and `.bak_1777066874`); Task 4.1 adds a third. Do not skip.
- **Hidden callers** — search beyond `sci_fi_dashboard/`:
  ```bash
  grep -rn "atomic_facts" workspace/ scripts/ baileys-bridge/ 2>/dev/null
  ```
  Anything not in the planned-removal list above is a missed dependency. Investigate before proceeding.
- **Dashboard reflow** — removing the `mem-stat-atomic-facts` tile may leave a layout gap. Test the `/dashboard` UI in a browser after the change.
- **`use_atomic` parameter callers** — `retriever.py` exports a function with `use_atomic` defaulting to True. If external code (or tests) passes `use_atomic=True` explicitly, removing the parameter breaks the call. Soft-deprecate the parameter for one cycle: keep it, log `DeprecationWarning`, but the body is a no-op. Cleanup in a future phase.
- **`embedding_dimensions` mismatch** — `db.py` uses `EMBEDDING_DIMENSIONS = 768` for `vec_items`; `update_memory_schema.py:45-50` shows `atomic_facts_vec` was created with `embedding[384]`. The dimension mismatch is itself evidence the schema drifted. Don't try to harmonize it — just drop the table.
- **`kg_processed=1` on session ingest depends on Phase 2's return-value check.** If Phase 2 is not yet merged, you have two options:
  - Land Phase 2 first (recommended), or
  - Inline-extract the `doc_id` from `add_memory`'s return inside Task 4.5: change `session_ingest.py` to capture `result = deps.memory_engine.add_memory(...)` and read `result.get("id")`. This is the same logic Phase 2 introduces, so doing it here pre-empts that edit. Coordinate with Phase 2's branch to avoid merge conflicts.
- **Gentle worker pruning** — `gentle_worker.py:52-63` runs `prune_graph()` on the SQLiteGraph (not on `atomic_facts`). No conflict.
- **Tests that read `atomic_facts`** — `workspace/tests/test_schema_migration.py`, `workspace/tests/test_retriever.py`, and `workspace/tests/test_embedding_pipeline_deep.py` all reference `atomic_facts` per the grep at the top of the brief. Update or delete the relevant cases. Do NOT just delete the test files — those tests cover other useful surfaces (schema migrations, retriever paths, embedding production-readiness).
- **Multiple worktree DBs** — `D:/Shorty/Synapse-OSS/.worktrees/phase-12/synapse.json.example` and `phase-17/synapse.json.example` are visible per Glob. They are example files for other parallel work; do NOT touch them in this phase.

## Out of scope (DO NOT do these in this phase)

- Reviving `atomic_facts` (Option B). Recommendation is firmly Option A.
- Backfilling 740 rows of `atomic_facts.entity` from `entity_links` triples. Possible, but risky and the value is low — that's a future-work item if anyone ever wants the deprecated table back.
- Touching `entity_links` schema or behaviour. Out of scope; that table is the working surface and stays exactly as-is.
- Adding a `kg_processed_at` timestamp. Just the boolean for now; timestamp can be added in a future phase if needed.
- Refactoring `_write_triple_to_entity_links` (`conv_kg_extractor.py:432`) — the helper is fine as-is.
- Removing `embedding_dimensions=768` constant or migrating embedding dimensions. Different scope.
- Touching `relationship_memories`, `roast_vault`, `gift_date_vault`, `memory_diary`, or `structured_memory` (`db.py:52-100`). Those tables are alive or staged for live; out of scope.

## Evidence references

- **E1.2** (`kg_processed=0` for ALL rows) — confirms the runtime never advances the flag.
- **E1.3** (`atomic_facts` dead since 2026-02-13) — confirms the table is stranded with 72% NULL metadata.
- **E1.4** (entity_links alive) — confirms the working KG surface has migrated; nothing of value is lost by deprecating `atomic_facts`.
- **E8** (code path index) — `scripts/personal/kg_bulk_extract.py:750` is the only place `kg_processed=1` is set today; `conv_kg_extractor.py:432, 803` are the runtime KG write sites that need the wiring.

## Files touched (expected)

- `workspace/sci_fi_dashboard/db.py` — add `_drop_atomic_facts_artifacts`; remove `atomic_facts` from `_ensure_jarvis_tables` and `_ensure_embedding_metadata`.
- `workspace/sci_fi_dashboard/retriever.py` — delete `atomic_facts_vec` query branch and stats line.
- `workspace/sci_fi_dashboard/session_ingest.py` — wire `kg_processed=1` after KG triple writes.
- `workspace/sci_fi_dashboard/conv_kg_extractor.py` — wire `kg_processed=1` in the periodic extractor's commit.
- `workspace/sci_fi_dashboard/static/dashboard/synapse.js` — remove `mem-stat-atomic-facts` line + corresponding HTML tile.
- `workspace/scripts/migrate_to_lancedb.py` — strip `migrate_atomic_facts` function and its call.
- `workspace/scripts/_obsolete/` — new dir; move `finish_facts.py`, `nightly_ingest.py`, `update_memory_schema.py` here with a README.
- `workspace/tests/test_schema_migration.py` — update for dropped table.
- `workspace/tests/test_retriever.py` — remove `atomic_facts` cases.
- `workspace/tests/test_kg_processed_flag.py` — new file with two tests.
- `CLAUDE.md` — schema section refresh; remove `atomic_facts` mentions.
