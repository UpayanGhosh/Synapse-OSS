"""
media/fetch.py — SSRF-safe HTTP media downloader.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from .ssrf import is_ssrf_blocked, safe_httpx_client

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 15.0  # seconds


class MediaFetchError(Exception):
    """Raised when fetch_media cannot retrieve the media."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def fetch_media(
    url: str,
    max_bytes: int,
    ssrf_policy: Literal["block", "allow"] = "block",
    timeout: float = _DEFAULT_TIMEOUT,
) -> bytes:
    """Download *url* and return its raw bytes.

    Parameters
    ----------
    url:
        Remote resource URL.
    max_bytes:
        Maximum number of bytes to download.
    ssrf_policy:
        ``"block"`` (default) applies the SSRF guard; ``"allow"`` skips it
        (for tests or trusted internal environments).
    timeout:
        Request timeout in seconds (default 15 s).

    Returns
    -------
    bytes
        Raw media bytes.

    Raises
    ------
    MediaFetchError
        On SSRF block, content-length or streaming size exceeded, non-2xx
        HTTP status, or timeout.
    """
    if ssrf_policy == "block" and await is_ssrf_blocked(url):
        raise MediaFetchError(f"SSRF blocked: {url}")

    try:
        async with safe_httpx_client(timeout=timeout) as client, client.stream("GET", url) as resp:
            if resp.status_code >= 300:
                raise MediaFetchError(f"HTTP {resp.status_code} fetching {url}")

            # Fast-fail on declared Content-Length
            content_length = resp.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > max_bytes:
                        raise MediaFetchError(
                            f"Content-Length {content_length} exceeds limit of {max_bytes} bytes"
                        )
                except ValueError:
                    pass  # Non-integer header — proceed and enforce while streaming

            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=65_536):
                total += len(chunk)
                if total > max_bytes:
                    raise MediaFetchError(f"Response body exceeds limit of {max_bytes} bytes")
                chunks.append(chunk)

    except MediaFetchError:
        raise
    except PermissionError as exc:
        raise MediaFetchError(f"SSRF blocked on redirect: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise MediaFetchError(f"Timeout after {timeout}s fetching {url}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise MediaFetchError(f"HTTP error fetching {url}: {exc}") from exc

    return b"".join(chunks)
