from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models


class QdrantVectorStore:
    def __init__(self, host: str = "localhost", port: int = 6333):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = "atomic_facts"
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                print(f"Creating collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=768,  # nomic-embed-text
                        distance=models.Distance.COSINE,
                        on_disk=True,  # Forced on-disk for 8GB M1
                    ),
                    optimizers_config=models.OptimizersConfigDiff(
                        memmap_threshold=10000  # Map to disk early
                    ),
                )
        except Exception as e:
            print(f"Error connecting to Qdrant: {e}")

    def upsert_facts(self, facts: list[dict[str, Any]]):
        """
        facts: List of dicts with {id, vector, metadata}
        """
        points = []
        for fact in facts:
            points.append(
                models.PointStruct(id=fact["id"], vector=fact["vector"], payload=fact["metadata"])
            )

        self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        score_threshold: float = 0.0,
        query_filter=None,
    ) -> list[dict[str, Any]]:
        kwargs = dict(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        if query_filter is not None:
            kwargs["query_filter"] = query_filter
        results = self.client.query_points(**kwargs).points
        return [{"id": r.id, "score": r.score, "metadata": r.payload} for r in results]


if __name__ == "__main__":
    # Test connection
    store = QdrantVectorStore()
    print("Qdrant Store initialized.")
