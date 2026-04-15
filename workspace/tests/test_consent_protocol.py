"""Tests for ConsentProtocol: explain → confirm → execute → snapshot cycle."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from sci_fi_dashboard.consent_protocol import (
    ConsentProtocol,
    ModificationIntent,
    PendingConsent,
    detect_modification_intent,
    is_affirmative,
    is_negative,
)
from sci_fi_dashboard.snapshot_engine import SnapshotEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path):
    """Prepare a tmp data_root with a minimal skills/ subtree."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill = skills_dir / "test-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("name: test-skill\n")
    return tmp_path


@pytest.fixture
def snapshot_engine(data_root):
    return SnapshotEngine(
        data_root=data_root,
        zone2_paths=("skills",),
        max_snapshots=10,
    )


@pytest.fixture
def protocol(snapshot_engine):
    return ConsentProtocol(snapshot_engine=snapshot_engine)


@pytest.fixture
def skill_intent():
    return ModificationIntent(
        description="Create a medication reminder skill",
        change_type="create_skill",
        target_zone2="skills",
    )


# ---------------------------------------------------------------------------
# explain() tests
# ---------------------------------------------------------------------------


def test_explanation_includes_description(protocol, skill_intent):
    msg = protocol.explain(skill_intent)
    assert "medication reminder" in msg


def test_explanation_includes_zone_description(protocol, skill_intent):
    msg = protocol.explain(skill_intent)
    # ZONE_2_DESCRIPTIONS["skills"] = "Skill capabilities (what Synapse can do)"
    assert "Skill capabilities" in msg


def test_explanation_includes_prompt(protocol, skill_intent):
    msg = protocol.explain(skill_intent)
    assert "yes" in msg.lower() or "no" in msg.lower()


# ---------------------------------------------------------------------------
# confirm_and_execute() — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_and_execute_success(protocol, skill_intent):
    executor = AsyncMock(return_value={"created": True})
    result = await protocol.confirm_and_execute(skill_intent, executor)

    assert result["status"] == "success"
    assert result["snapshot_id"]
    assert result["result"] == {"created": True}
    executor.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_and_execute_creates_two_snapshots(protocol, snapshot_engine, skill_intent):
    executor = AsyncMock(return_value=None)
    await protocol.confirm_and_execute(skill_intent, executor)

    snapshots = snapshot_engine.list_snapshots()
    # pre-modification + post-modification
    assert len(snapshots) >= 2


# ---------------------------------------------------------------------------
# confirm_and_execute() — failure / auto-revert path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_revert_on_failure(protocol, skill_intent):
    executor = AsyncMock(side_effect=RuntimeError("disk full"))
    result = await protocol.confirm_and_execute(skill_intent, executor)

    assert result["status"] == "reverted"
    assert "disk full" in result["error"]
    assert result["reverted_to"]


@pytest.mark.asyncio
async def test_auto_revert_snapshot_count(protocol, snapshot_engine, skill_intent):
    """After a failed execute, at least 2 snapshots exist: pre-mod + pre-restore."""
    executor = AsyncMock(side_effect=RuntimeError("broken"))
    await protocol.confirm_and_execute(skill_intent, executor)

    snapshots = snapshot_engine.list_snapshots()
    # pre-modification snapshot + the restore creates another pre-restore snapshot
    assert len(snapshots) >= 2


# ---------------------------------------------------------------------------
# PendingConsent — session scoping and TTL
# ---------------------------------------------------------------------------


def test_consent_session_scoped(skill_intent):
    explanation = "Would you like to proceed?"
    now = time.time()
    pc_a = PendingConsent(
        intent=skill_intent,
        session_id="session-A",
        sender_id="user-1",
        explanation=explanation,
        created_at=now,
    )
    pc_b = PendingConsent(
        intent=skill_intent,
        session_id="session-B",
        sender_id="user-1",
        explanation=explanation,
        created_at=now,
    )
    assert pc_a.session_id != pc_b.session_id
    assert pc_a is not pc_b


def test_pending_consent_not_expired_immediately(skill_intent):
    pc = PendingConsent(
        intent=skill_intent,
        session_id="s",
        sender_id="u",
        explanation="?",
        created_at=time.time(),
        ttl_seconds=300.0,
    )
    assert not pc.is_expired


def test_pending_consent_expires(skill_intent):
    pc = PendingConsent(
        intent=skill_intent,
        session_id="s",
        sender_id="u",
        explanation="?",
        created_at=time.time() - 1.0,  # created 1 second ago
        ttl_seconds=0.1,  # TTL of 0.1s
    )
    assert pc.is_expired


# ---------------------------------------------------------------------------
# detect_modification_intent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_skill_creation():
    intent = await detect_modification_intent("create a skill for tracking weather")
    assert intent is not None
    assert intent.change_type == "create_skill"
    assert intent.target_zone2 == "skills"


@pytest.mark.asyncio
async def test_detect_cron_creation():
    intent = await detect_modification_intent("remind me to take medication at 8am")
    assert intent is not None
    assert intent.change_type == "create_cron"
    assert intent.target_zone2 == "state/agents"


@pytest.mark.asyncio
async def test_detect_normal_message():
    intent = await detect_modification_intent("how's the weather today?")
    assert intent is None


@pytest.mark.asyncio
async def test_detect_case_insensitive():
    intent = await detect_modification_intent("Can you CREATE A SKILL for me?")
    assert intent is not None
    assert intent.change_type == "create_skill"


# ---------------------------------------------------------------------------
# is_affirmative / is_negative
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["yes", "y", "yeah", "yep", "sure", "ok", "okay", "go ahead"])
def test_is_affirmative_yes(text):
    assert is_affirmative(text) is True


@pytest.mark.parametrize("text", ["no", "n", "nah", "nope", "cancel", "stop"])
def test_is_negative_no(text):
    assert is_negative(text) is True


def test_is_affirmative_returns_false_for_no():
    assert is_affirmative("no") is False


def test_is_negative_returns_false_for_yes():
    assert is_negative("yes") is False


def test_is_affirmative_strips_whitespace():
    assert is_affirmative("  yes  ") is True


def test_is_negative_strips_whitespace():
    assert is_negative("  no  ") is True
