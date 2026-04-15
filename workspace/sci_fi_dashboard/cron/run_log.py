"""
Cron Scheduler — append-only run log.

Each job gets its own JSONL file at ``log_dir/cron-log/{job_id}.jsonl``.
Old entries are pruned based on retention days and a per-job max-runs cap.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RunLog:
    """Append-only JSONL run log with retention and pruning."""

    def __init__(
        self,
        log_dir: str | Path,
        retention_days: int = 30,
        max_runs: int = 1000,
    ):
        self._base = Path(log_dir) / "cron-log"
        self._retention_days = retention_days
        self._max_runs = max_runs

    def _job_path(self, job_id: str) -> Path:
        return self._base / f"{job_id}.jsonl"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, job_id: str, entry: dict[str, Any]) -> None:
        """Append a run entry for *job_id*.  Auto-creates the directory."""
        path = self._job_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, default=str)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get(self, job_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent *limit* entries (newest last)."""
        path = self._job_path(job_id)
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
        except OSError as exc:
            logger.warning("Could not read run log %s: %s", path, exc)
            return []

        entries: list[dict[str, Any]] = []
        for raw in lines[-limit:]:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return entries

    def prune(self) -> int:
        """Delete entries older than retention window and cap at max_runs.

        Returns the total number of entries removed across all job files.
        """
        if not self._base.exists():
            return 0

        cutoff_ms = int((time.time() - self._retention_days * 86_400) * 1000)
        total_removed = 0

        for logfile in self._base.glob("*.jsonl"):
            try:
                lines = logfile.read_text(encoding="utf-8").strip().splitlines()
            except OSError:
                continue

            kept: list[str] = []
            for raw in lines:
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    total_removed += 1
                    continue
                ts = entry.get("timestamp_ms", 0)
                if ts >= cutoff_ms:
                    kept.append(raw)
                else:
                    total_removed += 1

            # Apply max_runs cap (keep the newest)
            if len(kept) > self._max_runs:
                total_removed += len(kept) - self._max_runs
                kept = kept[-self._max_runs :]

            if len(kept) < len(lines):
                logfile.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")

            # Remove empty files
            if not kept:
                with contextlib.suppress(OSError):
                    logfile.unlink()

        return total_removed
