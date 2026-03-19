"""memory_manager.py — Workspace .md file I/O (Subtask 4 — junior dev).

This module is imported by compaction.py and context_assembler.py.
Stub signatures are defined here so the package is importable while the
junior developer completes the full implementation.

Full implementation requirements (from team-plan.md Subtask 4):
- BOOTSTRAP_FILES / MINIMAL_BOOTSTRAP_FILES constants
- is_subagent_or_cron_key(session_key) -> bool
- async load_bootstrap_files(workspace_dir, session_key=None) -> list[dict]
  (2 MB truncation, case-fallback MEMORY.md/memory.md, silent skip on FileNotFoundError)
- async append_daily_note(workspace_dir, note) -> None  (creates memory/ subdir)
- async seed_workspace(workspace_dir) -> None  (exclusive-create 'x' mode)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_TWO_MB = 2 * 1024 * 1024

BOOTSTRAP_FILES: list[str] = [
    "SOUL.md",
    "AGENTS.md",
    "USER.md",
    "IDENTITY.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
]

MINIMAL_BOOTSTRAP_FILES: list[str] = [
    "SOUL.md",
    "AGENTS.md",
    "USER.md",
    "IDENTITY.md",
]


def is_subagent_or_cron_key(session_key: str) -> bool:
    """Return ``True`` if *session_key* represents a sub-agent or cron session."""
    if ":subagent:" in session_key:
        return True
    # cron key shape: agent:<id>:cron:...
    parts = session_key.split(":")
    return len(parts) >= 3 and parts[2] == "cron"


async def load_bootstrap_files(
    workspace_dir: Path,
    session_key: str | None = None,
) -> list[dict]:
    """Read workspace bootstrap files and return their contents.

    Selects ``MINIMAL_BOOTSTRAP_FILES`` for sub-agent / cron keys, otherwise
    ``BOOTSTRAP_FILES``.  Files that do not exist are silently skipped.  Content
    is truncated at 2 MB per file.

    Returns:
        ``[{"name": str, "path": str, "content": str}, ...]``
    """
    file_list = (
        MINIMAL_BOOTSTRAP_FILES
        if (session_key and is_subagent_or_cron_key(session_key))
        else BOOTSTRAP_FILES
    )

    def _read_all() -> list[dict]:
        results: list[dict] = []
        for filename in file_list:
            # Special case: try MEMORY.md then memory.md on case-sensitive filesystems.
            candidates = [filename]
            if filename == "MEMORY.md":
                candidates = ["MEMORY.md", "memory.md"]

            for candidate in candidates:
                fp = workspace_dir / candidate
                try:
                    content = fp.read_bytes()
                    if len(content) > _TWO_MB:
                        content = content[:_TWO_MB]
                    results.append(
                        {
                            "name": candidate,
                            "path": str(fp),
                            "content": content.decode("utf-8", errors="replace"),
                        }
                    )
                    break  # found — stop trying fallback names
                except FileNotFoundError:
                    continue  # try next candidate or skip silently
        return results

    return await asyncio.to_thread(_read_all)


async def append_daily_note(workspace_dir: Path, note: str) -> None:
    """Append *note* to today's daily-note file in ``<workspace_dir>/memory/``."""

    def _write() -> None:
        memory_dir = workspace_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        note_file = memory_dir / f"{date_str}.md"
        with open(note_file, "a", encoding="utf-8") as fh:
            fh.write("\n" + note + "\n")

    await asyncio.to_thread(_write)


async def seed_workspace(workspace_dir: Path) -> None:
    """Create *workspace_dir* and write empty bootstrap files (never overwrites existing)."""

    def _seed() -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for filename in BOOTSTRAP_FILES:
            fp = workspace_dir / filename
            try:
                with open(fp, "x", encoding="utf-8"):
                    pass  # empty file created via exclusive-create mode
            except FileExistsError:
                pass  # already present — never overwrite

    await asyncio.to_thread(_seed)
