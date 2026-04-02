"""
Tests for sci_fi_dashboard.browser.interactions — page interaction implementations.

All functions are tested with fully mocked playwright Page objects.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.browser.interactions import (
    click,
    evaluate_js,
    fill_form,
    hover,
    press_key,
    select_option,
    take_screenshot,
    take_snapshot,
    type_text,
    wait_for,
    _BLOCKED_JS_PATTERNS,
    _MAX_SNAPSHOT_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_page(content="<html><body>Hello World</body></html>"):
    page = AsyncMock()
    locator = AsyncMock()
    locator.screenshot = AsyncMock(return_value=b"\x89PNG_FAKE")
    locator.click = AsyncMock()
    locator.dblclick = AsyncMock()
    locator.fill = AsyncMock()
    locator.hover = AsyncMock()
    locator.select_option = AsyncMock()
    page.locator = MagicMock(return_value=locator)
    page.screenshot = AsyncMock(return_value=b"\x89PNG_FAKE")
    page.content = AsyncMock(return_value=content)
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.evaluate = AsyncMock(return_value="42")
    page.wait_for_function = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_url = AsyncMock()
    page.viewport_size = {"width": 1280, "height": 720}
    page.set_viewport_size = AsyncMock()
    page.accessibility = MagicMock()
    page.accessibility.snapshot = AsyncMock(return_value={"role": "page"})
    return page


# ---------------------------------------------------------------------------
# take_screenshot
# ---------------------------------------------------------------------------


class TestTakeScreenshot:
    @pytest.mark.asyncio
    async def test_viewport_screenshot(self):
        page = _mock_page()
        result = await take_screenshot(page, full_page=False)
        assert isinstance(result, bytes)
        page.screenshot.assert_awaited_once_with(full_page=False)

    @pytest.mark.asyncio
    async def test_full_page_screenshot(self):
        page = _mock_page()
        result = await take_screenshot(page, full_page=True)
        page.screenshot.assert_awaited_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_element_screenshot(self):
        page = _mock_page()
        result = await take_screenshot(page, element_selector="#header")
        page.locator.assert_called_with("#header")

    @pytest.mark.asyncio
    async def test_resizes_oversized_viewport(self):
        page = _mock_page()
        page.viewport_size = {"width": 3000, "height": 3000}
        await take_screenshot(page, full_page=False)
        page.set_viewport_size.assert_awaited_once_with(
            {"width": 2000, "height": 2000}
        )


# ---------------------------------------------------------------------------
# take_snapshot
# ---------------------------------------------------------------------------


class TestTakeSnapshot:
    @pytest.mark.asyncio
    async def test_aria_format(self):
        page = _mock_page()
        result = await take_snapshot(page, format="aria")
        assert "snapshot" in result
        page.accessibility.snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ai_format_strips_scripts_and_styles(self):
        html = (
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert('x')</script>Hello World</body></html>"
        )
        page = _mock_page(content=html)
        result = await take_snapshot(page, format="ai")
        assert "alert" not in result["snapshot"]
        assert "color:red" not in result["snapshot"]
        assert "Hello World" in result["snapshot"]

    @pytest.mark.asyncio
    async def test_ai_format_truncation(self):
        page = _mock_page(content="<body>" + "A" * 60_000 + "</body>")
        result = await take_snapshot(page, format="ai")
        assert result["truncated"] is True
        assert len(result["snapshot"]) <= _MAX_SNAPSHOT_CHARS


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------


class TestClick:
    @pytest.mark.asyncio
    async def test_single_click(self):
        page = _mock_page()
        result = await click(page, selector="#btn")
        assert result["ok"] is True
        page.locator.assert_called_with("#btn")

    @pytest.mark.asyncio
    async def test_double_click(self):
        page = _mock_page()
        result = await click(page, selector="#btn", double=True)
        assert result["ok"] is True
        page.locator("#btn").dblclick.assert_awaited()


# ---------------------------------------------------------------------------
# type_text
# ---------------------------------------------------------------------------


class TestTypeText:
    @pytest.mark.asyncio
    async def test_type_text_fills_and_returns_ok(self):
        page = _mock_page()
        result = await type_text(page, selector="#input", text="hello")
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_type_text_with_submit(self):
        page = _mock_page()
        result = await type_text(page, selector="#input", text="hello", submit=True)
        page.keyboard.press.assert_awaited_once_with("Enter")


# ---------------------------------------------------------------------------
# press_key
# ---------------------------------------------------------------------------


class TestPressKey:
    @pytest.mark.asyncio
    async def test_press_key(self):
        page = _mock_page()
        result = await press_key(page, key="Escape")
        assert result["ok"] is True
        assert result["key"] == "Escape"


# ---------------------------------------------------------------------------
# hover
# ---------------------------------------------------------------------------


class TestHover:
    @pytest.mark.asyncio
    async def test_hover(self):
        page = _mock_page()
        result = await hover(page, selector="#menu")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# select_option
# ---------------------------------------------------------------------------


class TestSelectOption:
    @pytest.mark.asyncio
    async def test_select_option(self):
        page = _mock_page()
        result = await select_option(page, selector="#dropdown", values=["opt1", "opt2"])
        assert result["ok"] is True
        assert result["selected"] == ["opt1", "opt2"]


# ---------------------------------------------------------------------------
# fill_form
# ---------------------------------------------------------------------------


class TestFillForm:
    @pytest.mark.asyncio
    async def test_fill_form_multiple_fields(self):
        page = _mock_page()
        fields = [
            {"selector": "#name", "value": "Alice"},
            {"selector": "#email", "value": "alice@example.com"},
        ]
        result = await fill_form(page, fields=fields)
        assert result["ok"] is True
        assert result["filled"] == 2

    @pytest.mark.asyncio
    async def test_fill_form_empty_fields(self):
        page = _mock_page()
        result = await fill_form(page, fields=[])
        assert result["filled"] == 0


# ---------------------------------------------------------------------------
# wait_for
# ---------------------------------------------------------------------------


class TestWaitFor:
    @pytest.mark.asyncio
    async def test_wait_for_text(self):
        page = _mock_page()
        result = await wait_for(page, text="Loading complete")
        assert result["ok"] is True
        assert result["condition"] == "text"

    @pytest.mark.asyncio
    async def test_wait_for_selector(self):
        page = _mock_page()
        result = await wait_for(page, selector="#done")
        assert result["ok"] is True
        assert result["condition"] == "selector"

    @pytest.mark.asyncio
    async def test_wait_for_url(self):
        page = _mock_page()
        result = await wait_for(page, url="https://example.com/done")
        assert result["ok"] is True
        assert result["condition"] == "url"

    @pytest.mark.asyncio
    async def test_wait_for_none_specified(self):
        page = _mock_page()
        result = await wait_for(page)
        assert result["ok"] is False
        assert result["condition"] == "none_specified"

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_30s(self):
        page = _mock_page()
        await wait_for(page, text="hi", timeout_ms=60_000)
        # The actual timeout passed should be clamped to 30000
        page.wait_for_function.assert_awaited_once()
        call_kwargs = page.wait_for_function.call_args
        assert call_kwargs[1]["timeout"] == 30_000


# ---------------------------------------------------------------------------
# evaluate_js
# ---------------------------------------------------------------------------


class TestEvaluateJs:
    @pytest.mark.asyncio
    async def test_safe_expression_evaluated(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="1 + 1")
        assert result["ok"] is True
        assert result["result"] == "42"  # mock returns "42"

    @pytest.mark.asyncio
    async def test_blocked_fetch(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="fetch('https://evil.com')")
        assert result["ok"] is False
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_blocked_document_cookie(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="document.cookie")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_blocked_localstorage(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="localStorage.getItem('key')")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_blocked_websocket(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="new WebSocket('ws://evil.com')")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_blocked_eval(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="eval('alert(1)')")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_blocked_xmlhttprequest(self):
        page = _mock_page()
        result = await evaluate_js(page, expression="new XMLHttpRequest()")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_result_truncation(self):
        page = _mock_page()
        page.evaluate = AsyncMock(return_value="x" * 60_000)
        result = await evaluate_js(page, expression="'x'.repeat(60000)")
        assert result["truncated"] is True
        assert len(result["result"]) <= 50_000


# ---------------------------------------------------------------------------
# JS blocklist patterns
# ---------------------------------------------------------------------------


class TestJsBlocklistPatterns:
    def test_all_dangerous_patterns_covered(self):
        dangerous = [
            "fetch(", "XMLHttpRequest", "document.cookie",
            "localStorage", "sessionStorage", "indexedDB",
            "navigator.sendBeacon", "importScripts",
            "WebSocket", "eval(", "Function(",
        ]
        for expr in dangerous:
            blocked = any(p.search(expr) for p in _BLOCKED_JS_PATTERNS)
            assert blocked, f"Expected {expr!r} to be blocked"

    def test_safe_patterns_not_blocked(self):
        safe = [
            "document.title",
            "window.innerWidth",
            "document.querySelector('div')",
            "Math.random()",
        ]
        for expr in safe:
            blocked = any(p.search(expr) for p in _BLOCKED_JS_PATTERNS)
            assert not blocked, f"Expected {expr!r} to be safe"
