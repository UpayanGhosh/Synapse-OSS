"""
base.py — Abstract VectorStore interface for Synapse-OSS.

All vector backend implementations (LanceDB, future alternatives) must
implement this ABC so memory_engine.py can swap backends without code changes.
"""

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    """Minimal interface required by MemoryEngine."""

    @abstractmethod
    def upsert_facts(self, facts: list[dict]) -> None:
        """Insert or update a batch of facts.

        Each fact dict has the shape:
            {
                "id": int,
                "vector": list[float],
                "metadata": {
                    "text": str,
                    "hemisphere_tag": str,
                    "unix_timestamp": int,
                    "importance": int,
                    "source_id": int,        # optional
                    "entity": str,           # optional
                    "category": str,         # optional
                }
            }
        """

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        query_filter: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[dict]:
        """ANN search returning results in MemoryEngine's expected format.

        Returns a list of dicts:
            [{"id": int, "score": float, "metadata": {...}}, ...]

        score is a similarity score in [0, 1] where 1 = identical.
        query_filter is a SQL-like WHERE clause string (LanceDB syntax).
        """

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the store."""
