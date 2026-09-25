from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard import personal_memory
from sci_fi_dashboard.multiuser.session_key import build_session_key

PersonalMemoryStore = personal_memory.PersonalMemoryStore
PersonMemoryContext = personal_memory.PersonMemoryContext
resolve_person_memory_context = personal_memory.resolve_person_memory_context

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "memory-contract"


@pytest.fixture
def memory_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _ctx(person_id: str, conversation_id: str, visibility: str = "private") -> PersonMemoryContext:
    return PersonMemoryContext(
        person_id=person_id,
        conversation_id=conversation_id,
        visibility=visibility,
    )


def _capture(
    store: PersonalMemoryStore,
    context: PersonMemoryContext,
    *,
    source_message_id: str,
    content: str,
    occurred_at: datetime,
) -> str:
    episode_id = store.capture_episode(
        context,
        source_message_id=source_message_id,
        content=content,
        occurred_at=occurred_at,
    )
    assert episode_id
    return episode_id


def _scope_key(base: str, context, *, channel: str, peer: str, kind: str, dm_scope: str):
    resolver = getattr(personal_memory, "scope_conversation_key", None)
    if resolver is not None:
        return resolver(base, context, dm_scope=dm_scope, agent_id="the_creator")
    return build_session_key(
        agent_id="the_creator",
        channel=channel,
        peer_id=peer,
        peer_kind=kind,
        account_id=channel,
        dm_scope=dm_scope,
        main_key=f"{channel}:dm",
        identity_links={},
    )


def test_episode_is_raw_durable_idempotent_and_preserves_event_provenance(memory_root: Path) -> None:
    db_path = memory_root / "memory.db"
    context = _ctx("person:alice", "whatsapp:alice")
    event_time = datetime(2026, 9, 23, 8, 30, tzinfo=UTC)
    recorded_time = datetime(2026, 9, 25, 6, 0, tzinfo=UTC)
    store = PersonalMemoryStore(db_path)

    first_id = store.capture_episode(
        context,
        source_message_id="wa-message-1",
        content="The tiny red umbrella joke still makes Alice laugh.",
        occurred_at="2026-09-23T14:00:00+05:30",
        recorded_at=recorded_time,
    )
    duplicate_id = _capture(
        store,
        context,
        source_message_id="wa-message-1",
        content="The tiny red umbrella joke still makes Alice laugh.",
        occurred_at=event_time,
    )

    assert duplicate_id == first_id

    reopened = PersonalMemoryStore(db_path)
    [episode] = reopened.recall(context, "tiny red umbrella joke", limit=3)
    assert episode.episode_id == first_id
    assert episode.person_id == "person:alice"
    assert episode.conversation_id == "whatsapp:alice"
    assert episode.source_message_id == "wa-message-1"
    assert episode.content == "The tiny red umbrella joke still makes Alice laugh."
    assert datetime.fromisoformat(episode.occurred_at) == event_time
    assert datetime.fromisoformat(episode.recorded_at) == recorded_time
    assert episode.visibility == "private"


def test_episode_timestamp_source_is_durable_and_limited_to_trusted_labels(
    memory_root: Path,
) -> None:
    db_path = memory_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = _ctx("person:alice", "whatsapp:alice")
    occurred_at = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)
    episode_id = store.capture_episode(
        context,
        source_message_id="delayed-message",
        content="Remind me Saturday morning.",
        occurred_at=occurred_at,
        occurred_at_source="received_at",
    )

    reopened = PersonalMemoryStore(db_path)
    [episode] = reopened.recall(context, "Saturday morning reminder", limit=3)
    assert episode.episode_id == episode_id
    assert episode.occurred_at_source == "received_at"
    assert datetime.fromisoformat(episode.occurred_at) == occurred_at

    with pytest.raises(ValueError):
        reopened.capture_episode(
            context,
            source_message_id="untrusted-time-label",
            content="Narrative time is not a verified event timestamp.",
            occurred_at=occurred_at,
            occurred_at_source="model_inference",
        )


