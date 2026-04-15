"""
Test Suite: File Operations
============================
Tests for file_ops/edit.py, file_ops/paging.py, and file_ops/workspace_guard.py.

Covers:
- apply_edit: text replacement, atomic writes, edge cases
- read_file_paged: adaptive paging, binary detection, offset continuation
- WorkspaceGuard: path traversal prevention, read/write mode enforcement
"""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.file_ops.edit import apply_edit
from sci_fi_dashboard.file_ops.paging import (
    DEFAULT_PAGE_MAX_BYTES,
    read_file_paged,
)
from sci_fi_dashboard.file_ops.workspace_guard import WorkspaceGuard

# ---------------------------------------------------------------------------
# apply_edit
# ---------------------------------------------------------------------------


class TestApplyEdit:
    """Tests for file_ops/edit.py — text patch application."""

    @pytest.mark.unit
    def test_basic_replacement(self, tmp_path):
        """Replace a unique string in a file."""
        f = tmp_path / "test.txt"
        f.write_text("hello world, hello universe", encoding="utf-8")

        result = apply_edit(str(f), "world", "planet", expected_count=1)
        assert result["ok"] is True
        assert result["replacements"] == 1
        assert f.read_text(encoding="utf-8") == "hello planet, hello universe"

    @pytest.mark.unit
    def test_old_text_not_found(self, tmp_path):
        """When old_text is not in the file, return error."""
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")

        result = apply_edit(str(f), "nonexistent", "replacement")
        assert result["ok"] is False
        assert "not found" in result["error"]

    @pytest.mark.unit
    def test_more_occurrences_than_expected(self, tmp_path):
        """When old_text appears more times than expected_count, return error."""
        f = tmp_path / "test.txt"
        f.write_text("aaa bbb aaa bbb aaa", encoding="utf-8")

        result = apply_edit(str(f), "aaa", "ccc", expected_count=1)
        assert result["ok"] is False
        assert "found 3 times" in result["error"]

    @pytest.mark.unit
    def test_replace_multiple_occurrences(self, tmp_path):
        """Replace exactly expected_count occurrences."""
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo bar foo", encoding="utf-8")

        result = apply_edit(str(f), "foo", "baz", expected_count=2)
        assert result["ok"] is True
        assert result["replacements"] == 2
        content = f.read_text(encoding="utf-8")
        assert content == "baz bar baz bar foo"

    @pytest.mark.unit
    def test_atomic_write_survives_content(self, tmp_path):
        """The written file should have correct byte count."""
        f = tmp_path / "test.txt"
        f.write_text("original content", encoding="utf-8")

        result = apply_edit(str(f), "original", "modified")
        assert result["ok"] is True
        assert result["bytes_written"] == len(b"modified content")

    @pytest.mark.unit
    def test_multiline_replacement(self, tmp_path):
        """Replace text spanning multiple lines."""
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")

        result = apply_edit(str(f), "line2\nline3", "replaced2\nreplaced3")
        assert result["ok"] is True
        content = f.read_text(encoding="utf-8")
        assert "replaced2\nreplaced3" in content

    @pytest.mark.unit
    def test_empty_new_text_deletes_old(self, tmp_path):
        """Replacing with empty string effectively deletes the old text."""
        f = tmp_path / "test.txt"
        f.write_text("hello cruel world", encoding="utf-8")

        result = apply_edit(str(f), " cruel", "")
        assert result["ok"] is True
        assert f.read_text(encoding="utf-8") == "hello world"

    @pytest.mark.unit
    def test_unicode_content(self, tmp_path):
        """Handle unicode content correctly."""
        f = tmp_path / "test.txt"
        f.write_text("hello \u2603 snowman", encoding="utf-8")

        result = apply_edit(str(f), "\u2603", "\u2764")
        assert result["ok"] is True
        assert "\u2764" in f.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# read_file_paged
# ---------------------------------------------------------------------------


