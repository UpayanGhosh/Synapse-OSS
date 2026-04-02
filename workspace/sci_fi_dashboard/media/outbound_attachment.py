"""
media/outbound_attachment.py — Resolve media:// URIs to real file paths for outbound delivery.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_DEFAULT_MEDIA_ROOT = Path.home() / ".synapse" / "state" / "media"


class MediaResolutionError(Exception):
    """Raised when a media:// URI cannot be resolved to a valid file path."""


def resolve_media_path(
    uri: str,
    media_root: Path | None = None,
) -> str:
    """Resolve a ``media://`` URI or plain file path to an absolute path.

    Parameters
    ----------
    uri:
        A ``media://inbound/<id>`` URI produced by ``chat_attachments.py``,
        or a plain filesystem path.
    media_root:
        Override for ``~/.synapse/state/media/`` (used in tests).

    Returns
    -------
    str
        Absolute path to the existing media file.

    Raises
    ------
    MediaResolutionError
        If the URI is invalid, the ID contains unsafe characters (path
        separators, ``..``, null bytes), or the file is not found.
    """
    root = media_root or _DEFAULT_MEDIA_ROOT

    if uri.startswith("media://"):
        parsed = urlparse(uri)
        subdir = parsed.netloc           # e.g. "inbound"
        raw_id = parsed.path.lstrip("/")  # e.g. "abc123def456"

        # --- Security checks ---
        if not raw_id:
            raise MediaResolutionError(f"Empty media ID in URI: {uri!r}")
        if "\x00" in raw_id:
            raise MediaResolutionError(f"Null byte in media ID: {uri!r}")
        if "/" in raw_id or "\\" in raw_id:
            raise MediaResolutionError(f"Path separator in media ID: {uri!r}")
        if ".." in raw_id:
            raise MediaResolutionError(f"Directory traversal in media ID: {uri!r}")
        if not _SAFE_ID_RE.match(raw_id):
            raise MediaResolutionError(f"Unsafe characters in media ID: {raw_id!r}")

        media_dir = root / subdir
        if not media_dir.is_dir():
            raise MediaResolutionError(f"Media directory not found: {media_dir}")

        # store.py names files as "{subdir}---{id}{ext}" — glob by ID prefix
        prefix = f"{subdir}---{raw_id}"
        matches = [
            m for m in media_dir.glob(f"{prefix}*")
            if m.is_file() and not m.name.endswith(".tmp")
        ]

        if not matches:
            raise MediaResolutionError(
                f"No media file found for ID {raw_id!r} in {media_dir}"
            )
        if len(matches) > 1:
            logger.warning(
                "resolve_media_path: multiple files match ID %s — using %s",
                raw_id, matches[0],
            )

        return str(matches[0])

    else:
        # Plain file path — must resolve within media_root
        resolved = Path(uri).resolve()
        resolved_root = root.resolve()

        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            raise MediaResolutionError(
                f"Path {uri!r} resolves outside media root {resolved_root}"
            )

        if not resolved.exists():
            raise MediaResolutionError(f"File not found: {uri!r}")
        return str(resolved)
