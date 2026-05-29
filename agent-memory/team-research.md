# KG Extraction Refactor: Deep Codebase Research

## Summary of Key Findings

**Patterns found:**

- LLM Router async calls: `await router.call_with_metadata(role, messages)` returns LLMResult with text+metadata
- Message storage: ISO timestamps in messages.db per persona, query pattern `SELECT * FROM messages WHERE timestamp > ?`
- KG dual-write: SQLiteGraph.add_edge() + _write_triple_to_entity_links() archival pattern
- Background scheduling: async gentle_worker_loop() in pipeline_helpers.py, currently 600s idle wait
- Lazy-load pattern: TripleExtractor shows load-on-first-use + threading.Timer cleanup
- Config expansion: SynapseConfig uses frozen dataclass with dict-based layer loading from synapse.json
- Fact extraction: _parse_llm_output and _normalize_result can be lifted verbatim from triple_extractor.py

**Dependencies:**

- conv_kg_extractor.py depends on: SynapseConfig, _deps.synapse_llm_router, _deps.sbs_registry, SQLiteGraph
- gentle_worker_loop depends on: conv_kg_extractor.run_batch_extraction, deps module
- fact_extractor.py wraps: conv_kg_extractor.run_batch_extraction (new)
- triple_extractor.py: isolated, should be deprecated (not deleted)

**Gotchas:**

- Messages DB varies by persona: ~./synapse/sbs/PERSONA_ID/indices/messages.db
- Timestamps must be ISO format strings for DB queries and state persistence
- Async boundary: gentle_worker_loop is async, cannot use threading.Timer
- TripleExtractor import triggers torch/transformers load at module level
- entity_links uses archival (archived=1) not deletion
- State file MUST persist kg_last_extracted_at as ISO timestamp
- Model roles ("casual", "vault") must exist in model_mappings
- add_edge() auto-creates nodes, so no explicit add_node() call needed

**Key locations:**

- Message query source: workspace/sci_fi_dashboard/sbs/processing/batch.py:461-469
- LLMRouter call signature: workspace/sci_fi_dashboard/llm_router.py:763-782 (call_with_metadata)
- SQLiteGraph.add_edge: workspace/sci_fi_dashboard/sqlite_graph.py:94-111
- entity_links write: workspace/scripts/fact_extractor.py:84-99 (_write_triple_to_entity_links)
- entities.json update: workspace/scripts/fact_extractor.py:126-145 (_update_entities_json)
- Extraction helpers to reuse: workspace/sci_fi_dashboard/triple_extractor.py:28-213 (_EXTRACTION_PROMPT, _parse_llm_output, _normalize_result)
- Async worker loop: workspace/sci_fi_dashboard/pipeline_helpers.py:245-266
- gentle_worker.py KG task: workspace/sci_fi_dashboard/gentle_worker.py:102-133
- SBS registry: workspace/sci_fi_dashboard/_deps.py:198-201
- SynapseConfig pattern: workspace/synapse_config.py:32-157


---

## Detailed Reference: LLM Router

**SynapseLLMRouter.call_with_metadata() signature (line 885-916):**
```
async def call_with_metadata(
    self,
    role: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> LLMResult
```

**Returns:** LLMResult(text, model, prompt_tokens, completion_tokens, total_tokens, finish_reason)

**Usage pattern in dual_cognition.py:**
```python
from sci_fi_dashboard import _deps as deps
result = await deps.synapse_llm_router.call_with_metadata("casual", [
    {"role": "user", "content": "Extract facts from: ..."}
])
extracted_text = result.text
```

---

## Detailed Reference: Message Query & SBS

**SBSOrchestrator structure (_deps.py line 198-201):**
```python
sbs_registry: dict[str, SBSOrchestrator] = {
    p["id"]: SBSOrchestrator(os.path.join(SBS_DATA_DIR, p["id"]))
    for p in PERSONAS_CONFIG["personas"]
}
```

**To fetch messages for persona "the_creator":**
```python
from sci_fi_dashboard import _deps as deps
sbs = deps.sbs_registry["the_creator"]
# OR use: sbs = deps.get_sbs_for_target("the_creator")

# Access messages database:
db_path = sbs.logger.db_path  # ~/.synapse/sbs/the_creator/indices/messages.db

# Query messages since timestamp:
import sqlite3
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT msg_id, timestamp, role, content FROM messages WHERE timestamp > ? ORDER BY timestamp ASC LIMIT 200",
    ("2026-04-06T12:00:00",)
).fetchall()
messages = [dict(r) for r in rows]
```

---

## Detailed Reference: Dual-Write Pattern

**Write triple to both stores (from fact_extractor.py pattern):**
```python
from sci_fi_dashboard.sqlite_graph import SQLiteGraph
from sci_fi_dashboard.db import DB_PATH as MEMORY_DB_PATH
import sqlite3

# Initialize stores
kg_graph = SQLiteGraph()
conn = sqlite3.connect(MEMORY_DB_PATH)

# For each triple (subject, relation, object):
subj, rel, obj = "alice", "likes", "coffee"

# 1. Write to SQLiteGraph (auto-creates nodes)
kg_graph.add_edge(subj, obj, relation=rel, weight=1.0, evidence="extracted from conversation")

# 2. Write to entity_links table (archival pattern)
# First ensure table exists:
conn.execute("""
    CREATE TABLE IF NOT EXISTS entity_links (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        subject   TEXT NOT NULL,
        relation  TEXT NOT NULL,
        object    TEXT NOT NULL,
        archived  INTEGER DEFAULT 0,
        source_fact_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Then write with archival:
fact_id = 123  # from atomic_facts table, or 0
conn.execute(
    "UPDATE entity_links SET archived = 1 WHERE subject = ? AND relation = ? AND archived = 0",
    (subj, rel)
)
conn.execute(
    "INSERT INTO entity_links (subject, relation, object, archived, source_fact_id) VALUES (?, ?, ?, 0, ?)",
    (subj, rel, obj, fact_id)
)
conn.commit()

# 3. Collect entity names for entities.json
entities = {subj, obj}  # set
```

