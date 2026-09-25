"""Property tests for the bounded, field-specific style control vocabulary."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sci_fi_dashboard.personal_memory import (
    PersonalMemoryService,
    PersonalMemoryStore,
    PersonMemoryContext,
    validate_style_control,
)

TONE_CONTROLS = frozenset(
    {"professional_precise", "casual_witty", "technical_depth", "creative_playful"}
)
VERBOSITY_CONTROLS = frozenset({"concise", "normal", "detailed"})
ALL_STYLE_CONTROLS = TONE_CONTROLS | VERBOSITY_CONTROLS
TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "style-control"
INVALID_STYLE_CONTROLS = st.one_of(
    st.text(max_size=80),
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.lists(st.text(max_size=16), max_size=3),
    st.dictionaries(st.text(max_size=16), st.text(max_size=16), max_size=3),
).filter(lambda value: type(value) is not str or value not in ALL_STYLE_CONTROLS)


def _new_memory_db_path() -> Path:
    test_dir = TEST_DATA_ROOT / uuid4().hex
    test_dir.mkdir(parents=True, exist_ok=False)
    return test_dir / "memory.db"


@settings(max_examples=25, deadline=None)
@given(
    field=st.sampled_from(("tone", "verbosity")),
    control=st.one_of(
        st.text(max_size=80),
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=True, allow_infinity=True),
        st.lists(st.text(max_size=16), max_size=3),
        st.dictionaries(st.text(max_size=16), st.text(max_size=16), max_size=3),
    ),
)
def test_only_field_specific_canonical_controls_are_accepted(field, control):
    allowed = TONE_CONTROLS if field == "tone" else VERBOSITY_CONTROLS
    is_allowed = type(control) is str and control in allowed

    if is_allowed:
        assert validate_style_control(field, control) == control
    else:
        with pytest.raises(ValueError):
            validate_style_control(field, control)


@pytest.mark.parametrize(
    ("field", "controls", "other_field"),
    [
        ("tone", TONE_CONTROLS, "verbosity"),
        ("verbosity", VERBOSITY_CONTROLS, "tone"),
    ],
)
def test_canonical_controls_round_trip_without_crossing_fields(field, controls, other_field):
    for control in controls:
        assert validate_style_control(field, control) == control
        with pytest.raises(ValueError):
            validate_style_control(other_field, control)


@settings(max_examples=20, deadline=None)
@given(invalid_control=INVALID_STYLE_CONTROLS)
def test_invalid_style_control_rolls_back_earlier_relationship_update(
    invalid_control,
):
    db_path = _new_memory_db_path()
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    evidence = "Keep the conversation warm and straightforward."
    payload = {
        "confirmed_facts": [],
        "relationship_updates": [
            {
                "field": "humor",
                "value": "warm callback humor",
                "mode": "explicit",
                "evidence": evidence,
            },
            {
                "field": "tone",
                "value": "warm and straightforward",
                "style_control": invalid_control,
                "mode": "explicit",
                "evidence": evidence,
            },
        ],
    }
    store = PersonalMemoryStore(db_path)
    service = PersonalMemoryService(store, extractor=lambda _observation: payload)
    episode_id = service.capture_user_turn(
        context,
        source_message_id="style-control-invalid",
        content=evidence,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 0
    assert store.get_relationship(context)["preferences"] == {}
    with sqlite3.connect(db_path) as conn:
        [status] = conn.execute(
            "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    assert status == "pending"


def test_style_projection_preserves_unicode_profile_value_and_source_evidence():
    db_path = _new_memory_db_path()
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    profile_value = "फ़ॉर्मल 🌿—short, but keep warmth"
    evidence = "मेरी बातचीत शैली फ़ॉर्मल 🌿—short, but keep warmth रखें।"
    payload = {
        "confirmed_facts": [],
        "relationship_updates": [
            {
                "field": "tone",
                "value": profile_value,
                "style_control": "professional_precise",
                "mode": "explicit",
                "evidence": evidence,
            }
        ],
    }
    store = PersonalMemoryStore(db_path)
    service = PersonalMemoryService(store, extractor=lambda _observation: payload)
    service.capture_user_turn(
        context,
        source_message_id="style-control-unicode",
        content=evidence,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )

    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    relationship = store.get_relationship(context)
    assert relationship["preferences"]["tone"] == profile_value
    assert relationship["runtime_style"]["tone"] == "professional_precise"
    with sqlite3.connect(db_path) as conn:
        [stored_value, stored_evidence] = conn.execute(
            "SELECT value, evidence FROM personal_relationship_updates "
            "WHERE field='tone' AND explicit=1"
        ).fetchone()
    assert stored_value == profile_value
    assert stored_evidence == evidence
