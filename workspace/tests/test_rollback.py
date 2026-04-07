"""
Tests for RollbackResolver (Plan 02-05).

Covers:
- MOD-04: Rollback by date (ISO, relative, month-day)
- MOD-05: Rollback by description ("undo the last change")
- MOD-06: Forward history preservation after rollback

Test strategy: isolated SnapshotEngine backed by tmp_path; controlled
timestamps injected via snapshot creation helpers; no monkeypatching of
datetime needed because we compare snapshot positions, not wall-clock times.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sci_fi_dashboard.rollback import RollbackResolver, RollbackResult
from sci_fi_dashboard.snapshot_engine import SnapshotEngine, SnapshotMeta


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

ZONE2_PATHS: tuple[str, ...] = ("skills",)


def make_engine(tmp_path: Path, max_snapshots: int = 50) -> SnapshotEngine:
    """Create a SnapshotEngine rooted in tmp_path with a 'skills' zone."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SnapshotEngine(
        data_root=tmp_path,
        zone2_paths=ZONE2_PATHS,
        max_snapshots=max_snapshots,
    )


def make_resolver(tmp_path: Path) -> tuple[SnapshotEngine, RollbackResolver]:
    engine = make_engine(tmp_path)
    resolver = RollbackResolver(engine)
    return engine, resolver


def add_skill_file(tmp_path: Path, name: str, content: str = "# skill") -> None:
    """Create a dummy skill file in the skills zone so snapshots capture something."""
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content)


# ---------------------------------------------------------------------------
# Task 1 tests — core rollback by date
# ---------------------------------------------------------------------------


class TestRollbackByDate:
    def test_rollback_by_date_selects_nearest_before(self, tmp_path: Path) -> None:
        """Given snapshots on March 14 and March 16, 'March 15' selects March 14."""
        engine, resolver = make_resolver(tmp_path)

        add_skill_file(tmp_path, "skill_a")
        snap_mar14 = engine.create("mar14-skill", "create_skill")

        add_skill_file(tmp_path, "skill_b")
        snap_mar16 = engine.create("mar16-skill", "create_skill")

        # Build two known datetime objects around a target
        target = datetime(2026, 3, 15, 12, 0, 0)
        dt_mar14 = target - timedelta(days=1)  # one day before target
        dt_mar16 = target + timedelta(days=1)  # one day after target

        # Use a mock engine that returns our controlled snapshots
        mock_engine = MagicMock()
        mock_snap_mar14 = MagicMock(spec=SnapshotMeta)
        mock_snap_mar14.id = "20260314T120000-mar14-skill"
        mock_snap_mar14.timestamp = dt_mar14.isoformat()
        mock_snap_mar14.description = "mar14-skill"
        mock_snap_mar14.change_type = "create_skill"

        mock_snap_mar16 = MagicMock(spec=SnapshotMeta)
        mock_snap_mar16.id = "20260316T120000-mar16-skill"
        mock_snap_mar16.timestamp = dt_mar16.isoformat()
        mock_snap_mar16.description = "mar16-skill"
        mock_snap_mar16.change_type = "create_skill"

        mock_pre_restore = MagicMock(spec=SnapshotMeta)
        mock_pre_restore.id = "20260315T130000-pre-restore"
        mock_pre_restore.timestamp = datetime.now().isoformat()
        mock_pre_restore.description = "pre-restore"
        mock_pre_restore.change_type = "restore"

        # list_snapshots returns newest-first: mar16 before mar14
        mock_engine.list_snapshots.return_value = [mock_snap_mar16, mock_snap_mar14]
        mock_engine.restore.return_value = mock_pre_restore

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve_by_date(target)

        assert result.restored_snapshot.id == mock_snap_mar14.id
        mock_engine.restore.assert_called_once_with(mock_snap_mar14.id)

    def test_rollback_by_date_no_snapshots_raises(self, tmp_path: Path) -> None:
        """When no snapshots exist, resolve_by_date raises ValueError."""
        engine, resolver = make_resolver(tmp_path)
        with pytest.raises(ValueError, match="No snapshots found"):
            resolver.resolve_by_date(datetime(2026, 3, 15))

    def test_rollback_iso_date(self, tmp_path: Path) -> None:
        """'go back to 2026-03-15' parses the ISO date and calls resolve_by_date."""
        engine, resolver = make_resolver(tmp_path)
        add_skill_file(tmp_path, "skill_iso")
        engine.create("iso-skill", "create_skill")

        # We test _parse_date directly to verify ISO parsing
        parsed = resolver._parse_date("go back to 2026-03-15")
        assert parsed is not None
        assert parsed.year == 2026
        assert parsed.month == 3
        assert parsed.day == 15

    def test_rollback_yesterday(self, tmp_path: Path) -> None:
        """'go back to yesterday' resolves to a date 1 day before now."""
        engine, resolver = make_resolver(tmp_path)
        now = datetime.now()

        parsed = resolver._parse_date("go back to yesterday")
        assert parsed is not None
        # Should be within 5 seconds of now - 1 day (accounting for execution time)
        expected = now - timedelta(days=1)
        diff = abs((parsed - expected).total_seconds())
        assert diff < 5

    def test_rollback_last_week(self, tmp_path: Path) -> None:
        """'go back to last week' resolves to a date 7 days before now."""
        engine, resolver = make_resolver(tmp_path)
        now = datetime.now()

        parsed = resolver._parse_date("go back to last week")
        assert parsed is not None
        expected = now - timedelta(days=7)
        diff = abs((parsed - expected).total_seconds())
        assert diff < 5

    def test_rollback_n_days_ago(self, tmp_path: Path) -> None:
        """'go back to 3 days ago' resolves to 3 days before now."""
        engine, resolver = make_resolver(tmp_path)
        now = datetime.now()

        parsed = resolver._parse_date("go back to 3 days ago")
        assert parsed is not None
        expected = now - timedelta(days=3)
        diff = abs((parsed - expected).total_seconds())
        assert diff < 5

    def test_rollback_month_day(self, tmp_path: Path) -> None:
        """'go back to March 15' parses the month-day form."""
        engine, resolver = make_resolver(tmp_path)
        parsed = resolver._parse_date("go back to march 15")
        assert parsed is not None
        assert parsed.month == 3
        assert parsed.day == 15

    def test_rollback_month_day_with_ordinal(self, tmp_path: Path) -> None:
        """'March 15th' also parses correctly."""
        engine, resolver = make_resolver(tmp_path)
        parsed = resolver._parse_date("roll back to march 15th")
        assert parsed is not None
        assert parsed.month == 3
        assert parsed.day == 15


