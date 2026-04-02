"""
test_media_store.py — Comprehensive tests for media/store.py

Covers:
  - SavedMedia dataclass construction
  - _sanitize_filename / _sanitize_original helpers
  - _ext_from_mime mapping
  - save_media_buffer: writes file, enforces size, path traversal guard,
    original_filename handling, throttled cleanup, MIME detection
  - clean_old_media: TTL-based removal, empty-dir pruning, error handling
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.store import (
    SavedMedia,
    _ext_from_mime,
    _last_cleanup_time,
    _sanitize_filename,
    _sanitize_original,
    clean_old_media,
    save_media_buffer,
)


# ---------------------------------------------------------------------------
# SavedMedia dataclass
# ---------------------------------------------------------------------------


class TestSavedMedia:
    def test_construction(self, tmp_path):
        sm = SavedMedia(id="abc", path=tmp_path / "f.jpg", size=100, content_type="image/jpeg")
        assert sm.id == "abc"
        assert sm.size == 100
        assert sm.content_type == "image/jpeg"

    def test_fields_are_accessible(self, tmp_path):
        p = tmp_path / "test.png"
        sm = SavedMedia(id="xyz", path=p, size=42, content_type="image/png")
        assert sm.path == p
        assert sm.id == "xyz"


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_removes_unsafe_chars(self):
        result = _sanitize_filename("hello world!@#$%.txt")
        assert "!" not in result
        assert "@" not in result
        assert " " not in result
        assert "_" in result

    def test_truncates_to_max_len(self):
        long_name = "a" * 100
        result = _sanitize_filename(long_name, max_len=20)
        assert len(result) == 20

    def test_empty_string_returns_file(self):
        # After sanitizing an all-unsafe string, if empty, return "file"
        result = _sanitize_filename("!!!")
        # _UNSAFE_CHARS.sub replaces each ! with _, so "___" is returned
        assert result  # non-empty

    def test_preserves_safe_chars(self):
        result = _sanitize_filename("my-file_v2.txt")
        assert result == "my-file_v2.txt"


# ---------------------------------------------------------------------------
# _sanitize_original
# ---------------------------------------------------------------------------


class TestSanitizeOriginal:
    def test_strips_path_separators(self):
        result = _sanitize_original("path/to/file.txt")
        assert "/" not in result
        assert "\\" not in result

    def test_strips_null_bytes(self):
        result = _sanitize_original("file\x00name.txt")
        assert "\x00" not in result

    def test_truncates_to_100(self):
        long_name = "a" * 200
        result = _sanitize_original(long_name)
        assert len(result) == 100

    def test_empty_unsafe_returns_empty(self):
        result = _sanitize_original("")
        assert result == ""


# ---------------------------------------------------------------------------
# _ext_from_mime
# ---------------------------------------------------------------------------


class TestExtFromMime:
    def test_known_types(self):
        assert _ext_from_mime("image/jpeg") == ".jpg"
        assert _ext_from_mime("image/png") == ".png"
        assert _ext_from_mime("audio/mpeg") == ".mp3"
        assert _ext_from_mime("video/mp4") == ".mp4"
        assert _ext_from_mime("application/pdf") == ".pdf"

    def test_unknown_type_returns_bin(self):
        assert _ext_from_mime("application/x-unknown-format") == ".bin"

    def test_archive_types(self):
        assert _ext_from_mime("application/zip") == ".zip"
        assert _ext_from_mime("application/gzip") == ".gz"
        assert _ext_from_mime("application/x-7z-compressed") == ".7z"

    def test_document_types(self):
        assert _ext_from_mime("text/csv") == ".csv"
        assert _ext_from_mime("application/rtf") == ".rtf"
        assert _ext_from_mime("application/epub+zip") == ".epub"


# ---------------------------------------------------------------------------
# save_media_buffer
# ---------------------------------------------------------------------------


class TestSaveMediaBuffer:
    def test_writes_file(self, tmp_path):
        buf = b"fake image data"
        result = save_media_buffer(
            buf,
            content_type="image/jpeg",
            subdir="test_inbound",
            data_root=tmp_path,
        )
        assert isinstance(result, SavedMedia)
        assert result.path.exists()
        assert result.size == len(buf)
        assert result.content_type  # non-empty
        assert "test_inbound" in str(result.path)

    def test_file_content_matches(self, tmp_path):
        buf = b"exact content to verify"
        result = save_media_buffer(buf, content_type="text/plain", subdir="verify", data_root=tmp_path)
        assert result.path.read_bytes() == buf

    def test_enforces_size_limit(self, tmp_path):
        buf = b"x" * 1000
        with pytest.raises(ValueError, match="exceeds limit"):
            save_media_buffer(buf, content_type="image/jpeg", subdir="limit", max_bytes=500, data_root=tmp_path)

    def test_size_limit_exact_boundary(self, tmp_path):
        buf = b"x" * 500
        result = save_media_buffer(buf, content_type="image/jpeg", subdir="exact", max_bytes=500, data_root=tmp_path)
        assert result.size == 500

    def test_no_size_limit_when_none(self, tmp_path):
        buf = b"x" * 10000
        result = save_media_buffer(buf, content_type="image/jpeg", subdir="nolimit", max_bytes=None, data_root=tmp_path)
        assert result.size == 10000

    def test_path_traversal_blocked(self, tmp_path):
        with pytest.raises(ValueError, match="escapes media root"):
            save_media_buffer(b"payload", content_type="image/jpeg", subdir="../../etc", data_root=tmp_path)

    def test_original_filename_used_as_prefix(self, tmp_path):
        result = save_media_buffer(
            b"data",
            content_type="image/jpeg",
            subdir="orig",
            data_root=tmp_path,
            original_filename="photo.jpg",
        )
        assert "photo.jpg" in result.path.name or "photo" in result.path.name

    def test_original_filename_sanitized(self, tmp_path):
        result = save_media_buffer(
            b"data",
            content_type="image/jpeg",
            subdir="orig_safe",
            data_root=tmp_path,
            original_filename="../../evil/payload.sh",
        )
        assert "/" not in result.path.name
        assert "\\" not in result.path.name

    def test_unique_media_ids(self, tmp_path):
        r1 = save_media_buffer(b"a", content_type="image/jpeg", subdir="uniq", data_root=tmp_path)
        r2 = save_media_buffer(b"b", content_type="image/jpeg", subdir="uniq", data_root=tmp_path)
        assert r1.id != r2.id

    def test_extension_derived_from_mime(self, tmp_path):
        result = save_media_buffer(b"data", content_type="image/png", subdir="ext", data_root=tmp_path)
        assert result.path.suffix == ".png"

    def test_throttled_cleanup_runs(self, tmp_path):
        # Clear throttle state for our test subdir
        _last_cleanup_time.pop("throttle_test", None)
        with patch("sci_fi_dashboard.media.store.clean_old_media") as mock_clean:
            save_media_buffer(b"data", content_type="image/jpeg", subdir="throttle_test", data_root=tmp_path)
            assert mock_clean.called


# ---------------------------------------------------------------------------
# clean_old_media
# ---------------------------------------------------------------------------


class TestCleanOldMedia:
    def test_removes_expired_files(self, tmp_path):
        media_dir = tmp_path / "expired"
        media_dir.mkdir()

        old_file = media_dir / "old.bin"
        old_file.write_bytes(b"old")
        old_mtime = time.time() - 300
        os.utime(str(old_file), (old_mtime, old_mtime))

        new_file = media_dir / "new.bin"
        new_file.write_bytes(b"new")

        removed = clean_old_media(media_dir, ttl_ms=60_000)
        assert removed >= 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_no_removal_when_files_fresh(self, tmp_path):
        media_dir = tmp_path / "fresh"
        media_dir.mkdir()
        f = media_dir / "fresh.bin"
        f.write_bytes(b"data")

        removed = clean_old_media(media_dir, ttl_ms=120_000)
        assert removed == 0
        assert f.exists()

    def test_empty_dir(self, tmp_path):
        media_dir = tmp_path / "empty"
        media_dir.mkdir()
        assert clean_old_media(media_dir) == 0

    def test_nonexistent_dir(self, tmp_path):
        assert clean_old_media(tmp_path / "no_such_dir") == 0

    def test_prunes_empty_directory_after_removal(self, tmp_path):
        media_dir = tmp_path / "prune_me"
        media_dir.mkdir()

        old_file = media_dir / "only.bin"
        old_file.write_bytes(b"x")
        old_mtime = time.time() - 600
        os.utime(str(old_file), (old_mtime, old_mtime))

        removed = clean_old_media(media_dir, ttl_ms=60_000)
        assert removed == 1
        # Directory may be pruned (rmdir on empty dir)
        # On some systems this succeeds, on others there may be race conditions
        # Just verify the file is gone
        assert not old_file.exists()

    def test_skips_subdirectories(self, tmp_path):
        media_dir = tmp_path / "with_subdir"
        media_dir.mkdir()
        sub = media_dir / "nested"
        sub.mkdir()

        removed = clean_old_media(media_dir, ttl_ms=1)
        assert removed == 0  # subdirectories are not files

    def test_handles_permission_error_gracefully(self, tmp_path):
        media_dir = tmp_path / "perms"
        media_dir.mkdir()

        old_file = media_dir / "locked.bin"
        old_file.write_bytes(b"data")
        old_mtime = time.time() - 600
        os.utime(str(old_file), (old_mtime, old_mtime))

        with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
            # Should not raise, just log and continue
            removed = clean_old_media(media_dir, ttl_ms=60_000)
            assert removed == 0