**Update entities.json (from fact_extractor.py:126-145):**
```python
import json
from pathlib import Path

entities_json_path = Path("workspace/sci_fi_dashboard/entities.json")

# Load existing
try:
    with open(entities_json_path) as f:
        current = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    current = {}

# Add new entities
for entity in entities:
    if entity.strip():
        current[entity.strip()] = 1

# Write back
with open(entities_json_path, "w") as f:
    json.dump(current, f, ensure_ascii=False, indent=2)
```

---

## Detailed Reference: KG State Persistence

**Read state:**
```python
import json
from pathlib import Path
from datetime import datetime

sbs_data_dir = "~/.synapse/sbs/the_creator"
kg_state_file = Path(sbs_data_dir) / "kg_state.json"

if kg_state_file.exists():
    with open(kg_state_file) as f:
        state = json.load(f)
    last_ts = state.get("kg_last_extracted_at", "2000-01-01T00:00:00")
else:
    last_ts = "2000-01-01T00:00:00"
```

**Write state:**
```python
from datetime import datetime

state = {"kg_last_extracted_at": datetime.now().isoformat()}
with open(kg_state_file, "w") as f:
    json.dump(state, f)
```

---

## Detailed Reference: Extraction Prompt & Parsing

**From triple_extractor.py (lines 28-41):**
```python
_EXTRACTION_PROMPT = """\
Extract key atomic facts and knowledge graph triples from the following text.
Return ONLY valid JSON with this structure:
{{
  "facts": [
    {{"entity": "main subject", "content": "atomic fact", "category": "Work|Relationship|Plan|Preference|Health|Location"}}
  ],
  "triples": [
    ["subject", "relation", "object"]
  ]
}}

Text:
{content}"""
```

**JSON Parsing (3-tier fallback, triple_extractor.py:142-176):**
Tier 1: direct json.loads()
Tier 2: extract from markdown code block ```json ... ```
Tier 3: regex-find patterns like ["subject", "relation", "object"]

**Normalization (triple_extractor.py:184-213):**
- Lowercase all entities, relations, objects
- Collapse whitespace: re.sub(r"\s+", " ", text)
- Deduplicate facts and triples using sets
- Return: {"facts": [...], "triples": [...]}

---

## Detailed Reference: Config Pattern

**To add KGExtractionConfig:**

```python
# In workspace/synapse_config.py, add:

@dataclass(frozen=True)
class KGExtractionConfig:
    """Configuration for KG extraction."""
    enabled: bool = True
    min_messages: int = 15
    extract_interval_seconds: int = 1200  # 20 minutes

# In SynapseConfig dataclass, add field:
kg_extraction: KGExtractionConfig = field(default_factory=KGExtractionConfig)

# In SynapseConfig.load(), add to field list:
kg_raw = raw.get("kg_extraction", {})
kg_config = KGExtractionConfig(**{
    k: v for k, v in kg_raw.items()
    if k in KGExtractionConfig.__dataclass_fields__
})

# Then in constructor:
kg_extraction=kg_config,

# Access in code:
from synapse_config import SynapseConfig
cfg = SynapseConfig.load()
if cfg.kg_extraction.enabled:
    min_msgs = cfg.kg_extraction.min_messages
```

---

## Detailed Reference: gentle_worker_loop Async Integration

**Current location (pipeline_helpers.py:245-266):**
```python
async def gentle_worker_loop():
    while True:
        try:
            battery = psutil.sensors_battery()
            is_plugged = battery.power_plugged if battery else True
            cpu_load = psutil.cpu_percent(interval=None)

            if is_plugged and cpu_load < 20.0:
                deps.brain.prune_graph()
                deps.conflicts.prune_conflicts()
                await asyncio.sleep(600)  # 10 min
            else:
                await asyncio.sleep(60)   # 1 min
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[WARN] Worker: {e}")
            await asyncio.sleep(60)
```

**To add KG extraction (with 20-min timer):**

Track a counter that increments every 600s:
- _kg_extract_tick = 0, increments each sleep cycle
- Every 2 cycles (1200s), fire extraction
- OR: use time-based guard for 30-min fallback

Pattern:
```python
_kg_extract_tick = 0
_kg_last_extract_time = time.time()

while True:
    if is_plugged and cpu_load < 20.0:
        deps.brain.prune_graph()
        deps.conflicts.prune_conflicts()
        
        # KG extraction every 2 cycles (approx 20 min)
        _kg_extract_tick += 1
        if _kg_extract_tick >= 2 or time.time() - _kg_last_extract_time >= 1800:
            _kg_extract_tick = 0
            _kg_last_extract_time = time.time()
            try:
                await asyncio.create_task(
                    conv_kg_extractor.run_batch_extraction(...)
                )
            except Exception as e:
                print(f"[WARN] KG extraction failed: {e}")
        
        await asyncio.sleep(600)
    else:
        await asyncio.sleep(60)
```

