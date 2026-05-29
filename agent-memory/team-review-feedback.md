# Review Feedback — Round 1

## Unified Verdict: NEEDS CHANGES

Both reviewers agree the overall architecture is sound but flagged blocking issues that must be resolved before implementation.

---

## BLOCKING CHANGES (Must Fix)

### B1: Dual-write is not transactional (R1-MAJOR)
**Problem:** SQLiteGraph (knowledge_graph.db) and entity_links (memory.db) are separate databases — cross-DB atomicity is impossible. If one write succeeds and the other fails, the graph becomes inconsistent.
**Required Fix:** Ensure `_set_last_kg_timestamp()` (the watermark advance) is the ABSOLUTE LAST operation and only fires if ALL writes succeed. Structure the write sequence as:
1. Write to SQLiteGraph (add_edge)
2. Write to entity_links
3. Update entities.json
4. ONLY THEN advance the kg_state timestamp
If any step fails, the timestamp stays put — next run re-processes those messages (idempotent).

### B2: kg_state.json timestamp must not advance on partial failure (R1-MAJOR)
**Problem:** If some triples write but entity_links fails, those messages are permanently skipped because the watermark already advanced.
**Required Fix:** Wrap the entire write sequence in a try/except. Only call `_set_last_kg_timestamp()` inside the success path. On any exception, log the error and leave the timestamp unchanged. The next batch will re-fetch and re-process the same messages (which is safe because add_edge upserts and entity_links archival is idempotent).

### B3: Remove run_until_complete() from gentle_worker.py (R1-MAJOR)
**Problem:** Subtask 5 proposes using `asyncio.get_event_loop().run_until_complete()` inside `heavy_task_kg_extraction()`. This is a guaranteed `RuntimeError` crash when the FastAPI gateway is running (event loop already active).
**Required Fix:** Remove KG extraction from `gentle_worker.py` entirely. Rely SOLELY on the async `gentle_worker_loop()` integration in `pipeline_helpers.py` (Subtask 4). This eliminates the dual-scheduling concern and the sync/async mismatch. `gentle_worker.py`'s only change should be removing the old `heavy_task_kg_extraction()` method and its schedule entry.

### B4: SQLiteGraph._persistent_conn thread-safety violation (R2-MAJOR, R1 missed this)
**Problem:** `SQLiteGraph` uses `_persistent_conn` with `check_same_thread=False`. When `add_edge()` is called from `asyncio.to_thread()`, it shares this connection across threads. SQLite connections are NOT thread-safe even with `check_same_thread=False` — that flag just suppresses the warning.
**Required Fix:** In `run_batch_extraction()`, do NOT call `graph_store.add_edge()` inside `asyncio.to_thread()`. Instead, either:
- (A) Collect all triples first, then write them synchronously in the main thread after `to_thread` returns, OR
- (B) Create a temporary `sqlite3.connect()` inside the thread callable and write directly, bypassing the singleton, OR
- (C) Accumulate triples from the LLM call, then call `graph_store.add_edge()` directly (without `to_thread`) since `add_edge` is fast (no I/O wait worth threading).

**Recommended: Option C** — `add_edge()` is a simple INSERT/UPDATE, sub-millisecond. No need for `to_thread` on the write path. Use `to_thread` only for the LLM call if needed (but `router.call()` is already async, so even that may not need threading).

---

## NON-BLOCKING CHANGES (Should Fix)

### NB1: LLM provider variance in JSON output
**Issue:** Different LLM providers (Gemini Flash, GPT-4o-mini, local Ollama) have varying JSON compliance. The 3-tier parsing fallback from `triple_extractor.py` helps, but consider adding `response_format={"type": "json_object"}` for providers that support it (OpenAI, Gemini).
**Suggestion:** Check if litellm supports `response_format` passthrough and use it when available.

### NB2: Concurrency guard
**Issue:** If two `gentle_worker_loop` ticks fire close together, two extraction batches could run simultaneously on the same persona.
**Suggestion:** Add a simple `asyncio.Lock` per persona or a boolean `_extraction_running` flag to prevent overlapping runs.

### NB3: kg_state.json vs SQLite for state
**Issue:** JSON file for state tracking is fine for now but could be lost if the user deletes the sbs directory. Consider whether a `kg_state` table in memory.db would be more robust.
**Suggestion:** Keep JSON for now (simpler, matches existing SBS patterns), but document the trade-off.

---

## ARCHITECT ACTION ITEMS

1. Revise architecture spec to address B1-B4
2. Specifically: define the write sequence with watermark-last ordering
3. Remove `gentle_worker.py` changes from Subtask 5 — extraction lives ONLY in `gentle_worker_loop()`
4. Clarify that `add_edge()` and entity_links writes happen in the main async context (no `to_thread` for DB writes)
5. Add concurrency guard (asyncio.Lock) to `run_batch_extraction()`
6. Note JSON response_format opportunity for compatible providers
