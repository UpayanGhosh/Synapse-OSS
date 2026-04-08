"""Integration tests for Phase 2: Safe Self-Modification + Rollback.

Verifies the full system working end-to-end:
- consent → execute → snapshot → rollback cycle
- Zone 1 write rejection (Sentinel)
- Auto-revert on executor failure
- Forward history preservation after rollback
- Self-contained snapshot restore
- Concurrent consent session isolation
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sci_fi_dashboard.snapshot_engine import SnapshotEngine
from sci_fi_dashboard.consent_protocol import (
    ConsentProtocol,
    ModificationIntent,
    PendingConsent,
    detect_modification_intent,
    is_affirmative,
    is_negative,
)
from sci_fi_dashboard.rollback import RollbackResolver
from sci_fi_dashboard.sbs.sentinel.gateway import Sentinel, SentinelError
from sci_fi_dashboard.sbs.sentinel.manifest import ZONE_1_PATHS


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def selfmod_system(tmp_path):
    """Wire together the full self-modification system for integration testing."""
    skills_dir = tmp_path / "skills" / "greeting-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: greeting\ndescription: Says hello\n---\n"
    )

    engine = SnapshotEngine(data_root=tmp_path, zone2_paths=("skills",), max_snapshots=20)
    consent = ConsentProtocol(snapshot_engine=engine)
    rollback = RollbackResolver(snapshot_engine=engine)

    return {
        "engine": engine,
        "consent": consent,
        "rollback": rollback,
        "data_root": tmp_path,
        "skills_dir": tmp_path / "skills",
    }


@pytest.fixture
def skill_intent():
    return ModificationIntent(
        description="Create weather forecast skill",
        change_type="create_skill",
        target_zone2="skills",
    )


# ---------------------------------------------------------------------------
# 1. Full consent → execute → snapshot cycle
# ---------------------------------------------------------------------------


async def test_full_consent_snapshot_cycle(selfmod_system, skill_intent):
    """consent.explain + confirm_and_execute creates snapshots and real files."""
    engine = selfmod_system["engine"]
    consent = selfmod_system["consent"]
    data_root = selfmod_system["data_root"]

    explanation = consent.explain(skill_intent)
    assert "weather forecast" in explanation
    assert "yes" in explanation.lower() or "no" in explanation.lower()

    new_skill_dir = data_root / "skills" / "weather-skill"

    async def executor():
        new_skill_dir.mkdir(parents=True, exist_ok=True)
        (new_skill_dir / "SKILL.md").write_text(
            "---\nname: weather-skill\ndescription: Weather forecasts\n---\n"
        )
        return {"created": True}

    result = await consent.confirm_and_execute(skill_intent, executor)

    assert result["status"] == "success"
    assert result["snapshot_id"]
    assert new_skill_dir.exists()
    assert (new_skill_dir / "SKILL.md").exists()

    snapshots = engine.list_snapshots()
    assert len(snapshots) >= 2  # pre-modification + post-modification


# ---------------------------------------------------------------------------
# 2. Auto-revert on executor failure
# ---------------------------------------------------------------------------


async def test_auto_revert_full_cycle(selfmod_system, skill_intent):
    """When executor raises, ConsentProtocol auto-reverts to pre-snapshot."""
    engine = selfmod_system["engine"]
    consent = selfmod_system["consent"]
    data_root = selfmod_system["data_root"]

    failing_dir = data_root / "skills" / "broken-skill"

    async def failing_executor():
        failing_dir.mkdir(parents=True, exist_ok=True)
        raise RuntimeError("disk full simulation")

    result = await consent.confirm_and_execute(skill_intent, failing_executor)

    assert result["status"] == "reverted"
    assert "disk full" in result["error"]
    assert result["reverted_to"]

    # Pre-snapshot was created and is listed
    snapshots = engine.list_snapshots()
    assert len(snapshots) >= 1
    assert any(s.id == result["reverted_to"] for s in snapshots)


# ---------------------------------------------------------------------------
# 3. Full consent → rollback cycle
# ---------------------------------------------------------------------------


async def test_consent_then_rollback_removes_skill(selfmod_system, skill_intent):
    """Execute a skill creation, then roll back to the pre-modification snapshot to undo it."""
    engine = selfmod_system["engine"]
    consent = selfmod_system["consent"]
    rollback = selfmod_system["rollback"]
    data_root = selfmod_system["data_root"]

    new_skill = data_root / "skills" / "new-skill"

    async def executor():
        new_skill.mkdir(parents=True, exist_ok=True)
        (new_skill / "SKILL.md").write_text("---\nname: new-skill\n---\n")
        return {"created": True}

    result = await consent.confirm_and_execute(skill_intent, executor)
    assert result["status"] == "success"
    assert new_skill.exists()

    # Find the pre-modification snapshot (captured BEFORE the change was applied)
    snapshots = engine.list_snapshots()
    pre_mod = next(s for s in snapshots if s.change_type == "pre_modification")

    # Explicitly restore to the pre-modification state — this is the real "undo"
    rb_result = rollback.resolve_by_id(pre_mod.id)
    assert rb_result.restored_snapshot.id == pre_mod.id
    assert rb_result.pre_restore_snapshot is not None  # forward history preserved (MOD-06)

    # After restoring to pre-modification state, the new skill is gone
    assert not new_skill.exists()


# ---------------------------------------------------------------------------
# 4. Zone 1 write rejection by Sentinel (MOD-07)
# ---------------------------------------------------------------------------


def test_zone1_write_rejected_by_sentinel(tmp_path):
    """Sentinel.check_access raises SentinelError for every Zone 1 write attempt."""
    sentinel = Sentinel(project_root=tmp_path)

    # Create a representative Zone 1 file so path resolution works
    (tmp_path / "api_gateway.py").write_text("# zone 1")
    (tmp_path / "main.py").write_text("# zone 1")

    for zone1_path in ("api_gateway.py", "main.py"):
        with pytest.raises(SentinelError):
            sentinel.check_access(zone1_path, "write")


def test_zone1_sentinel_directory_write_rejected(tmp_path):
    """Sentinel blocks writes into Zone 1 directories (e.g. sbs/sentinel/)."""
    sentinel = Sentinel(project_root=tmp_path)

    # Create the directory structure
    sentinel_dir = tmp_path / "sbs" / "sentinel"
    sentinel_dir.mkdir(parents=True)
    (sentinel_dir / "manifest.py").write_text("# protected")

    with pytest.raises(SentinelError):
        sentinel.check_access("sbs/sentinel/manifest.py", "write")


# ---------------------------------------------------------------------------
# 5. Self-contained snapshot restore (MOD-10)
# ---------------------------------------------------------------------------


async def test_snapshot_self_contained_restore(selfmod_system, skill_intent):
    """Snapshot A can be restored even when a later snapshot B is deleted."""
    engine = selfmod_system["engine"]
    consent = selfmod_system["consent"]
    data_root = selfmod_system["data_root"]

    # Create snapshot A (baseline)
    snap_a = engine.create("baseline state", "pre_modification")

    # Add new skill (create snapshot B)
    new_skill = data_root / "skills" / "temp-skill"
    new_skill.mkdir(parents=True, exist_ok=True)
    (new_skill / "SKILL.md").write_text("---\nname: temp\n---\n")
    snap_b = engine.create("added temp-skill", "create_skill")

    # Manually remove snapshot B's archive to simulate corruption
    snap_b_path = engine._snapshots_dir / f"{snap_b.id}.tar.gz"
    if snap_b_path.exists():
        snap_b_path.unlink()

    # Restore snapshot A — should still succeed even without snapshot B
    # restore() returns the pre-restore snapshot it creates (not the target snapshot)
    pre_restore = engine.restore(snap_a.id)
    assert pre_restore is not None
    assert pre_restore.change_type == "restore"


# ---------------------------------------------------------------------------
# 6. Forward history preservation after rollback (MOD-06)
# ---------------------------------------------------------------------------


def test_forward_history_preserved_after_rollback(selfmod_system):
    """Rolling back does not delete any existing snapshots."""
    engine = selfmod_system["engine"]

    s1 = engine.create("state 1", "create_skill")
    s2 = engine.create("state 2", "create_skill")
    s3 = engine.create("state 3", "create_skill")

    count_before = len(engine.list_snapshots())

    # Rollback to s1
    engine.restore(s1.id)

    snapshots_after = engine.list_snapshots()
    # Original 3 snapshots still exist; restore added at least 1 new one
    assert len(snapshots_after) >= count_before + 1

    original_ids = {s1.id, s2.id, s3.id}
    current_ids = {s.id for s in snapshots_after}
    assert original_ids.issubset(current_ids), "Original snapshots must not be deleted"


# ---------------------------------------------------------------------------
# 7. Concurrent consent session isolation (T-02-02)
# ---------------------------------------------------------------------------


def test_concurrent_consent_sessions_are_independent(skill_intent):
    """Two PendingConsent objects with different session_ids are fully independent."""
    now = time.time()
    explanation = "Shall I proceed? (yes / no)"

    pc_a = PendingConsent(
        intent=skill_intent,
        session_id="session-alice",
        sender_id="alice",
        explanation=explanation,
        created_at=now,
    )
    pc_b = PendingConsent(
        intent=skill_intent,
        session_id="session-bob",
        sender_id="bob",
        explanation=explanation,
        created_at=now,
    )

    # Expire bob's consent but not alice's
    pc_b_expired = PendingConsent(
        intent=skill_intent,
        session_id="session-bob",
        sender_id="bob",
        explanation=explanation,
        created_at=now - 1.0,
        ttl_seconds=0.1,
    )

    assert not pc_a.is_expired
    assert pc_b_expired.is_expired
    assert pc_a.session_id != pc_b.session_id
    assert pc_a.sender_id != pc_b.sender_id


# ---------------------------------------------------------------------------
# 8. Full detect-intent → explain → confirm pipeline (async)
# ---------------------------------------------------------------------------


async def test_detect_intent_then_consent_flow(selfmod_system):
    """detect_modification_intent → explain → confirm_and_execute runs end-to-end."""
    engine = selfmod_system["engine"]
    consent = selfmod_system["consent"]
    data_root = selfmod_system["data_root"]

    intent = await detect_modification_intent("create a skill for tracking weather")
    assert intent is not None
    assert intent.change_type == "create_skill"

    explanation = consent.explain(intent)
    assert "weather" in explanation.lower() or "skill" in explanation.lower()
    assert is_affirmative("yes")
    assert is_negative("no")

    new_skill = data_root / "skills" / "weather-tracking"

    async def executor():
        new_skill.mkdir(parents=True, exist_ok=True)
        (new_skill / "SKILL.md").write_text("---\nname: weather-tracking\n---\n")
        return {"created": True}

    result = await consent.confirm_and_execute(intent, executor)
    assert result["status"] == "success"
    assert new_skill.exists()
    assert len(engine.list_snapshots()) >= 2
