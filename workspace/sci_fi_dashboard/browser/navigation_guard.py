"""
browser/navigation_guard.py — Two-phase SSRF navigation validator.

Validates URLs before navigation and after (to catch redirect pivots).
Only http:// and https:// are permitted; about:blank is the sole exception.
"""

from __future__ import annotations

from sci_fi_dashboard.media.ssrf import is_ssrf_blocked


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
        raise NavigationBlockedError(url, f"protocol not allowed (only http/https)")

    if await is_ssrf_blocked(url):
        raise NavigationBlockedError(url, "resolves to a private or blocked address")


async def assert_navigation_result_allowed(url: str) -> None:
    """Raise NavigationBlockedError if the final post-navigation *url* is not safe.

    Catches public→private redirect pivots.
    """
    await assert_navigation_allowed(url)
