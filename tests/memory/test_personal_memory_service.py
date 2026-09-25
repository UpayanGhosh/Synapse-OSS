from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.personal_memory import (
    PersonalMemoryService,
    PersonalMemoryStore,
    PersonMemoryContext,
)
from sci_fi_dashboard.user_memory import UserMemoryFact, upsert_user_memory_facts

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "memory-service"


@pytest.fixture
def service_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_user_turn_capture_survives_extraction_failure_and_service_restart(
    service_root: Path,
) -> None:
    db_path = service_root / "memory.db"
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    extractor_calls = 0

    def broken_extractor(*_args, **_kwargs):
        nonlocal extractor_calls
        extractor_calls += 1
        raise RuntimeError("synthetic extractor outage")

    first_service = PersonalMemoryService(
        PersonalMemoryStore(db_path),
        extractor=broken_extractor,
    )
    episode_id = first_service.capture_user_turn(
        context,
        source_message_id="wa-msg-inside-joke-1",
        content="Our tiny red umbrella has become the official meeting mascot.",
        occurred_at=datetime(2026, 9, 23, 8, 30, tzinfo=UTC),
    )
    duplicate_id = first_service.capture_user_turn(
        context,
        source_message_id="wa-msg-inside-joke-1",
        content="Our tiny red umbrella has become the official meeting mascot.",
        occurred_at=datetime(2026, 9, 23, 8, 30, tzinfo=UTC),
    )

    assert episode_id == duplicate_id
    asyncio.run(first_service.process_pending_once(limit=8))
    assert extractor_calls == 1, "duplicate capture must not enqueue duplicate extraction work"

    restarted = PersonalMemoryService(PersonalMemoryStore(db_path), extractor=broken_extractor)
    [recalled] = restarted.store.recall(
        context,
        "tiny red umbrella meeting mascot",
        limit=3,
    )
    assert recalled.episode_id == episode_id
    assert recalled.content == "Our tiny red umbrella has become the official meeting mascot."
    assert recalled.source_message_id == "wa-msg-inside-joke-1"


