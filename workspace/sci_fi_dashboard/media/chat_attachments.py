"""
media/chat_attachments.py — Inbound attachment parser for the gateway.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .constants import MediaKind, media_kind_from_mime
from .mime import detect_mime
from .store import save_media_buffer

logger = logging.getLogger(__name__)

# Images at or below this size are inlined as base64; larger images are offloaded.
_INLINE_IMAGE_MAX = 2 * 1024 * 1024  # 2 MB


@dataclass
class ParsedMessage:
    """Result of parsing a message that may contain attachments."""

    message: str  # original text + media:// markers for offloaded files
    inline_images: list[dict] = field(default_factory=list)  # base64 dicts for ≤2 MB images
    offloaded_refs: list[dict] = field(default_factory=list)  # {id, path, mime} for offloaded


async def parse_message_with_attachments(
    message: str,
    attachments: list[dict],  # each: {url, mime?, filename?, size?}
    max_bytes: int = 5_000_000,
) -> ParsedMessage:
    """Parse inbound attachments and classify them as inline or offloaded.

    Rules
    -----
    - ≤ 2 MB image  →  base64-encoded, added to ``inline_images``.
    - > 2 MB image or any audio/video/document  →  saved via
      ``store.save_media_buffer()``, a ``media://inbound/<id>`` marker is
      appended to ``message``, and an entry is added to ``offloaded_refs``.
    - MIME is detected via ``mime.detect_mime()``; attachments with an
      undetectable MIME (no hint, no filename) are skipped with a warning.
    - **Best-effort cleanup**: if attachment *N* fails, all files saved for
      attachments 0 … N-1 are deleted before re-raising.

    Parameters
    ----------
    message:
        Original message text.
    attachments:
        List of attachment descriptors.  Each must have at least ``"url"``.
        Optional keys: ``"mime"``, ``"filename"``, ``"size"``.
    max_bytes:
        Maximum bytes to download per attachment (default 5 MB).

    Returns
    -------
    ParsedMessage
    """
    from .fetch import MediaFetchError, fetch_media

    inline_images: list[dict] = []
    offloaded_refs: list[dict] = []
    saved_paths: list[Path] = []  # for rollback on failure
    extra_markers: list[str] = []

    for i, attachment in enumerate(attachments):
        url: str = attachment.get("url", "")
        hint_mime: str | None = attachment.get("mime")
        filename: str | None = attachment.get("filename")

        try:
            data = await fetch_media(url, max_bytes=max_bytes, ssrf_policy="block")

            mime = detect_mime(data, header_mime=hint_mime, filename=filename)
            if mime == "application/octet-stream" and not hint_mime and not filename:
                logger.warning(
                    "parse_message_with_attachments: undetectable MIME for attachment %d (%s), skipping",
                    i,
                    url,
                )
                continue

            kind = media_kind_from_mime(mime)
            file_size = len(data)

            if kind == MediaKind.IMAGE and file_size <= _INLINE_IMAGE_MAX:
                # Inline: base64-encode
                b64 = base64.b64encode(data).decode("ascii")
                inline_images.append(
                    {
                        "mime": mime,
                        "data": b64,
                        "filename": filename or "",
                        "size": file_size,
                    }
                )
            else:
                # Offload: save to disk
                saved = save_media_buffer(
                    data,
                    content_type=mime,
                    subdir="inbound",
                    max_bytes=max_bytes,
                )
                saved_paths.append(saved.path)
                marker = f"media://inbound/{saved.id}"
                extra_markers.append(marker)
                offloaded_refs.append(
                    {
                        "id": saved.id,
                        "path": str(saved.path),
                        "mime": saved.content_type,
                    }
                )

        except (MediaFetchError, ValueError, OSError) as exc:
            logger.error(
                "parse_message_with_attachments: failed on attachment %d (%s): %s",
                i,
                url,
                exc,
            )
            # Best-effort cleanup of files saved so far
            for p in saved_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError as clean_err:
                    logger.warning("Cleanup failed for %s: %s", p, clean_err)
            raise

    full_message = " ".join([message] + extra_markers).strip() if extra_markers else message

    return ParsedMessage(
        message=full_message,
        inline_images=inline_images,
        offloaded_refs=offloaded_refs,
    )
