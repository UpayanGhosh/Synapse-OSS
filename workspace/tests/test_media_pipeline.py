"""
Tests for the media pipeline — MIME detection, size enforcement, TTL cleanup,
SSRF guard, and SavedMedia construction.

Covers:
  - detect_mime with known extension returns correct MIME
  - detect_mime fallback to header_mime
  - detect_mime fallback to application/octet-stream
  - media_kind_from_mime("image/jpeg") returns MediaKind.IMAGE
  - max_bytes_for_kind(MediaKind.IMAGE) returns 6 MB
  - save_media_buffer writes file to correct location (use tmp_path)
  - save_media_buffer enforces size limit (raises ValueError)
  - clean_old_media removes expired files (use tmp_path)
  - is_ssrf_blocked("http://127.0.0.1") returns True
  - is_ssrf_blocked("http://10.0.0.1") returns True
  - is_ssrf_blocked("https://api.openai.com") returns False
  - SavedMedia construction
"""

import os
import sys
import time
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.media.constants import (
        MAX_IMAGE_BYTES,
        MediaKind,
        max_bytes_for_kind,
        media_kind_from_mime,
    )

    CONSTANTS_AVAILABLE = True
except ImportError:
    CONSTANTS_AVAILABLE = False

try:
    from sci_fi_dashboard.media.mime import detect_mime

    MIME_AVAILABLE = True
except ImportError:
    MIME_AVAILABLE = False

try:
    from sci_fi_dashboard.media.store import SavedMedia, clean_old_media, save_media_buffer

    STORE_AVAILABLE = True
except ImportError:
    STORE_AVAILABLE = False

try:
    from sci_fi_dashboard.media.ssrf import is_ssrf_blocked

    SSRF_AVAILABLE = True
except ImportError:
    SSRF_AVAILABLE = False

_skip_constants = pytest.mark.skipif(
    not CONSTANTS_AVAILABLE,
    reason="media/constants.py not yet available",
)
_skip_mime = pytest.mark.skipif(
    not MIME_AVAILABLE,
    reason="media/mime.py not yet available",
)
_skip_store = pytest.mark.skipif(
    not STORE_AVAILABLE,
    reason="media/store.py not yet available",
)
_skip_ssrf = pytest.mark.skipif(
    not SSRF_AVAILABLE,
    reason="media/ssrf.py not yet available",
)


class TestDetectMime:
    """detect_mime() multi-strategy MIME detection."""

    @_skip_mime
    def test_extension_jpeg(self):
        """Known extension .jpg returns image/jpeg."""
        result = detect_mime(b"", filename="photo.jpg")
        assert result == "image/jpeg"

    @_skip_mime
    def test_extension_png(self):
        """Known extension .png returns image/png."""
        result = detect_mime(b"", filename="image.png")
        assert result == "image/png"

    @_skip_mime
    def test_extension_pdf(self):
        """Known extension .pdf returns application/pdf."""
        result = detect_mime(b"", filename="document.pdf")
        assert result == "application/pdf"

    @_skip_mime
    def test_fallback_to_header_mime(self):
        """When no magic or extension match, header_mime is used."""
        result = detect_mime(b"", header_mime="text/plain")
        assert result == "text/plain"

    @_skip_mime
    def test_fallback_to_octet_stream(self):
        """When nothing matches, falls back to application/octet-stream."""
        result = detect_mime(b"")
        assert result == "application/octet-stream"

    @_skip_mime
    def test_header_mime_stripped(self):
        """Header MIME with surrounding whitespace is trimmed."""
        result = detect_mime(b"", header_mime="  image/gif  ")
        assert result == "image/gif"

    @_skip_mime
    def test_octet_stream_header_ignored(self):
        """application/octet-stream header falls through to extension."""
        result = detect_mime(
            b"", header_mime="application/octet-stream", filename="test.mp4"
        )
        assert result == "video/mp4"


class TestMediaKind:
    """MediaKind enum, media_kind_from_mime, max_bytes_for_kind."""

    @_skip_constants
    def test_media_kind_image(self):
        assert media_kind_from_mime("image/jpeg") == MediaKind.IMAGE

    @_skip_constants
    def test_media_kind_audio(self):
        assert media_kind_from_mime("audio/ogg") == MediaKind.AUDIO

    @_skip_constants
    def test_media_kind_video(self):
        assert media_kind_from_mime("video/mp4") == MediaKind.VIDEO

    @_skip_constants
    def test_media_kind_document_fallback(self):
        assert media_kind_from_mime("application/pdf") == MediaKind.DOCUMENT

    @_skip_constants
    def test_max_bytes_image(self):
        assert max_bytes_for_kind(MediaKind.IMAGE) == 6 * 1024 * 1024

    @_skip_constants
    def test_max_bytes_matches_constant(self):
        assert max_bytes_for_kind(MediaKind.IMAGE) == MAX_IMAGE_BYTES