# ---------------------------------------------------------------------------
# Task 2 tests — undo last change (resolve_latest)
# ---------------------------------------------------------------------------


class TestRollbackUndoLast:
    def test_rollback_undo_last_skips_restore_snapshots(self, tmp_path: Path) -> None:
        """'undo the last change' skips restore-type snapshots and picks the newest real one."""
        mock_engine = MagicMock()

        mock_restore_snap = MagicMock(spec=SnapshotMeta)
        mock_restore_snap.id = "20260407T130000-pre-restore"
        mock_restore_snap.timestamp = datetime.now().isoformat()
        mock_restore_snap.description = "pre-restore"
        mock_restore_snap.change_type = "restore"  # should be skipped

        mock_real_snap = MagicMock(spec=SnapshotMeta)
        mock_real_snap.id = "20260407T120000-add-skill"
        mock_real_snap.timestamp = (datetime.now() - timedelta(hours=1)).isoformat()
        mock_real_snap.description = "add-skill"
        mock_real_snap.change_type = "create_skill"  # should be selected

        mock_pre_restore = MagicMock(spec=SnapshotMeta)
        mock_pre_restore.id = "20260407T140000-pre-restore-2"
        mock_pre_restore.timestamp = datetime.now().isoformat()
        mock_pre_restore.description = "pre-restore-2"
        mock_pre_restore.change_type = "restore"

        mock_engine.list_snapshots.return_value = [mock_restore_snap, mock_real_snap]
        mock_engine.restore.return_value = mock_pre_restore

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve_latest()

        assert result.restored_snapshot.id == mock_real_snap.id
        mock_engine.restore.assert_called_once_with(mock_real_snap.id)

    def test_rollback_undo_last_no_eligible_snapshots_raises(self, tmp_path: Path) -> None:
        """When all snapshots are restore-type, resolve_latest raises ValueError."""
        mock_engine = MagicMock()
        mock_snap = MagicMock(spec=SnapshotMeta)
        mock_snap.change_type = "restore"
        mock_engine.list_snapshots.return_value = [mock_snap]

        resolver = RollbackResolver(mock_engine)
        with pytest.raises(ValueError, match="No snapshots available"):
            resolver.resolve_latest()

    def test_rollback_undo_last_empty_raises(self, tmp_path: Path) -> None:
        """When no snapshots exist at all, resolve_latest raises ValueError."""
        mock_engine = MagicMock()
        mock_engine.list_snapshots.return_value = []

        resolver = RollbackResolver(mock_engine)
        with pytest.raises(ValueError, match="No snapshots available"):
            resolver.resolve_latest()


# ---------------------------------------------------------------------------
# Task 3 tests — rollback by ID
# ---------------------------------------------------------------------------


