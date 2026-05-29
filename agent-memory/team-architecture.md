# KG Extraction Refactor: Architecture Spec (Revision 2)

**Revision notes:** Addresses all blocking feedback (B1-B4) and non-blocking items (NB1-NB3) from Round 1 review.

**Approach:** Replace the torch-based `TripleExtractor` with a new async `ConvKGExtractor` that sends the existing `_EXTRACTION_PROMPT` to `SynapseLLMRouter.call("casual", ...)`, extracts triples from recent conversation messages (not documents), and runs as a non-blocking task inside `gentle_worker_loop()` on a ~20-minute cadence.

---

## Implementation Order

### 1. Subtask 7 -- `KGExtractionConfig` in `synapse_config.py`

Must come first because all other modules read from it.

- Add a frozen dataclass `KGExtractionConfig` immediately after `SBSConfig` (line 55).
- Fields: `enabled: bool = True`, `min_messages: int = 15`, `extract_interval_seconds: int = 1200`.
- In `SynapseConfig.load()`, parse `raw.get("kg_extraction", {})` using the same `{k: v for k, v in ... if k in __dataclass_fields__}` filter pattern used for `sbs_raw` at line 137.
- Add `kg_extraction: KGExtractionConfig = field(default_factory=KGExtractionConfig)` to `SynapseConfig` fields (after `vector_store` at line 83).
- Pass `kg_extraction=kg_config` into the `cls(...)` constructor at line 142.

### 2. Subtask 1 -- Core `ConvKGExtractor` class in new file `conv_kg_extractor.py`

The extraction engine. No deps on torch/transformers.

- Copy `_EXTRACTION_PROMPT`, `_parse_llm_output`, `_normalize_result`, `_chunk_text` verbatim from `triple_extractor.py`. These are pure functions with zero torch deps (only `re`, `json`, `logging`).
- Class `ConvKGExtractor` with `__init__(self, llm_router: SynapseLLMRouter, role: str = "casual")`.
- Method `async def extract(self, text: str) -> dict` -- chunks text via `_chunk_text()`, for each chunk builds `messages = [{"role": "user", "content": _EXTRACTION_PROMPT.format(content=chunk)}]`, calls `await self._router.call(self._role, messages, temperature=0.3, max_tokens=1500)`, parses with `_parse_llm_output`, normalizes with `_normalize_result`, merges all chunk results, returns `{"facts": [...], "triples": [...]}`.
- Max concurrency: process chunks sequentially (simple, avoids rate-limit bursts). No parallelism needed since batches are small.
- **[NB1] JSON response_format:** When calling `self._router.call()`, pass `response_format={"type": "json_object"}` as an additional kwarg. This requires a minor change to `SynapseLLMRouter.call()` and `_do_call()` to accept and forward `**kwargs` to `self._router.acompletion()`. litellm already supports `response_format` passthrough for OpenAI, Gemini, and other compatible providers. For providers that do not support it (e.g., local Ollama), litellm silently ignores it. The 3-tier JSON parsing fallback in `_parse_llm_output` remains as the safety net regardless, so this is a best-effort enhancement.

### 3. Subtask 2 -- State tracking and message fetching helpers

Added to `conv_kg_extractor.py`.

- `_get_last_kg_timestamp(sbs_data_dir: str) -> str` -- reads `<sbs_data_dir>/kg_state.json`, returns `kg_last_extracted_at` or `"2000-01-01T00:00:00"` if missing.
- `_set_last_kg_timestamp(sbs_data_dir: str, ts: str) -> None` -- writes `{"kg_last_extracted_at": ts}` to `kg_state.json`. Use `os.makedirs(sbs_data_dir, exist_ok=True)` before write.
- `async def fetch_messages_since(db_path: str, since_iso: str, limit: int = 200) -> list[dict]` -- uses `asyncio.to_thread()` wrapping a `sqlite3.connect()` / `execute()` / `fetchall()` call. Query: `SELECT msg_id, timestamp, role, content FROM messages WHERE timestamp > ? ORDER BY timestamp ASC LIMIT ?`. Returns list of dicts. The thread-local connection is opened and closed within the callable, so there is no shared-connection issue.
- **[NB3] kg_state.json trade-off:** The state file lives at `<sbs_data_dir>/kg_state.json` (one per persona). This matches the existing SBS pattern of per-persona JSON state files and is simpler than a database table. The trade-off: if the user deletes the sbs directory, the watermark is lost and extraction restarts from epoch. This is acceptable because (a) `add_edge` upserts are idempotent, (b) `entity_links` archival is idempotent, and (c) reprocessing messages is a correctness-preserving no-op, just costs an extra LLM call. If a more durable approach is needed in the future, a `kg_state` table in `memory.db` can replace this without changing the interface -- `_get_last_kg_timestamp` / `_set_last_kg_timestamp` are the only two functions that touch the file, so migration is a single-file change.

