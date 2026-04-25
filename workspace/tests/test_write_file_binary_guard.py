"""
Test Suite: write_file Binary Guard
====================================
The write_file tool refuses binary file extensions early (before Sentinel) and
returns an actionable error message that teaches the LLM the right alternative
path — POST /add for memory.db, sqlite3/ffmpeg/etc. for other binaries.

Triggered by the 2026-04-25 incident: bot tried write_file('memory.db', ...),
got Sentinel-blocked, and surrendered with "I can't update memory.db". The
guard's purpose is procedural guidance, not security (Sentinel still gates
everything else).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.tool_registry import (
    BINARY_WRITE_EXTENSIONS,
    ToolContext,
    _write_file_factory,
)


@pytest.fixture
def owner_context() -> ToolContext:
    """Owner context — write_file factory returns a tool only for owners."""
    return ToolContext(
        chat_id="chat_test",
        sender_id="owner_test",
        sender_is_owner=True,
        workspace_dir="/tmp/synapse",
        config={},
        channel_id="whatsapp",
    )


class TestWriteFileBinaryGuard:
    """Binary-extension guard fires before Sentinel with an actionable error."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_file_binary_db_returns_actionable_error(
        self, owner_context, tmp_path
    ):
        """When LLM tries write_file on memory.db, error teaches it to use POST /add."""
        tool = _write_file_factory(owner_context)
        assert tool is not None, "factory should return a tool for owner context"

        result = await tool.execute(
            {"path": str(tmp_path / "memory.db"), "content": "stuff"}
        )

        assert result.is_error, "binary-extension write should be refused"
        err_text = (
            result.content if hasattr(result, "content") else str(result)
        ).lower()
        # The error message must teach the LLM what to do:
        #   * mention "binary" so the LLM understands WHY it was refused
        #   * point at POST /add as the proper memorization path
        #   * reference MEMORY.md so the LLM can re-read for the full procedure
        assert "binary" in err_text
        assert "/add" in err_text or "post" in err_text
        assert "memory.md" in err_text or "memory ingestion" in err_text

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_file_text_file_does_not_trigger_binary_guard(
        self, owner_context, tmp_path
    ):
        """write_file on .md / .txt / .py does NOT trip the binary guard.

        The call may still fail Sentinel for path-policy reasons (Sentinel runs
        only when initialized with a project_root, and tests don't init it),
        but the binary guard itself must NOT fire — the error path differs.
        """
        tool = _write_file_factory(owner_context)
        assert tool is not None

        result = await tool.execute(
            {"path": str(tmp_path / "notes.md"), "content": "# hi"}
        )

        err_text = (
            (result.content if hasattr(result, "content") else "") or ""
        ).lower()
        # The binary-guard error message specifically says "binary file" — it
        # must NOT appear here. Whether the write itself succeeded or hit a
        # different error (Sentinel uninitialized, etc.) is orthogonal.
        assert "binary file" not in err_text
        # Likewise, the binary-guard's MEMORY.md hint must not fire on text.
        assert "memory ingestion protocol" not in err_text

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_file_other_binary_extensions_refused(
        self, owner_context, tmp_path
    ):
        """A representative sample of binary extensions also trip the guard."""
        tool = _write_file_factory(owner_context)
        assert tool is not None

        # Spot-check a handful of representative extensions across the
        # categories the guard covers (DB, archive, image, audio, video, doc).
        for filename in (
            "data.sqlite",
            "archive.zip",
            "photo.png",
            "voice.ogg",
            "clip.mp4",
            "doc.pdf",
        ):
            result = await tool.execute(
                {"path": str(tmp_path / filename), "content": "stuff"}
            )
            assert result.is_error, f"{filename} should be refused"
            err_text = (
                result.content if hasattr(result, "content") else str(result)
            ).lower()
            assert "binary" in err_text, f"{filename}: missing 'binary' in error"

    @pytest.mark.unit
    def test_binary_extensions_set_includes_memory_db(self):
        """memory.db's extension must be in the canonical guard set."""
        assert ".db" in BINARY_WRITE_EXTENSIONS
        assert ".sqlite" in BINARY_WRITE_EXTENSIONS
        assert ".sqlite3" in BINARY_WRITE_EXTENSIONS
