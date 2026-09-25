from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.embedding.base import ProviderInfo
from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext
from sci_fi_dashboard.personal_memory_service import PersonalMemoryService

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "memory-embeddings"


@pytest.fixture
def db_path() -> Path:
    directory = TEST_DATA_ROOT / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    return directory / "memory.db"


class FixtureEmbeddingProvider:
    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.query_texts: list[str] = []

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="fixture",
            model="fixture-semantic-v1",
            dimensions=3,
            requires_network=False,
            requires_gpu=False,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_batches.append(list(texts))
        return [[1.0, 0.0, 0.0] if "umbrella" in text else [0.0, 1.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_texts.append(text)
        return [1.0, 0.0, 0.0] if "parasol" in text else [0.0, 1.0, 0.0]


def test_provider_embeddings_recall_paraphrase_scoped_and_survive_restart(db_path: Path) -> None:
    provider = FixtureEmbeddingProvider()
    store = PersonalMemoryStore(db_path)
    alice = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    service = PersonalMemoryService(store, embedding_provider=provider)
    occurred = datetime(2026, 9, 23, tzinfo=UTC)

    alice_id = service.capture_user_turn(
        alice,
        source_message_id="alice-umbrella",
        content="Our tiny red umbrella is the official meeting mascot.",
        occurred_at=occurred,
    )
    service.capture_user_turn(
        bob,
        source_message_id="bob-private",
        content="Bob's private notes about a different topic.",
        occurred_at=occurred,
    )
    asyncio.run(service.process_pending_once(limit=8))

    assert provider.document_batches == [[
        "Our tiny red umbrella is the official meeting mascot.",
        "Bob's private notes about a different topic.",
    ]]
    [remembered] = asyncio.run(service.recall(alice, "scarlet parasol mascot", limit=3))
    assert remembered.episode_id == alice_id
    assert asyncio.run(service.recall(bob, "scarlet parasol mascot", limit=3)) == []

    restarted = PersonalMemoryService(PersonalMemoryStore(db_path), embedding_provider=provider)
    [after_restart] = asyncio.run(restarted.recall(alice, "scarlet parasol mascot", limit=3))
    assert after_restart.episode_id == alice_id
    assert len(provider.document_batches) == 1, "restart should reuse durable embeddings"
    assert provider.query_texts == ["scarlet parasol mascot"] * 3


@pytest.mark.parametrize("bad_vector", [[1.0, 0.0], [math.nan, 0.0, 0.0]])
def test_invalid_embedding_falls_back_to_lexical_memory(db_path: Path, bad_vector) -> None:
    class InvalidProvider(FixtureEmbeddingProvider):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.document_batches.append(list(texts))
            return [bad_vector for _ in texts]

    provider = InvalidProvider()
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    service = PersonalMemoryService(PersonalMemoryStore(db_path), embedding_provider=provider)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="invalid-vector-source",
        content="The tiny red umbrella is our meeting mascot.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    asyncio.run(service.process_pending_once(limit=8))

    [remembered] = asyncio.run(service.recall(context, "tiny red umbrella meeting", limit=3))
    assert remembered.episode_id == episode_id