def test_same_source_message_cannot_be_replayed_with_conflicting_content(memory_root: Path) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    context = _ctx("person:alice", "telegram:alice")
    _capture(
        store,
        context,
        source_message_id="message-1",
        content="Alice told the tiny red umbrella joke.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        store.capture_episode(
            context,
            source_message_id="message-1",
            content="A different message must not replace the original.",
            occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "occurred_at",
    [datetime(2026, 9, 23, 8, 30), "not-a-timestamp"],
)
def test_capture_rejects_missing_or_invalid_timezone(memory_root: Path, occurred_at) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")

    with pytest.raises((TypeError, ValueError)):
        store.capture_episode(
            _ctx("person:alice", "whatsapp:alice"),
            source_message_id="message-1",
            content="An event with no trustworthy time.",
            occurred_at=occurred_at,
        )


def test_private_episode_and_relationship_are_isolated_between_people(memory_root: Path) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    alice = _ctx("person:alice", "whatsapp:alice")
    bob = _ctx("person:bob", "whatsapp:bob")
    alice_episode = _capture(
        store,
        alice,
        source_message_id="alice-1",
        content="Alice prefers goofy jokes about the tiny red umbrella.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    _capture(
        store,
        bob,
        source_message_id="bob-1",
        content="Bob prefers calm, concise conversations.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    store.apply_relationship_update(
        alice,
        {"humor": "playful"},
        source_episode_id=alice_episode,
        evidence="prefers goofy jokes",
    )

    alice_recall = store.recall(alice, "tiny red umbrella joke", limit=3)
    bob_recall = store.recall(bob, "tiny red umbrella joke", limit=3)
    assert any(item.content.startswith("Alice prefers goofy") for item in alice_recall)
    assert bob_recall == []
    assert store.recall(alice, "the capital city population", limit=3) == []
    assert store.get_relationship(alice)["preferences"] == {"humor": "playful"}
    assert store.get_relationship(bob)["preferences"] == {}


