"""
RollbackResolver — natural-language-driven snapshot rollback.

Translates user intent ("undo the last change", "go back to March 15") into a
SnapshotEngine.restore() call.  Date parsing is regex-based (no external
dateparser dependency — research finding #6).

Implements:
  - MOD-04: Rollback by date (ISO, relative, month-day)
  - MOD-05: Rollback by description ("undo the last change")
  - MOD-06: Forward history preservation (SnapshotEngine always creates a
    pre-restore snapshot before overwriting Zone 2 content)

Security:
  - Snapshot ID validation is delegated to SnapshotEngine.restore(), which
    applies re.fullmatch(r"[a-zA-Z0-9T-]+", id) before any path construction
    (T-02-03).
  - _parse_date() only produces datetime objects — no file-path construction
    from user text occurs in this module.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sci_fi_dashboard.snapshot_engine import SnapshotEngine, SnapshotMeta


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RollbackResult:
    """Result of a successful rollback operation."""

    restored_snapshot: SnapshotMeta
    """The snapshot that was restored to."""

    pre_restore_snapshot: SnapshotMeta
    """The pre-rollback snapshot created to preserve forward history (MOD-06)."""

    message: str
    """Human-readable summary of the rollback."""


# ---------------------------------------------------------------------------
# Month lookup (lower-case)
# ---------------------------------------------------------------------------

_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_MONTH_PATTERN = "|".join(_MONTHS.keys())


# ---------------------------------------------------------------------------
# RollbackResolver
# ---------------------------------------------------------------------------


class RollbackResolver:
    """Translates natural language rollback requests into SnapshotEngine calls.

    Usage::

        engine = SnapshotEngine(data_root, zone2_paths)
        resolver = RollbackResolver(engine)
        result = resolver.resolve("go back to March 15")
    """

    def __init__(self, snapshot_engine: SnapshotEngine) -> None:
        self._engine = snapshot_engine
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, user_text: str) -> RollbackResult:
        """Parse user text and determine the rollback target.

        Dispatch order:
        1. "undo" / "revert" / "take back" keywords  → resolve_latest()
        2. Snapshot ID pattern (YYYYMMDDTHHMMSS-...)  → resolve_by_id()
        3. Parseable date expression                   → resolve_by_date()
        4. Otherwise                                   → ValueError

        Args:
            user_text: Free-form user input describing the rollback intent.

        Returns:
            RollbackResult with both the restored and pre-restore snapshots.

        Raises:
            ValueError: When no rollback target can be inferred.
        """
        text_lower = user_text.lower().strip()

        # Pattern 1: undo/revert keywords → latest non-restore snapshot
        if any(kw in text_lower for kw in ("undo", "revert", "take back")):
            self._logger.debug("[RollbackResolver] Detected 'undo' pattern")
            return self.resolve_latest()

        # Pattern 2: looks like a snapshot ID (YYYYMMDDTHHmmSS-…)
        if re.match(r"\d{8}t\d{6}-", text_lower):
            self._logger.debug("[RollbackResolver] Detected snapshot ID pattern")
            # Use original casing for the ID
            return self.resolve_by_id(user_text.strip())

        # Pattern 3: date expression in text
        target_date = self._parse_date(text_lower)
        if target_date is not None:
            self._logger.debug(
                "[RollbackResolver] Resolved date: %s", target_date.isoformat()
            )
            return self.resolve_by_date(target_date)

        raise ValueError(
            f"Could not determine rollback target from: {user_text!r}. "
            "Try: 'undo the last change', 'go back to March 15', "
            "'go back to yesterday', or 'go back to 2026-03-15'."
        )

    def resolve_latest(self) -> RollbackResult:
        """Restore the most recent non-restore snapshot (MOD-05).

        Skips snapshots with change_type in {"restore", "pre_modification"} so
        that "undo the last change" always picks a meaningful user-initiated
        change rather than a meta-snapshot.

        Returns:
            RollbackResult for the restored snapshot.

        Raises:
            ValueError: When no eligible non-restore snapshot exists.
        """
        _SKIP_TYPES = {"restore", "pre_modification"}
        snapshots = self._engine.list_snapshots()  # newest-first

        for snap in snapshots:
            if snap.change_type not in _SKIP_TYPES:
                self._logger.info(
                    "[RollbackResolver] resolve_latest → restoring %s", snap.id
                )
                pre_restore = self._engine.restore(snap.id)
                return RollbackResult(
                    restored_snapshot=snap,
                    pre_restore_snapshot=pre_restore,
                    message=f"Restored to: {snap.description} ({snap.timestamp})",
                )

        raise ValueError(
            "No snapshots available to restore. "
            "All existing snapshots are of type 'restore' or 'pre_modification'."
        )

    def resolve_by_date(self, target: datetime) -> RollbackResult:
        """Find and restore the snapshot nearest to (but not after) target (MOD-04).

        Algorithm:
        1. Prefer the latest snapshot whose timestamp ≤ target (nearest before).
        2. If no snapshot is before target, fall back to the absolute nearest
           snapshot in either direction (handles edge cases like "go back to
           a date before all snapshots").

        Args:
            target: Target datetime to resolve against.

        Returns:
            RollbackResult for the resolved snapshot.

        Raises:
            ValueError: When no snapshots exist at all.
        """
        snapshots = self._engine.list_snapshots()  # newest-first

        if not snapshots:
            raise ValueError(f"No snapshots found near {target.isoformat()}")

        # Pass 1: latest snapshot at or before target
        best: SnapshotMeta | None = None
        best_delta: timedelta | None = None

        for snap in snapshots:
            snap_dt = datetime.fromisoformat(snap.timestamp)
            delta = target - snap_dt
            if delta.total_seconds() >= 0:  # snap is before or at target
                if best_delta is None or delta < best_delta:
                    best = snap
                    best_delta = delta

        # Pass 2 fallback: absolute nearest in either direction
        if best is None:
            for snap in snapshots:
                snap_dt = datetime.fromisoformat(snap.timestamp)
                abs_delta = timedelta(seconds=abs((target - snap_dt).total_seconds()))
                if best_delta is None or abs_delta < best_delta:
                    best = snap
                    best_delta = abs_delta

        if best is None:
            raise ValueError(f"No snapshots found near {target.isoformat()}")

        self._logger.info(
            "[RollbackResolver] resolve_by_date → restoring %s", best.id
        )
        pre_restore = self._engine.restore(best.id)
        return RollbackResult(
            restored_snapshot=best,
            pre_restore_snapshot=pre_restore,
            message=f"Restored to: {best.description} ({best.timestamp})",
        )

    def resolve_by_id(self, snapshot_id: str) -> RollbackResult:
        """Restore a specific snapshot by its exact ID.

        Snapshot ID validation (path-traversal prevention) is delegated to
        SnapshotEngine.restore(), which applies re.fullmatch before any path
        construction (T-02-03).

        Args:
            snapshot_id: Exact snapshot ID string (e.g. "20260315T120000-test").

        Returns:
            RollbackResult for the restored snapshot.

        Raises:
            ValueError: When no snapshot with that ID exists.
        """
        snap = self._engine.get_snapshot(snapshot_id)
        if snap is None:
            raise ValueError(f"Snapshot not found: {snapshot_id!r}")

        self._logger.info(
            "[RollbackResolver] resolve_by_id → restoring %s", snapshot_id
        )
        pre_restore = self._engine.restore(snapshot_id)
        return RollbackResult(
            restored_snapshot=snap,
            pre_restore_snapshot=pre_restore,
            message=f"Restored to: {snap.description} ({snap.timestamp})",
        )

    # ------------------------------------------------------------------
    # Date parser (regex-based — no external deps per research finding #6)
    # ------------------------------------------------------------------

    def _parse_date(self, text: str) -> datetime | None:
        """Extract a target datetime from lowercase user text.

        Patterns handled (in priority order):
        1. ISO date:       "2026-03-15"
        2. "yesterday"
        3. "last week"
        4. "N days ago"    (e.g. "3 days ago")
        5. "N weeks ago"   (e.g. "2 weeks ago")
        6. Month + day:    "March 15", "march 15th"

        Args:
            text: Lowercased user input.

        Returns:
            datetime object or None if no date expression found.
        """
        now = datetime.now()

        # 1. ISO date: YYYY-MM-DD
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass  # Invalid date components — keep trying

        # 2. "yesterday"
        if "yesterday" in text:
            return now - timedelta(days=1)

        # 3. "last week"
        if "last week" in text:
            return now - timedelta(days=7)

        # 4. "N days ago"
        m = re.search(r"(\d+)\s*days?\s*ago", text)
        if m:
            return now - timedelta(days=int(m.group(1)))

        # 5. "N weeks ago"
        m = re.search(r"(\d+)\s*weeks?\s*ago", text)
        if m:
            return now - timedelta(weeks=int(m.group(1)))

        # 6. Month name + day: "March 15", "march 15th"
        m = re.search(
            rf"({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?",
            text,
        )
        if m:
            month = _MONTHS[m.group(1)]
            day = int(m.group(2))
            year = now.year
            try:
                target = datetime(year, month, day)
            except ValueError:
                return None
            # If the resulting date is in the future, assume the previous year
            if target > now:
                target = datetime(year - 1, month, day)
            return target

        return None
