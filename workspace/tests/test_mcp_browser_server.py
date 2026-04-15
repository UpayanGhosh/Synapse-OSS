"""
Tests for sci_fi_dashboard.mcp_servers.browser_server — headless Chromium MCP.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _text(results: list) -> str:
    return results[0].text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_browser_tool(self):
        from sci_fi_dashboard.mcp_servers.browser_server import list_tools

        tools = await list_tools()
        assert len(tools) == 1
        assert tools[0].name == "browser"

    @pytest.mark.asyncio
    async def test_browser_tool_has_action_enum(self):
        from sci_fi_dashboard.mcp_servers.browser_server import list_tools

        tools = await list_tools()
        action_prop = tools[0].inputSchema["properties"]["action"]
        assert "enum" in action_prop
        expected_actions = {
            "start",
            "stop",
            "status",
            "open",
            "close",
            "tabs",
            "navigate",
            "screenshot",
            "snapshot",
            "console",
            "act",
        }
        assert set(action_prop["enum"]) == expected_actions

    @pytest.mark.asyncio
    async def test_required_is_action(self):
        from sci_fi_dashboard.mcp_servers.browser_server import list_tools

        tools = await list_tools()
        assert tools[0].inputSchema["required"] == ["action"]


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


class TestLifecycleActions:
    @pytest.mark.asyncio
    async def test_start_browser(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.start_browser = AsyncMock(return_value={"status": "started"})

        with (
            patch("sci_fi_dashboard.mcp_servers.browser_server.call_tool.__module__"),
            patch.dict(
                "sys.modules",
                {
                    "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                        NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                    ),
                    "sci_fi_dashboard.browser.session": mock_sess,
                    "sci_fi_dashboard.browser.interactions": MagicMock(),
                },
            ),
        ):
            result = await call_tool("browser", {"action": "start"})

        data = json.loads(_text(result))
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_stop_browser(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.stop_browser = AsyncMock(return_value={"status": "stopped"})

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                    NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                ),
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "stop"})

        data = json.loads(_text(result))
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_status(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.get_status = AsyncMock(
            return_value={"connected": True, "tab_count": 2, "tabs": ["t1", "t2"]}
        )

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                    NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                ),
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "status"})

        data = json.loads(_text(result))
        assert data["connected"] is True
        assert data["tab_count"] == 2


# ---------------------------------------------------------------------------
# Tab management
# ---------------------------------------------------------------------------


class TestTabManagement:
    @pytest.mark.asyncio
    async def test_open_tab(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.open_tab = AsyncMock(
            return_value={"tab_id": "t1", "url": "https://example.com", "title": "Example"}
        )

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                    NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                ),
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "open", "url": "https://example.com"})

        data = json.loads(_text(result))
        assert data["tab_id"] == "t1"

    @pytest.mark.asyncio
    async def test_close_tab(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.close_tab = AsyncMock(return_value={"closed": "t1"})

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                    NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                ),
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "close", "tab_id": "t1"})

        data = json.loads(_text(result))
        assert data["closed"] == "t1"

    @pytest.mark.asyncio
    async def test_list_tabs(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.list_tabs = AsyncMock(
            return_value=[
                {"tab_id": "t1", "url": "https://a.com", "title": "A"},
            ]
        )

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": MagicMock(
                    NavigationBlockedError=type("NBE", (Exception,), {"reason": ""})
                ),
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "tabs"})

        data = json.loads(_text(result))
        assert len(data) == 1


# ---------------------------------------------------------------------------
# Navigation blocked
# ---------------------------------------------------------------------------


class TestNavigationBlocked:
    @pytest.mark.asyncio
    async def test_blocked_navigation_returns_blocked_message(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        class NavigationBlockedError(Exception):
            def __init__(self, url, reason):
                self.url = url
                self.reason = reason
                super().__init__(f"Blocked: {reason}")

        mock_sess = MagicMock()
        mock_sess.navigate = AsyncMock(
            side_effect=NavigationBlockedError("http://169.254.0.1", "SSRF")
        )

        mock_nav = MagicMock()
        mock_nav.NavigationBlockedError = NavigationBlockedError

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": mock_nav,
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool(
                "browser",
                {"action": "navigate", "tab_id": "t1", "url": "http://169.254.0.1"},
            )

        assert "BLOCKED:" in _text(result)


# ---------------------------------------------------------------------------
# Missing parameter
# ---------------------------------------------------------------------------


class TestMissingParameter:
    @pytest.mark.asyncio
    async def test_missing_tab_id_for_close(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_sess = MagicMock()
        mock_sess.close_tab = AsyncMock(side_effect=KeyError("tab_id"))

        mock_nav = MagicMock()
        mock_nav.NavigationBlockedError = type("NBE", (Exception,), {"reason": ""})

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": mock_nav,
                "sci_fi_dashboard.browser.session": mock_sess,
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "close"})

        assert "Missing parameter" in _text(result) or "Error" in _text(result)


# ---------------------------------------------------------------------------
# Unknown action / tool
# ---------------------------------------------------------------------------


class TestUnknown:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        mock_nav = MagicMock()
        mock_nav.NavigationBlockedError = type("NBE", (Exception,), {"reason": ""})

        with patch.dict(
            "sys.modules",
            {
                "sci_fi_dashboard.browser.navigation_guard": mock_nav,
                "sci_fi_dashboard.browser.session": MagicMock(),
                "sci_fi_dashboard.browser.interactions": MagicMock(),
            },
        ):
            result = await call_tool("browser", {"action": "badaction"})

        assert "Unknown action" in _text(result)

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        from sci_fi_dashboard.mcp_servers.browser_server import call_tool

        result = await call_tool("not_browser", {})
        assert "Unknown tool" in _text(result)
