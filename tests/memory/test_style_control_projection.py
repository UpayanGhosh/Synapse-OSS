from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard import personal_memory
from sci_fi_dashboard.chat_pipeline import _apply_scoped_relationship_style
from sci_fi_dashboard.personal_memory import (
    PersonalMemoryService,
    PersonalMemoryStore,
    PersonMemoryContext,
)
from sci_fi_dashboard.style_policy import StylePolicy

TEST_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "style-control"


def _root() -> Path:
    path = TEST_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _base_policy() -> StylePolicy:
    return StylePolicy(
        tone="casual_witty", length="normal", scope="session", source="default",
        session_key="alice", reason="default", updated_at=0,
    )


def test_full_phrase_explicit_preferences_project_to_canonical_runtime_style() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    content = "My default voice is straightforward and formal, and I prefer brief replies."
    payload = {
        "relationship_updates": [
            {
                "field": "tone", "value": "straightforward and formal",
                "style_control": "professional_precise", "mode": "explicit", "confidence": 1,
                "evidence": "straightforward and formal",
            },
            {
                "field": "verbosity", "value": "brief replies",
                "style_control": "concise", "mode": "explicit", "confidence": 1,
                "evidence": "brief replies",
            },
        ]
    }
    service = PersonalMemoryService(store, extractor=lambda _observation: payload)
    service.capture_user_turn(
        context, source_message_id="style-natural-phrase", content=content,
        occurred_at=datetime(2026, 9, 25, 9, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    relationship = store.get_relationship(context)
    assert relationship["preferences"]["tone"] == "straightforward and formal"
    assert relationship["preferences"]["verbosity"] == "brief replies"
    assert relationship["runtime_style"] == {"tone": "professional_precise", "verbosity": "concise"}
    policy = _apply_scoped_relationship_style(_base_policy(), "What do you think?", relationship)
    assert (policy.tone, policy.length) == ("professional_precise", "concise")


def test_humor_preference_does_not_become_a_tone_control() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    content = "Please avoid playful jokes."
    payload = {
        "relationship_updates": [{
            "field": "humor", "value": "avoid playful jokes", "mode": "explicit",
            "confidence": 1, "evidence": "avoid playful jokes",
        }]
    }
    service = PersonalMemoryService(store, extractor=lambda _observation: payload)
    service.capture_user_turn(
        context, source_message_id="humor-is-independent", content=content,
        occurred_at=datetime(2026, 9, 25, 10, tzinfo=UTC),
    )

    asyncio.run(service.process_pending_once(limit=1))
    relationship = store.get_relationship(context)
    assert relationship["preferences"]["humor"] == "avoid playful jokes"
    assert relationship["runtime_style"] == {}
    policy = _apply_scoped_relationship_style(_base_policy(), "How was your day?", relationship)
    assert policy.tone == "casual_witty"


def test_reextract_can_fill_a_missing_control_on_the_same_legacy_relationship_row() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    source = store.capture_episode(
        context, source_message_id="legacy-style-row", content="I prefer straightforward and formal replies.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context, {"tone": "straightforward and formal"}, source_episode_id=source,
        evidence="straightforward and formal replies",
    )
    with sqlite3.connect(store.db_path) as conn:
        before = conn.execute(
            "SELECT id,value,evidence,occurred_at,recorded_at,style_control "
            "FROM personal_relationship_updates WHERE source_episode_id=?",
            (source,),
        ).fetchone()
    store.apply_relationship_update(
        context,
        {"tone": {"value": "straightforward and formal", "style_control": "professional_precise"}},
        source_episode_id=source,
        evidence="straightforward and formal replies",
    )

    assert store.get_relationship(context)["runtime_style"] == {"tone": "professional_precise"}
    with sqlite3.connect(store.db_path) as conn:
        after = conn.execute(
            "SELECT id,value,evidence,occurred_at,recorded_at,style_control "
            "FROM personal_relationship_updates WHERE source_episode_id=?",
            (source,),
        ).fetchone()
    assert after[:5] == before[:5]
    assert after[5] == "professional_precise"


def test_superseded_episode_reextraction_cannot_restore_old_style_control() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    old_source = store.capture_episode(
        context, source_message_id="old-style-no-control", content="I prefer formal replies.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context, {"tone": "formal"}, source_episode_id=old_source, evidence="formal replies",
    )
    new_source = store.capture_episode(
        context, source_message_id="new-style-control", content="Actually, I prefer a relaxed tone.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context,
        {"tone": {"value": "relaxed", "style_control": "casual_witty"}},
        source_episode_id=new_source, evidence="prefer a relaxed tone",
    )
    store.apply_relationship_update(
        context,
        {"tone": {"value": "formal", "style_control": "professional_precise"}},
        source_episode_id=old_source, evidence="formal replies",
    )

    relationship = store.get_relationship(context)
    assert relationship["preferences"]["tone"] == "relaxed"
    assert relationship["runtime_style"] == {"tone": "casual_witty"}


def test_existing_relationship_table_migrates_nullable_control_column() -> None:
    db_path = _root() / "legacy-style.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE personal_relationship_updates (
               id INTEGER PRIMARY KEY AUTOINCREMENT, owner_key TEXT NOT NULL,
               field TEXT NOT NULL, value TEXT NOT NULL, explicit INTEGER NOT NULL,
               confidence REAL, source_episode_id TEXT NOT NULL, evidence TEXT NOT NULL,
               occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
               UNIQUE(owner_key,field,value,explicit,source_episode_id))"""
        )
    store = PersonalMemoryStore(db_path)
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    source = store.capture_episode(
        context, source_message_id="legacy-schema-control", content="I like brief replies.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context,
        {"verbosity": {"value": "brief replies", "style_control": "concise"}},
        source_episode_id=source, evidence="brief replies",
    )

    assert store.get_relationship(context)["runtime_style"] == {"verbosity": "concise"}


def test_inferred_controls_need_distinct_agreeing_sources_even_if_phrases_differ() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    outputs = iter((
        {"relationship_updates": [{
            "field": "tone", "value": "relaxed and warm", "style_control": "casual_witty",
            "mode": "inferred", "confidence": 0.82, "evidence": "I loved that little callback.",
        }]},
        {"relationship_updates": [{
            "field": "tone", "value": "friendly with some wit", "style_control": "casual_witty",
            "mode": "inferred", "confidence": 0.78, "evidence": "That joke made my day.",
        }]},
    ))
    service = PersonalMemoryService(store, extractor=lambda _observation: next(outputs))
    first = datetime(2026, 9, 23, 9, tzinfo=UTC)
    service.capture_user_turn(
        context, source_message_id="inference-one", content="I loved that little callback.",
        occurred_at=first,
    )
    service.capture_user_turn(
        context, source_message_id="inference-two", content="That joke made my day.",
        occurred_at=first + timedelta(days=1),
    )

    assert asyncio.run(service.process_pending_once(limit=2)) == 2
    relationship = store.get_relationship(context)
    assert relationship["runtime_style"] == {"tone": "casual_witty"}
    assert relationship["inferred"]["tone"]["value"] in {
        "relaxed and warm", "friendly with some wit",
    }


def test_supplied_invalid_control_rolls_back_the_whole_extraction_payload() -> None:
    store = PersonalMemoryStore(_root() / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice")
    payload = {
        "relationship_updates": [
            {
                "field": "tone", "value": "formal", "style_control": "professional_precise",
                "mode": "explicit", "confidence": 1, "evidence": "I prefer formal replies.",
            },
            {
                "field": "verbosity", "value": "short", "style_control": "professional_precise",
                "mode": "explicit", "confidence": 1, "evidence": "I prefer formal replies.",
            },
        ]
    }
    service = PersonalMemoryService(store, extractor=lambda _observation: payload)
    service.capture_user_turn(
        context, source_message_id="invalid-style-control", content="I prefer formal replies.",
        occurred_at=datetime(2026, 9, 25, 11, tzinfo=UTC),
    )

    asyncio.run(service.process_pending_once(limit=1))
    relationship = store.get_relationship(context)
    assert relationship["preferences"] == {}
    assert relationship["runtime_style"] == {}


@pytest.mark.parametrize(
    ("field", "control"),
    [
        ("tone", "professional_precise"),
        ("tone", "casual_witty"),
        ("tone", "technical_depth"),
        ("tone", "creative_playful"),
        ("verbosity", "concise"),
        ("verbosity", "normal"),
        ("verbosity", "detailed"),
    ],
)
def test_style_control_validator_accepts_only_field_specific_enums(field: str, control: str) -> None:
    assert personal_memory.validate_style_control(field, control) == control


@pytest.mark.parametrize(
    ("field", "control"),
    [
        ("tone", "concise"),
        ("verbosity", "professional_precise"),
        ("humor", "creative_playful"),
        ("formality", "professional_precise"),
        ("address_as", "casual_witty"),
        ("tone", "professional and friendly"),
        ("verbosity", None),
    ],
)
def test_style_control_validator_rejects_unknown_or_mismatched_enums(field: str, control: object) -> None:
    with pytest.raises(ValueError):
        personal_memory.validate_style_control(field, control)
