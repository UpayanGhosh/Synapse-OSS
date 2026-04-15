"""
SnapshotEngine — atomic Zone 2 snapshot lifecycle management.

Creates timestamped snapshots under ~/.synapse/snapshots/, lists them sorted
newest-first, and restores Zone 2 content from any prior snapshot without
requiring any other snapshot (MOD-10 self-contained guarantee).

Security:
  - T-02-03: All snapshot IDs are slugified (alphanumeric + hyphens only).
    restore() validates the supplied ID with re.fullmatch before any path use.
  - T-02-04: max_snapshots enforced on every create(); configurable via
    synapse.json -> snapshots_max_count (default 50).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

_SNAPSHOT_JSON = "SNAPSHOT.json"
_ZONE2_SUBDIR = "zone2"


@dataclass(frozen=True)
class SnapshotMeta:
    """Immutable metadata record stored in SNAPSHOT.json inside each snapshot dir."""

    id: str
    """Snapshot identifier: ``YYYYMMDDTHHMMSS-slugified-description``."""

    timestamp: str
    """ISO 8601 creation timestamp (``datetime.now().isoformat()``)."""

    description: str
    """Plain-language description supplied by the caller."""

    change_type: str
    """One of: ``create_skill`` | ``delete_skill`` | ``create_cron`` |
    ``modify_config`` | ``restore``."""

    zone2_paths: tuple[str, ...]
    """Relative Zone 2 paths that were captured in this snapshot."""

    pre_snapshot_id: str = ""
    """For restore events: the source snapshot ID that was restored from."""

    path: Path = field(default_factory=lambda: Path("."))
    """Absolute path to the snapshot directory on disk (not serialised to JSON)."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SnapshotEngine:
    """Manages the full snapshot lifecycle: create, list, restore, prune."""

    def __init__(
        self,
        data_root: Path,
        zone2_paths: tuple[str, ...],
        max_snapshots: int = 50,
    ) -> None:
        self._data_root = data_root
        self._snapshots_dir = data_root / "snapshots"
        self._zone2_paths = zone2_paths
        self._max_snapshots = max_snapshots

        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_tmp()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        description: str,
        change_type: str,
        pre_snapshot_id: str = "",
    ) -> SnapshotMeta:
        """Atomically create a new Zone 2 snapshot.

        Uses a .tmp staging directory + os.replace() for atomicity — a
        crash before the rename leaves only a .tmp that is cleaned at
        next startup (T-02-04).

        Args:
            description: Human-readable description (sanitised to a safe slug).
            change_type: Category tag (``create_skill``, ``restore``, …).
            pre_snapshot_id: When called from restore(), the source snapshot ID.

        Returns:
            SnapshotMeta with all fields populated, including the on-disk path.
        """
        timestamp = datetime.now().isoformat()
        snapshot_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{self._slugify(description)}"

        tmp_path = self._snapshots_dir / f"{snapshot_id}.tmp"
        final_path = self._snapshots_dir / snapshot_id

        try:
            tmp_path.mkdir(parents=True, exist_ok=True)
            zone2_dir = tmp_path / _ZONE2_SUBDIR

            # Copy each Zone 2 path into the staging directory
            captured: list[str] = []
            for rel_path in self._zone2_paths:
                src = self._data_root / rel_path
                if not src.exists():
                    logger.debug("[Snapshot] Zone 2 path %s does not exist — skipping", src)
                    continue
                dest = zone2_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(str(src), str(dest))
                else:
                    shutil.copy2(str(src), str(dest))
                captured.append(rel_path)

            meta = SnapshotMeta(
                id=snapshot_id,
                timestamp=timestamp,
                description=description,
                change_type=change_type,
                zone2_paths=tuple(captured),
                pre_snapshot_id=pre_snapshot_id,
                path=final_path,
            )

            # Serialise metadata (exclude path — it's runtime-only)
            meta_dict = dataclasses.asdict(meta)
            meta_dict.pop("path", None)
            meta_dict["zone2_paths"] = list(meta.zone2_paths)
            (tmp_path / _SNAPSHOT_JSON).write_text(
                json.dumps(meta_dict, indent=2), encoding="utf-8"
            )

            # Atomic rename — only after all writes succeed
            os.replace(str(tmp_path), str(final_path))

        except BaseException:
            shutil.rmtree(str(tmp_path), ignore_errors=True)
            raise

        self._enforce_max_snapshots()

        logger.info("[Snapshot] Created %s (%s)", snapshot_id, change_type)
        return dataclasses.replace(meta, path=final_path)

    def list_snapshots(self) -> list[SnapshotMeta]:
        """Return all snapshots sorted newest-first (by timestamp string, ISO 8601).

        Directories that do not contain a valid SNAPSHOT.json are silently skipped.
        """
        results: list[SnapshotMeta] = []
        if not self._snapshots_dir.exists():
            return results

        for entry in self._snapshots_dir.iterdir():
            if not entry.is_dir() or entry.name.endswith(".tmp"):
                continue
            meta = self._load_meta(entry)
            if meta is not None:
                results.append(meta)

        results.sort(key=lambda m: m.timestamp, reverse=True)
        return results

    def restore(self, snapshot_id: str) -> SnapshotMeta:
        """Restore Zone 2 paths from a prior snapshot.

        Steps:
        1. Validate snapshot_id against ``[a-zA-Z0-9T-]+`` (T-02-03).
        2. Create a "pre-restore" snapshot capturing current Zone 2 state.
        3. Overwrite each live Zone 2 path with the snapshot copy.

        Args:
            snapshot_id: ID of the snapshot to restore.

        Returns:
            SnapshotMeta of the pre-restore snapshot created in step 2.

        Raises:
            ValueError: If snapshot_id contains illegal characters.
            FileNotFoundError: If the snapshot directory does not exist.
        """
        # T-02-03: Validate ID to prevent path traversal
        if not re.fullmatch(r"[a-zA-Z0-9T\-]+", snapshot_id):
            raise ValueError(
                f"Invalid snapshot_id: '{snapshot_id}'. "
                "Only alphanumeric characters, 'T', and hyphens are allowed."
            )

        snapshot_path = self._snapshots_dir / snapshot_id
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

        source_meta = self._load_meta(snapshot_path)
        if source_meta is None:
            raise FileNotFoundError(f"Snapshot {snapshot_id} has no valid SNAPSHOT.json")

        # Step 1: Preserve forward history by snapshotting current state first (MOD-06)
        pre_restore_meta = self.create(
            description=f"pre-restore-{snapshot_id}",
            change_type="restore",
            pre_snapshot_id=snapshot_id,
        )

        # Step 2: Overwrite live Zone 2 paths from snapshot
        zone2_src_root = snapshot_path / _ZONE2_SUBDIR
        for rel_path in source_meta.zone2_paths:
            src = zone2_src_root / rel_path
            dest = self._data_root / rel_path

            if not src.exists():
                logger.warning("[Snapshot] Restore: source path %s missing — skipping", src)
                continue

            # Remove current live version
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(str(dest))
                else:
                    dest.unlink()

            # Copy from snapshot
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                shutil.copy2(str(src), str(dest))

        logger.info(
            "[Snapshot] Restored %s → live (pre-restore: %s)", snapshot_id, pre_restore_meta.id
        )
        return pre_restore_meta

    def get_snapshot(self, snapshot_id: str) -> SnapshotMeta | None:
        """Load and return a single snapshot's metadata, or None if not found."""
        snap_path = self._snapshots_dir / snapshot_id
        if not snap_path.exists():
            return None
        return self._load_meta(snap_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slugify(self, text: str) -> str:
        """Convert text to a safe alphanumeric+hyphens slug (max 60 chars).

        Replaces any non-alphanumeric character with a hyphen, strips leading/
        trailing hyphens, and truncates to 60 characters.  Prevents path traversal
        for T-02-03.
        """
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]

    def _cleanup_stale_tmp(self) -> None:
        """Remove any ``.tmp`` directories left over from interrupted operations."""
        if not self._snapshots_dir.exists():
            return
        for entry in self._snapshots_dir.iterdir():
            if entry.is_dir() and entry.name.endswith(".tmp"):
                logger.info("[Snapshot] Removing stale tmp directory: %s", entry.name)
                shutil.rmtree(str(entry), ignore_errors=True)

    def _enforce_max_snapshots(self) -> None:
        """Prune the oldest snapshot(s) when the count exceeds max_snapshots."""
        snapshots = self.list_snapshots()
        while len(snapshots) > self._max_snapshots:
            oldest = snapshots[-1]  # list is newest-first, so last = oldest
            logger.info("[Snapshot] Pruning oldest snapshot: %s", oldest.id)
            shutil.rmtree(str(oldest.path), ignore_errors=True)
            snapshots = snapshots[:-1]

    def _load_meta(self, snap_dir: Path) -> SnapshotMeta | None:
        """Parse SNAPSHOT.json inside a snapshot directory into a SnapshotMeta."""
        json_path = snap_dir / _SNAPSHOT_JSON
        if not json_path.exists():
            return None
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return SnapshotMeta(
                id=data["id"],
                timestamp=data["timestamp"],
                description=data["description"],
                change_type=data["change_type"],
                zone2_paths=tuple(data.get("zone2_paths", [])),
                pre_snapshot_id=data.get("pre_snapshot_id", ""),
                path=snap_dir,
            )
        except (KeyError, json.JSONDecodeError) as exc:
            logger.warning("[Snapshot] Skipping corrupt snapshot %s: %s", snap_dir.name, exc)
            return None
