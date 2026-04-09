# QA Test Report - KG Extraction Refactor
Date: 2026-04-06

## Acceptance Criteria

### Subtask 1 AC: No torch/transformers; extract() is async; required functions present
PASS
- File exists at workspace/sci_fi_dashboard/conv_kg_extractor.py.
- Grep: zero matches for import torch or from transformers.
- ConvKGExtractor.extract() is declared async def (line 319).
- Returns {facts:[...], triples:[...]} (line 368) matching old shape.
- _EXTRACTION_PROMPT (l37), _parse_llm_output (l103), _normalize_result (l145), _chunk_text (l65) present.
- response_format={type:json_object} passed to router.call() (line 350). PASS.

### Subtask 2 AC: State helpers and fetch_messages_since correct
PASS
- _get_last_kg_timestamp (l249): reads kg_state.json via pathlib.Path, fallback 2000-01-01T00:00:00.
- _set_last_kg_timestamp (l266): writes {kg_last_extracted_at: ts}, os.makedirs before write.
- fetch_messages_since (l275): async, asyncio.to_thread for read, thread-local conn, correct SQL.

### Subtask 3 AC: run_batch_extraction dual-writes; watermark is last
PASS WITH WARNING
- run_batch_extraction (l376), acquires _extraction_lock at entry (l397).
- Write sequence: (h) add_edge direct (ll441-445), (i) entity_links local conn (ll448-458),
  (j) entities.json (ll461-466), (k) watermark last (l469).
- Steps h-k in single try/except (ll439-476). Watermark never advances on failure.
WARNING: Empty-result fast-path at ll432-436 advances watermark OUTSIDE the try/except.
If _set_last_kg_timestamp fails there, exception propagates unhandled. Minor gap; does not
violate any stated AC.

### Subtask 4 AC: gentle_worker_loop schedules extraction; failures swallowed
PASS
- _kg_tick and _kg_last_time initialized before while True (ll250-251).
- Tick logic: _kg_tick >= 2 OR 30-min fallback (ll263-264).
- run_batch_extraction awaited directly (l270), not create_task.
- except Exception (l281) wraps extraction; swallows failures.
- logger.warning used for failure (l282) -- improvement over spec print().
- str(sbs.data_dir) used (l272). Path(__file__).parent / entities.json (ll276-278).

### Subtask 5 AC: heavy_task_kg_extraction and schedule entry removed; no run_until_complete
PASS
- Grep: zero matches for heavy_task_kg_extraction, scripts.fact_extractor, TripleExtractor.
- Comment at l106 confirms KG extraction moved to pipeline_helpers.py.
- Remaining methods all call check_conditions() before running.
- Schedule retains graph pruning (10 min), db optimize (30 min), proactive (15 min).
- Grep: zero matches for run_until_complete.

### Subtask 6 AC: fact_extractor.py thin wrapper; triple_extractor.py emits DeprecationWarning
PASS WITH OBSERVATION
- fact_extractor.py imports only synapse_config, conv_kg_extractor, llm_router, sqlite_graph.
  No torch, no TripleExtractor. PASS.
- --dry-run (l155): extracts without writes. PASS.
- --force: effective_min=0 if force else cfg.kg_extraction.min_messages (ll95-96). PASS.
- triple_extractor.py: warnings.warn at module top (ll27-31), DeprecationWarning, stacklevel=2. PASS.
OBSERVATION: --limit NOT forwarded to run_batch_extraction in non-dry-run path. See FINDING-1.

### Subtask 7 AC: KGExtractionConfig; enabled=false prevents extraction; synapse.json.example updated
PASS
- KGExtractionConfig frozen dataclass at l58: enabled=True, min_messages=15, interval=1200.
- Placed after SBSConfig (l57). Field on SynapseConfig at l102 with default_factory.
- Parsed via raw.get(kg_extraction,{}) filtered through __dataclass_fields__ (ll155, 164-167, 184).
- Guard: if not cfg.kg_extraction.enabled: return {skipped:True} (ll399-401). PASS.
- synapse.json.example has kg_extraction section (ll73-77) with all three correct keys. PASS.

---

## Cross-Cutting Checks

- No torch imports in conv_kg_extractor.py: PASS - grep returns zero matches.
- No run_until_complete in gentle_worker.py: PASS - grep returns zero matches.
- No asyncio.to_thread on write operations: PASS - to_thread only at l301 (read query).
  All writes (add_edge, entity_links, entities.json, kg_state.json) are direct calls.
- Logger not print (new KG code): PASS - conv_kg_extractor.py uses only logger.*.
  pipeline_helpers.py uses logger.warning for KG failure (l282).
  Pre-existing print() in pipeline_helpers.py is in outer worker shell / validate_env().
- Pathlib paths: PASS - pathlib.Path imported (l26), used for state file (ll255,268) and
  messages.db path (l407). pipeline_helpers.py uses Path(__file__).parent (l277).

---

## Additional Findings

### FINDING-1 (Warning): --limit not forwarded in non-dry-run CLI mode
File: workspace/scripts/fact_extractor.py, lines 96-105
args.limit is used only in the dry-run path. In the normal write path, run_batch_extraction
uses default limit=200 regardless of --limit arg. Result: --limit 100 is silently ignored
during a live write run.

### FINDING-2 (Warning): Empty-result watermark advance is unguarded
File: workspace/sci_fi_dashboard/conv_kg_extractor.py, lines 432-436
When LLM returns empty facts+triples, _set_last_kg_timestamp is called outside the write
try/except. A failure raises an unhandled exception from run_batch_extraction instead of
returning the documented dict. The gentle_worker_loop outer except catches it, but callers
depending on the return dict will see an exception.

### FINDING-3 (Info): Module-level _extraction_lock is not per-persona
Lock is module-scoped; extraction for the_creator blocks the_partner.
Architecture spec documents this as deliberate. No action needed.

### FINDING-4 (Info): _call_claude_cli does not forward **kwargs
File: workspace/sci_fi_dashboard/llm_router.py, line 909
claude_max path calls _call_claude_cli without **kwargs; response_format not forwarded.
Does not affect KG extraction (uses casual role).

---

## Overall: PASS

All 7 acceptance criteria pass. All 5 cross-cutting checks pass. No blocking failures.

### Failures needing fix:
None.

### Warnings to consider addressing (non-blocking):
1. FINDING-1 -- --limit silently ignored in non-dry-run CLI mode (fact_extractor.py ll96-105).
2. FINDING-2 -- Empty-result watermark advance at conv_kg_extractor.py ll432-436 is outside
   the try/except guard.
