"""transcript.py — JSONL transcript I/O with auto-repair.

This module is imported by compaction.py and context_assembler.py.

Features:
- transcript_path(session_entry, data_root, agent_id) -> Path
- async append_message(path, message: dict) -> None  (asyncio.to_thread)
- async load_messages(path, limit=None) -> list[dict]  (skip corrupt lines + limit + auto-repair)
- limit_history_turns(messages, limit) -> list[dict]  (walk-backwards user-count)
- async archive_transcript(path) -> None  (rename to .deleted.<ms>)
- repair_orphaned_tool_pairs(messages) -> tuple[list[dict], RepairReport]
- repair_all_transcripts(sessions_dir) -> int
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from sci_fi_dashboard.multiuser.session_store import SessionEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repair data model
# ---------------------------------------------------------------------------


@dataclass
class RepairReport:
    """Summary of a transcript repair pass."""

    orphaned_tool_results_removed: int = 0
    orphaned_tool_calls_removed: int = 0
    total_messages_before: int = 0
    total_messages_after: int = 0

    @property
    def repairs_made(self) -> int:
        return self.orphaned_tool_results_removed + self.orphaned_tool_calls_removed


# ---------------------------------------------------------------------------
# Repair functions (moved from compaction.py and enhanced)
# ---------------------------------------------------------------------------


def repair_orphaned_tool_pairs(messages: list[dict]) -> tuple[list[dict], RepairReport]:
    """Remove orphaned tool_use / tool_result pairs and return a report.

    After a compaction rewrite the second half may begin mid-exchange, leaving
    tool_result messages with no matching tool_use above them, or vice versa.
    This pass strips any such unpaired entries.

    Returns:
        A tuple of (repaired_messages, RepairReport).
    """
    report = RepairReport(total_messages_before=len(messages))

    # Collect tool_use IDs that are present.
    tool_use_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tid = tc.get("id") or tc.get("tool_use_id") or tc.get("name")
                if tid:
                    tool_use_ids.add(tid)

    # Collect tool_result IDs that are present.
    tool_result_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id") or msg.get("tool_use_id")
            if tid:
                tool_result_ids.add(tid)

    result: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool":
            tid = msg.get("tool_call_id") or msg.get("tool_use_id")
            if tid and tid not in tool_use_ids:
                logger.debug("transcript: dropping orphaned tool_result id=%s", tid)
                report.orphaned_tool_results_removed += 1
                continue
        result.append(msg)

    report.total_messages_after = len(result)
    return result, report


def repair_all_transcripts(sessions_dir: Path) -> int:
    """Scan and repair all ``.jsonl`` transcript files in *sessions_dir*.

    Returns the total number of files that had repairs applied.
    """
    repaired_count = 0
    if not sessions_dir.exists():
        return repaired_count

    for jsonl_file in sessions_dir.glob("*.jsonl"):
        try:
            messages: list[dict] = []
            with open(jsonl_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            repaired, report = repair_orphaned_tool_pairs(messages)
            if report.repairs_made > 0:
                # Rewrite the file atomically.
                import tempfile
                import contextlib

                fd, tmp_path = tempfile.mkstemp(
                    dir=str(jsonl_file.parent), suffix=".tmp"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        for msg in repaired:
                            fh.write(json.dumps(msg, separators=(",", ":")) + "\n")
                    os.replace(tmp_path, str(jsonl_file))
                except Exception:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
                    raise

                repaired_count += 1
                logger.info(
                    "transcript: repaired %s — removed %d orphaned entries",
                    jsonl_file.name,
                    report.repairs_made,
                )
        except Exception:
            logger.warning(
                "transcript: failed to repair %s", jsonl_file, exc_info=True
            )

    return repaired_count


def transcript_path(session_entry: SessionEntry, data_root: Path, agent_id: str) -> Path:
    """Return the JSONL file path for *session_entry*."""
    return (
        data_root
        / "state"
        / "agents"
        / agent_id
        / "sessions"
        / f"{session_entry.session_id}.jsonl"
    )


async def append_message(path: Path, message: dict) -> None:
    """Append *message* as a single JSONL line to *path*."""

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(message, separators=(",", ":")) + "\n")

    await asyncio.to_thread(_write)


async def load_messages(path: Path, limit: int | None = None) -> list[dict]:
    """Read all messages from the JSONL *path*, skipping blank or corrupt lines.

    Automatically repairs orphaned tool_use / tool_result pairs on every load.
    If *limit* is set, returns the tail containing exactly *limit* user turns.
    """

    def _read() -> list[dict]:
        if not path.exists():
            return []
        messages: list[dict] = []
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "transcript: skipping corrupt line %d in %s", lineno, path
                    )
        return messages

    messages = await asyncio.to_thread(_read)

    # Auto-repair orphaned tool pairs.
    if messages:
        repaired, report = repair_orphaned_tool_pairs(messages)
        if report.repairs_made > 0:
            logger.info(
                "transcript: auto-repaired %d orphaned entries in %s",
                report.repairs_made,
                path,
            )
            messages = repaired

    if limit is not None:
        messages = limit_history_turns(messages, limit)
    return messages


def limit_history_turns(messages: list[dict], limit: int) -> list[dict]:
    """Return the tail of *messages* that contains exactly *limit* user turns.

    Walks backwards counting ``role == "user"`` entries.  The slice starts
    immediately after the ``limit``-th-from-end user turn.

    If there are fewer than *limit* user turns, the full list is returned.
    """
    user_count = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_count += 1
            if user_count > limit:
                return messages[i + 1 :]
    return messages


async def archive_transcript(path: Path) -> None:
    """Rename *path* to ``<path>.deleted.<timestamp_ms>``."""
    ts_ms = int(time.time() * 1000)
    dest = Path(f"{path}.deleted.{ts_ms}")
    await asyncio.to_thread(os.rename, path, dest)
