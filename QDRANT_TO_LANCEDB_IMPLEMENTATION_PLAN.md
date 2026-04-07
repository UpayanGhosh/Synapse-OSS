# Replace Qdrant with LanceDB: Complete Implementation Plan

## Context

**Problem:** Synapse-OSS requires Docker to run Qdrant on port `6333`, creating contributor friction (`500MB+` download, `100-300MB` RAM, platform issues). https://github.com/UpayanGhosh/Synapse-OSS/discussions/27 proposes eliminating Docker entirely.

**Solution:** Replace Qdrant with LanceDB, an embedded, pip-installable vector database with disk-backed IVF-PQ indexing and native hybrid search.

**Embedding strategy:** External Embedding + Raw Vectors (Approach A). Synapse's existing `FastEmbedProvider` generates vectors externally; LanceDB receives pre-computed `float[768]` vectors. This preserves:

- The `lru_cache(500)` on `get_embedding()` (`2-3x` faster on cached queries)
- Provider hot-swap via `factory.py` cascade (`FastEmbed -> Ollama -> Gemini`)
- Correct `search_query:` / `search_document:` prefix handling for `nomic-embed-text`
- Dual-write to `sqlite-vec` as safety fallback
- Failure isolation (embedding crashes do not break storage)

**Current interface:** `QdrantVectorStore` has only 3 methods (`__init__`, `upsert_facts`, `search`) totaling about 70 lines. Drop-in replacement is straightforward.

---

## Phase 0: Dependencies and Configuration (non-breaking)

### 0.1 Add LanceDB dependency

`requirements.txt` — add after `sqlite-vec>=0.1.1` (line 28):

```txt
lancedb>=0.6.0                   # Embedded vector DB (replaces Qdrant - zero Docker)
```

`pyproject.toml` — add to dependencies array (line 24):

```toml
"lancedb>=0.6.0",
```

`requirements-optional.txt` — mark Qdrant as deprecated:

```txt
# --- Vector Database (DEPRECATED - being replaced by LanceDB) ---
# qdrant-client>=1.6.0   # No longer needed; kept for reference
```

### 0.2 Add `vector_store` config to `SynapseConfig`

`workspace/synapse_config.py`:

1. Add field to `SynapseConfig` dataclass (after line 82 `embedding: dict`):

```python
vector_store: dict = field(default_factory=dict)
```

2. Add variable in `load()` method (after line 111 `embedding: dict = {}`):

```python
vector_store: dict[str, Any] = {}
```

3. Add parsing in config reading block (after line 131 `embedding = raw.get("embedding", {})`):

```python
vector_store = raw.get("vector_store", {})
```

4. Add to constructor call (after line 152 `embedding=embedding`):

```python
vector_store=vector_store,
```

`synapse.json.example` — add new top-level key:

```json
"vector_store": {
    "backend": "lancedb",
    "lancedb": {
        "db_path": null,
        "table_name": "memories"
    }
}
```

When `db_path` is `null`, it defaults to `SynapseConfig.load().db_dir / "lancedb"` (that is, `~/.synapse/workspace/db/lancedb/`).

---

## Phase 1: Create `LanceDBVectorStore` Package

New directory structure:

```txt
workspace/sci_fi_dashboard/vector_store/
    __init__.py
    base.py
    lancedb_store.py
```

### 1.1 `vector_store/__init__.py`

```python
from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

__all__ = ["LanceDBVectorStore"]
```

### 1.2 `vector_store/base.py` — Abstract interface

```python
from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    @abstractmethod
    def upsert_facts(self, facts: list[dict[str, Any]]) -> None:
        """Upsert vectors. facts: [{id, vector, metadata}]"""

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float = 0.0,
        query_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search. Returns [{id, score, metadata}]. query_filter is a SQL WHERE clause."""

    @abstractmethod
    def close(self) -> None:
        """Clean shutdown."""
```

### 1.3 `vector_store/lancedb_store.py` — Full implementation

LanceDB table schema (PyArrow):

```python
import pyarrow as pa

SCHEMA = pa.schema([
    pa.field("id", pa.int64()),
    pa.field("vector", pa.list_(pa.float32(), 768)),
    pa.field("text", pa.utf8()),
    pa.field("hemisphere_tag", pa.utf8()),
    pa.field("unix_timestamp", pa.int64()),
    pa.field("importance", pa.int64()),
    pa.field("source_id", pa.int64()),
    pa.field("entity", pa.utf8()),
    pa.field("category", pa.utf8()),
])
```

