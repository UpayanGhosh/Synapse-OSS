"""
lancedb_store.py — LanceDB-backed VectorStore for Synapse-OSS.

Embedded, pip-installable vector DB for Synapse-OSS.
Zero Docker dependency — data lives at ~/.synapse/workspace/db/lancedb/.

Design notes:
- External embeddings: receives pre-computed float[768] vectors from MemoryEngine.
- Idempotent upsert via merge_insert on "id" column.
- IVF_PQ index deferred until >= 256 rows (brute-force is faster below that).
- Score conversion: LanceDB returns cosine distance (0=identical),
  converted to similarity score (1=identical).
- prefilter=True on hemisphere filter cuts search space ~50% before ANN.
"""

import logging
from pathlib import Path

import pyarrow as pa

from sci_fi_dashboard.vector_store.base import VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "memories"
_INDEX_THRESHOLD = 256  # rows required before building IVF_PQ index


def _default_db_path() -> Path:
    """Return ~/.synapse/workspace/db/lancedb/ as the default LanceDB location."""
    try:
        from synapse_config import SynapseConfig

        return SynapseConfig.load().db_dir / "lancedb"
    except Exception:
        return Path.home() / ".synapse" / "workspace" / "db" / "lancedb"


def _build_schema(embedding_dimensions: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64()),
            pa.field("vector", pa.list_(pa.float32(), embedding_dimensions)),
            pa.field("text", pa.utf8()),
            pa.field("hemisphere_tag", pa.utf8()),
            pa.field("unix_timestamp", pa.int64()),
            pa.field("importance", pa.int64()),
            pa.field("source_id", pa.int64()),
            pa.field("entity", pa.utf8()),
            pa.field("category", pa.utf8()),
        ]
    )


class LanceDBVectorStore(VectorStore):
    """Embedded LanceDB vector store for Synapse-OSS."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        table_name: str = _DEFAULT_TABLE,
        embedding_dimensions: int = 768,
    ) -> None:
        import lancedb

        self._embedding_dimensions = embedding_dimensions
        self._table_name = table_name
        self._schema = _build_schema(embedding_dimensions)

        resolved_path = Path(db_path) if db_path else _default_db_path()
        resolved_path.mkdir(parents=True, exist_ok=True)

        self._db = lancedb.connect(str(resolved_path))
        self.table = self._open_or_create_table()
        logger.info("[OK] LanceDBVectorStore connected at %s (table=%s)", resolved_path, table_name)

    def _open_or_create_table(self):
        """Open existing table or create with schema. Never overwrites existing data."""
        existing = self._db.table_names()
        if self._table_name in existing:
            return self._db.open_table(self._table_name)
        return self._db.create_table(self._table_name, schema=self._schema)

    def _ensure_index(self) -> None:
        """Build IVF_PQ + scalar + FTS indexes once enough rows exist.

        Called lazily after upserts. Safe to call repeatedly — LanceDB skips
        if index already up-to-date.
        """
        try:
            num_rows = self.table.count_rows()
            if num_rows < _INDEX_THRESHOLD:
                return

            num_partitions = max(1, num_rows // 4096)
            self.table.create_index(
                metric="cosine",
                num_partitions=num_partitions,
                replace=True,
            )
            self.table.create_scalar_index("hemisphere_tag")
            self.table.create_fts_index("text", replace=True)
        except Exception as e:
            logger.warning("[WARN] LanceDB index creation failed (non-fatal): %s", e)

    def upsert_facts(self, facts: list[dict]) -> None:
        """Idempotent batch upsert. Same id overwrites, never duplicates."""
        if not facts:
            return

        rows = []
        for f in facts:
            meta = f.get("metadata", {})
            rows.append(
                {
                    "id": int(f["id"]),
                    "vector": [float(x) for x in f["vector"]],
                    "text": str(meta.get("text", "")),
                    "hemisphere_tag": str(meta.get("hemisphere_tag", "safe")),
                    "unix_timestamp": int(meta.get("unix_timestamp", 0)),
                    "importance": int(meta.get("importance", 5)),
                    "source_id": int(meta.get("source_id", 0)),
                    "entity": str(meta.get("entity", "")),
                    "category": str(meta.get("category", "")),
                }
            )

        (
            self.table.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(rows)
        )
        self._ensure_index()

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        query_filter: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        """Cosine ANN search. Returns similarity scores (1=identical, 0=orthogonal).

        IMPORTANT: LanceDB returns cosine distance (0=identical).
        We convert: score = 1 - distance, so higher score = more similar.
        """
        try:
            searcher = self.table.search(query_vector).metric("cosine").limit(limit)
            if query_filter:
                searcher = searcher.where(query_filter, prefilter=True)

            results = searcher.to_list()
        except Exception as e:
            logger.warning("[WARN] LanceDB search failed: %s", e)
            return []

        output = []
        for r in results:
            score = 1.0 - float(r.get("_distance", 1.0))
            if score < score_threshold:
                continue
            output.append(
                {
                    "id": r["id"],
                    "score": score,
                    "metadata": {
                        "text": r.get("text", ""),
                        "hemisphere_tag": r.get("hemisphere_tag", "safe"),
                        "unix_timestamp": r.get("unix_timestamp", 0),
                        "importance": r.get("importance", 5),
                        "source_id": r.get("source_id", 0),
                        "entity": r.get("entity", ""),
                        "category": r.get("category", ""),
                    },
                }
            )
        return output

    def delete_by_id(self, doc_id: int) -> bool:
        """Delete the row with matching id. Returns True on success."""
        try:
            self.table.delete(f"id = {int(doc_id)}")
            return True
        except Exception as e:
            logger.warning("[WARN] LanceDB delete_by_id failed for %s: %s", doc_id, e)
            return False

    def close(self) -> None:
        """No-op — LanceDB is embedded and manages its own lifecycle."""