### 4. Subtask 3 -- `run_batch_extraction()` orchestrator

Added to `conv_kg_extractor.py`. The single entry point for all callers.

**Signature:**

```
async def run_batch_extraction(
    persona_id: str,
    sbs_data_dir: str,
    llm_router: SynapseLLMRouter,
    graph: SQLiteGraph,
    memory_db_path: str,
    entities_json_path: str,
    min_messages: int = 15,
    force: bool = False,
) -> dict
```

**Returns:** `{"extracted": int, "facts": int}` on success, `{"skipped": True, ...}` when skipped.

**[NB2] Concurrency guard:** A module-level `_extraction_lock = asyncio.Lock()` is acquired at the top of `run_batch_extraction()` via `async with _extraction_lock:`. If two `gentle_worker_loop` ticks fire close together, the second call blocks until the first completes. This prevents overlapping extraction batches from racing on the same persona's state file and graph writes. The lock is module-scoped (not per-persona) because extraction is lightweight and sequential execution is preferred over fine-grained concurrency.

**[B1 + B2] Revised write sequence with watermark-last ordering and partial-failure safety:**

The core extraction body (inside the lock) follows this exact sequence:

```
Step (a): Guard -- if not cfg.kg_extraction.enabled: return {"skipped": True}
Step (b): Read watermark -- last_ts = _get_last_kg_timestamp(sbs_data_dir)
Step (c): Resolve messages DB path -- os.path.join(sbs_data_dir, "indices", "messages.db")
Step (d): Fetch messages -- msgs = await fetch_messages_since(db_path, last_ts, limit=200)
Step (e): Threshold check -- if len(msgs) < min_messages and not force: return {"skipped": True, "pending": len(msgs)}
Step (f): Build text -- text = "\n".join(f"[{m['role']}]: {m['content']}" for m in msgs)
Step (g): LLM extraction -- result = await extractor.extract(text)
Step (h): Write ALL triples to SQLiteGraph -- graph.add_edge(...) for each triple     [DIRECT CALL, no to_thread]
Step (i): Write ALL entity_links to memory.db                                          [DIRECT CALL, no to_thread]
Step (j): Update entities.json                                                         [DIRECT CALL, no to_thread]
Step (k): Advance watermark -- _set_last_kg_timestamp(sbs_data_dir, msgs[-1]["timestamp"])
```

**Critical: Steps (h) through (k) are wrapped in a single try/except block.**

```
try:
    # (h) Write triples to SQLiteGraph
    for subj, rel, obj in result["triples"]:
        graph.add_edge(subj, obj, relation=rel, weight=1.0, evidence="conv_kg")

    # (i) Write entity_links to memory.db
    conn = sqlite3.connect(memory_db_path)
    try:
        _ensure_entity_links(conn)
        for subj, rel, obj in result["triples"]:
            _write_triple_to_entity_links(conn, subj, rel, obj, fact_id=0)
        conn.commit()
    finally:
        conn.close()

    # (j) Update entities.json
    all_entities = set()
    for subj, rel, obj in result["triples"]:
        all_entities.add(subj)
        all_entities.add(obj)
    _update_entities_json(entities_json_path, all_entities)

    # (k) Advance watermark -- ONLY on full success
    _set_last_kg_timestamp(sbs_data_dir, msgs[-1]["timestamp"])

except Exception as write_err:
    logger.error("KG write failed for %s, watermark NOT advanced: %s", persona_id, write_err)
    return {"error": str(write_err), "extracted": 0}
```

**Why this ordering satisfies B1 and B2:**