Class implementation:

```python
class LanceDBVectorStore(VectorStore):
    def __init__(
        self,
        db_path: str | None = None,
        table_name: str = "memories",
        embedding_dimensions: int = 768,
    ):
        # db_path defaults to SynapseConfig.load().db_dir / "lancedb"
        # Open/create LanceDB database directory
        # Create or open table with schema above (dynamic dims from embedding_dimensions)
        # Store embedding_dimensions for schema validation

    def _ensure_index(self) -> None:
        # Called lazily after upserts
        # Skip if table has < 256 rows (brute-force is faster at small scale)
        # Create IVF_PQ index: num_partitions = max(1, num_rows // 4096)
        # Create scalar index on hemisphere_tag for fast pre-filtering
        # Create FTS index on text column via create_fts_index()

    def upsert_facts(self, facts: list[dict[str, Any]]) -> None:
        # Convert [{id, vector, metadata}] to list of flat dicts:
        #   [{id, vector, text, hemisphere_tag, unix_timestamp, importance, source_id, entity, category}]
        # Flatten: metadata values become top-level columns
        # Default missing metadata keys to "" (str) or 0 (int)
        # Use table.merge_insert("id")
        #   .when_matched_update_all()
        #   .when_not_matched_insert_all()
        #   .execute(data)
        # This is idempotent - same ID overwrites, not duplicates

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float = 0.0,
        query_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        # query = self.table.search(query_vector).metric("cosine").limit(limit)
        # if query_filter: query = query.where(query_filter, prefilter=True)
        # results = query.to_list()
        #
        # IMPORTANT: LanceDB returns cosine _distance (0 = identical, 2 = opposite)
        # Qdrant returns cosine similarity (1 = identical, -1 = opposite)
        # Conversion: score = 1 - distance
        #
        # Filter by score_threshold after conversion
        # Return [{
        #   "id": r["id"],
        #   "score": 1 - r["_distance"],
        #   "metadata": {
        #       "text": r["text"],
        #       "hemisphere_tag": r["hemisphere_tag"],
        #       "unix_timestamp": r["unix_timestamp"],
        #       "importance": r["importance"],
        #       ...
        #   }
        # }]

    def close(self) -> None:
        # LanceDB is embedded - this is a no-op or cleanup handle
```

Critical design notes:

- `prefilter=True` on `.where()` pre-filters before vector search, reducing search space by about 50% (`safe` vs `spicy` hemisphere). This is the default in LanceDB, but being explicit is safer.
- Score conversion `1 - distance` is essential. `memory_engine.py:230` uses `r["score"] * 0.4` in the 3-factor scoring formula. Returning raw distance would invert ranking.
- `merge_insert` handles idempotent upserts natively. No delete-then-insert path is needed.

---

## Phase 2: Rewire All Qdrant Consumers

### 2.1 `workspace/sci_fi_dashboard/memory_engine.py` (primary consumer)

Import block (lines 60-71) — replace entirely:

```python
# REMOVE these lines:
sys.path.append(os.path.join(WORKSPACE_ROOT, "scripts", "v2_migration"))
try:
    from scripts.v2_migration.qdrant_handler import QdrantVectorStore
except ImportError:
    sys.path.append(os.path.join(WORKSPACE_ROOT, "sci_fi_dashboard"))
    from retriever import QdrantVectorStore

# REPLACE with:
from sci_fi_dashboard.vector_store import LanceDBVectorStore
```

Constructor (line 100):

```python
# BEFORE:
self.qdrant_store = QdrantVectorStore()

# AFTER:
self.vector_store = LanceDBVectorStore()
```

`query()` method — hemisphere filter (lines 195-224) — replace entire Qdrant filter block:

```python
# REMOVE lines 195-224 (qdrant_models import + Filter construction + search call)

# REPLACE with:
if hemisphere == "spicy":
    hemisphere_filter = "hemisphere_tag IN ('safe', 'spicy')"
else:
    hemisphere_filter = "hemisphere_tag = 'safe'"

q_results = self.vector_store.search(
    query_vec, limit=limit * 3, query_filter=hemisphere_filter
)
```

