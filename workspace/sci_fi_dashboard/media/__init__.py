"""
media — Media pipeline for Synapse-OSS.

Provides MIME detection, size-enforced disk storage with TTL cleanup, and an
SSRF guard for safe remote downloads.
"""

from .audio_preflight import AudioPreflightResult, check_audio_preflight
from .audio_transcriber import transcribe_audio
from .chat_attachments import ParsedMessage, parse_message_with_attachments
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
    VISION_CAPABLE_PREFIXES,
    MediaKind,
    max_bytes_for_kind,
    media_kind_from_mime,
    model_supports_vision,
)
from .delivery_queue import DeliveryQueue, QueuedDelivery
from .fetch import MediaFetchError, fetch_media
from .mime import detect_mime
from .outbound_attachment import MediaResolutionError, resolve_media_path
from .ssrf import download_to_file, is_ssrf_blocked, safe_httpx_client
from .store import SavedMedia, clean_old_media, save_media_buffer

__all__ = [
    # audio_preflight
    "AudioPreflightResult",
    "check_audio_preflight",
    # audio_transcriber
    "transcribe_audio",
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
    "VISION_CAPABLE_PREFIXES",
    "MediaKind",
    "max_bytes_for_kind",
    "media_kind_from_mime",
    "model_supports_vision",
    # mime
    "detect_mime",
    # ssrf
    "download_to_file",
    "is_ssrf_blocked",
    "safe_httpx_client",
    # store
    "SavedMedia",
    "clean_old_media",
    "save_media_buffer",
    # fetch
    "MediaFetchError",
    "fetch_media",
    # chat_attachments
    "ParsedMessage",
    "parse_message_with_attachments",
    # delivery_queue
    "DeliveryQueue",
    "QueuedDelivery",
    # outbound_attachment
    "MediaResolutionError",
    "resolve_media_path",
]
