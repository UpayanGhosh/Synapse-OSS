"""
browser/session.py — Browser session and page state management.

One global playwright instance, lazy-started. Pages are keyed by tab_id
(UUID string). Session tabs track which tabs belong to which session_key
for batch cleanup.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from weakref import WeakKeyDictionary

from playwright.async_api import async_playwright, Browser, Page, Playwright

from .navigation_guard import assert_navigation_allowed, assert_navigation_result_allowed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_playwright: Playwright | None = None
_browser: Browser | None = None
_pages: dict[str, Page] = {}
_page_states: WeakKeyDictionary = WeakKeyDictionary()
_session_tabs: dict[str, list[str]] = {}

_CONSOLE_CAP = 500
_ERROR_CAP = 200


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------

@dataclass
class PageState:
    console: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attach_listeners(page: Page) -> None:
    state = PageState()
    _page_states[page] = state

    def on_console(msg):
        if len(state.console) < _CONSOLE_CAP:
            state.console.append({
                "type": msg.type,
                "text": msg.text,
                "timestamp": _now(),
            })

    def on_pageerror(exc):
        if len(state.errors) < _ERROR_CAP:
            state.errors.append({
                "message": str(exc),
                "timestamp": _now(),
            })

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_browser() -> dict:
    """Launch playwright chromium headless. No-op if already running."""
    global _playwright, _browser

    if _browser is not None and _browser.is_connected():
        return {"status": "already_running"}

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    logger.info("Browser started (chromium headless)")
    return {"status": "started", "browser_type": "chromium"}


async def stop_browser() -> dict:
    """Close all pages, close browser, reset all state."""
    global _playwright, _browser, _pages, _page_states, _session_tabs

    for tab_id, page in list(_pages.items()):
        try:
            await page.close()
        except Exception:
            pass

    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass

    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass

    _playwright = None
    _browser = None
    _pages = {}
    _page_states = WeakKeyDictionary()
    _session_tabs = {}

    logger.info("Browser stopped")
    return {"status": "stopped"}


async def get_status() -> dict:
    connected = _browser is not None and _browser.is_connected()
    tab_ids = list(_pages.keys())
    return {"connected": connected, "tab_count": len(tab_ids), "tabs": tab_ids}


async def open_tab(url: str, session_key: str = "default") -> dict:
    """Open a new page and navigate to *url*."""
    await assert_navigation_allowed(url)

    if _browser is None or not _browser.is_connected():
        await start_browser()

    page = await _browser.new_page()
    _attach_listeners(page)

    await page.goto(url, wait_until="domcontentloaded")
    await assert_navigation_result_allowed(page.url)

    tab_id = str(uuid.uuid4())
    _pages[tab_id] = page
    _session_tabs.setdefault(session_key, []).append(tab_id)

    logger.info("Opened tab %s → %s", tab_id, page.url)
    return {"tab_id": tab_id, "url": page.url, "title": await page.title()}


async def close_tab(tab_id: str) -> dict:
    """Close a tab by id and remove from all tracking structures."""
    page = _pages.pop(tab_id, None)
    if page is None:
        return {"closed": tab_id, "note": "tab not found"}

    try:
        await page.close()
    except Exception:
        pass

    for tabs in _session_tabs.values():
        if tab_id in tabs:
            tabs.remove(tab_id)

    return {"closed": tab_id}


async def list_tabs() -> list[dict]:
    """Return [{tab_id, url, title}] for all open pages."""
    result = []
    for tab_id, page in list(_pages.items()):
        try:
            result.append({
                "tab_id": tab_id,
                "url": page.url,
                "title": await page.title(),
            })
        except Exception:
            result.append({"tab_id": tab_id, "url": "unknown", "title": "unknown"})
    return result


async def navigate(tab_id: str, url: str) -> dict:
    """Navigate an existing tab to a new URL."""
    await assert_navigation_allowed(url)

    page = _pages.get(tab_id)
    if page is None:
        raise KeyError(f"tab_id not found: {tab_id}")

    await page.goto(url, wait_until="domcontentloaded")
    await assert_navigation_result_allowed(page.url)

    return {"url": page.url, "title": await page.title()}


async def get_console(tab_id: str) -> dict:
    """Return console messages and page errors for a tab."""
    page = _pages.get(tab_id)
    if page is None:
        raise KeyError(f"tab_id not found: {tab_id}")

    state: PageState = _page_states.get(page, PageState())
    return {"console": state.console, "errors": state.errors}


async def cleanup_session_tabs(session_key: str) -> None:
    """Close all tabs registered to *session_key*."""
    tab_ids = _session_tabs.pop(session_key, [])
    for tab_id in list(tab_ids):
        await close_tab(tab_id)
    logger.info("Cleaned up %d tabs for session %r", len(tab_ids), session_key)


def get_page(tab_id: str) -> Page:
    """Return the Page for *tab_id*, raising KeyError if not found."""
    page = _pages.get(tab_id)
    if page is None:
        raise KeyError(f"tab_id not found: {tab_id}")
    return page
