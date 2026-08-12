---
phase: 260406-rze
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - workspace/sci_fi_dashboard/smart_entity.py
  - workspace/sci_fi_dashboard/entities.json
  - workspace/sci_fi_dashboard/_deps.py
autonomous: true
requirements:
  - entities.json must ship as empty {} in OSS repo
  - EntityGate must load node names from knowledge_graph.db at startup
  - entities.json remains usable as optional alias override file

must_haves:
  truths:
    - "EntityGate loads entity names from SQLiteGraph.get_all_node_names() at startup"
    - "entities.json ships as {} and is treated as optional alias overrides only"
    - "Gateway boots successfully with 0 KG nodes and with N KG nodes"
    - "Custom aliases in entities.json (e.g. SOTE: [Shadow of the Erdtree]) are merged on top of KG names"
    - "_deps.py initialises EntityGate AFTER SQLiteGraph so the graph instance is available"
  artifacts:
    - path: "workspace/sci_fi_dashboard/smart_entity.py"
      provides: "Refactored EntityGate with load_from_graph() method"
      exports: ["EntityGate"]
    - path: "workspace/sci_fi_dashboard/entities.json"
      provides: "Empty OSS-safe alias override file"
      contains: "{}"
    - path: "workspace/sci_fi_dashboard/_deps.py"
      provides: "Updated singleton wiring — graph passed to EntityGate"
  key_links:
    - from: "_deps.py"
      to: "smart_entity.EntityGate"
      via: "EntityGate(graph_store=brain, entities_file='entities.json')"
    - from: "smart_entity.EntityGate.__init__"
      to: "SQLiteGraph.get_all_node_names()"
      via: "graph_store.get_all_node_names() in load_from_graph()"
---

<objective>
Refactor EntityGate to source entity names from knowledge_graph.db (via SQLiteGraph) instead of the
static 3.9 MB personal entities.json file. entities.json is repurposed as an optional alias override
file that ships empty in the OSS repo.

Purpose: entities.json contains personal chat history and cannot be committed to the OSS repo. Using
the live KG as the source of truth also keeps EntityGate automatically up-to-date as new triples are
added.

Output: smart_entity.py with a new constructor signature that accepts a graph_store, _deps.py wired
correctly, and entities.json reset to {}.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/PROJECT.md

<interfaces>
<!-- Key contracts the executor needs. No codebase exploration required. -->

From workspace/sci_fi_dashboard/sqlite_graph.py:
```python
class SQLiteGraph:
    def get_all_node_names(self) -> list[str]:
        """Returns all node name strings from the nodes table."""
        ...
```

From workspace/sci_fi_dashboard/smart_entity.py (current):
```python
class EntityGate:
    def __init__(self, entities_file="entities.json"):
        # loads FlashText from JSON only
    def extract_entities(self, text) -> list[str]: ...
    def extract_keywords(self, text) -> list[str]: ...  # alias
    def add_entity(self, standard_name, variations): ...
```

From workspace/sci_fi_dashboard/_deps.py (current wiring):
```python
brain = SQLiteGraph()                                      # line 103
gate  = EntityGate(entities_file="entities.json")         # line 104
memory_engine = MemoryEngine(graph_store=brain,
                             keyword_processor=gate)      # line 108
```

