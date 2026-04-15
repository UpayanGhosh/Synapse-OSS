"""
Tests for sci_fi_dashboard.browser.session — browser session and tab management.

Note: Playwright is fully mocked. No real browser is launched.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers — mock playwright objects
# ---------------------------------------------------------------------------


def _mock_page(url="https://example.com", title="Example"):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.close = AsyncMock()
    page.goto = AsyncMock()
    page.on = MagicMock()
    page.viewport_size = {"width": 1280, "height": 720}
    return page


def _mock_browser(connected=True):
    browser = MagicMock()
    browser.is_connected.return_value = connected
    browser.new_page = AsyncMock(return_value=_mock_page())
    browser.close = AsyncMock()
    return browser


# ---------------------------------------------------------------------------
# Tab limit enforcement
# ---------------------------------------------------------------------------


class TestTabLimit:
    @pytest.mark.asyncio
    async def test_open_tab_enforces_max_tabs(self):
        import sci_fi_dashboard.browser.session as sess

        # Backup and replace module state
        old_pages = sess._pages
        old_browser = sess._browser
        old_session_tabs = sess._session_tabs
        try:
            sess._browser = _mock_browser()
            sess._pages = {f"t{i}": _mock_page() for i in range(20)}
            sess._session_tabs = {}

            with pytest.raises(RuntimeError, match="Tab limit"):
                await sess.open_tab("https://example.com")
        finally:
            sess._pages = old_pages
            sess._browser = old_browser
            sess._session_tabs = old_session_tabs


# ---------------------------------------------------------------------------
# get_page
# ---------------------------------------------------------------------------


class TestGetPage:
    def test_returns_page_for_known_id(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            page = _mock_page()
            sess._pages = {"t1": page}
            assert sess.get_page("t1") is page
        finally:
            sess._pages = old_pages

    def test_raises_for_unknown_id(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            sess._pages = {}
            with pytest.raises(KeyError, match="tab_id not found"):
                sess.get_page("missing")
        finally:
            sess._pages = old_pages


# ---------------------------------------------------------------------------
# close_tab
# ---------------------------------------------------------------------------


class TestCloseTab:
    @pytest.mark.asyncio
    async def test_close_known_tab(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        old_session_tabs = sess._session_tabs
        try:
            page = _mock_page()
            sess._pages = {"t1": page}
            sess._session_tabs = {"default": ["t1"]}

            result = await sess.close_tab("t1")
            assert result["closed"] == "t1"
            assert "t1" not in sess._pages
            page.close.assert_awaited_once()
        finally:
            sess._pages = old_pages
            sess._session_tabs = old_session_tabs

    @pytest.mark.asyncio
    async def test_close_unknown_tab(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            sess._pages = {}
            result = await sess.close_tab("missing")
            assert "not found" in result.get("note", "")
        finally:
            sess._pages = old_pages


# ---------------------------------------------------------------------------
# list_tabs
# ---------------------------------------------------------------------------


class TestListTabs:
    @pytest.mark.asyncio
    async def test_lists_all_open_tabs(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            sess._pages = {
                "t1": _mock_page("https://a.com", "A"),
                "t2": _mock_page("https://b.com", "B"),
            }

            result = await sess.list_tabs()
            assert len(result) == 2
            urls = {r["url"] for r in result}
            assert "https://a.com" in urls
            assert "https://b.com" in urls
        finally:
            sess._pages = old_pages

    @pytest.mark.asyncio
    async def test_handles_page_error_gracefully(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            bad_page = AsyncMock()
            bad_page.url = property(lambda self: (_ for _ in ()).throw(Exception("dead")))
            type(bad_page).url = PropertyMock(side_effect=Exception("dead"))
            bad_page.title = AsyncMock(side_effect=Exception("dead"))

            sess._pages = {"t1": bad_page}
            result = await sess.list_tabs()
            assert len(result) == 1
            assert result[0]["url"] == "unknown"
        finally:
            sess._pages = old_pages


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_connected_status(self):
        import sci_fi_dashboard.browser.session as sess

        old_browser = sess._browser
        old_pages = sess._pages
        try:
            sess._browser = _mock_browser(connected=True)
            sess._pages = {"t1": _mock_page(), "t2": _mock_page()}

            status = await sess.get_status()
            assert status["connected"] is True
            assert status["tab_count"] == 2
        finally:
            sess._browser = old_browser
            sess._pages = old_pages

    @pytest.mark.asyncio
    async def test_disconnected_status(self):
        import sci_fi_dashboard.browser.session as sess

        old_browser = sess._browser
        old_pages = sess._pages
        try:
            sess._browser = None
            sess._pages = {}

            status = await sess.get_status()
            assert status["connected"] is False
            assert status["tab_count"] == 0
        finally:
            sess._browser = old_browser
            sess._pages = old_pages


# ---------------------------------------------------------------------------
# get_console
# ---------------------------------------------------------------------------


class TestGetConsole:
    @pytest.mark.asyncio
    async def test_returns_console_for_tab(self):
        from weakref import WeakKeyDictionary

        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        old_states = sess._page_states
        try:
            page = _mock_page()
            sess._pages = {"t1": page}

            ps = sess.PageState()
            ps.console = [{"type": "log", "text": "hi", "timestamp": "t"}]
            ps.errors = [{"message": "oops", "timestamp": "t"}]
            sess._page_states = WeakKeyDictionary()
            sess._page_states[page] = ps

            result = await sess.get_console("t1")
            assert len(result["console"]) == 1
            assert len(result["errors"]) == 1
        finally:
            sess._pages = old_pages
            sess._page_states = old_states

    @pytest.mark.asyncio
    async def test_console_unknown_tab_raises(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        try:
            sess._pages = {}
            with pytest.raises(KeyError):
                await sess.get_console("missing")
        finally:
            sess._pages = old_pages


# ---------------------------------------------------------------------------
# cleanup_session_tabs
# ---------------------------------------------------------------------------


class TestCleanupSessionTabs:
    @pytest.mark.asyncio
    async def test_closes_all_session_tabs(self):
        import sci_fi_dashboard.browser.session as sess

        old_pages = sess._pages
        old_session_tabs = sess._session_tabs
        try:
            p1 = _mock_page()
            p2 = _mock_page()
            sess._pages = {"t1": p1, "t2": p2}
            sess._session_tabs = {"mykey": ["t1", "t2"]}

            await sess.cleanup_session_tabs("mykey")
            assert "mykey" not in sess._session_tabs
            assert "t1" not in sess._pages
            assert "t2" not in sess._pages
        finally:
            sess._pages = old_pages
            sess._session_tabs = old_session_tabs
