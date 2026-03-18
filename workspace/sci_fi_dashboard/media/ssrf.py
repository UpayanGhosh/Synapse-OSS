"""
media/ssrf.py — SSRF guard and safe URL downloader.

``is_ssrf_blocked`` resolves a URL's hostname asynchronously (via
``loop.getaddrinfo``) and returns ``True`` if the resolved IP falls within
any private, loopback, or link-local range.  The function is fail-closed:
any resolution error also returns ``True``.

``download_to_file`` streams a remote URL to disk with an SSRF check,
size enforcement, and symlink rejection.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .store import SavedMedia

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blocked IP networks (RFC 1918, loopback, link-local, ULA)
# ---------------------------------------------------------------------------

_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# Hostnames that are always blocked regardless of DNS resolution
_BLOCKED_HOSTNAME_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
)

_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def is_ssrf_blocked(url: str) -> bool:
    """Return ``True`` if *url* resolves to a private / loopback address.

    Uses ``asyncio.get_running_loop().getaddrinfo()`` for non-blocking DNS
    resolution.  Fail-closed: any resolution error returns ``True``.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True

        # Fast hostname blocklist check
        hostname_lower = hostname.lower()
        if hostname_lower in _BLOCKED_HOSTNAMES:
            return True
        for suffix in _BLOCKED_HOSTNAME_SUFFIXES:
            if hostname_lower.endswith(suffix):
                return True

        # Non-blocking DNS resolution
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(hostname, None)

        for _family, _type, _proto, _canonname, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                # Unparseable IP — fail closed
                return True
            for net in _BLOCKED_NETS:
                if addr in net:
                    logger.debug(
                        "is_ssrf_blocked: %s resolved to %s (in %s) — blocked",
                        url, ip_str, net,
                    )
                    return True

        return False

    except Exception:
        # Fail-closed: DNS failure, malformed URL, etc.
        logger.debug("is_ssrf_blocked: resolution failed for %s — blocking", url)
        return True


async def download_to_file(
    url: str,
    dest: Path,
    max_bytes: int,
    headers: dict | None = None,
) -> SavedMedia:
    """Download *url* to *dest* with SSRF check, streaming, and symlink rejection.

    Parameters
    ----------
    url:
        Remote resource URL.
    dest:
        Local file path to write to.  Must not be a symlink.
    max_bytes:
        Maximum number of bytes to download.
    headers:
        Optional HTTP headers for the request.

    Returns
    -------
    SavedMedia
        Descriptor for the downloaded file.

    Raises
    ------
    PermissionError
        If the URL is SSRF-blocked.
    ValueError
        If the download exceeds *max_bytes*.
    OSError
        If *dest* is a symlink.
    """
    # Lazy import to avoid hard dependency on httpx at module level
    import httpx  # noqa: F811

    from .mime import detect_mime
    from .store import SavedMedia

    # SSRF guard
    if await is_ssrf_blocked(url):
        raise PermissionError(f"SSRF blocked: {url}")

    # Symlink rejection
    if dest.is_symlink():
        raise OSError(f"Refusing to write to symlink: {dest}")

    # Ensure parent directory exists
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp = dest.with_suffix(dest.suffix + ".tmp")

    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client,
        client.stream("GET", url, headers=headers or {}) as resp,
    ):
        resp.raise_for_status()
        content_type = resp.headers.get("content-type")

        total = 0
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            with os.fdopen(fd, "wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=65_536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(
                            f"Download exceeds {max_bytes} byte limit"
                        )
                    fh.write(chunk)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(str(tmp))
            raise

    os.replace(str(tmp), str(dest))

    with contextlib.suppress(OSError):
        os.chmod(str(dest), 0o644)

    # Read a sample for MIME detection
    with open(dest, "rb") as f:
        sample = f.read(8192)

    mime = detect_mime(sample, header_mime=content_type, filename=dest.name)

    return SavedMedia(
        id=dest.stem,
        path=dest,
        size=total,
        content_type=mime,
    )