class TestSaveMediaBuffer:
    """save_media_buffer() — disk write with size enforcement."""

    @_skip_store
    def test_writes_file(self, tmp_path):
        """save_media_buffer writes a file to the expected subdirectory."""
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
        assert result.content_type  # should be non-empty
        # Verify file is under the correct subdirectory
        assert "test_inbound" in str(result.path)

    @_skip_store
    def test_enforces_size_limit(self, tmp_path):
        """save_media_buffer raises ValueError when buffer exceeds max_bytes."""
        buf = b"x" * 1000
        with pytest.raises(ValueError, match="exceeds limit"):
            save_media_buffer(
                buf,
                content_type="image/jpeg",
                subdir="test_limit",
                max_bytes=500,
                data_root=tmp_path,
            )

    @_skip_store
    def test_size_limit_exact_boundary(self, tmp_path):
        """Buffer at exactly max_bytes does NOT raise."""
        buf = b"x" * 500
        result = save_media_buffer(
            buf,
            content_type="image/jpeg",
            subdir="test_exact",
            max_bytes=500,
            data_root=tmp_path,
        )
        assert result.size == 500


class TestCleanOldMedia:
    """clean_old_media() — TTL-based file removal."""

    @_skip_store
    def test_removes_expired_files(self, tmp_path):
        """Expired files are removed by clean_old_media."""
        media_dir = tmp_path / "state" / "media" / "test_clean"
        media_dir.mkdir(parents=True)

        # Create an old file with mtime in the past
        old_file = media_dir / "old_file.bin"
        old_file.write_bytes(b"old data")
        # Set mtime to 5 minutes ago
        old_mtime = time.time() - 300
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Create a recent file
        new_file = media_dir / "new_file.bin"
        new_file.write_bytes(b"new data")

        # Clean with a TTL of 60 seconds (old_file should be removed)
        removed = clean_old_media(media_dir, ttl_ms=60_000)

        assert removed >= 1
        assert not old_file.exists()
        assert new_file.exists()

    @_skip_store
    def test_no_removal_when_files_fresh(self, tmp_path):
        """Fresh files are not removed."""
        media_dir = tmp_path / "state" / "media" / "test_fresh"
        media_dir.mkdir(parents=True)

        fresh_file = media_dir / "fresh.bin"
        fresh_file.write_bytes(b"fresh data")

        removed = clean_old_media(media_dir, ttl_ms=120_000)
        assert removed == 0
        assert fresh_file.exists()

    @_skip_store
    def test_empty_dir(self, tmp_path):
        """Empty directory returns 0 removed."""
        media_dir = tmp_path / "state" / "media" / "test_empty"
        media_dir.mkdir(parents=True)
        assert clean_old_media(media_dir) == 0

    @_skip_store
    def test_nonexistent_dir(self, tmp_path):
        """Non-existent directory returns 0 removed."""
        assert clean_old_media(tmp_path / "does_not_exist") == 0


class TestSavedMedia:
    """SavedMedia dataclass construction."""

    @_skip_store
    def test_construction(self, tmp_path):
        test_path = tmp_path / "test.jpg"
        sm = SavedMedia(
            id="abc123",
            path=test_path,
            size=1024,
            content_type="image/jpeg",
        )
        assert sm.id == "abc123"
        assert sm.path == test_path
        assert sm.size == 1024
        assert sm.content_type == "image/jpeg"


class TestSSRFGuard:
    """is_ssrf_blocked() — SSRF protection."""

    @_skip_ssrf
    async def test_loopback_blocked(self):
        """127.0.0.1 is blocked."""
        assert await is_ssrf_blocked("http://127.0.0.1") is True

    @_skip_ssrf
    async def test_private_10_blocked(self):
        """10.0.0.1 is blocked."""
        assert await is_ssrf_blocked("http://10.0.0.1") is True

    @_skip_ssrf
    async def test_private_192_blocked(self):
        """192.168.x.x is blocked."""
        assert await is_ssrf_blocked("http://192.168.1.1/secret") is True

    @_skip_ssrf
    async def test_private_172_blocked(self):
        """172.16.x.x is blocked."""
        assert await is_ssrf_blocked("http://172.16.0.1") is True

    @_skip_ssrf
    async def test_link_local_blocked(self):
        """169.254.x.x link-local is blocked."""
        assert await is_ssrf_blocked("http://169.254.1.1") is True

    @_skip_ssrf
    async def test_localhost_hostname_blocked(self):
        """'localhost' hostname is blocked."""
        assert await is_ssrf_blocked("http://localhost:8080") is True

    @_skip_ssrf
    async def test_public_url_allowed(self):
        """A public URL like api.openai.com is NOT blocked."""
        assert await is_ssrf_blocked("https://api.openai.com") is False

    @_skip_ssrf
    async def test_empty_url_blocked(self):
        """Empty/malformed URL is blocked (fail-closed)."""
        assert await is_ssrf_blocked("") is True

    @_skip_ssrf
    async def test_no_hostname_blocked(self):
        """URL without hostname is blocked (fail-closed)."""
        assert await is_ssrf_blocked("file:///etc/passwd") is True