`query()` method — result source labels (lines 253, 277):

```python
# BEFORE:
"source": "qdrant_fast"
"source": "qdrant_reranked"

# AFTER:
"source": "lancedb_fast"
"source": "lancedb_reranked"
```

`add_memory()` method — upsert (lines 334-347):

```python
# BEFORE:
self.qdrant_store.upsert_facts([{...}])

# AFTER:
self.vector_store.upsert_facts([{...}])
```

Also update error message on line 347:

```python
print(f"[WARN] LanceDB upsert failed: {lancedb_err}")
```

Summary of attribute rename: `self.qdrant_store -> self.vector_store` throughout the file. Grep for all occurrences.

### 2.2 `workspace/scripts/nightly_ingest.py`

Remove Qdrant imports (lines 13-14):

```python
# REMOVE:
from qdrant_client import QdrantClient
from qdrant_client.http import models
```

Add LanceDB import (after line 12):

```python
from sci_fi_dashboard.vector_store import LanceDBVectorStore
```

Replace Qdrant client creation (line 78):

```python
# BEFORE:
qdrant = QdrantClient(host="localhost", port=6333)

# AFTER:
lance_store = LanceDBVectorStore()
```

Replace Qdrant upsert (lines 86-106) — replace `PointStruct` construction and upsert:

```python
# BEFORE: building models.PointStruct list + qdrant.upsert(collection_name="atomic_facts", points=points)

# AFTER:
facts_batch = []
for fact in data.get("atomic_facts", []):
    vec = get_embedding(fact)
    cursor.execute(
        "INSERT INTO atomic_facts (content, source_doc_id) VALUES (?, ?)", (fact, doc_id)
    )
    fact_id = cursor.lastrowid
    facts_batch.append({
        "id": fact_id,
        "vector": vec,
        "metadata": {
            "text": fact,
            "source_id": doc_id,
            "unix_timestamp": ts or int(time.time()),
        },
    })

if facts_batch:
    lance_store.upsert_facts(facts_batch)
```

### 2.3 Archive/remove old Qdrant files

| Action | File |
|---|---|
| Delete | `workspace/scripts/migrate_temporal.py` (one-time Qdrant payload migration, obsolete) |
| Keep but mark deprecated | `workspace/scripts/v2_migration/qdrant_handler.py` (reference for interface contract during migration, remove in next release) |
| Keep but mark deprecated | `workspace/scripts/v2_migration/migrate_vectors.py` (superseded by `migrate_to_lancedb.py`) |

---

## Phase 3: Data Migration Script

New file: `workspace/scripts/migrate_to_lancedb.py`

Source of truth: `sqlite-vec` (has all data via dual-write in `add_memory()`). No Qdrant connection needed.

```python
"""Migrate all vectors from sqlite-vec to LanceDB.

Usage:
    cd workspace && python scripts/migrate_to_lancedb.py [--dry-run]

Source: memory.db (sqlite-vec tables: vec_items + atomic_facts_vec)
Target: LanceDBVectorStore at ~/.synapse/workspace/db/lancedb/
"""
```

```python
def migrate(dry_run: bool = False):
    # 1. Connect to memory.db with sqlite-vec extension loaded
    conn = get_db_connection()

    # 2. Migrate documents (vec_items -> LanceDB)
    #    Query:
    #      SELECT d.id, d.content, d.hemisphere_tag, d.unix_timestamp,
    #             d.importance, d.filename, vec_to_json(v.embedding) as embedding
    #      FROM vec_items v
    #      JOIN documents d ON v.document_id = d.id
    #
    #    Note: vec_to_json() converts sqlite-vec binary blob to JSON array
    #    Alternative: use struct.unpack(f"{768}f", v.embedding) for raw blob

    # 3. Migrate atomic facts (atomic_facts_vec -> LanceDB)
    #    Query:
    #      SELECT af.id, af.content, af.entity, af.category, af.source_doc_id,
    #             vec_to_json(v.embedding) as embedding
    #      FROM atomic_facts_vec v
    #      JOIN atomic_facts af ON v.fact_id = af.id
    #
    #    Atomic facts do not have hemisphere_tag - default to "safe"

    # 4. Batch upsert to LanceDB (1000 rows per batch)
    #    - Use LanceDBVectorStore.upsert_facts() for each batch
    #    - Print progress every 500 rows

    # 5. Trigger index creation (IVF_PQ + scalar on hemisphere_tag + FTS on text)

    # 6. Verification:
    #    - Count documents in sqlite-vec: SELECT COUNT(*) FROM vec_items
    #    - Count atomic facts in sqlite-vec: SELECT COUNT(*) FROM atomic_facts_vec
    #    - Count rows in LanceDB table
    #    - Print comparison + any delta

    # 7. Summary stats
```