class TestReadFilePaged:
    """Tests for file_ops/paging.py — adaptive paged file reading."""

    @pytest.mark.unit
    def test_small_file_not_truncated(self, tmp_path):
        """A file smaller than the page size should not be truncated."""
        f = tmp_path / "small.txt"
        f.write_text("small content", encoding="utf-8")

        result = read_file_paged(str(f))
        assert result["content"] == "small content"
        assert result["truncated"] is False
        assert result["next_offset"] is None

    @pytest.mark.unit
    def test_large_file_truncated(self, tmp_path):
        """A file larger than page size should be truncated with next_offset."""
        f = tmp_path / "large.txt"
        # Write more than DEFAULT_PAGE_MAX_BYTES (50KB)
        content = "x" * (DEFAULT_PAGE_MAX_BYTES + 1000)
        f.write_text(content, encoding="utf-8")

        result = read_file_paged(str(f))
        assert result["truncated"] is True
        assert result["next_offset"] is not None
        assert result["notice"] is not None
        assert len(result["content"]) <= DEFAULT_PAGE_MAX_BYTES

    @pytest.mark.unit
    def test_offset_continuation(self, tmp_path):
        """Reading with offset should continue from that position."""
        f = tmp_path / "large.txt"
        content = "A" * 100 + "B" * 100
        f.write_bytes(content.encode("utf-8"))

        result = read_file_paged(str(f), offset=100, page_bytes=100)
        assert result["content"].startswith("B")
        assert result["offset"] == 100

    @pytest.mark.unit
    def test_custom_page_bytes(self, tmp_path):
        """Custom page_bytes should be respected (clamped to min/max)."""
        f = tmp_path / "test.txt"
        content = "x" * 200000
        f.write_text(content, encoding="utf-8")

        # page_bytes below minimum is clamped to DEFAULT_PAGE_MAX_BYTES
        result = read_file_paged(str(f), page_bytes=100)
        assert result["bytes_read"] == DEFAULT_PAGE_MAX_BYTES

    @pytest.mark.unit
    def test_adaptive_context_tokens(self, tmp_path):
        """model_context_tokens should influence page size."""
        f = tmp_path / "test.txt"
        content = "x" * 200000
        f.write_text(content, encoding="utf-8")

        # 100k tokens * 4 chars * 0.2 share = 80000 chars
        result = read_file_paged(str(f), model_context_tokens=100000)
        assert result["bytes_read"] == 80000

    @pytest.mark.unit
    def test_binary_file_detected(self, tmp_path):
        """Binary files should be detected and return is_binary=True."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd" * 1000)

        # Patch the MIME detector to return None (no image)
        with patch(
            "sci_fi_dashboard.file_ops.paging._load_detect_mime",
            return_value=None,
        ):
            result = read_file_paged(str(f))
        assert result["is_binary"] is True
        assert "Binary file" in result["content"]

    @pytest.mark.unit
    def test_total_size_reported(self, tmp_path):
        """total_size should match the actual file size."""
        f = tmp_path / "sized.txt"
        content = "hello world"
        f.write_text(content, encoding="utf-8")

        result = read_file_paged(str(f))
        assert result["total_size"] == os.path.getsize(str(f))

    @pytest.mark.unit
    def test_bytes_read_accurate(self, tmp_path):
        """bytes_read should reflect actual bytes read."""
        f = tmp_path / "test.txt"
        content = "abcde"
        f.write_text(content, encoding="utf-8")

        result = read_file_paged(str(f))
        assert result["bytes_read"] == len(content.encode("utf-8"))

    @pytest.mark.unit
    def test_empty_file(self, tmp_path):
        """Empty file should return empty content, not truncated."""
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        result = read_file_paged(str(f))
        assert result["content"] == ""
        assert result["truncated"] is False
        assert result["bytes_read"] == 0


# ---------------------------------------------------------------------------
# WorkspaceGuard
# ---------------------------------------------------------------------------


class TestWorkspaceGuard:
    """Tests for file_ops/workspace_guard.py — path traversal prevention."""

    @pytest.fixture
    def guard(self, tmp_path):
        """Create a WorkspaceGuard rooted in tmp_path."""
        return WorkspaceGuard(tmp_path, mode="rw")

    @pytest.fixture
    def ro_guard(self, tmp_path):
        """Create a read-only WorkspaceGuard."""
        return WorkspaceGuard(tmp_path, mode="ro")

    @pytest.fixture
    def disabled_guard(self, tmp_path):
        """Create a disabled WorkspaceGuard."""
        return WorkspaceGuard(tmp_path, mode="none")

    @pytest.mark.unit
    def test_resolve_relative_path(self, guard, tmp_path):
        """Relative paths should be resolved relative to workspace root."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file.txt").write_text("ok")

        resolved = guard.assert_readable("subdir/file.txt")
        assert resolved == (tmp_path / "subdir" / "file.txt").resolve()

    @pytest.mark.unit
    def test_resolve_absolute_path_within_root(self, guard, tmp_path):
        """Absolute paths within root should resolve successfully."""
        f = tmp_path / "file.txt"
        f.write_text("ok")

        resolved = guard.assert_readable(str(f))
        assert resolved == f.resolve()

    @pytest.mark.unit
    def test_path_traversal_rejected(self, guard):
        """Paths escaping the workspace root should raise PermissionError."""
        with pytest.raises(PermissionError, match="Path escape"):
            guard.assert_readable("../../etc/passwd")

    @pytest.mark.unit
    def test_null_byte_rejected(self, guard):
        """Paths with null bytes should be rejected."""
        with pytest.raises(PermissionError, match="null bytes"):
            guard.assert_readable("file\x00.txt")

    @pytest.mark.unit
    def test_assert_writable_in_rw_mode(self, guard, tmp_path):
        """In rw mode, assert_writable should succeed for valid paths."""
        f = tmp_path / "writable.txt"
        f.write_text("ok")

        resolved = guard.assert_writable(str(f))
        assert resolved == f.resolve()

    @pytest.mark.unit
    def test_assert_writable_in_ro_mode_raises(self, ro_guard, tmp_path):
        """In ro mode, assert_writable should raise PermissionError."""
        f = tmp_path / "file.txt"
        f.write_text("ok")

        with pytest.raises(PermissionError, match="read-only"):
            ro_guard.assert_writable(str(f))

    @pytest.mark.unit
    def test_assert_writable_in_none_mode_raises(self, disabled_guard, tmp_path):
        """In none mode, assert_writable should raise PermissionError."""
        f = tmp_path / "file.txt"
        f.write_text("ok")

        with pytest.raises(PermissionError, match="disabled"):
            disabled_guard.assert_writable(str(f))

    @pytest.mark.unit
    def test_assert_readable_in_ro_mode_succeeds(self, ro_guard, tmp_path):
        """In ro mode, assert_readable should still work."""
        f = tmp_path / "file.txt"
        f.write_text("ok")

        resolved = ro_guard.assert_readable(str(f))
        assert resolved == f.resolve()

    @pytest.mark.unit
    def test_root_is_resolved(self, tmp_path):
        """WorkspaceGuard root should be resolved (no symlinks)."""
        guard = WorkspaceGuard(tmp_path)
        assert guard.root == tmp_path.resolve()

    @pytest.mark.unit
    def test_path_traversal_with_dotdot(self, guard):
        """../../../ patterns should be caught."""
        with pytest.raises(PermissionError, match="Path escape"):
            guard.assert_readable("subdir/../../../etc/passwd")

    @pytest.mark.unit
    def test_deeply_nested_valid_path(self, guard, tmp_path):
        """Deep paths within root should resolve correctly."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        f = deep / "deep.txt"
        f.write_text("deep content")

        resolved = guard.assert_readable("a/b/c/deep.txt")
        assert resolved == f.resolve()
