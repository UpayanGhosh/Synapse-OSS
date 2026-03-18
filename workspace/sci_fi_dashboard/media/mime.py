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
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}

_FALLBACK = "application/octet-stream"


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
    # Strategy 1: python-magic on raw bytes
    if _MAGIC_AVAILABLE and len(data) > 0:
        try:
            detected = magic.from_buffer(data, mime=True)  # type: ignore[union-attr]
            if detected and detected != _FALLBACK:
                return detected
        except Exception:
            logger.debug("python-magic detection failed, trying fallbacks")

    # Strategy 2: trust the caller-supplied header MIME
    if header_mime and header_mime.strip() and header_mime.strip() != _FALLBACK:
        return header_mime.strip()

    # Strategy 3: extension lookup
    if filename:
        ext = PurePosixPath(filename).suffix.lower()
        if ext in MIME_BY_EXT:
            return MIME_BY_EXT[ext]

    # Strategy 4: give up
    return _FALLBACK
