"""
Entry point for synapse.web-scrape skill.

Fetches a URL, strips HTML tags, and returns readable text (up to 8000 chars).
Uses the SSRF guard from sci_fi_dashboard.media.ssrf to prevent server-side
request forgery. Falls back to a simple private-IP check if the guard is unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Attempt to import the SSRF guard from the media module.
# Falls back to a lightweight private-IP check if unavailable (e.g. isolated test runs).
try:
    from sci_fi_dashboard.media.ssrf import is_ssrf_blocked as _ssrf_guard

    _HAS_SSRF_GUARD = True
except ImportError:
    _HAS_SSRF_GUARD = False


@dataclass
class ScrapeResult:
    context_block: str
    source_urls: list[str] = field(default_factory=list)
    error: str = ""


async def scrape_url_context(user_message: str, session_context: dict | None) -> ScrapeResult:
    """
    Extract URL from user_message, fetch the page, strip HTML, and return plain text.
    """
    import httpx  # lazy import

    url = _extract_url(user_message)
    if not url:
        return ScrapeResult(context_block="", error="No URL found in message.")

    # SSRF guard — reject private / loopback targets
    blocked = await _check_ssrf(url)
    if blocked:
        return ScrapeResult(context_block="", error="URL blocked by SSRF guard.")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Synapse-WebScrape/1.0 (+https://github.com/synapse-oss)"},
            )
            response.raise_for_status()

            raw_text = response.text
            plain_text = _strip_html(raw_text)
            plain_text = plain_text[:8000]  # hard cap

            if not plain_text.strip():
                return ScrapeResult(
                    context_block="",
                    error="Page fetched but no readable text could be extracted.",
                )

            return ScrapeResult(
                context_block=f"Content from {url}:\n\n{plain_text}",
                source_urls=[url],
            )

    except httpx.HTTPStatusError as exc:
        return ScrapeResult(
            context_block="",
            error=f"HTTP {exc.response.status_code} when fetching {url}",
        )
    except Exception as exc:  # noqa: BLE001
        return ScrapeResult(
            context_block="",
            error=f"Failed to fetch URL: {exc}",
        )


def _extract_url(text: str) -> str:
    """Pull the first http/https URL from the message."""
    m = re.search(r"https?://[^\s]+", text)
    return m.group(0).rstrip(".,;:)\"'") if m else ""


def _strip_html(html: str) -> str:
    """Remove HTML/XML tags and collapse whitespace."""
    # Remove script and style blocks entirely
    no_scripts = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    no_tags = re.sub(r"<[^>]+>", " ", no_scripts)
    # Collapse repeated whitespace
    cleaned = re.sub(r"\s+", " ", no_tags)
    return cleaned.strip()


async def _check_ssrf(url: str) -> bool:
    """Return True if the URL should be blocked."""
    if _HAS_SSRF_GUARD:
        return await _ssrf_guard(url)
    # Lightweight fallback: block obvious private/loopback ranges
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return True
    # Block loopback and link-local names
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        addr = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(addr)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except Exception:  # noqa: BLE001
        return True  # block on resolution failure
