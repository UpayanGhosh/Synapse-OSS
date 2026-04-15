"""
browser/navigation_guard.py — Three-phase SSRF navigation validator.

1. Pre-navigation: validate the requested URL.
2. Redirect-hop: validate every intermediate redirect via a Playwright
   ``response`` event hook (catches public-to-private redirect pivots
   *during* navigation, not just after).
3. Post-navigation: validate the final landed URL.

Only http:// and https:// are permitted; about:blank is the sole exception.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from sci_fi_dashboard.media.ssrf import is_ssrf_blocked

if TYPE_CHECKING:
    from playwright.async_api import Page, Response

logger = logging.getLogger(__name__)


class NavigationBlockedError(Exception):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Navigation blocked for {url!r}: {reason}")


async def assert_navigation_allowed(url: str) -> None:
    """Raise NavigationBlockedError if *url* is not safe to navigate to.

    Allows http:// and https:// only (plus about:blank).
    Delegates IP/hostname SSRF checks to is_ssrf_blocked().
    """
    if url == "about:blank":
        return

    lower = url.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        raise NavigationBlockedError(url, "protocol not allowed (only http/https)")

    if await is_ssrf_blocked(url):
        raise NavigationBlockedError(url, "resolves to a private or blocked address")


async def assert_navigation_result_allowed(url: str) -> None:
    """Raise NavigationBlockedError if the final post-navigation *url* is not safe.

    Catches public-to-private redirect pivots that were not caught by the
    redirect-hop listener (e.g. meta-refresh or JS-driven redirects).
    """
    await assert_navigation_allowed(url)


# ---------------------------------------------------------------------------
# Redirect-hop guard (attaches to Playwright Page events)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def redirect_guard(page: Page):
    """Context manager that validates every redirect hop during a navigation.

    Usage::

        async with redirect_guard(page):
            await page.goto(url, wait_until="domcontentloaded")

    If any 3xx redirect targets a private/loopback address, the ``response``
    handler logs a warning and closes the page to abort the redirect chain.
    A ``NavigationBlockedError`` is then raised by the post-navigation check.
    """
    blocked_url: str | None = None

    async def _on_response(response: Response) -> None:
        nonlocal blocked_url
        # Only inspect redirect responses (3xx)
        if 300 <= response.status < 400:
            location = response.headers.get("location")
            if location and await is_ssrf_blocked(location):
                blocked_url = location
                logger.warning(
                    "Redirect-hop blocked: %s -> %s (private/loopback)",
                    response.url,
                    location,
                )
                # Abort the navigation by closing the page context
                with contextlib.suppress(Exception):
                    await page.close()

    page.on("response", _on_response)
    try:
        yield
    finally:
        # Playwright does not have remove_listener; the listener is scoped to
        # the page lifetime and will be garbage-collected when the page closes.
        pass

    if blocked_url is not None:
        raise NavigationBlockedError(
            blocked_url,
            "redirect hop resolves to a private or blocked address",
        )