def test_group_context_only_recalls_group_shared_episodes_not_private_person_memory(
    memory_root: Path,
) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    alice_private = _ctx("person:alice", "dm:alice")
    group = _ctx("person:alice", "group:family", visibility="group")
    private_id = _capture(
        store,
        alice_private,
        source_message_id="private-1",
        content="Alice has a private tiny red umbrella joke.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    _capture(
        store,
        group,
        source_message_id="group-1",
        content="The family shared a tiny blue umbrella story.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )

    group_results = store.recall(group, "umbrella story", limit=3)
    assert [item.content for item in group_results] == [
        "The family shared a tiny blue umbrella story."
    ]
    with pytest.raises(ValueError):
        store.apply_relationship_update(
            group,
            {"humor": "playful"},
            source_episode_id=private_id,
            evidence="private tiny red umbrella joke",
        )


def test_relationship_correction_suppresses_stale_active_recall_and_preserves_history(
    memory_root: Path,
) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    context = _ctx("person:alice", "whatsapp:alice")
    first_id = _capture(
        store,
        context,
        source_message_id="style-1",
        content="Keep the tone formal in work conversations.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    second_id = _capture(
        store,
        context,
        source_message_id="style-2",
        content="Correction: use a casual tone with me, even at work.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context,
        {"tone": "formal"},
        source_episode_id=first_id,
        evidence="Keep the tone formal",
    )
    first = store.get_relationship(context)
    store.apply_relationship_update(
        context,
        {"tone": "casual"},
        source_episode_id=second_id,
        evidence="Correction: use a casual tone",
    )
    corrected = store.get_relationship(context)

    assert first["version"] == 1
    assert corrected["version"] == 2
    assert corrected["preferences"]["tone"] == "casual"
    active = store.recall(context, "formal tone correction casual", limit=5)
    assert {item.episode_id for item in active} == {second_id}
    history = store.recall(context, "formal tone correction casual", limit=5, include_history=True)
    historical = {item.episode_id: item for item in history}
    assert set(historical) == {first_id, second_id}
    assert historical[first_id].content == "Keep the tone formal in work conversations."
    assert historical[first_id].status == "superseded"
    assert historical[first_id].superseded_by == second_id
    assert historical[second_id].status == "active"


def test_late_older_relationship_update_cannot_replace_newer_correction(memory_root: Path) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    context = _ctx("person:alice", "whatsapp:alice")
    old_id = _capture(
        store,
        context,
        source_message_id="style-old",
        content="Keep my tone formal.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    new_id = _capture(
        store,
        context,
        source_message_id="style-new",
        content="Correction: keep my tone casual.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )

    store.apply_relationship_update(
        context,
        {"tone": "casual"},
        source_episode_id=new_id,
        evidence="Correction: keep my tone casual",
    )
    store.apply_relationship_update(
        context,
        {"tone": "formal"},
        source_episode_id=old_id,
        evidence="Keep my tone formal",
    )

    relationship = store.get_relationship(context)
    assert relationship["version"] == 1
    assert relationship["preferences"]["tone"] == "casual"


def test_inferred_relationship_requires_repeated_independent_evidence_and_explicit_override(
    memory_root: Path,
) -> None:
    store = PersonalMemoryStore(memory_root / "memory.db")
    context = _ctx("person:alice", "whatsapp:alice")
    episode_one = _capture(
        store,
        context,
        source_message_id="humor-1",
        content="I like playful jokes.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    episode_two = _capture(
        store,
        context,
        source_message_id="humor-2",
        content="That goofy joke made my day.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    playful_update = {"humor": {"value": "playful", "confidence": 0.8}}

    store.apply_inferred_relationship_update(
        context,
        playful_update,
        source_episode_id=episode_one,
        evidence="I like playful jokes",
    )
    assert store.get_relationship(context)["inferred"] == {}

    store.apply_inferred_relationship_update(
        context,
        playful_update,
        source_episode_id=episode_two,
        evidence="goofy joke made my day",
    )
    inferred = store.get_relationship(context)["inferred"]["humor"]
    assert inferred["value"] == "playful"
    assert inferred["confidence"] >= 0.7
    assert set(inferred["source_episode_ids"]) == {episode_one, episode_two}

    contradictory_episode = _capture(
        store,
        context,
        source_message_id="humor-3",
        content="I prefer a formal tone for one presentation.",
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    store.apply_inferred_relationship_update(
        context,
        {"humor": {"value": "formal", "confidence": 0.95}},
        source_episode_id=contradictory_episode,
        evidence="prefer a formal tone",
    )
    assert store.get_relationship(context)["inferred"]["humor"]["value"] == "playful"

    store.apply_relationship_update(
        context,
        {"humor": "formal"},
        source_episode_id=contradictory_episode,
        evidence="prefer a formal tone",
    )
    assert store.get_relationship(context)["preferences"]["humor"] == "formal"


def test_legacy_unowned_personal_document_is_not_adopted_or_recalled(memory_root: Path) -> None:
    db_path = memory_root / "memory.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE documents (id INTEGER PRIMARY KEY, filename TEXT, content TEXT)"
        )
        conn.execute(
            "INSERT INTO documents(filename, content) VALUES (?, ?)",
            ("relationship_memory", "The old profile mentions the tiny red umbrella joke."),
        )

    store = PersonalMemoryStore(db_path)
    assert store.recall(_ctx("person:alice", "whatsapp:alice"), "tiny red umbrella", limit=3) == []


def test_person_resolver_fails_closed_for_ambiguous_channel_identity_and_untrusted_api() -> None:
    assert (
        resolve_person_memory_context(
            channel_id="whatsapp",
            peer_id=None,
            conversation_id="conversation-1",
            chat_type="direct",
        )
        is None
    )
    assert (
        resolve_person_memory_context(
            channel_id=None,
            peer_id=None,
            conversation_id="session-from-request-body",
            origin="api",
            api_authenticated=False,
        )
        is None
    )
    api_context = resolve_person_memory_context(
        channel_id="untrusted-channel",
        peer_id="attacker-supplied-peer",
        conversation_id="session-from-request-body",
        origin="api",
        api_authenticated=True,
    )
    assert api_context is not None
    assert api_context.person_id == "local-api-owner"
    assert api_context.visibility == "private"


def test_group_resolver_marks_group_context_instead_of_person_private_context() -> None:
    group_context = resolve_person_memory_context(
        channel_id="whatsapp",
        peer_id="family-room",
        conversation_id="family-room",
        chat_type="group",
    )

    assert group_context is not None
    assert group_context.person_id is None
    assert group_context.conversation_id == "family-room"
    assert group_context.visibility == "group"


def test_channel_person_identity_is_stable_and_independent_of_persona_session() -> None:
    alice_whatsapp = resolve_person_memory_context(
        channel_id="whatsapp",
        peer_id="alice-phone",
        conversation_id="agent-a:whatsapp:alice-phone",
    )
    alice_whatsapp_again = resolve_person_memory_context(
        channel_id="whatsapp",
        peer_id="alice-phone",
        conversation_id="agent-b:whatsapp:alice-phone",
    )
    same_label_other_channel = resolve_person_memory_context(
        channel_id="telegram",
        peer_id="alice-phone",
        conversation_id="agent-a:telegram:alice-phone",
    )

    assert alice_whatsapp is not None
    assert alice_whatsapp_again is not None
    assert same_label_other_channel is not None
    assert alice_whatsapp.person_id == alice_whatsapp_again.person_id
    assert alice_whatsapp.person_id != same_label_other_channel.person_id


def test_person_scoped_conversation_key_splits_main_scope_without_merging_sessions(
) -> None:
    person_a = _ctx("person:alice", "whatsapp:alice")
    person_b = _ctx("person:bob", "whatsapp:bob")

    alice_whatsapp = _scope_key(
        "agent:creator:whatsapp:dm:alice",
        person_a,
        channel="whatsapp",
        peer="alice",
        kind="direct",
        dm_scope="main",
    )
    bob_telegram = _scope_key(
        "agent:the_creator:whatsapp:dm:bob",
        person_b,
        channel="whatsapp",
        peer="bob",
        kind="direct",
        dm_scope="main",
    )
    alice_same_session = _scope_key(
        "agent:the_creator:whatsapp:dm:alice",
        person_a,
        channel="whatsapp",
        peer="alice",
        kind="direct",
        dm_scope="main",
    )

    assert alice_whatsapp != bob_telegram
    assert alice_whatsapp == alice_same_session


def test_group_and_unverified_conversations_never_share_main_private_history() -> None:
    family_a = _scope_key(
        "agent:the_creator:whatsapp:group:family-a",
        _ctx("person:alice", "family-a", visibility="group"),
        channel="whatsapp",
        peer="family-a",
        kind="group",
        dm_scope="main",
    )
    family_b = _scope_key(
        "agent:the_creator:whatsapp:group:family-b",
        _ctx("person:bob", "family-b", visibility="group"),
        channel="whatsapp",
        peer="family-b",
        kind="group",
        dm_scope="main",
    )
    anonymous_a = _scope_key(
        "agent:the_creator:whatsapp:dm:alice",
        None,
        channel="whatsapp",
        peer="alice",
        kind="direct",
        dm_scope="main",
    )
    anonymous_b = _scope_key(
        "agent:the_creator:whatsapp:dm:alice",
        None,
        channel="whatsapp",
        peer="alice",
        kind="direct",
        dm_scope="main",
    )

    assert family_a == "agent:the_creator:whatsapp:group:family-a"
    assert family_b == "agent:the_creator:whatsapp:group:family-b"
    assert family_a != family_b
    assert anonymous_a != "agent:the_creator:whatsapp:dm:alice"
    assert anonymous_b != "agent:the_creator:whatsapp:dm:alice"
    assert anonymous_a != anonymous_b