class TestRollbackById:
    def test_rollback_by_id_succeeds(self, tmp_path: Path) -> None:
        """resolve_by_id restores the exact snapshot with that ID."""
        mock_engine = MagicMock()

        target_snap = MagicMock(spec=SnapshotMeta)
        target_snap.id = "20260315T120000-test"
        target_snap.timestamp = "2026-03-15T12:00:00"
        target_snap.description = "test"
        target_snap.change_type = "create_skill"

        pre_restore = MagicMock(spec=SnapshotMeta)
        pre_restore.id = "20260407T130000-pre-restore"
        pre_restore.timestamp = datetime.now().isoformat()
        pre_restore.description = "pre-restore"
        pre_restore.change_type = "restore"

        mock_engine.get_snapshot.return_value = target_snap
        mock_engine.restore.return_value = pre_restore

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve_by_id("20260315T120000-test")

        assert result.restored_snapshot.id == "20260315T120000-test"
        mock_engine.get_snapshot.assert_called_once_with("20260315T120000-test")
        mock_engine.restore.assert_called_once_with("20260315T120000-test")

    def test_rollback_by_id_not_found_raises(self, tmp_path: Path) -> None:
        """resolve_by_id raises ValueError when snapshot ID doesn't exist."""
        mock_engine = MagicMock()
        mock_engine.get_snapshot.return_value = None

        resolver = RollbackResolver(mock_engine)
        with pytest.raises(ValueError, match="Snapshot not found"):
            resolver.resolve_by_id("20260315T120000-nonexistent")


# ---------------------------------------------------------------------------
# Task 4 tests — forward history preservation (MOD-06)
# ---------------------------------------------------------------------------


class TestForwardHistoryPreservation:
    def test_rollback_preserves_forward_history(self, tmp_path: Path) -> None:
        """After rollback, list_snapshots() includes all original + pre-restore snapshot."""
        engine = make_engine(tmp_path)
        resolver = RollbackResolver(engine)

        # Create 3 snapshots
        add_skill_file(tmp_path, "skill_a", "# A")
        s1 = engine.create("skill-a-created", "create_skill")

        add_skill_file(tmp_path, "skill_b", "# B")
        s2 = engine.create("skill-b-created", "create_skill")

        add_skill_file(tmp_path, "skill_c", "# C")
        s3 = engine.create("skill-c-created", "create_skill")

        before_count = len(engine.list_snapshots())
        assert before_count == 3

        # Rollback to s1
        result = resolver.resolve_by_id(s1.id)

        after_snapshots = engine.list_snapshots()
        after_count = len(after_snapshots)

        # Forward history preserved: original 3 + 1 pre-restore = 4
        assert after_count == before_count + 1, (
            f"Expected {before_count + 1} snapshots after rollback, got {after_count}"
        )

        # All original IDs are still present
        snap_ids = {s.id for s in after_snapshots}
        assert s1.id in snap_ids
        assert s2.id in snap_ids
        assert s3.id in snap_ids

        # The pre-restore snapshot is also present
        assert result.pre_restore_snapshot.id in snap_ids

    def test_rollback_result_contains_both_snapshots(self, tmp_path: Path) -> None:
        """RollbackResult has both restored_snapshot and pre_restore_snapshot set."""
        mock_engine = MagicMock()

        target_snap = MagicMock(spec=SnapshotMeta)
        target_snap.id = "20260315T120000-original"
        target_snap.timestamp = "2026-03-15T12:00:00"
        target_snap.description = "original"
        target_snap.change_type = "create_skill"

        pre_snap = MagicMock(spec=SnapshotMeta)
        pre_snap.id = "20260407T130000-pre-restore"
        pre_snap.timestamp = datetime.now().isoformat()
        pre_snap.description = "pre-restore"
        pre_snap.change_type = "restore"

        mock_engine.get_snapshot.return_value = target_snap
        mock_engine.restore.return_value = pre_snap

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve_by_id("20260315T120000-original")

        assert result.restored_snapshot is target_snap
        assert result.pre_restore_snapshot is pre_snap
        assert result.message  # non-empty message


# ---------------------------------------------------------------------------
# Task 5 tests — resolve() dispatcher (natural language)
# ---------------------------------------------------------------------------