def test_missing_identity_is_a_noop_for_personal_capture(service_root: Path) -> None:
    store = PersonalMemoryStore(service_root / "memory.db")
    service = PersonalMemoryService(store)

    result = service.capture_user_turn(
        None,
        source_message_id="unverified-api-message",
        content="Do not persist this in another person's profile.",
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert result is None


def test_explicit_natural_preference_payload_from_luna_is_projected(service_root: Path) -> None:
    """The extractor's explicit classification should not require magic wording."""
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    user_turn = (
        "My default vibe: relaxed, a little playful, and pretty brief. "
        "I like a goofy callback now and then."
    )
    luna_payload = {
        "confirmed_facts": [],
        "relationship_updates": [
            {
                "field": "tone",
                "value": "relaxed and a little playful",
                "mode": "explicit",
                "confidence": 1,
                "evidence": "My default vibe: relaxed, a little playful, and pretty brief.",
            },
            {
                "field": "verbosity",
                "value": "pretty brief",
                "mode": "explicit",
                "confidence": 1,
                "evidence": "My default vibe: relaxed, a little playful, and pretty brief.",
            },
            {
                "field": "humor",
                "value": "Use a goofy callback now and then",
                "mode": "explicit",
                "confidence": 1,
                "evidence": "I like a goofy callback now and then.",
            },
        ],
    }
    service = PersonalMemoryService(store, extractor=lambda _observation: luna_payload)
    service.capture_user_turn(
        context,
        source_message_id="luna-natural-preference-red",
        content=user_turn,
        occurred_at=datetime(2026, 9, 25, 10, 43, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    preferences = store.get_relationship(context)["preferences"]
    assert preferences["tone"] == "relaxed and a little playful"
    assert preferences["verbosity"] == "pretty brief"
    assert preferences["humor"] == "Use a goofy callback now and then"


def test_claimed_personal_observation_recovers_after_service_restart(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    extracted: list[str] = []

    def extractor(observation: dict) -> dict:
        extracted.append(observation["source_episode_id"])
        return {"relationship_updates": []}

    first = PersonalMemoryService(store, extractor=extractor)
    episode_id = first.capture_user_turn(
        context,
        source_message_id="crash-after-claim",
        content="Our tiny red umbrella is still the meeting mascot.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE user_memory_observations SET status='processing', attempt_count=1 "
            "WHERE source_episode_id=?",
            (episode_id,),
        )

    restarted = PersonalMemoryService(PersonalMemoryStore(db_path), extractor=extractor)
    assert asyncio.run(restarted.process_pending_once(limit=8)) == 1
    assert extracted == [episode_id]
    with sqlite3.connect(db_path) as conn:
        [status, attempts] = conn.execute(
            "SELECT status, attempt_count FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    assert (status, attempts) == ("processed", 2)


def test_late_old_preference_extraction_cannot_overwrite_new_correction(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(observation: dict) -> dict:
        if "casual tone" in observation["text"]:
            return {
                "relationship_updates": [
                    {
                        "field": "tone",
                        "value": "casual",
                        "mode": "explicit",
                        "evidence": "Please use a casual tone at work.",
                    }
                ]
            }
        return {
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "formal",
                    "mode": "explicit",
                    "evidence": "Please keep my work tone formal.",
                }
            ]
        }

    service = PersonalMemoryService(PersonalMemoryStore(db_path), extractor=extractor)
    service.capture_user_turn(
        context,
        source_message_id="new-correction",
        content="Please use a casual tone at work.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    assert service.store.get_relationship(context)["preferences"]["tone"] == "casual"

    service.capture_user_turn(
        context,
        source_message_id="late-old-preference",
        content="Please keep my work tone formal.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    assert service.store.get_relationship(context)["preferences"]["tone"] == "casual"


def test_foreign_evidence_retries_then_fails_without_losing_raw_episode(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "formal",
                    "mode": "explicit",
                    "evidence": "Someone else asked for a formal tone.",
                }
            ]
        }

    service = PersonalMemoryService(store, extractor=extractor)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="foreign-evidence",
        content="The red umbrella story made me laugh.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    for expected_attempt in (1, 2, 3):
        assert asyncio.run(service.process_pending_once(limit=1)) == 0
        with sqlite3.connect(db_path) as conn:
            [status, attempts] = conn.execute(
                "SELECT status, attempt_count FROM user_memory_observations WHERE source_episode_id=?",
                (episode_id,),
            ).fetchone()
            if expected_attempt < 3:
                conn.execute(
                    "UPDATE user_memory_observations SET next_attempt_at='2000-01-01T00:00:00+00:00' "
                    "WHERE source_episode_id=?",
                    (episode_id,),
                )
        assert attempts == expected_attempt
        assert status == ("failed" if expected_attempt == 3 else "pending")
        assert store.get_relationship(context)["preferences"] == {}

    [raw] = store.recall(context, "red umbrella story", limit=3)
    assert raw.episode_id == episode_id


def test_invalid_update_rejects_entire_extractor_payload_atomically(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "friendly",
                    "mode": "explicit",
                    "evidence": "Please use a friendly tone.",
                },
                {
                    "field": "humor",
                    "value": "sarcastic",
                    "mode": "explicit",
                    "evidence": "A different user asked for sarcasm.",
                },
            ]
        }

    service = PersonalMemoryService(store, extractor=extractor)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="partially-invalid-payload",
        content="Please use a friendly tone. The umbrella story was funny.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 0
    assert store.get_relationship(context)["preferences"] == {}
    with sqlite3.connect(db_path) as conn:
        [status] = conn.execute(
            "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    assert status == "pending"


def test_fact_corrections_preserve_pure_and_mixed_history_and_assistant_echoes(
    service_root: Path,
) -> None:
    store = PersonalMemoryStore(service_root / "memory.db")
    alice = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    bob = PersonMemoryContext("person:bob", "whatsapp:bob", "private")
    occurrences: dict[str, datetime] = {}
    fact_sources = {
        "Please keep my work tone formal.": ("formal", "Please keep my work tone formal."),
        "Please use a casual tone at work.": ("casual", "Please use a casual tone at work."),
        "Please keep my work tone precise.": ("precise", "Please keep my work tone precise."),
        "Please keep my work tone formal. Our red umbrella is the team's mascot.": (
            "formal",
            "Please keep my work tone formal.",
        ),
    }

    def extractor(observation: dict) -> dict:
        value, evidence = fact_sources[observation["text"]]
        return {
            "confirmed_facts": [{
                "kind": "preference", "key": "work_tone", "value": value,
                "summary": f"Prefers a {value} tone at work.", "confidence": 0.95,
                "evidence": evidence,
            }],
            "relationship_updates": [],
        }

    service = PersonalMemoryService(store, extractor=extractor)

    def capture(context: PersonMemoryContext, source_id: str, content: str, day: int) -> str:
        occurred_at = datetime(2026, 9, day, tzinfo=UTC)
        occurrences[source_id] = occurred_at
        episode_id = service.capture_user_turn(
            context, source_message_id=source_id, content=content, occurred_at=occurred_at
        )
        assert episode_id is not None
        return episode_id

    def extract_next() -> None:
        assert asyncio.run(service.process_pending_once(limit=1)) == 1

    alice_old = capture(alice, "alice-formal", "Please keep my work tone formal.", 20)
    extract_next()
    store.record_assistant_reply(
        alice, source_episode_id=alice_old, source_message_id="alice-formal-echo",
        content="Got it, I'll keep your work tone formal.",
        occurred_at=occurrences["alice-formal"], delivery_state="accepted",
    )
    capture(alice, "alice-casual", "Please use a casual tone at work.", 22)
    extract_next()
    alice_latest = capture(alice, "alice-precise", "Please keep my work tone precise.", 24)
    extract_next()
    assert service.capture_user_turn(
        alice, source_message_id="alice-precise",
        content="Please keep my work tone precise.",
        occurred_at=occurrences["alice-precise"],
    ) == alice_latest

    alice_history = store.recall(alice, "work tone formal", limit=10, include_history=True)
    old_episode = next(row for row in alice_history if row.episode_id == alice_old)
    echo = next(row for row in alice_history if row.source_message_id == "alice-formal-echo")
    assert old_episode.status == "superseded"
    assert echo.status == "superseded"
    assert old_episode.corrections == ({
        "kind": "preference", "key": "work_tone",
        "obsolete_evidence": "Please keep my work tone formal.",
        "current_value": "precise", "current_source_episode_id": alice_latest,
        "current_occurred_at": occurrences["alice-precise"].isoformat(),
    },)
    assert echo.corrections == old_episode.corrections
    assert len(old_episode.corrections) == 1
    assert alice_old not in {
        row.episode_id for row in store.recall(alice, "work tone formal", limit=10)
    }

    mixed_content = "Please keep my work tone formal. Our red umbrella is the team's mascot."
    bob_old = capture(bob, "bob-mixed", mixed_content, 20)
    extract_next()
    store.record_assistant_reply(
        bob, source_episode_id=bob_old, source_message_id="bob-mixed-echo",
        content="I remember the red umbrella mascot and your formal work tone.",
        occurred_at=occurrences["bob-mixed"], delivery_state="accepted",
    )
    bob_latest = capture(bob, "bob-casual", "Please use a casual tone at work.", 22)
    extract_next()

    bob_history = store.recall(bob, "red umbrella mascot formal tone", limit=10, include_history=True)
    mixed_episode = next(row for row in bob_history if row.episode_id == bob_old)
    mixed_echo = next(row for row in bob_history if row.source_message_id == "bob-mixed-echo")
    expected_note = ({
        "kind": "preference", "key": "work_tone",
        "obsolete_evidence": "Please keep my work tone formal.",
        "current_value": "casual", "current_source_episode_id": bob_latest,
        "current_occurred_at": occurrences["bob-casual"].isoformat(),
    },)
    assert mixed_episode.status == "active"
    assert "red umbrella is the team's mascot" in mixed_episode.content
    assert mixed_episode.corrections == expected_note
    assert mixed_echo.status == "active"
    assert mixed_echo.corrections == expected_note


def test_database_failure_rolls_back_prior_updates_in_same_payload(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "friendly",
                    "mode": "explicit",
                    "evidence": "Please use a friendly tone.",
                },
                {
                    "field": "humor",
                    "value": "playful",
                    "mode": "explicit",
                    "evidence": "Please keep jokes playful.",
                },
            ]
        }

    service = PersonalMemoryService(store, extractor=extractor)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="storage-fails-second-projection",
        content="Please use a friendly tone. Please keep jokes playful.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TRIGGER fail_second_relationship_update
               BEFORE INSERT ON personal_relationship_updates
               WHEN NEW.field='humor'
               BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"""
        )

    assert asyncio.run(service.process_pending_once(limit=1)) == 0
    assert store.get_relationship(context)["preferences"] == {}
    with sqlite3.connect(db_path) as conn:
        [status] = conn.execute(
            "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    assert status == "pending"


def test_confirmed_fact_is_linked_to_same_owner_source_episode(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "reply_style",
                    "value": "concise",
                    "summary": "Alice prefers concise replies.",
                    "confidence": 0.94,
                    "evidence": "Please keep replies concise.",
                }
            ],
            "relationship_updates": [],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="fact-source-episode",
        content="Please keep replies concise.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row[1] for row in conn.execute("PRAGMA table_info(user_memory_facts)")}
        assert "source_episode_id" in columns
        row = conn.execute(
            "SELECT user_id,kind,key,value,source_episode_id,evidence,status "
            "FROM user_memory_facts WHERE user_id=? AND kind=? AND key=?",
            ("person:alice", "preference", "reply_style"),
        ).fetchone()
    assert row is not None
    assert tuple(row) == (
        "person:alice", "preference", "reply_style", "concise", episode_id,
        "Please keep replies concise.", "active",
    )


def test_mixed_fact_and_relationship_payload_is_atomic_when_fact_evidence_is_foreign(
    service_root: Path,
) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "reply_style",
                    "value": "concise",
                    "summary": "Alice prefers concise replies.",
                    "confidence": 0.94,
                    "evidence": "Please keep replies concise.",
                },
                {
                    "kind": "relationship",
                    "key": "another_person",
                    "value": "Bob prefers formal replies.",
                    "summary": "Bob prefers formal replies.",
                    "confidence": 0.94,
                    "evidence": "Bob asked for formal replies.",
                },
            ],
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "friendly",
                    "mode": "explicit",
                    "evidence": "Please keep replies concise.",
                }
            ],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    service.capture_user_turn(
        context,
        source_message_id="mixed-payload-invalid-fact",
        content="Please keep replies concise.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 0
    assert store.get_relationship(context)["preferences"] == {}
    with sqlite3.connect(db_path) as conn:
        [fact_count] = conn.execute(
            "SELECT COUNT(*) FROM user_memory_facts WHERE user_id=?",
            ("person:alice",),
        ).fetchone()
    assert fact_count == 0


def test_late_old_confirmed_fact_cannot_overwrite_newer_correction(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(observation: dict) -> dict:
        if "brief" in observation["text"]:
            value, evidence = "concise", "Please keep my replies brief."
        else:
            value, evidence = "detailed", "Please give detailed replies."
        return {
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "reply_style",
                    "value": value,
                    "summary": f"Alice prefers {value} replies.",
                    "confidence": 0.94,
                    "evidence": evidence,
                }
            ],
            "relationship_updates": [],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    new_episode_id = service.capture_user_turn(
        context,
        source_message_id="new-fact-correction",
        content="Please keep my replies brief.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    service.capture_user_turn(
        context,
        source_message_id="late-old-fact",
        content="Please give detailed replies.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value,source_episode_id FROM user_memory_facts "
            "WHERE user_id=? AND kind=? AND key=?",
            ("person:alice", "preference", "reply_style"),
        ).fetchone()
    assert row is not None
    assert row[0] == "concise"
    assert row[1] == new_episode_id


def test_scoped_facts_exclude_legacy_rows_without_episode_provenance(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "current_style",
                    "value": "concise",
                    "summary": "Alice prefers concise replies.",
                    "confidence": 0.94,
                    "evidence": "Please keep replies concise.",
                }
            ],
            "relationship_updates": [],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    source_id = service.capture_user_turn(
        context,
        source_message_id="provenance-backed-fact",
        content="Please keep replies concise.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    with sqlite3.connect(db_path) as conn:
        upsert_user_memory_facts(
            conn,
            [
                UserMemoryFact(
                    user_id="person:alice",
                    kind="preference",
                    key="legacy_style",
                    value="formal",
                    summary="Legacy unowned profile says formal replies.",
                    confidence=0.9,
                    source_doc_id=None,
                    evidence="Please keep replies formal.",
                )
            ],
        )

    facts = store.get_scoped_facts(context)
    assert [fact["key"] for fact in facts] == ["current_style"]
    assert facts[0]["source_episode_id"] == source_id
    assert facts[0]["summary"] == "Alice prefers concise replies."


def test_fact_storage_failure_rolls_back_valid_relationship_projection(service_root: Path) -> None:
    db_path = service_root / "memory.db"
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "relationship_updates": [
                {
                    "field": "tone",
                    "value": "friendly",
                    "mode": "explicit",
                    "evidence": "Please use a friendly tone.",
                }
            ],
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "reply_style",
                    "value": "concise",
                    "summary": "Alice prefers concise replies.",
                    "confidence": 0.94,
                    "evidence": "Please keep replies concise.",
                }
            ],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="fact-storage-failure",
        content="Please use a friendly tone. Please keep replies concise.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TRIGGER fail_confirmed_fact_insert
               BEFORE INSERT ON user_memory_facts
               BEGIN SELECT RAISE(ABORT, 'synthetic fact storage failure'); END"""
        )

    assert asyncio.run(service.process_pending_once(limit=1)) == 0
    assert store.get_relationship(context)["preferences"] == {}
    assert store.get_scoped_facts(context) == []
    with sqlite3.connect(db_path) as conn:
        [status] = conn.execute(
            "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    assert status == "pending"
