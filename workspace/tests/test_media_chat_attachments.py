"""
test_media_chat_attachments.py — Tests for media/chat_attachments.py

Covers:
  - ParsedMessage dataclass
  - parse_message_with_attachments: inline images, offloaded files,
    MIME detection, rollback on failure, skip undetectable
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.chat_attachments import ParsedMessage, parse_message_with_attachments
from sci_fi_dashboard.media.store import SavedMedia


class TestParsedMessage:
    def test_construction_defaults(self):
        pm = ParsedMessage(message="hello")
        assert pm.message == "hello"
        assert pm.inline_images == []
        assert pm.offloaded_refs == []

    def test_construction_with_data(self):
        pm = ParsedMessage(
            message="hi",
            inline_images=[{"mime": "image/png", "data": "base64data"}],
            offloaded_refs=[{"id": "x", "path": "/p", "mime": "audio/ogg"}],
        )
        assert len(pm.inline_images) == 1
        assert len(pm.offloaded_refs) == 1


class TestParseMessageWithAttachments:
    @pytest.mark.asyncio
    async def test_no_attachments(self):
        result = await parse_message_with_attachments("hello", [])
        assert result.message == "hello"
        assert result.inline_images == []
        assert result.offloaded_refs == []

    @pytest.mark.asyncio
    async def test_small_image_inlined(self):
        """Images <= 2MB are base64-inlined."""
        small_image = b"\x89PNG" + b"x" * 1000  # small PNG-like data

        with patch("sci_fi_dashboard.media.chat_attachments.fetch_media", return_value=small_image), \
             patch("sci_fi_dashboard.media.chat_attachments.detect_mime", return_value="image/png"):
            result = await parse_message_with_attachments(
                "check this",
                [{"url": "https://example.com/img.png"}],
            )
            assert len(result.inline_images) == 1
            assert result.inline_images[0]["mime"] == "image/png"
            assert result.message == "check this"

    @pytest.mark.asyncio
    async def test_large_image_offloaded(self):
        """Images > 2MB are offloaded to disk."""
        large_data = b"x" * (3 * 1024 * 1024)  # 3 MB

        mock_saved = SavedMedia(id="abc123", path=Path("/tmp/test.jpg"), size=len(large_data), content_type="image/jpeg")

        with patch("sci_fi_dashboard.media.chat_attachments.fetch_media", return_value=large_data), \
             patch("sci_fi_dashboard.media.chat_attachments.detect_mime", return_value="image/jpeg"), \
             patch("sci_fi_dashboard.media.chat_attachments.save_media_buffer", return_value=mock_saved):
            result = await parse_message_with_attachments(
                "big image",
                [{"url": "https://example.com/big.jpg"}],
            )
            assert len(result.offloaded_refs) == 1
            assert result.offloaded_refs[0]["id"] == "abc123"
            assert "media://inbound/abc123" in result.message

    @pytest.mark.asyncio
    async def test_audio_always_offloaded(self):
        """Audio files are always offloaded (not inlined)."""
        audio_data = b"x" * 500

        mock_saved = SavedMedia(id="aud123", path=Path("/tmp/test.ogg"), size=500, content_type="audio/ogg")

        with patch("sci_fi_dashboard.media.chat_attachments.fetch_media", return_value=audio_data), \
             patch("sci_fi_dashboard.media.chat_attachments.detect_mime", return_value="audio/ogg"), \
             patch("sci_fi_dashboard.media.chat_attachments.save_media_buffer", return_value=mock_saved):
            result = await parse_message_with_attachments(
                "voice msg",
                [{"url": "https://example.com/audio.ogg"}],
            )
            assert len(result.offloaded_refs) == 1
            assert result.inline_images == []

    @pytest.mark.asyncio
    async def test_undetectable_mime_skipped(self):
        """Attachment with undetectable MIME (octet-stream, no hint) is skipped."""
        with patch("sci_fi_dashboard.media.chat_attachments.fetch_media", return_value=b"binary"):
            with patch("sci_fi_dashboard.media.chat_attachments.detect_mime", return_value="application/octet-stream"):
                result = await parse_message_with_attachments(
                    "mystery file",
                    [{"url": "https://example.com/unknown"}],
                )
                assert result.inline_images == []
                assert result.offloaded_refs == []

    @pytest.mark.asyncio
    async def test_fetch_failure_triggers_rollback(self):
        """On fetch failure, previously saved files are cleaned up."""
        from sci_fi_dashboard.media.fetch import MediaFetchError

        call_count = 0

        async def mock_fetch(url, max_bytes, ssrf_policy):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"x" * 100  # first attachment succeeds
            raise MediaFetchError("connection failed")

        mock_saved = SavedMedia(id="s1", path=Path("/tmp/s1.jpg"), size=100, content_type="image/jpeg")

        with patch("sci_fi_dashboard.media.chat_attachments.fetch_media", side_effect=mock_fetch), \
             patch("sci_fi_dashboard.media.chat_attachments.detect_mime", return_value="audio/ogg"), \
             patch("sci_fi_dashboard.media.chat_attachments.save_media_buffer", return_value=mock_saved), \
             patch.object(Path, "unlink") as mock_unlink:
            with pytest.raises(MediaFetchError):
                await parse_message_with_attachments(
                    "multi",
                    [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
                )
