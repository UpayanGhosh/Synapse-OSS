"""
file_ops/paging.py — Adaptive paged file reading.

Ports the OpenClaw paging model to Python:
  DEFAULT_PAGE_MAX_BYTES   = 50 KB
  MAX_ADAPTIVE_PAGE_BYTES  = 512 KB
  ADAPTIVE_CONTEXT_SHARE   = 0.20  (20% of model context window)
  CHARS_PER_TOKEN          = 4
  MAX_PAGES                = 8
"""
import base64
import os

DEFAULT_PAGE_MAX_BYTES = 50 * 1024      # 50 KB
MAX_ADAPTIVE_PAGE_BYTES = 512 * 1024    # 512 KB
ADAPTIVE_CONTEXT_SHARE = 0.2            # 20% of context window
CHARS_PER_TOKEN = 4
MAX_PAGES = 8


def _load_detect_mime():
    try:
        from ..media.mime import detect_mime
        return detect_mime
    except ImportError:
        pass
    try:
        from media.mime import detect_mime
        return detect_mime
    except ImportError:
        return None


def read_file_paged(
    path: str,
    offset: int = 0,
    page_bytes: int | None = None,
    model_context_tokens: int | None = None,
) -> dict:
    """
    Read a file with adaptive paging.

    Returns a dict with keys:
      content, offset, bytes_read, truncated, next_offset, total_size, notice.
    For image files: content is base64-encoded, is_binary=True, mime set.
    For other binary: content is a placeholder string, is_binary=True.
    """
    # 1. Calculate effective page size
    if page_bytes is not None:
        page_size = max(DEFAULT_PAGE_MAX_BYTES, min(page_bytes, MAX_ADAPTIVE_PAGE_BYTES))
    elif model_context_tokens is not None:
        adaptive = int(model_context_tokens * CHARS_PER_TOKEN * ADAPTIVE_CONTEXT_SHARE)
        page_size = max(DEFAULT_PAGE_MAX_BYTES, min(adaptive, MAX_ADAPTIVE_PAGE_BYTES))
    else:
        page_size = DEFAULT_PAGE_MAX_BYTES

    total_size = os.path.getsize(path)

    # 2-3. Open in binary mode, seek, read
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(page_size)
        # 5. Check if more content exists
        has_more = bool(f.read(1))

    bytes_read = len(data)

    # MIME detection for binary handling
    detect_mime = _load_detect_mime()
    mime = detect_mime(data[:16384]) if detect_mime else None

    if mime and mime.startswith("image/"):
        return {
            "content": base64.b64encode(data).decode(),
            "mime": mime,
            "is_binary": True,
            "offset": offset,
            "bytes_read": bytes_read,
            "truncated": has_more,
            "next_offset": offset + bytes_read if has_more else None,
            "total_size": total_size,
            "notice": None,
        }

    # Detect non-image binary: try strict UTF-8 decode
    try:
        data.decode("utf-8")
        is_binary = False
    except UnicodeDecodeError:
        is_binary = True

    if is_binary:
        return {
            "content": f"[Binary file: {mime or 'application/octet-stream'}, {total_size} bytes]",
            "is_binary": True,
            "offset": offset,
            "bytes_read": bytes_read,
            "truncated": False,
            "next_offset": None,
            "total_size": total_size,
            "notice": None,
        }

    # 4. Decode as UTF-8 with errors="replace"
    content = data.decode("utf-8", errors="replace")

    notice = None
    next_offset = None
    if has_more:
        next_offset = offset + bytes_read
        notice = f"[Capped at {page_size} bytes. Use offset={next_offset} to continue.]"

    return {
        "content": content,
        "offset": offset,
        "bytes_read": bytes_read,
        "truncated": has_more,
        "next_offset": next_offset,
        "total_size": total_size,
        "notice": notice,
    }