Important: The script must be idempotent (safe to re-run) via `merge_insert` on the `id` column.

Embedding extraction from `sqlite-vec`: the `vec_items` table stores embeddings as binary blobs. To extract:

```python
import struct

# blob is bytes from sqlite-vec
embedding = list(struct.unpack(f"{768}f", blob))
```

---

## Phase 4: Infrastructure Cleanup

### 4.1 `docker-compose.yml`

Remove Qdrant service entirely. Remove `depends_on: - qdrant` from `synapse` service. Remove `qdrant_data` volume.

After:

```yaml
services:
  synapse:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    volumes:
      - synapse_data:/root/.synapse

volumes:
  synapse_data:
```

### 4.2 `synapse_start.sh`

Remove the entire `[1/3] Starting Qdrant...` block (lines 17-31). Renumber:

- `[1/3] Starting Qdrant...` -> delete
- `[2/3] Starting Ollama...` -> `[1/2] Starting Ollama...`
- `[3/3] Starting API Gateway...` -> `[2/2] Starting API Gateway...`

### 4.3 `synapse_start.bat`

Remove the Docker guard block (lines 32-39, `docker info` check).

Remove the entire `[1/3] Starting Qdrant...` block (lines 80-92).

Renumber:

- `[2/3] Starting Ollama...` -> `[1/2] Starting Ollama...`
- `[3/3] Starting API Gateway...` -> `[2/2] Starting API Gateway...`

### 4.4 `synapse_health.sh`

Remove line 41:

```sh
curl -sf http://localhost:6333/collections > /dev/null && echo " Qdrant     (6333)" || echo " Qdrant DOWN"
```

Optionally add LanceDB health check:

```sh
LANCE_DIR="${SYNAPSE_HOME:-$HOME/.synapse}/workspace/db/lancedb"
[ -d "$LANCE_DIR" ] && echo " LanceDB    (embedded)" || echo " LanceDB dir missing"
```

### 4.5 `workspace/sci_fi_dashboard/pipeline_helpers.py`

Remove lines 105 and 112:

```python
# REMOVE:
qdrant_on = _port_open("localhost", 6333)
print(f"   Qdrant         {'[ON]' if qdrant_on else '[--]'}  vector search")
```

Replace with:

```python
lance_dir = SynapseConfig.load().db_dir / "lancedb"
lance_on = lance_dir.exists()
print(f"   LanceDB        {'[ON]' if lance_on else '[--]'}  vector search (embedded)")
```

### 4.6 `.gitignore`

Add (keeping existing Qdrant entries is harmless):

```gitignore
# LanceDB data
*.lance
lancedb/
```

### 4.7 `workspace/change_tracker.py` (line 100)

Add LanceDB file exclusion pattern alongside existing Qdrant exclusion.

### 4.8 `workspace/sci_fi_dashboard/chat_parser.py` (line 241)

Replace `"qdrant"` keyword with `"lancedb"` in tech keyword list.

---

## Phase 5: Test Updates

### 5.1 `workspace/tests/test_memory_engine.py`

Every `patch("sci_fi_dashboard.memory_engine.QdrantVectorStore")` becomes `patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore")`.

Occurrences to update (found by grep):

- Line 40: `patch("sci_fi_dashboard.memory_engine.QdrantVectorStore")`
- Line 51: same
- Line 62: `_make_engine` helper
- All other test classes that call `_make_engine` or patch directly

Also rename all `engine.qdrant_store` references to `engine.vector_store`.

Update mock fixture docstring (line 28):

```python
"""Mock LanceDB, flashrank, flashtext to avoid real connections."""
```