class TestResolveDispatcher:
    def test_resolve_natural_language_undo(self, tmp_path: Path) -> None:
        """'undo the last change' dispatches to resolve_latest()."""
        mock_engine = MagicMock()
        mock_snap = MagicMock(spec=SnapshotMeta)
        mock_snap.id = "20260407T120000-add-skill"
        mock_snap.timestamp = datetime.now().isoformat()
        mock_snap.description = "add-skill"
        mock_snap.change_type = "create_skill"

        mock_pre = MagicMock(spec=SnapshotMeta)
        mock_pre.id = "20260407T130000-pre-restore"
        mock_pre.timestamp = datetime.now().isoformat()
        mock_pre.description = "pre-restore"
        mock_pre.change_type = "restore"

        mock_engine.list_snapshots.return_value = [mock_snap]
        mock_engine.restore.return_value = mock_pre

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve("undo the last change")

        assert result.restored_snapshot.id == mock_snap.id

    def test_resolve_you_were_better_last_week(self, tmp_path: Path) -> None:
        """'you were better last week' resolves via date parsing."""
        mock_engine = MagicMock()
        now = datetime.now()

        old_snap = MagicMock(spec=SnapshotMeta)
        old_snap.id = "20260401T120000-old-skill"
        old_snap.timestamp = (now - timedelta(days=8)).isoformat()
        old_snap.description = "old-skill"
        old_snap.change_type = "create_skill"

        mock_pre = MagicMock(spec=SnapshotMeta)
        mock_pre.id = "20260407T130000-pre-restore"
        mock_pre.timestamp = now.isoformat()
        mock_pre.description = "pre-restore"
        mock_pre.change_type = "restore"

        mock_engine.list_snapshots.return_value = [old_snap]
        mock_engine.restore.return_value = mock_pre

        resolver = RollbackResolver(mock_engine)
        # "last week" triggers date parsing → resolve_by_date
        result = resolver.resolve("you were better last week")
        assert result is not None

    def test_resolve_go_back_to_march_15(self, tmp_path: Path) -> None:
        """'go back to March 15' parses the month-day and finds the right snapshot."""
        mock_engine = MagicMock()
        now = datetime.now()

        # Snapshot from "before March 15" this year (or last year if past)
        year = now.year if datetime(now.year, 3, 14) < now else now.year - 1
        dt_mar14 = datetime(year, 3, 14, 12, 0, 0)

        snap = MagicMock(spec=SnapshotMeta)
        snap.id = "20260314T120000-test-snap"
        snap.timestamp = dt_mar14.isoformat()
        snap.description = "test-snap"
        snap.change_type = "create_skill"

        mock_pre = MagicMock(spec=SnapshotMeta)
        mock_pre.id = "20260315T000000-pre-restore"
        mock_pre.timestamp = now.isoformat()
        mock_pre.description = "pre-restore"
        mock_pre.change_type = "restore"

        mock_engine.list_snapshots.return_value = [snap]
        mock_engine.restore.return_value = mock_pre

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve("go back to March 15")
        assert result is not None

    def test_resolve_unrecognized_raises(self, tmp_path: Path) -> None:
        """Completely unrecognized text raises ValueError."""
        engine, resolver = make_resolver(tmp_path)
        with pytest.raises(ValueError, match="Could not determine rollback target"):
            resolver.resolve("hello world this makes no sense for rollback xyz")

    def test_resolve_snapshot_id_dispatches_to_resolve_by_id(self, tmp_path: Path) -> None:
        """A string that looks like a snapshot ID dispatches to resolve_by_id()."""
        mock_engine = MagicMock()

        snap = MagicMock(spec=SnapshotMeta)
        snap.id = "20260315T120000-some-skill"
        snap.timestamp = "2026-03-15T12:00:00"
        snap.description = "some-skill"
        snap.change_type = "create_skill"

        mock_pre = MagicMock(spec=SnapshotMeta)
        mock_pre.id = "20260407T130000-pre-restore"
        mock_pre.timestamp = datetime.now().isoformat()
        mock_pre.description = "pre-restore"
        mock_pre.change_type = "restore"

        mock_engine.get_snapshot.return_value = snap
        mock_engine.restore.return_value = mock_pre

        resolver = RollbackResolver(mock_engine)
        result = resolver.resolve("20260315T120000-some-skill")
        assert result.restored_snapshot.id == "20260315T120000-some-skill"


# ---------------------------------------------------------------------------
# Task 6 tests — _parse_date edge cases
# ---------------------------------------------------------------------------


class TestParseDateEdgeCases:
    def test_parse_date_weeks_ago(self, tmp_path: Path) -> None:
        """'2 weeks ago' resolves to 14 days before now."""
        engine, resolver = make_resolver(tmp_path)
        now = datetime.now()
        parsed = resolver._parse_date("2 weeks ago")
        assert parsed is not None
        expected = now - timedelta(weeks=2)
        diff = abs((parsed - expected).total_seconds())
        assert diff < 5

    def test_parse_date_returns_none_for_unknown(self, tmp_path: Path) -> None:
        """Completely unknown text returns None from _parse_date."""
        engine, resolver = make_resolver(tmp_path)
        result = resolver._parse_date("make the system better somehow")
        assert result is None

    def test_parse_date_iso_invalid_components_skips(self, tmp_path: Path) -> None:
        """An ISO-looking date with invalid components (month=13) falls through."""
        engine, resolver = make_resolver(tmp_path)
        # 2026-13-01 — invalid month; should skip to next patterns
        result = resolver._parse_date("go back to 2026-13-01")
        # No other date patterns present → None
        assert result is None
