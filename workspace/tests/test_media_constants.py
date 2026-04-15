"""
test_media_constants.py — Tests for media/constants.py

Covers:
  - MediaKind enum values
  - Size limit constants
  - media_kind_from_mime mapping
  - max_bytes_for_kind lookup
  - model_supports_vision
  - TTL, file mode, and cleanup constants
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.media.constants import (
    CLEANUP_THROTTLE_SECONDS,
    DEFAULT_TTL_MS,
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    MEDIA_DIR_MODE,
    MEDIA_FILE_MODE,
    MEDIA_MAX_BYTES,
    VISION_CAPABLE_PREFIXES,
    MediaKind,
    max_bytes_for_kind,
    media_kind_from_mime,
    model_supports_vision,
)


class TestMediaKindEnum:
    def test_enum_values(self):
        assert MediaKind.IMAGE.value == "image"
        assert MediaKind.AUDIO.value == "audio"
        assert MediaKind.VIDEO.value == "video"
        assert MediaKind.DOCUMENT.value == "document"

    def test_enum_members(self):
        members = list(MediaKind)
        assert len(members) == 4


class TestSizeLimits:
    def test_image_6mb(self):
        assert MAX_IMAGE_BYTES == 6 * 1024 * 1024

    def test_audio_16mb(self):
        assert MAX_AUDIO_BYTES == 16 * 1024 * 1024

    def test_video_16mb(self):
        assert MAX_VIDEO_BYTES == 16 * 1024 * 1024

    def test_document_100mb(self):
        assert MAX_DOCUMENT_BYTES == 100 * 1024 * 1024

    def test_global_fallback_5mb(self):
        assert MEDIA_MAX_BYTES == 5 * 1024 * 1024


class TestTTLAndModes:
    def test_default_ttl_2_minutes(self):
        assert DEFAULT_TTL_MS == 120_000

    def test_file_mode(self):
        assert MEDIA_FILE_MODE == 0o644

    def test_dir_mode(self):
        assert MEDIA_DIR_MODE == 0o700

    def test_cleanup_throttle(self):
        assert CLEANUP_THROTTLE_SECONDS == 60


class TestMediaKindFromMime:
    def test_image_types(self):
        assert media_kind_from_mime("image/jpeg") == MediaKind.IMAGE
        assert media_kind_from_mime("image/png") == MediaKind.IMAGE
        assert media_kind_from_mime("image/webp") == MediaKind.IMAGE

    def test_audio_types(self):
        assert media_kind_from_mime("audio/mpeg") == MediaKind.AUDIO
        assert media_kind_from_mime("audio/ogg") == MediaKind.AUDIO

    def test_video_types(self):
        assert media_kind_from_mime("video/mp4") == MediaKind.VIDEO
        assert media_kind_from_mime("video/webm") == MediaKind.VIDEO

    def test_document_fallback(self):
        assert media_kind_from_mime("application/pdf") == MediaKind.DOCUMENT
        assert media_kind_from_mime("text/plain") == MediaKind.DOCUMENT

    def test_unknown_falls_to_document(self):
        assert media_kind_from_mime("unknown/type") == MediaKind.DOCUMENT

    def test_no_slash_falls_to_document(self):
        assert media_kind_from_mime("plaintext") == MediaKind.DOCUMENT


class TestMaxBytesForKind:
    def test_image_limit(self):
        assert max_bytes_for_kind(MediaKind.IMAGE) == MAX_IMAGE_BYTES

    def test_audio_limit(self):
        assert max_bytes_for_kind(MediaKind.AUDIO) == MAX_AUDIO_BYTES

    def test_video_limit(self):
        assert max_bytes_for_kind(MediaKind.VIDEO) == MAX_VIDEO_BYTES

    def test_document_limit(self):
        assert max_bytes_for_kind(MediaKind.DOCUMENT) == MAX_DOCUMENT_BYTES


class TestModelSupportsVision:
    def test_gemini_2_vision(self):
        assert model_supports_vision("gemini/gemini-2.0-flash") is True

    def test_anthropic_claude_3_vision(self):
        assert model_supports_vision("anthropic/claude-3-5-sonnet") is True

    def test_anthropic_claude_4_vision(self):
        assert model_supports_vision("anthropic/claude-4-sonnet") is True

    def test_openai_gpt4o_vision(self):
        assert model_supports_vision("openai/gpt-4o-latest") is True

    def test_copilot_gpt4o_vision(self):
        assert model_supports_vision("github_copilot/gpt-4o") is True

    def test_ollama_no_vision(self):
        assert model_supports_vision("ollama_chat/mistral") is False

    def test_groq_no_vision(self):
        assert model_supports_vision("groq/llama-3.3-70b") is False

    def test_empty_string(self):
        assert model_supports_vision("") is False

    def test_vision_capable_prefixes_is_frozenset(self):
        assert isinstance(VISION_CAPABLE_PREFIXES, frozenset)