### 5.2 `workspace/tests/test_embedding_integration.py` (lines 14-22)

Remove the entire `qdrant_client` pre-stub block:

```python
for _mod in [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "qdrant_client.http.models.models",
    "qdrant_client.models",
]:
    sys.modules.setdefault(_mod, MagicMock())
```

### 5.3 `workspace/tests/test_embedding_pipeline_deep.py` (lines 32-41)

Remove the same `qdrant_client` pre-stub block.

### 5.4 `workspace/tests/test_embedding_production_readiness.py`

Remove any `QdrantVectorStore` patches. Verify by grepping the file.

### 5.5 `workspace/tests/test_schema_migration.py` (lines 232-258)

Replace `TestQdrantDimensionsParameterized` class with:

```python
class TestLanceDBDimensionsParameterized(unittest.TestCase):
    """LanceDBVectorStore must accept embedding_dimensions and not hardcode 768."""

    def test_lancedb_dimensions_stored_on_instance(self):
        from sci_fi_dashboard.vector_store import LanceDBVectorStore
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LanceDBVectorStore(db_path=tmpdir, embedding_dimensions=512)
            # Verify the schema uses 512-dim vectors
            schema = store.table.schema
            vec_field = schema.field("vector")
            self.assertEqual(vec_field.type.list_size, 512)

            # Default is 768
            store_default = LanceDBVectorStore(
                db_path=os.path.join(tmpdir, "default"), embedding_dimensions=768
            )
            vec_field_default = store_default.table.schema.field("vector")
            self.assertEqual(vec_field_default.type.list_size, 768)
```

### 5.6 `workspace/tests/test_llm_router.py` and `test_whatsapp_channel.py`

Update or remove any skip messages referencing `qdrant_client`. These tests currently skip when `qdrant_client` import fails; after migration, that condition no longer applies.

### 5.7 New file: `workspace/tests/test_vector_store.py`

Test cases:

```python
class TestLanceDBVectorStore:
    """Tests for LanceDBVectorStore."""

    # Uses tmp_path fixture for isolated LanceDB directories

    def test_init_creates_db_and_table(self, tmp_path):
        """__init__ should create the LanceDB dir and memories table."""

    def test_upsert_single_fact(self, tmp_path):
        """upsert_facts with one fact should insert it."""

    def test_upsert_idempotent(self, tmp_path):
        """Upserting same ID twice should update, not duplicate."""

    def test_upsert_batch(self, tmp_path):
        """Batch upsert of 100 facts should work."""

    def test_search_returns_correct_format(self, tmp_path):
        """search should return [{id, score, metadata}]."""

    def test_search_cosine_score_conversion(self, tmp_path):
        """Score should be 1 - distance (identical vectors -> score ~1.0)."""

    def test_search_hemisphere_filter_safe(self, tmp_path):
        """hemisphere_tag = 'safe' should exclude spicy results."""

    def test_search_hemisphere_filter_spicy(self, tmp_path):
        """hemisphere_tag IN ('safe', 'spicy') should return both."""

    def test_search_score_threshold(self, tmp_path):
        """Results below score_threshold should be excluded."""

    def test_search_empty_table(self, tmp_path):
        """Search on empty table should return []."""

    def test_search_limit(self, tmp_path):
        """Should return at most `limit` results."""

    def test_custom_embedding_dimensions(self, tmp_path):
        """embedding_dimensions=512 should create 512-dim vector column."""

    def test_missing_metadata_keys_default(self, tmp_path):
        """Facts with partial metadata should use defaults for missing keys."""
```

---

## Phase 6: Documentation Updates

### 6.1 `ARCHITECTURE.md`

- Replace `Qdrant | Qdrant (native binary) | :6333 | High-speed semantic vector search` with `LanceDB | Embedded (pip install) | N/A | Embedded vector + FTS search`
- Update Mermaid diagram: `Qdrant Vector -> LanceDB (embedded)`
- Remove port `6333` from port table
- Update retrieval description: `FlashRank re-scores Qdrant candidates` -> `FlashRank re-scores LanceDB candidates`

### 6.2 `CLAUDE.md`

- Remove `Qdrant at :6333 -- high-speed ANN search` from Memory section
- Add `LanceDB (embedded, ~/.synapse/workspace/db/lancedb/)` in its place
- Remove port `6333` from Ports line
- Update architecture description in Request Flow if Qdrant is mentioned

