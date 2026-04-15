"""
media/store.py — Persist inbound/outbound media buffers to disk.

Files are stored under ``<data_root>/state/media/<subdir>/`` with atomic
writes (temp-file + os.replace) and a TTL-based cleanup pass that is
throttled to at most once per 60 seconds per directory.
"""

import contextlib
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    CLEANUP_THROTTLE_SECONDS,
    DEFAULT_TTL_MS,
    MEDIA_DIR_MODE,
    MEDIA_FILE_MODE,
)
from .mime import detect_mime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cleanup throttle state (module-level)
# ---------------------------------------------------------------------------

_last_cleanup_time: dict[str, float] = {}

# ---------------------------------------------------------------------------
# SavedMedia DTO
# ---------------------------------------------------------------------------


@dataclass
class SavedMedia:
    """Metadata returned after a successful media save."""

    id: str
    path: Path
    size: int
    content_type: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize_filename(name: str, max_len: int = 60) -> str:
    """Strip unsafe characters and truncate to *max_len* characters."""
    safe = _UNSAFE_CHARS.sub("_", name)
    return safe[:max_len] if safe else "file"


def _sanitize_original(name: str) -> str:
    """Sanitize a user-supplied original filename for safe disk storage.

    Strips path separators, null bytes, and unsafe characters, then
    truncates to 100 characters.
    """
    # Strip path components — keep only the basename
    name = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    safe = _UNSAFE_CHARS.sub("_", name)
    return safe[:100] if safe else ""


def _ext_from_mime(mime: str) -> str:
    """Derive a file extension from a MIME type (best effort)."""
    mapping: dict[str, str] = {
        # Images
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "image/avif": ".avif",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
        # Video
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
        "video/x-flv": ".flv",
        "video/x-ms-wmv": ".wmv",
        # Audio
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/flac": ".flac",
        "audio/aac": ".aac",
        "audio/x-ms-wma": ".wma",
        "audio/wav": ".wav",
        "audio/opus": ".opus",
        # Documents
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument" ".wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument" ".spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument" ".presentationml.presentation": ".pptx",
        "text/csv": ".csv",
        "application/rtf": ".rtf",
        "application/epub+zip": ".epub",
        # Archives
        "application/zip": ".zip",
        "application/gzip": ".gz",
        "application/x-tar": ".tar",
        "application/x-7z-compressed": ".7z",
        "application/vnd.rar": ".rar",
    }
    return mapping.get(mime, ".bin")


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------


def clean_old_media(media_dir: Path, ttl_ms: int = DEFAULT_TTL_MS) -> int:
    """Remove files in *media_dir* whose mtime is older than *ttl_ms*.

    Returns the number of files removed.  Errors on individual files are
    logged and swallowed so one bad entry does not block the rest.

    After cleaning, if the directory is empty it is pruned via
    ``os.rmdir`` (safe — only removes empty directories).
    """
    if not media_dir.is_dir():
        return 0

    cutoff = time.time() - (ttl_ms / 1000.0)
    removed = 0

    for entry in media_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("clean_old_media: failed to remove %s: %s", entry, exc)

    if removed:
        logger.debug("clean_old_media: removed %d expired file(s) from %s", removed, media_dir)
        # Prune the directory if it is now empty (race-safe).
        # Only attempt after actual removals — an empty dir that was just
        # created by save_media_buffer() must NOT be pruned.
        try:
            os.rmdir(str(media_dir))
            logger.debug("clean_old_media: pruned empty directory %s", media_dir)
        except OSError:
            # Directory is not empty or was already removed — both are fine.
            pass

    return removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_media_buffer(
    buffer: bytes,
    content_type: str | None = None,
    subdir: str = "inbound",
    max_bytes: int | None = None,
    data_root: Path | None = None,
    original_filename: str | None = None,
) -> SavedMedia:
    """Write *buffer* to disk and return a :class:`SavedMedia` descriptor.

    Parameters
    ----------
    buffer:
        Raw file bytes.
    content_type:
        Optional MIME hint from the sender.
    subdir:
        Sub-directory under ``<data_root>/state/media/`` (e.g. ``inbound``).
    max_bytes:
        Maximum allowed buffer size.  Raises ``ValueError`` if exceeded.
        When *None*, no size check is performed.
    data_root:
        Override for ``~/.synapse``.
    original_filename:
        Optional original filename from the sender.  When provided it is
        sanitized and used as a human-readable prefix in the stored
        filename (``{sanitized}---{media_id}{ext}``).

    Returns
    -------
    SavedMedia
    """
    # --- size enforcement ---
    if max_bytes is not None and len(buffer) > max_bytes:
        raise ValueError(f"Buffer size {len(buffer)} exceeds limit of {max_bytes} bytes")

    # --- resolve paths ---
    root = data_root or (Path.home() / ".synapse")
    media_base = root / "state" / "media"
    media_dir = (media_base / subdir).resolve()

    # Path traversal guard — subdir must not escape media_base
    try:
        media_dir.relative_to(media_base.resolve())
    except ValueError as exc:
        raise ValueError(f"subdir {subdir!r} escapes media root {media_base}") from exc

    media_dir.mkdir(parents=True, exist_ok=True)

    # Best-effort directory permission (advisory on Windows)
    with contextlib.suppress(OSError):
        os.chmod(str(media_dir), MEDIA_DIR_MODE)

    # --- throttled cleanup ---
    now = time.monotonic()
    if now - _last_cleanup_time.get(subdir, 0.0) > CLEANUP_THROTTLE_SECONDS:
        _last_cleanup_time[subdir] = now
        clean_old_media(media_dir)

    # --- detect MIME ---
    mime = detect_mime(buffer, header_mime=content_type)

    # --- generate filename ---
    media_id = uuid.uuid4().hex[:12]
    ext = _ext_from_mime(mime)

    # Use the sanitized original filename as prefix when available,
    # falling back to the subdir name.
    sanitized_orig = _sanitize_original(original_filename) if original_filename else ""
    prefix = sanitized_orig if sanitized_orig else _sanitize_filename(subdir)
    filename = f"{prefix}---{media_id}{ext}"

    dest = media_dir / filename

    # --- atomic write: temp-file + os.replace ---
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, MEDIA_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(buffer)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp))
        raise

    os.replace(str(tmp), str(dest))

    # Re-enforce permissions after replace (umask drift guard)
    with contextlib.suppress(OSError):
        os.chmod(str(dest), MEDIA_FILE_MODE)

    logger.debug("save_media_buffer: wrote %d bytes to %s", len(buffer), dest)

    return SavedMedia(
        id=media_id,
        path=dest,
        size=len(buffer),
        content_type=mime,
    )
