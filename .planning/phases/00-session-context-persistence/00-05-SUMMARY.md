---
plan: 00-05
phase: 00-session-context-persistence
status: complete
tasks_completed: 3
tasks_total: 3
requirements_covered:
  - SESS-08
commits:
  - 85d1f93
  - d07f59a
---

# Summary: Plan 00-05 — `/new` Session Reset + Full Memory Loop

## What Was Built

### Task 1 — `workspace/sci_fi_dashboard/session_ingest.py` (new, 163 lines)

Full background memory-loop ingestion coroutine:

- `_ingest_session_background(archived_path, agent_id, session_key, hemisphere)` — async coroutine, run via `asyncio.create_task()`
- Reads archived JSONL via `load_messages(archived_path)`
- Groups into batches of `BATCH_SIZE=5` turns (10 messages); partial tail batch included
- Per batch:
  1. **Vector**: `deps.memory_engine.add_memory(content, category="whatsapp_session", hemisphere=hemisphere)`
  2. **KG**: `ConvKGExtractor.extract(text)` → validated triples → `deps.brain.add_node()` + `deps.brain.add_relation()` + `_write_triple_to_entity_links(conn, subj, rel, obj, fact_id=0, confidence=confidence)`
  3. **Sleep**: `await asyncio.sleep(BATCH_SLEEP_S)` between batches (not after last)
- `deps.brain.save_graph()` called after all batches when KG triples were written
- All heavy imports (`_deps`, `conv_kg_extractor`, `synapse_config`) are deferred inside the coroutine to prevent circular import at module load time
- Glob fallback for archived filename in case of millisecond timestamp drift

### Task 2 — `workspace/sci_fi_dashboard/pipeline_helpers.py` (modified)

Two additions:

**Module level:**
```python
_session_ingest_tasks: set[asyncio.Task] = set()  # GC anchor for /new background tasks
```

**`_handle_new_command()` helper (before `process_message_pipeline`):**
- Gets current session entry, archives transcript via `archive_transcript(old_path)` → returns `Path`
- Invalidates `deps.conversation_cache`
- Calls `session_store.delete(session_key)` then `session_store.update(session_key, {"compaction_count": 0})` — delete first is critical since `_merge_entry()` never overwrites `session_id` once set
- Fires `asyncio.create_task(_ingest_session_background(...))` with done-callback GC guard
- Returns confirmation string immediately

**`/new` detection in `process_message_pipeline()`:**
```python
if user_msg.strip().lower() == "/new":
    return await _handle_new_command(...)
```
Inserted after Step 3 (session store created) and **before** Step 4 (`load_messages`). Early-return bypasses the LLM entirely.

### Task 3 — `workspace/tests/test_session_persistence.py` (appended)

`TestSessionResetCommand` class (5 tests), guarded by `@_skip_pipeline`:
- `test_new_returns_confirmation` — reply contains archive/reset/fresh/remember keyword
- `test_new_archives_transcript` — original JSONL gone, `*.jsonl.deleted.*` glob finds 1 file
- `test_new_rotates_session_id` — `new_entry.session_id != old_entry.session_id`
- `test_background_ingestion_runs_full_loop` — mocks vector+KG, asserts 2 batches from 6 turns, checks `[WhatsApp session` header
- `test_history_empty_after_new` — `load_messages` on new path returns `[]`

`_skip_pipeline` guard added (checks `pipeline_helpers` + `session_ingest` importability) to skip gracefully when `pyarrow`/`lancedb` ML deps are absent.

## Deviations

None — plan executed as specified. `archive_transcript()` already returns `Path` (fixed in 00-02 Task 0).

## Key Files

| File | Role |
|------|------|
| `workspace/sci_fi_dashboard/session_ingest.py` | New — full vector + KG background loop |
| `workspace/sci_fi_dashboard/pipeline_helpers.py` | Modified — `/new` detection + `_handle_new_command` |
| `workspace/tests/test_session_persistence.py` | Modified — `TestSessionResetCommand` appended |