### 6.3 `README.md`

- Remove Docker/Qdrant from prerequisites
- Highlight `zero Docker dependency` as a feature

### 6.4 `HOW_TO_RUN.md`

- Remove `Docker runs the Qdrant vector database` section
- Remove Docker as prerequisite (Docker was only needed for Qdrant)
- Remove Qdrant troubleshooting section
- Update startup description to 2 steps (Ollama + Gateway)

### 6.5 `DEPENDENCIES.md`

- Replace Qdrant reference with LanceDB
- Update conditional import notes

### 6.6 `CONTRIBUTING.md`

- Update note about tests so they no longer require a live Qdrant service

### 6.7 `SETUP_PERSONA.md`

- `databases (memory.db and Qdrant)` -> `databases (memory.db and LanceDB)`

### 6.8 `workspace/README.md`

- Update Mermaid diagram
- Update file tree to show `vector_store/` module

---

## Rollback Safety

| Concern | Safety mechanism |
|---|---|
| Data loss | LanceDB writes to a new directory (`~/.synapse/workspace/db/lancedb/`). Nothing existing is deleted. |
| `sqlite-vec` path | Dual-write continues. `retriever.py` CLI path is completely unaffected. |
| Qdrant data | Docker volume stays intact. Not touched by this migration. |
| Runtime failures | All vector store calls in `memory_engine.py` are wrapped in `try/except` (lines 286-294, 335-347). |
| Rollback procedure | Revert the `memory_engine.py` import to `QdrantVectorStore`, restart Docker and Qdrant. |

---

## Implementation Order

| Step | Phase | What | Risk |
|---|---|---|---|
| 1 | Phase 0 | Add LanceDB dependency and `vector_store` config | None, no behavioral change |
| 2 | Phase 1 | Create `vector_store/` package with `LanceDBVectorStore` | None, new code not wired yet |
| 3 | Phase 5.7 | Write `test_vector_store.py` (TDD) | None, tests only |
| 4 | Phase 2.1 | Rewire `memory_engine.py` | Medium, core pipeline change |
| 5 | Phase 2.2 | Rewire `nightly_ingest.py` | Low, background job |
| 6 | Phase 2.3 | Archive old Qdrant files | None |
| 7 | Phase 3 | Create and run migration script | Low, reads from `sqlite-vec`, writes to new dir |
| 8 | Phase 5.1-5.6 | Update existing tests | Low |
| 9 | Phase 4 | Infrastructure cleanup (`docker-compose`, scripts) | Low, removing dead code |
| 10 | Phase 6 | Documentation updates | None |

---

## Verification

1. Install LanceDB

```sh
pip install lancedb>=0.6.0
```

2. Run new vector store tests

```sh
cd workspace && pytest tests/test_vector_store.py -v
```

3. Run memory engine tests

```sh
cd workspace && pytest tests/test_memory_engine.py -v
```

4. Run full test suite

```sh
cd workspace && pytest tests/ -v
```

5. Run data migration (dry-run first)

```sh
cd workspace && python scripts/migrate_to_lancedb.py --dry-run
cd workspace && python scripts/migrate_to_lancedb.py
```

6. Smoke test: start gateway without Docker/Qdrant

```sh
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload
```

Post to `/chat/the_creator` and verify memory retrieval works.

7. Verify no active Qdrant references remain

```sh
grep -r "qdrant" workspace/sci_fi_dashboard/ --include="*.py" | grep -v "_archived" | grep -v "# DEPRECATED"
grep -r "6333" workspace/ --include="*.py"
grep -r "QdrantVectorStore" workspace/ --include="*.py" | grep -v "_archived" | grep -v "v2_migration"
```

---

## Future: Phase 7 - Unify Retrieval Paths (separate PR)

Not in this PR. Currently two parallel retrieval paths exist:

- `memory_engine.py::query()` -> LanceDB (after this migration)
- `retriever.py::query_memories()` -> `sqlite-vec`

LanceDB's native hybrid search (`BM25 + vector + RRF` via `create_fts_index()` + `query_type="hybrid"`) could eventually replace both, eliminating the `sqlite-vec` dual-write. Keep dual-write as fallback safety for now.
