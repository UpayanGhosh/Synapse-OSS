from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext
from sci_fi_dashboard.personal_memory_service import PersonalMemoryService
from sci_fi_dashboard.tool_registry import ToolContext, _query_memory_factory


@pytest.fixture
def store() -> PersonalMemoryStore:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "memory-retrieval" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return PersonalMemoryStore(root / "memory.db")


def _capture(
    store: PersonalMemoryStore,
    context: PersonMemoryContext,
    message_id: str,
    content: str,
    minute: int,
) -> str:
    episode_id = store.capture_episode(
        context,
        source_message_id=message_id,
        content=content,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC) + timedelta(minutes=minute),
    )
    assert episode_id is not None
    return episode_id


def test_lexical_recall_excludes_only_active_question_and_finds_old_lunch_source(
    store: PersonalMemoryStore,
) -> None:
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    old = _capture(
        store, bob, "bob-lunch",
        "A pigeon stole my lunch sandwich from the balcony today. I called it our CFO; keep that as my joke.",
        0,
    )
    for minute in range(1, 18):
        _capture(store, bob, f"irrelevant-{minute}", f"The weather is clear on day {minute}.", minute)
    active = _capture(
        store, bob, "bob-current-question",
        "Search your memory for my lunch incident. What got taken?", 18,
    )

    results = store.recall(
        bob, "lunch incident what got taken", limit=1, exclude_episode_id=active,
    )

    assert [row.episode_id for row in results] == [old]
    service_results = asyncio.run(
        PersonalMemoryService(store).recall(
            bob, "lunch incident what got taken", limit=1, exclude_episode_id=active,
        )
    )
    assert [row.episode_id for row in service_results] == [old]


def test_exclusion_keeps_same_text_historical_source(store: PersonalMemoryStore) -> None:
    alice = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    old = _capture(store, alice, "older", "Our tiny red umbrella is the meeting mascot.", 0)
    active = _capture(store, alice, "active", "Our tiny red umbrella is the meeting mascot.", 1)

    rows = store.recall(alice, "tiny red umbrella meeting mascot", exclude_episode_id=active)

    assert [row.episode_id for row in rows] == [old]


def test_one_term_fallback_needs_specific_anchor_and_yields_to_strong_hit(
    store: PersonalMemoryStore,
) -> None:
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    weak = _capture(store, bob, "weak", "A pigeon stole my lunch sandwich.", 0)
    assert store.recall(bob, "lunch incident what got taken", limit=1)[0].episode_id == weak

    strong = _capture(store, bob, "strong", "The lunch incident involved a spilled drink.", 1)
    assert [row.episode_id for row in store.recall(bob, "lunch incident what got taken", limit=1)] == [strong]
    assert [row.episode_id for row in store.recall(bob, "lunch incident what got taken", limit=2)] == [strong, weak]

    assert store.recall(bob, "scarlet parasol mascot") == []


def test_historical_question_keeps_one_free_slot_for_old_lunch_source(
    store: PersonalMemoryStore,
) -> None:
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    source = _capture(
        store, bob, "254903-lunch-source",
        "A pigeon stole my lunch sandwich from the balcony.", 0,
    )
    _capture(
        store, bob, "another-lunch-mention",
        "I mentioned lunch during a long planning conversation with several unrelated agenda items and a scheduling update.",
        1,
    )
    question = _capture(
        store, bob, "f839-historical-question",
        "Earlier lunch incident: what was taken?", 2,
    )
    active = _capture(
        store, bob, "active-question",
        "Earlier lunch incident what was taken", 3,
    )

    rows = store.recall(
        bob, "earlier lunch incident what was taken", limit=5,
        exclude_episode_id=active,
    )

    assert [row.episode_id for row in rows] == [question, source]


def test_generic_only_overlap_is_not_a_weak_recall_anchor(store: PersonalMemoryStore) -> None:
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    _capture(store, bob, "generic-incident", "The incident report was filed at work.", 0)

    assert store.recall(bob, "lunch incident what got taken") == []


def test_native_query_memory_excludes_active_and_keeps_owner_scope(
    store: PersonalMemoryStore,
) -> None:
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    alice = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    old = _capture(store, bob, "bob-old", "A pigeon stole my lunch sandwich.", 0)
    _capture(store, alice, "alice-secret", "Alice's lunch incident involved SECRET-A-900.", 0)
    active = _capture(
        store, bob, "bob-active", "Search memory for my lunch incident. What got taken?", 1,
    )
    tool_context = ToolContext(
        chat_id="bob-session", sender_id="bob", sender_is_owner=False,
        workspace_dir=".", config={}, person_context=bob,
        personal_memory_store=store, exclude_episode_id=active,
    )

    result = asyncio.run(
        _query_memory_factory(None)(tool_context).execute(
            {"query": "lunch incident what got taken", "limit": 1,
             "exclude_episode_id": old}
        )
    )

    assert [row["episode_id"] for row in json.loads(result.content)] == [old]
    assert "SECRET-A-900" not in result.content