From workspace/sci_fi_dashboard/memory_engine.py:
```python
# MemoryEngine consumes gate via keyword_processor:
self.keyword_processor = keyword_processor   # stores reference
...
entities = self.keyword_processor.extract_keywords(text)  # called during query
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Refactor EntityGate to accept graph_store and load KG nodes at init</name>
  <files>workspace/sci_fi_dashboard/smart_entity.py</files>
  <action>
Rewrite EntityGate in workspace/sci_fi_dashboard/smart_entity.py as follows:

1. **New constructor signature:**
   ```python
   def __init__(self, graph_store=None, entities_file="entities.json"):
   ```
   - `graph_store`: optional SQLiteGraph instance (or any object with `get_all_node_names() -> list[str]`)
   - `entities_file`: path to optional JSON alias override file (same resolution logic as today)

2. **Load order inside `__init__`:**
   a. Call `self._load_from_graph(graph_store)` first — populates FlashText from KG nodes
   b. Call `self._load_aliases(entities_file)` second — merges any non-empty JSON aliases on top

3. **`_load_from_graph(graph_store)` method:**
   ```python
   def _load_from_graph(self, graph_store) -> None:
       if graph_store is None:
           print("[WARN] EntityGate: no graph_store provided — skipping KG load")
           return
       names = graph_store.get_all_node_names()
       # Add each name as its own keyword (no aliases, just exact match)
       for name in names:
           self.keyword_processor.add_keyword(name)
       print(f"[OK] EntityGate: loaded {len(names)} entities from knowledge graph")
   ```

4. **`_load_aliases(entities_file)` method** (rename/refactor of existing `load_entities()`):
   - Same logic as current `load_entities()`: resolve path, check exists, load JSON
   - Skip silently if file is empty (`{}`) — print nothing (not a warning, empty is normal)
   - If file has content: normalize values (list or int→[key]), call `add_keywords_from_dict`
   - Print count only if at least 1 alias was loaded: `[OK] EntityGate: merged N alias groups from {file}`
   - If file not found: `[WARN] EntityGate: alias file {file} not found — skipping`

5. **Keep `extract_entities`, `extract_keywords`, and `add_entity` unchanged** — callers depend on them.

6. **Update `__main__` block** to use the new signature:
   ```python
   gate = EntityGate()   # no graph, no aliases — still runnable standalone
   ```

Do NOT add SQLiteGraph as a hard import inside smart_entity.py — the graph is passed in, keeping this
module decoupled. Type hint it as `Any` or use a Protocol if desired, but do not import SQLiteGraph.
  </action>
  <verify>
    <automated>cd D:\Shreya\Synapse-OSS\workspace && python -c "
import sys; sys.path.insert(0, 'sci_fi_dashboard')
from sci_fi_dashboard.smart_entity import EntityGate
# Test 1: no-arg init works
g = EntityGate()
assert g.extract_entities('hello world') == [], 'empty gate should return no entities'

# Test 2: graph_store duck-typed correctly
class FakeGraph:
    def get_all_node_names(self): return ['Malenia', 'Elden Ring', 'Synapse']
g2 = EntityGate(graph_store=FakeGraph())
results = g2.extract_entities('Tell me about Malenia in Elden Ring')
assert 'Malenia' in results and 'Elden Ring' in results, f'expected entities, got {results}'
print('All assertions passed')
"
</automated>
  </verify>
  <done>
    EntityGate accepts graph_store and loads node names into FlashText. No-arg init works (empty gate).
    Duck-typed graph_store with get_all_node_names() is used correctly. Aliases from entities.json are
    merged on top when the file has content. All existing public methods (extract_entities,
    extract_keywords, add_entity) remain unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Wire _deps.py to pass brain into EntityGate, reset entities.json to {}</name>
  <files>workspace/sci_fi_dashboard/_deps.py, workspace/sci_fi_dashboard/entities.json</files>
  <action>
**In workspace/sci_fi_dashboard/_deps.py:**

Change line 104 from:
```python
gate = EntityGate(entities_file="entities.json")
```
to:
```python
gate = EntityGate(graph_store=brain, entities_file="entities.json")
```

`brain` is already initialised on line 103 (`brain = SQLiteGraph()`), so no import or ordering change
is needed. This is the only change required in _deps.py.

**In workspace/sci_fi_dashboard/entities.json:**

Replace the entire file contents with:
```json
{}
```

This removes the 111K personal entries while preserving the file as the alias override slot for users.
The empty object is valid — EntityGate's `_load_aliases()` will silently skip it.

**No changes needed in:**
- memory_engine.py — it receives gate via keyword_processor kwarg, unchanged
- api_gateway.py — it imports from _deps, unchanged
- verify_soul.py — it instantiates EntityGate directly with no graph; that still works with the new
  no-arg-safe constructor (graph_store defaults to None)
  </action>
  <verify>
    <automated>cd D:\Shreya\Synapse-OSS\workspace && python -c "
import json, sys
# Verify entities.json is empty dict
with open('sci_fi_dashboard/entities.json') as f:
    data = json.load(f)
assert data == {}, f'Expected empty dict, got {type(data)} with {len(data)} keys'

# Verify _deps.py passes brain to EntityGate (grep for the pattern)
with open('sci_fi_dashboard/_deps.py') as f:
    src = f.read()
assert 'EntityGate(graph_store=brain' in src, '_deps.py must pass graph_store=brain to EntityGate'
print('Wiring assertions passed')
"
</automated>
  </verify>
  <done>
    _deps.py passes graph_store=brain to EntityGate. entities.json contains only {}. Gateway startup
    loads KG nodes into FlashText at boot with no personal data in the repo.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| entities.json → FlashText | File read at startup; malformed JSON would crash init |
| KG nodes → FlashText | Node names from user's own DB; trusted but may include special chars |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-rze-01 | Tampering | entities.json | accept | File is user-controlled local config; no external input path |
| T-rze-02 | Denial of Service | _load_from_graph() with huge KG | accept | FlashText handles large keyword sets efficiently; 100K+ nodes is realistic ceiling for personal KGs |
| T-rze-03 | Information Disclosure | entities.json in OSS repo | mitigate | File is reset to {} in this plan; .gitignore note not needed since {} is safe to commit |
</threat_model>

<verification>
After both tasks complete, run the full gateway import smoke test:

```bash
cd D:\Shreya\Synapse-OSS\workspace
python -c "
import sys
sys.path.insert(0, '.')
# This import chain exercises _deps.py -> EntityGate -> SQLiteGraph
from sci_fi_dashboard import _deps as deps
print(f'brain nodes: {deps.brain.number_of_nodes()}')
print(f'gate type: {type(deps.gate).__name__}')
print(f'memory_engine type: {type(deps.memory_engine).__name__}')
print('Import smoke test passed')
"
```

Expected output: no exceptions, gate type is EntityGate, memory_engine type is MemoryEngine.

Also verify entities.json is safe to commit:
```bash
python -c "import json; d=json.load(open('workspace/sci_fi_dashboard/entities.json')); assert d=={}"
```
</verification>

<success_criteria>
- EntityGate.__init__ accepts (graph_store=None, entities_file="entities.json")
- KG node names are loaded into FlashText at startup via get_all_node_names()
- entities.json in the repo contains only {} — zero personal data
- _deps.py passes brain (SQLiteGraph instance) to EntityGate at singleton init time
- verify_soul.py still works (EntityGate with no graph_store, graceful degradation)
- No new imports of SQLiteGraph inside smart_entity.py (decoupled via duck typing)
</success_criteria>

<output>
After completion, create `.planning/quick/260406-rze-refactor-entitygate-to-load-entity-names/260406-rze-01-SUMMARY.md`

Include:
- What changed in each file
- Node count loaded from KG at time of testing
- Confirmation that entities.json is now {} and safe to commit
</output>