- The watermark (`_set_last_kg_timestamp`) is the ABSOLUTE LAST operation (step k), after ALL writes succeed.
- If `add_edge` fails (step h), we never reach entity_links, entities.json, or the watermark. Next run re-fetches the same messages.
- If `entity_links` fails (step i), we never reach entities.json or the watermark. Some triples may already be in SQLiteGraph, but that is safe because `add_edge` uses `ON CONFLICT ... DO UPDATE` (upsert). Next run re-processes and re-upserts -- idempotent.
- If `entities.json` fails (step j), the watermark does not advance. Next run re-processes -- idempotent (entities.json merge is additive).
- If `_set_last_kg_timestamp` itself fails (step k), the watermark stays at the old value. Next run re-processes -- idempotent. This is the most unlikely failure (simple JSON file write) but is still safe.

**[B4] No asyncio.to_thread() for DB writes:**

- `graph.add_edge()` is called DIRECTLY in the async context (no `to_thread`). Confirmed: `add_edge()` is a simple INSERT + UPSERT with `conn.commit()`, sub-millisecond. Threading it would only add overhead and, critically, would share `SQLiteGraph._persistent_conn` across threads, which is unsafe (the `check_same_thread=False` flag suppresses Python's warning but does NOT make the connection thread-safe at the SQLite C library level).
- `entity_links` writes use a FRESH `sqlite3.connect(memory_db_path)` opened and closed within the write block. This connection is local to the function, not shared, and the writes are sub-millisecond. No `to_thread` needed.
- `_update_entities_json` is a JSON read/merge/write, sub-millisecond. No `to_thread` needed.
- `fetch_messages_since` (step d) DOES use `asyncio.to_thread()` because it opens its own connection and the query may scan an index over potentially thousands of rows. This is the one place where threading is justified. The connection is created, used, and closed entirely within the thread callable -- no shared state.

**Why direct calls are safe here:** The entire write sequence (steps h-k) involves 4 categories of I/O: (1) SQLiteGraph inserts via `_persistent_conn` -- sub-ms each, (2) entity_links inserts via a local connection -- sub-ms each, (3) entities.json file write -- sub-ms, (4) kg_state.json file write -- sub-ms. Even with 50 triples, the total blocking time is under 10ms. This is well within acceptable limits for an async background worker that already sleeps 600s between ticks.

### 5. Subtask 4 -- Wire into `gentle_worker_loop()` in `pipeline_helpers.py`

**[B3] KG extraction lives ONLY here -- not in gentle_worker.py.**

- Add module-level: `import time` (already present), `from sci_fi_dashboard.conv_kg_extractor import run_batch_extraction`.
- Add two local variables before the `while True`: `_kg_tick = 0` and `_kg_last_time = time.time()`.
- Inside the `if is_plugged and cpu_load < 20.0:` block, after the prune calls and before `await asyncio.sleep(600)`:

```
_kg_tick += 1
if _kg_tick >= 2 or (time.time() - _kg_last_time) >= 1800:
    _kg_tick = 0
    _kg_last_time = time.time()
    try:
        cfg = SynapseConfig.load()
        for pid, sbs in deps.sbs_registry.items():
            await run_batch_extraction(
                persona_id=pid,
                sbs_data_dir=sbs.data_dir,
                llm_router=deps.synapse_llm_router,
                graph=deps.brain,
                memory_db_path=str(cfg.db_dir / "memory.db"),
                entities_json_path=str(Path(CURRENT_DIR) / "entities.json"),
                min_messages=cfg.kg_extraction.min_messages,
            )
    except Exception as e:
        print(f"[WARN] KG extraction failed: {e}")
```

- Key: the extraction is `await`-ed directly (not `create_task`), because it should complete before the next sleep. The broad `except Exception` ensures failures never crash the loop.
- The `_extraction_lock` inside `run_batch_extraction()` (NB2) prevents overlapping runs even if the timer logic fires twice.

### 6. Subtask 5 -- Update `gentle_worker.py` (REMOVAL ONLY)

**[B3] Remove `heavy_task_kg_extraction()` entirely from `gentle_worker.py`.**

The previous spec proposed replacing the method body with `asyncio.get_event_loop().run_until_complete(...)`. This is WRONG -- `run_until_complete()` raises `RuntimeError` when called inside an already-running event loop (which is always the case when FastAPI is up). The correct fix is to remove the method and its schedule entry entirely.

Changes to `gentle_worker.py`:
- DELETE the entire `heavy_task_kg_extraction()` method (lines 102-133).
- DELETE the schedule entry `schedule.every(20).minutes.do(self.heavy_task_kg_extraction)` (line 141).
- Do NOT add any replacement. KG extraction now lives exclusively in the async `gentle_worker_loop()` in `pipeline_helpers.py` (Subtask 4).
- Keep all other methods (`heavy_task_graph_pruning`, `heavy_task_db_optimize`, `heavy_task_proactive_checkin`) and their schedule entries unchanged.
- Remove the import of `SynapseConfig` from this method (it was only used here). If other methods also use it, keep the import.

**Rationale:** `gentle_worker.py` uses the `schedule` library in a synchronous `while self.is_running: schedule.run_pending(); time.sleep(1)` loop. This is fundamentally incompatible with async code. The async `gentle_worker_loop()` in `pipeline_helpers.py` runs inside the FastAPI event loop and is the correct home for any async work. Having KG extraction in both places would mean dual-scheduling with no coordination, which is worse than having it in one place.

### 7. Subtask 6 -- Rewrite `scripts/fact_extractor.py` as thin CLI wrapper + deprecate `triple_extractor.py`

- `fact_extractor.py`: Remove `from sci_fi_dashboard.triple_extractor import TripleExtractor`. Remove `tqdm`, `sqlite_vec` imports. Import `conv_kg_extractor.run_batch_extraction` instead. The `process_documents()` function becomes: for each persona, call `asyncio.run(run_batch_extraction(..., force=args.force, min_messages=0 if args.force else 15))`. `--dry-run` flag: call `extract()` only, print results, skip dual-write. `--limit` maps to `fetch_messages_since(limit=args.limit)`.
- `triple_extractor.py`: Add `warnings.warn("triple_extractor is deprecated; use conv_kg_extractor", DeprecationWarning, stacklevel=2)` at module top (before class def, after imports). Do NOT delete the file.

---

## Interfaces / Types to Create or Modify

```python
# synapse_config.py -- NEW dataclass
@dataclass(frozen=True)
class KGExtractionConfig:
    enabled: bool = True
    min_messages: int = 15
    extract_interval_seconds: int = 1200

# synapse_config.py -- MODIFIED field on SynapseConfig
kg_extraction: KGExtractionConfig = field(default_factory=KGExtractionConfig)

# conv_kg_extractor.py -- NEW module
class ConvKGExtractor:
    def __init__(self, llm_router: SynapseLLMRouter, role: str = "casual") -> None: ...
    async def extract(self, text: str) -> dict:
        """Returns {"facts": [{"entity","content","category"}], "triples": [[s,r,o]]}"""

def _get_last_kg_timestamp(sbs_data_dir: str) -> str: ...
def _set_last_kg_timestamp(sbs_data_dir: str, ts: str) -> None: ...
async def fetch_messages_since(db_path: str, since_iso: str, limit: int = 200) -> list[dict]: ...

# Module-level concurrency guard
_extraction_lock: asyncio.Lock  # created at module scope

async def run_batch_extraction(
    persona_id: str,
    sbs_data_dir: str,
    llm_router: SynapseLLMRouter,
    graph: SQLiteGraph,
    memory_db_path: str,
    entities_json_path: str,
    min_messages: int = 15,
    force: bool = False,
) -> dict:
    """Returns {"extracted": int, "facts": int} or {"skipped": True, ...}"""

# Private helpers lifted from fact_extractor.py (NOT imported from it):
def _ensure_entity_links(conn: sqlite3.Connection) -> None: ...
def _write_triple_to_entity_links(conn, subj, rel, obj, fact_id: int) -> None: ...
def _update_entities_json(entities_json_path: str, new_entities: set[str]) -> None: ...

# Lifted from triple_extractor.py (pure functions, no torch):
_EXTRACTION_PROMPT: str
def _chunk_text(text: str, max_chars: int = 1500) -> list[str]: ...
def _parse_llm_output(raw: str) -> dict: ...
def _normalize_result(result: dict) -> dict: ...
```

---

## Constraints

- Zero torch/transformers imports anywhere in `conv_kg_extractor.py`. Grep for `import torch` and `import transformers` after writing -- must return 0 hits.
- **[B4] No `asyncio.to_thread()` for any DB write path.** `SQLiteGraph.add_edge()`, entity_links writes, entities.json updates, and kg_state.json updates are all called directly in the async context. They are sub-ms operations. Only `fetch_messages_since()` uses `asyncio.to_thread()` (justified: read query may scan many rows, uses its own connection).
- **[B1] Watermark-last ordering.** `_set_last_kg_timestamp()` is the absolute last operation in the write sequence. It is inside the `try` block, after all other writes, and before the `except`. If any preceding write fails, the exception skips the watermark advance.
- **[B2] No watermark advance on partial failure.** Steps (h) through (k) are wrapped in a single `try/except`. On any exception, the function logs the error and returns `{"error": ...}` without advancing the watermark. The next batch re-fetches the same messages. This is safe because all writes are idempotent: `add_edge` upserts, entity_links archives then inserts, entities.json merges additively.
- **[B3] No `run_until_complete()` anywhere.** KG extraction lives exclusively in the async `gentle_worker_loop()` in `pipeline_helpers.py`. `gentle_worker.py` has its `heavy_task_kg_extraction()` method and schedule entry removed entirely. No sync-to-async bridge is needed.
- **[NB2] Concurrency guard.** `_extraction_lock = asyncio.Lock()` at module scope in `conv_kg_extractor.py`, acquired at the top of `run_batch_extraction()`. Prevents overlapping batches.
- **[NB1] JSON response_format.** Pass `response_format={"type": "json_object"}` through the LLM call chain when available. Requires threading `**kwargs` through `SynapseLLMRouter.call()` -> `_do_call()` -> `self._router.acompletion()`. litellm handles provider compatibility automatically. The 3-tier parsing fallback remains as the safety net.
- LLM calls use `await self._router.call(role, messages, temperature=0.3, max_tokens=1500)` -- NOT `call_with_metadata`. We don't need token counts for background extraction. Lower temperature (0.3) for structured JSON output.
- `_EXTRACTION_PROMPT` uses `{{` and `}}` for literal braces and `.format(content=...)` for interpolation -- preserve this exact pattern when copying.
- `_update_entities_json` in the new module must accept `entities_json_path` as a parameter (not rely on module-level constant) to support different working directories.
- State file `kg_state.json` lives at `<sbs_data_dir>/kg_state.json` (e.g. `~/.synapse/workspace/sci_fi_dashboard/synapse_data/the_creator/kg_state.json`). One file per persona.
- The `force=True` parameter on `run_batch_extraction` bypasses the `min_messages` threshold (sets effective min to 0) -- used only by CLI.
- Never add a second memory query inside any extraction path -- the extractor reads raw conversation messages, not MemoryEngine results.
- `gentle_worker_loop` extraction failures must be logged and swallowed -- never propagate to crash the loop.
- The `"casual"` role is used by default. If a user adds a `"kg"` role to `model_mappings` in `synapse.json`, they can pass `role="kg"` -- no code change needed, just config.
- File placement: `workspace/sci_fi_dashboard/conv_kg_extractor.py` -- same directory as `triple_extractor.py`.
- Imports in `conv_kg_extractor.py`: `from sci_fi_dashboard.llm_router import SynapseLLMRouter` and `from sci_fi_dashboard.sqlite_graph import SQLiteGraph`. Use relative-style absolute imports matching the rest of the codebase.

---

## Reviewer Feedback Traceability

| Feedback ID | Status | Where Addressed |
|-------------|--------|-----------------|
| B1 (watermark-last write ordering) | FIXED | Subtask 3 write sequence, steps (h)-(k); Constraints section |
| B2 (no watermark advance on partial failure) | FIXED | Subtask 3 try/except block; Constraints section |
| B3 (remove run_until_complete) | FIXED | Subtask 5 rewritten as deletion-only; Subtask 4 is sole home |
| B4 (no asyncio.to_thread for SQLiteGraph writes) | FIXED | Subtask 3 step (h) direct call; Constraints section |
| NB1 (JSON response_format) | ADDRESSED | Subtask 1 extract() method; Constraints section |
| NB2 (asyncio.Lock concurrency guard) | ADDRESSED | Subtask 3 _extraction_lock; Constraints section |
| NB3 (document kg_state.json trade-off) | ADDRESSED | Subtask 2 trade-off documentation |
