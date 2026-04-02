"""
media/mime.py — Multi-strategy MIME detection.

Priority:
  1. python-magic (magic bytes) — optional, guarded by try/except ImportError.
  2. Caller-supplied ``header_mime`` (e.g. from an HTTP Content-Type header).
  3. File extension lookup via ``MIME_BY_EXT``.
  4. Fallback: ``application/octet-stream``.
"""

import logging
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional python-magic
# ---------------------------------------------------------------------------

try:
    import magic  # python-magic

    _MAGIC_AVAILABLE = True
except ImportError:
    magic = None  # type: ignore[assignment]
    _MAGIC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Extension -> MIME mapping
# ---------------------------------------------------------------------------

MIME_BY_EXT: dict[str, str] = {
    # Images
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    # Video
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
    # Audio
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
    ".wav": "audio/wav",
    ".opus": "audio/opus",
    # Documents
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".xls": "application/vnd.ms-excel",
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".csv": "text/csv",
    ".rtf": "application/rtf",
    ".epub": "application/epub+zip",
    # Archives
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
}

_FALLBACK = "application/octet-stream"

# Generic container types where magic bytes may reveal a more specific type.
# For example, .xlsx files are ZIP archives — magic returns ``application/zip``
# but the extension-based result is more useful.
_GENERIC_CONTAINER_MIMES: frozenset[str] = frozenset({
    "application/zip",
    "application/x-tar",
    "application/gzip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_mime(
    data: bytes,
    header_mime: str | None = None,
    filename: str | None = None,
) -> str:
    """Detect the MIME type of *data* using multiple strategies.

    Parameters
    ----------
    data:
        Raw file bytes (at least the first few KB is sufficient for magic).
    header_mime:
        Optional MIME string supplied by the sender (e.g. HTTP Content-Type).
    filename:
        Optional original filename used for extension-based fallback.

    Returns
    -------
    str
        The best-guess MIME type, or ``application/octet-stream`` if unknown.
    """
    magic_mime: str | None = None

    # Strategy 1: python-magic on raw bytes
    if _MAGIC_AVAILABLE and len(data) > 0:
        try:
            detected = magic.from_buffer(data, mime=True)  # type: ignore[union-attr]
            if detected and detected != _FALLBACK:
                magic_mime = detected
        except Exception:
            logger.debug("python-magic detection failed, trying fallbacks")

    # Resolve extension-based MIME for comparison
    ext_mime: str | None = None
    if filename:
        ext = PurePosixPath(filename).suffix.lower()
        ext_mime = MIME_BY_EXT.get(ext)

    # If magic detected a generic container type (e.g. application/zip) but the
    # extension maps to a more specific type (e.g. .xlsx → spreadsheet MIME),
    # prefer the extension result.
    if magic_mime and magic_mime in _GENERIC_CONTAINER_MIMES and ext_mime:
        return ext_mime

    # If magic gave a non-generic result, trust it.
    if magic_mime:
        return magic_mime

    # Strategy 2: trust the caller-supplied header MIME
    if header_mime and header_mime.strip() and header_mime.strip() != _FALLBACK:
        return header_mime.strip()

    # Strategy 3: extension lookup
    if ext_mime:
        return ext_mime

    # Strategy 4: give up
    return _FALLBACK
