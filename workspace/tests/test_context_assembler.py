"""Tests for multiuser/context_assembler.py — build_system_prompt and assemble_context gaps.

Fills gaps not covered in test_multiuser.py:
- build_system_prompt() identity line, project context, authorized senders
- CONTEXT_WINDOW_WARN_TOKENS warning threshold
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from sci_fi_dashboard.multiuser.context_assembler import (
        CONTEXT_WINDOW_HARD_MIN_TOKENS,
        CONTEXT_WINDOW_WARN_TOKENS,
        ContextWindowTooSmallError,
        build_system_prompt,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(not AVAILABLE, reason="context_assembler not available")


@_skip
class TestBuildSystemPrompt:

    def test_identity_line(self):
        prompt = build_system_prompt([], "jarvis", "session:123")
        assert "You are jarvis" in prompt
        assert "Session: session:123" in prompt

    def test_project_context_section(self):
        files = [{"name": "SOUL.md", "path": "/ws/SOUL.md", "content": "Be helpful."}]
        prompt = build_system_prompt(files, "jarvis", "s1")
        assert "# Project Context" in prompt
        assert "## SOUL.md" in prompt
        assert "Be helpful." in prompt

    def test_multiple_bootstrap_files(self):
        files = [
            {"name": "SOUL.md", "path": "/ws/SOUL.md", "content": "Soul content."},
            {"name": "AGENTS.md", "path": "/ws/AGENTS.md", "content": "Agent config."},
        ]
        prompt = build_system_prompt(files, "bot", "s1")
        assert "## SOUL.md" in prompt
        assert "## AGENTS.md" in prompt
        assert "Soul content." in prompt
        assert "Agent config." in prompt

    def test_no_bootstrap_files(self):
        prompt = build_system_prompt([], "bot", "s1")
        assert "# Project Context" not in prompt

    def test_authorized_senders_section(self):
        prompt = build_system_prompt(
            [], "bot", "s1", extra_context={"allow_from": ["alice", "bob"]}
        )
        assert "## Authorized Senders" in prompt
        assert "alice" in prompt
        assert "bob" in prompt

    def test_no_authorized_senders_when_empty(self):
        prompt = build_system_prompt([], "bot", "s1", extra_context={"allow_from": []})
        assert "## Authorized Senders" not in prompt

    def test_no_authorized_senders_without_extra_context(self):
        prompt = build_system_prompt([], "bot", "s1")
        assert "## Authorized Senders" not in prompt

    def test_empty_file_content_handled(self):
        files = [{"name": "EMPTY.md", "path": "/ws/EMPTY.md", "content": ""}]
        prompt = build_system_prompt(files, "bot", "s1")
        assert "## EMPTY.md" in prompt


@_skip
class TestConstants:

    def test_hard_min_tokens(self):
        assert CONTEXT_WINDOW_HARD_MIN_TOKENS == 16_000

    def test_warn_tokens(self):
        assert CONTEXT_WINDOW_WARN_TOKENS == 32_000

    def test_exception_class(self):
        """ContextWindowTooSmallError is an Exception subclass."""
        assert issubclass(ContextWindowTooSmallError, Exception)
        exc = ContextWindowTooSmallError("test")
        assert str(exc) == "test"
