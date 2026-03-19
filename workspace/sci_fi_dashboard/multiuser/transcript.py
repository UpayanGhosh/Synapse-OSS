"""transcript.py — JSONL transcript I/O (Subtask 3 — junior dev).

This module is imported by compaction.py and context_assembler.py.
Stub signatures are defined here so the package is importable while the
junior developer completes the full implementation.

Full implementation requirements (from team-plan.md Subtask 3):
- transcript_path(session_entry, data_root, agent_id) -> Path
- async append_message(path, message: dict) -> None  (asyncio.to_thread)
- async load_messages(path, limit=None) -> list[dict]  (skip corrupt lines + limit)
- limit_history_turns(messages, limit) -> list[dict]  (walk-backwards user-count)
- async archive_transcript(path) -> None  (rename to .deleted.<ms>)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from sci_fi_dashboard.multiuser.session_store import SessionEntry

logger = logging.getLogger(__name__)


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
