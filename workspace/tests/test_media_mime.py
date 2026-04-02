"""
test_media_mime.py — Comprehensive tests for media/mime.py

Covers:
  - MIME detection priority: magic bytes > header > extension > fallback
  - Generic container override (e.g. .xlsx detected as zip by magic)
  - Extension lookup for all registered types
  - Edge cases: empty data, no hints, whitespace header
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.mime import (
    MIME_BY_EXT,
    _FALLBACK,
    _GENERIC_CONTAINER_MIMES,
    detect_mime,
)


# ---------------------------------------------------------------------------
# Extension-based detection (strategy 3)
# ---------------------------------------------------------------------------


class TestExtensionDetection:
    def test_all_image_extensions(self):
        assert detect_mime(b"", filename="photo.jpg") == "image/jpeg"
        assert detect_mime(b"", filename="photo.jpeg") == "image/jpeg"
        assert detect_mime(b"", filename="img.png") == "image/png"
        assert detect_mime(b"", filename="anim.gif") == "image/gif"
        assert detect_mime(b"", filename="photo.webp") == "image/webp"
        assert detect_mime(b"", filename="photo.heic") == "image/heic"
        assert detect_mime(b"", filename="photo.bmp") == "image/bmp"
        assert detect_mime(b"", filename="icon.svg") == "image/svg+xml"

    def test_video_extensions(self):
        assert detect_mime(b"", filename="clip.mp4") == "video/mp4"
        assert detect_mime(b"", filename="clip.mov") == "video/quicktime"
        assert detect_mime(b"", filename="clip.avi") == "video/x-msvideo"
        assert detect_mime(b"", filename="clip.mkv") == "video/x-matroska"
        assert detect_mime(b"", filename="clip.webm") == "video/webm"

    def test_audio_extensions(self):
        assert detect_mime(b"", filename="track.mp3") == "audio/mpeg"
        assert detect_mime(b"", filename="track.ogg") == "audio/ogg"
        assert detect_mime(b"", filename="track.flac") == "audio/flac"
        assert detect_mime(b"", filename="track.wav") == "audio/wav"
        assert detect_mime(b"", filename="track.opus") == "audio/opus"
        assert detect_mime(b"", filename="track.m4a") == "audio/mp4"

    def test_document_extensions(self):
        assert detect_mime(b"", filename="doc.pdf") == "application/pdf"
        assert detect_mime(b"", filename="doc.csv") == "text/csv"
        assert detect_mime(b"", filename="doc.rtf") == "application/rtf"
        assert detect_mime(b"", filename="book.epub") == "application/epub+zip"

    def test_archive_extensions(self):
        assert detect_mime(b"", filename="archive.zip") == "application/zip"
        assert detect_mime(b"", filename="archive.gz") == "application/gzip"
        assert detect_mime(b"", filename="archive.tar") == "application/x-tar"
        assert detect_mime(b"", filename="archive.7z") == "application/x-7z-compressed"
        assert detect_mime(b"", filename="archive.rar") == "application/vnd.rar"

    def test_case_insensitive_extension(self):
        assert detect_mime(b"", filename="PHOTO.JPG") == "image/jpeg"
        assert detect_mime(b"", filename="Doc.PDF") == "application/pdf"

    def test_unknown_extension_falls_through(self):
        # No magic, no header, unknown extension -> fallback
        result = detect_mime(b"", filename="file.xyz")
        assert result == _FALLBACK


# ---------------------------------------------------------------------------
# Header MIME detection (strategy 2)
# ---------------------------------------------------------------------------


class TestHeaderMimeDetection:
    def test_header_used_when_no_magic_or_extension(self):
        result = detect_mime(b"", header_mime="text/plain")
        assert result == "text/plain"

    def test_header_stripped_of_whitespace(self):
        result = detect_mime(b"", header_mime="  image/gif  ")
        assert result == "image/gif"

    def test_octet_stream_header_ignored(self):
        # application/octet-stream header falls through to extension
        result = detect_mime(b"", header_mime="application/octet-stream", filename="test.mp4")
        assert result == "video/mp4"

    def test_empty_header_ignored(self):
        result = detect_mime(b"", header_mime="   ", filename="test.png")
        assert result == "image/png"

    def test_header_preferred_over_extension(self):
        # When header is set and no magic, header wins over extension
        result = detect_mime(b"", header_mime="audio/flac", filename="file.txt")
        assert result == "audio/flac"


# ---------------------------------------------------------------------------
# Magic bytes detection (strategy 1)
# ---------------------------------------------------------------------------


class TestMagicBytesDetection:
    def test_magic_overrides_header_and_extension(self):
        """When python-magic detects a non-generic type, it wins."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.return_value = "image/png"
            result = detect_mime(b"\x89PNG", header_mime="image/jpeg", filename="test.jpg")
            assert result == "image/png"

    def test_magic_fallback_ignored_when_octet_stream(self):
        """If magic returns application/octet-stream, it falls through."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.return_value = "application/octet-stream"
            result = detect_mime(b"data", header_mime="text/plain")
            assert result == "text/plain"

    def test_magic_exception_handled(self):
        """If python-magic raises, falls through gracefully."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.side_effect = RuntimeError("magic failed")
            result = detect_mime(b"data", header_mime="image/jpeg")
            assert result == "image/jpeg"

    def test_magic_not_called_on_empty_data(self):
        """Magic is skipped when data is empty (len(data) == 0)."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            detect_mime(b"", header_mime="image/jpeg")
            mock_magic.from_buffer.assert_not_called()

    def test_magic_unavailable(self):
        """When python-magic is not installed, falls through to other strategies."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", False):
            result = detect_mime(b"\x89PNG", filename="test.png")
            assert result == "image/png"


# ---------------------------------------------------------------------------
# Generic container override
# ---------------------------------------------------------------------------


class TestGenericContainerOverride:
    def test_xlsx_zip_override(self):
        """Magic detects ZIP but extension says .xlsx -> prefer extension."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.return_value = "application/zip"
            result = detect_mime(b"PK\x03\x04", filename="spreadsheet.xlsx")
            expected = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            assert result == expected

    def test_docx_zip_override(self):
        """Magic detects ZIP but extension says .docx -> prefer extension."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.return_value = "application/zip"
            result = detect_mime(b"PK\x03\x04", filename="document.docx")
            expected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            assert result == expected

    def test_generic_zip_with_no_extension_returns_zip(self):
        """Magic detects ZIP with no filename -> returns zip."""
        with patch("sci_fi_dashboard.media.mime._MAGIC_AVAILABLE", True), \
             patch("sci_fi_dashboard.media.mime.magic") as mock_magic:
            mock_magic.from_buffer.return_value = "application/zip"
            result = detect_mime(b"PK\x03\x04")
            assert result == "application/zip"


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


class TestFallback:
    def test_all_none_returns_octet_stream(self):
        result = detect_mime(b"")
        assert result == "application/octet-stream"

    def test_no_data_no_hints(self):
        result = detect_mime(b"", header_mime=None, filename=None)
        assert result == "application/octet-stream"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestMimeConstants:
    def test_mime_by_ext_is_dict(self):
        assert isinstance(MIME_BY_EXT, dict)
        assert len(MIME_BY_EXT) > 20

    def test_generic_container_mimes_is_frozenset(self):
        assert isinstance(_GENERIC_CONTAINER_MIMES, frozenset)
        assert "application/zip" in _GENERIC_CONTAINER_MIMES
