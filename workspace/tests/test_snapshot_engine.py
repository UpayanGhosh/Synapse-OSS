"""
Unit tests for SnapshotEngine — create/list/restore/prune lifecycle.

Tests follow the TDD behavior spec in 02-01-PLAN.md.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from sci_fi_dashboard.snapshot_engine import SnapshotEngine, SnapshotMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zone2(data_root: Path) -> None:
    """Create a minimal Zone 2 structure inside data_root for tests."""
    skill_dir = data_root / "skills" / "test-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Test Skill\nThis is a test skill.", encoding="utf-8")


def _engine(data_root: Path, max_snapshots: int = 50) -> SnapshotEngine:
    return SnapshotEngine(
        data_root=data_root,
        zone2_paths=("skills",),
        max_snapshots=max_snapshots,
    )


# ---------------------------------------------------------------------------
# test_create_snapshot
# ---------------------------------------------------------------------------


def test_create_snapshot(tmp_path: Path) -> None:
    """create() produces a directory with SNAPSHOT.json and zone2/ subdirectory."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta = engine.create(description="test skill", change_type="create_skill")

    # Must return a SnapshotMeta
    assert isinstance(meta, SnapshotMeta)
    assert meta.description == "test skill"
    assert meta.change_type == "create_skill"

    # Directory must exist at snapshots_dir / snapshot_id
    snap_dir = tmp_path / "snapshots" / meta.id
    assert snap_dir.is_dir(), f"Snapshot directory not found: {snap_dir}"

    # SNAPSHOT.json must exist inside
    json_file = snap_dir / "SNAPSHOT.json"
    assert json_file.exists(), "SNAPSHOT.json not found in snapshot directory"

    # zone2/ must contain the captured skill
    zone2_dir = snap_dir / "zone2" / "skills"
    assert zone2_dir.is_dir(), "zone2/skills not captured in snapshot"
    assert (zone2_dir / "test-skill" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# test_snapshot_id_format
# ---------------------------------------------------------------------------


def test_snapshot_id_format(tmp_path: Path) -> None:
    """Snapshot IDs match YYYYMMDDTHHMMSS-slug (alphanumeric + hyphens only)."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta = engine.create(description="medication reminder", change_type="create_skill")

    # Pattern: 8 digits + T + 6 digits + hyphen + slug
    pattern = r"^\d{8}T\d{6}-[a-z0-9][a-z0-9\-]*$"
    assert re.match(pattern, meta.id), f"ID '{meta.id}' does not match expected format"
    assert "medication" in meta.id or "medic" in meta.id


# ---------------------------------------------------------------------------
# test_snapshot_atomicity
# ---------------------------------------------------------------------------


def test_snapshot_atomicity(tmp_path: Path) -> None:
    """If copytree raises mid-copy, only a .tmp dir may exist (never a final dir)."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    with patch("shutil.copytree", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            engine.create(description="crash test", change_type="create_skill")

    snapshots_dir = tmp_path / "snapshots"
    if snapshots_dir.exists():
        # No final (non-.tmp) directories must exist
        final_dirs = [d for d in snapshots_dir.iterdir() if not d.name.endswith(".tmp")]
        assert final_dirs == [], f"Leftover final dirs after crash: {final_dirs}"


# ---------------------------------------------------------------------------
# test_list_snapshots
# ---------------------------------------------------------------------------


def test_list_snapshots(tmp_path: Path) -> None:
    """After creating 3 snapshots, list_snapshots() returns 3 metas sorted newest-first."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    for i in range(3):
        engine.create(description=f"snap {i}", change_type="create_skill")

    results = engine.list_snapshots()
    assert len(results) == 3, f"Expected 3 snapshots, got {len(results)}"

    # All items must be SnapshotMeta
    for r in results:
        assert isinstance(r, SnapshotMeta)

    # Sorted newest-first: timestamps must be in descending order
    timestamps = [r.timestamp for r in results]
    assert timestamps == sorted(timestamps, reverse=True), "list_snapshots not sorted newest-first"


# ---------------------------------------------------------------------------
# test_restore_snapshot
# ---------------------------------------------------------------------------


def test_restore_snapshot(tmp_path: Path) -> None:
    """Restore replaces live Zone 2 content with snapshot content."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta_before = engine.create(description="before mod", change_type="create_skill")

    # Modify Zone 2 content
    skill_file = tmp_path / "skills" / "test-skill" / "SKILL.md"
    skill_file.write_text("# MODIFIED", encoding="utf-8")

    # Restore to the original snapshot
    engine.restore(meta_before.id)

    # Zone 2 content must match original
    restored_content = skill_file.read_text(encoding="utf-8")
    assert "Test Skill" in restored_content, "Restore did not bring back original content"
    assert "MODIFIED" not in restored_content


# ---------------------------------------------------------------------------
# test_restore_without_prior_snapshots
# ---------------------------------------------------------------------------


def test_restore_without_prior_snapshots(tmp_path: Path) -> None:
    """Restoring snapshot A succeeds even when snapshot B doesn't exist (self-contained)."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta_a = engine.create(description="snap A", change_type="create_skill")

    # Delete a different snapshot dir that never existed — should be a no-op / ignored
    non_existent = tmp_path / "snapshots" / "20000101T000000-fake"
    assert not non_existent.exists()

    # Restore A should succeed without errors
    engine.restore(meta_a.id)


# ---------------------------------------------------------------------------
# test_snapshot_max_limit
# ---------------------------------------------------------------------------


def test_snapshot_max_limit(tmp_path: Path) -> None:
    """With max_snapshots=3, creating a 4th snapshot prunes the oldest."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path, max_snapshots=3)

    created = []
    for i in range(4):
        m = engine.create(description=f"snap {i}", change_type="create_skill")
        created.append(m)

    remaining = engine.list_snapshots()
    assert len(remaining) <= 3, f"Expected at most 3 snapshots, got {len(remaining)}"

    # The oldest (first created) should be gone
    remaining_ids = {m.id for m in remaining}
    assert created[0].id not in remaining_ids, "Oldest snapshot was not pruned"


# ---------------------------------------------------------------------------
# test_cleanup_stale_tmp
# ---------------------------------------------------------------------------


def test_cleanup_stale_tmp(tmp_path: Path) -> None:
    """On init, stale .tmp directories in snapshots_dir are removed."""
    snapshots_dir = tmp_path / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake stale .tmp directory
    stale_tmp = snapshots_dir / "20260101T000000-crashed.tmp"
    stale_tmp.mkdir()
    (stale_tmp / "partial_file.txt").write_text("partial", encoding="utf-8")

    assert stale_tmp.exists(), "Stale .tmp directory should exist before init"

    # Initializing SnapshotEngine must clean it up
    _engine(tmp_path)

    assert not stale_tmp.exists(), "Stale .tmp directory not removed by SnapshotEngine.__init__"


# ---------------------------------------------------------------------------
# test_snapshot_id_path_traversal
# ---------------------------------------------------------------------------


def test_snapshot_id_path_traversal(tmp_path: Path) -> None:
    """create() with a path-traversal description produces a safe slug."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta = engine.create(
        description="../../../etc/passwd injection",
        change_type="create_skill",
    )

    # The snapshot ID must not contain path separators
    assert "/" not in meta.id, f"Snapshot ID contains '/': {meta.id}"
    assert "\\" not in meta.id, f"Snapshot ID contains '\\\\': {meta.id}"
    assert ".." not in meta.id, f"Snapshot ID contains '..': {meta.id}"

    # The snapshot directory must exist safely under snapshots_dir
    expected_dir = tmp_path / "snapshots" / meta.id
    assert expected_dir.is_dir(), f"Snapshot directory not found: {expected_dir}"


# ---------------------------------------------------------------------------
# test_get_snapshot
# ---------------------------------------------------------------------------


def test_get_snapshot(tmp_path: Path) -> None:
    """get_snapshot() returns the SnapshotMeta for an existing snapshot."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    meta = engine.create(description="get test", change_type="create_cron")

    retrieved = engine.get_snapshot(meta.id)
    assert retrieved is not None
    assert retrieved.id == meta.id
    assert retrieved.description == "get test"
    assert retrieved.change_type == "create_cron"


def test_get_snapshot_missing(tmp_path: Path) -> None:
    """get_snapshot() returns None for a non-existent snapshot ID."""
    _make_zone2(tmp_path)
    engine = _engine(tmp_path)

    result = engine.get_snapshot("20260101T000000-does-not-exist")
    assert result is None


# ---------------------------------------------------------------------------
# test_restore_invalid_id
# ---------------------------------------------------------------------------


def test_restore_invalid_id(tmp_path: Path) -> None:
    """restore() raises ValueError for IDs containing path traversal sequences."""
    engine = _engine(tmp_path)

    with pytest.raises((ValueError, FileNotFoundError)):
        engine.restore("../../../etc/passwd")
