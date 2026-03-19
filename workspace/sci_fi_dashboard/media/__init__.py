"""
media — Media pipeline for Synapse-OSS.

Provides MIME detection, size-enforced disk storage with TTL cleanup, and an
SSRF guard for safe remote downloads.
"""

from .constants import (
    CLEANUP_THROTTLE_SECONDS,
    DEFAULT_TTL_MS,
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    MEDIA_DIR_MODE,
    MEDIA_FILE_MODE,
    MEDIA_MAX_BYTES,
    MediaKind,
    max_bytes_for_kind,
    media_kind_from_mime,
)
from .mime import detect_mime
from .ssrf import download_to_file, is_ssrf_blocked
from .store import SavedMedia, clean_old_media, save_media_buffer

__all__ = [
    # constants
    "CLEANUP_THROTTLE_SECONDS",
    "DEFAULT_TTL_MS",
    "MAX_AUDIO_BYTES",
    "MAX_DOCUMENT_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_VIDEO_BYTES",
    "MEDIA_DIR_MODE",
    "MEDIA_FILE_MODE",
    "MEDIA_MAX_BYTES",
    "MediaKind",
    "max_bytes_for_kind",
    "media_kind_from_mime",
    # mime
    "detect_mime",
    # ssrf
    "download_to_file",
    "is_ssrf_blocked",
    # store
    "SavedMedia",
    "clean_old_media",
    "save_media_buffer",
]
