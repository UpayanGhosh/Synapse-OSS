"""
test_media_outbound.py — Tests for media/outbound_attachment.py

Covers:
  - resolve_media_path with media:// URIs
  - Security checks: empty ID, null byte, path separator, directory traversal
  - Plain file path resolution within media root
  - Plain file path outside media root blocked
  - Non-existent files
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.outbound_attachment import (
    MediaResolutionError,
    resolve_media_path,
)


class TestMediaURIResolution:
    def test_empty_media_id_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Empty media ID"):
            resolve_media_path("media://inbound/", media_root=media_root)

    def test_null_byte_in_id_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Null byte"):
            resolve_media_path("media://inbound/abc\x00def", media_root=media_root)

    def test_path_separator_in_id_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Path separator"):
            resolve_media_path("media://inbound/abc/def", media_root=media_root)

    def test_directory_traversal_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Directory traversal"):
            resolve_media_path("media://inbound/abc..def", media_root=media_root)

    def test_unsafe_characters_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Unsafe characters"):
            resolve_media_path("media://inbound/abc def", media_root=media_root)

    def test_media_dir_not_found(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        with pytest.raises(MediaResolutionError, match="Media directory not found"):
            resolve_media_path("media://inbound/abc123", media_root=media_root)

    def test_no_matching_file(self, tmp_path):
        media_root = tmp_path / "media"
        inbound = media_root / "inbound"
        inbound.mkdir(parents=True)
        with pytest.raises(MediaResolutionError, match="No media file found"):
            resolve_media_path("media://inbound/nonexistent", media_root=media_root)

    def test_resolves_existing_file(self, tmp_path):
        media_root = tmp_path / "media"
        inbound = media_root / "inbound"
        inbound.mkdir(parents=True)
        # Create a file matching the store naming pattern
        test_file = inbound / "inbound---abc123.jpg"
        test_file.write_bytes(b"data")

        result = resolve_media_path("media://inbound/abc123", media_root=media_root)
        assert result == str(test_file)


class TestPlainPathResolution:
    def test_path_inside_media_root(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()
        f = media_root / "test.jpg"
        f.write_bytes(b"data")

        result = resolve_media_path(str(f), media_root=media_root)
        assert result == str(f.resolve())

    def test_path_outside_media_root_blocked(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        f = outside / "secret.txt"
        f.write_text("secret")

        media_root = tmp_path / "media"
        media_root.mkdir()

        with pytest.raises(MediaResolutionError, match="resolves outside media root"):
            resolve_media_path(str(f), media_root=media_root)

    def test_nonexistent_file_rejected(self, tmp_path):
        media_root = tmp_path / "media"
        media_root.mkdir()

        with pytest.raises(MediaResolutionError, match="File not found"):
            resolve_media_path(str(media_root / "nope.txt"), media_root=media_root)
