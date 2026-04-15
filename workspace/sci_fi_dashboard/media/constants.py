"""
media/constants.py — MediaKind enum, per-kind size limits, and helper functions.

All size constants are in bytes.  DEFAULT_TTL_MS is the default time-to-live
for cached media files (milliseconds).
"""

from enum import Enum

# ---------------------------------------------------------------------------
# MediaKind
# ---------------------------------------------------------------------------


class MediaKind(Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


# ---------------------------------------------------------------------------
# Per-kind size limits
# ---------------------------------------------------------------------------

MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB
MAX_AUDIO_BYTES = 16 * 1024 * 1024  # 16 MB
MAX_VIDEO_BYTES = 16 * 1024 * 1024  # 16 MB
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024  # 100 MB

# Global fallback when kind is unknown or caller doesn't specify
MEDIA_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# TTL & file modes
# ---------------------------------------------------------------------------

DEFAULT_TTL_MS = 120_000  # 2 minutes
MEDIA_FILE_MODE = 0o644
MEDIA_DIR_MODE = 0o700
CLEANUP_THROTTLE_SECONDS = 60

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KIND_BY_PREFIX = {
    "image": MediaKind.IMAGE,
    "audio": MediaKind.AUDIO,
    "video": MediaKind.VIDEO,
}

_LIMIT_BY_KIND = {
    MediaKind.IMAGE: MAX_IMAGE_BYTES,
    MediaKind.AUDIO: MAX_AUDIO_BYTES,
    MediaKind.VIDEO: MAX_VIDEO_BYTES,
    MediaKind.DOCUMENT: MAX_DOCUMENT_BYTES,
}


def media_kind_from_mime(mime: str) -> MediaKind:
    """Map a MIME type prefix to a ``MediaKind``.  Falls back to DOCUMENT."""
    prefix = mime.split("/")[0] if "/" in mime else ""
    return _KIND_BY_PREFIX.get(prefix, MediaKind.DOCUMENT)


def max_bytes_for_kind(kind: MediaKind) -> int:
    """Return the maximum allowed byte size for the given ``MediaKind``."""
    return _LIMIT_BY_KIND.get(kind, MAX_DOCUMENT_BYTES)


# ---------------------------------------------------------------------------
# Vision support
# ---------------------------------------------------------------------------

VISION_CAPABLE_PREFIXES: frozenset[str] = frozenset(
    {
        "gemini/gemini-2",
        "gemini/gemini-1.5",
        "anthropic/claude-3",
        "anthropic/claude-4",
        "openai/gpt-4o",
        "openai/gpt-4-vision",
        "openai/o",
        "github_copilot/gpt-4o",
    }
)


def model_supports_vision(model_id: str) -> bool:
    """Check if a model ID is known to support vision/image input."""
    return any(model_id.startswith(prefix) for prefix in VISION_CAPABLE_PREFIXES)
