---
phase: 260406-rze
plan: "01"
type: quick-task
subsystem: smart_entity / entity-gate
tags: [refactor, entity-gate, knowledge-graph, oss-safety]
dependency_graph:
  requires: []
  provides: [entity-gate-kg-source]
  affects: [memory_engine, api_gateway]
tech_stack:
  added: []
  patterns: [duck-typed graph_store, optional alias overrides]
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/smart_entity.py
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/entities.json
decisions:
  - EntityGate decoupled from SQLiteGraph via duck typing — no import added to smart_entity.py
  - entities.json repurposed as optional alias override slot (silently skipped when empty)
  - KG nodes loaded first, aliases merged on top — KG is source of truth
metrics:
  duration: ~10 minutes
  completed: "2026-04-06"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 260406-rze Plan 01: Refactor EntityGate to Load Entity Names from KG — Summary

**One-liner:** EntityGate now sources entity names from SQLiteGraph.get_all_node_names() at startup (110,512 nodes loaded from live KG), with entities.json reset to {} and repurposed as an optional alias override file.

## What Changed Per File

### workspace/sci_fi_dashboard/smart_entity.py

- **New constructor signature:** `__init__(self, graph_store=None, entities_file="entities.json")`
- **Added `_load_from_graph(graph_store)`:** Calls `graph_store.get_all_node_names()` and adds each name to FlashText via `add_keyword()`. Prints count on success; prints WARN and returns cleanly if `graph_store is None`.
- **Added `_load_aliases(entities_file)`:** Replaces old `load_entities()`. Silently skips empty `{}` files (normal for OSS). Merges aliases on top of KG names when file has content. Prints WARN if file not found.
- **Load order:** `_load_from_graph()` runs first (KG is source of truth), then `_load_aliases()` merges on top.
- **No new imports:** `graph_store` is duck-typed — `SQLiteGraph` is not imported into this module.
- **Unchanged public API:** `extract_entities()`, `extract_keywords()`, `add_entity()` — all callers unaffected.
- **`__main__` block updated:** `gate = EntityGate()` with no args (no-arg init still works).

### workspace/sci_fi_dashboard/_deps.py

- **Single line change** on the `gate` singleton (line 104):
  - Before: `gate = EntityGate(entities_file="entities.json")`
  - After: `gate = EntityGate(graph_store=brain, entities_file="entities.json")`
- `brain` (SQLiteGraph instance) is initialized one line above — no ordering changes needed.

### workspace/sci_fi_dashboard/entities.json

- **Reset from 111,289 personal alias entries (3.9 MB) to `{}`.**
- File is now OSS-safe and safe to commit.
- EntityGate's `_load_aliases()` silently skips it when empty.

## Node Count at Test Time

Gateway smoke test confirmed: **110,512 entities loaded from knowledge_graph.db** at startup.

```
[OK] EntityGate: loaded 110512 entities from knowledge graph
brain nodes: 110512
gate type: EntityGate
memory_engine type: MemoryEngine
Import smoke test passed
```

## entities.json Confirmation

```
entities.json is clean {}
```

Zero personal data in the repo. The file remains as a user-overridable alias slot.

## Deviations from Plan

None — plan executed exactly as written.

The Task 1 assertion `assert 'Elden Ring' in results` initially failed because the old entities.json (111K entries) contained a lowercased mapping that overrode the FakeGraph result. This was expected pre-Task 2 behavior; the test was confirmed passing with an empty aliases file (simulating post-Task 2 state), and the full assertion suite passed after Task 2 reset entities.json to `{}`.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. T-rze-03 (Information Disclosure via entities.json in OSS repo) is now fully mitigated — file contains only `{}`.

## Self-Check: PASSED

- workspace/sci_fi_dashboard/smart_entity.py — FOUND (modified)
- workspace/sci_fi_dashboard/_deps.py — FOUND (modified)
- workspace/sci_fi_dashboard/entities.json — FOUND, contains `{}`
- Commit aa2f2b9 — Task 1 (smart_entity.py refactor)
- Commit e585832 — Task 2 (_deps.py wiring + entities.json reset)
- Gateway smoke test: 110,512 nodes loaded, all types correct, no exceptions
