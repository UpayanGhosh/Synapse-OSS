"""
Tests for sci_fi_dashboard.mcp_client — MCP client connection lifecycle, tool routing, discovery.
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.mcp_client import MCPServerConnection, SynapseMCPClient


# ---------------------------------------------------------------------------
# MCPServerConnection dataclass
# ---------------------------------------------------------------------------


class TestMCPServerConnection:
    def test_defaults(self):
        conn = MCPServerConnection(name="test")
        assert conn.name == "test"
        assert conn.session is None
        assert conn.tools == []
        assert conn.connected is False
        assert conn.ctx is None


# ---------------------------------------------------------------------------
# SynapseMCPClient — tool map and listing
# ---------------------------------------------------------------------------


class TestToolMap:
    def test_list_all_tools_empty_when_no_servers(self):
        client = SynapseMCPClient()
        assert client.list_all_tools() == []

    def test_list_all_tools_includes_qualified_names(self):
        client = SynapseMCPClient()
        client._servers["test_server"] = MCPServerConnection(
            name="test_server",
            connected=True,
            tools=[
                {"name": "search", "description": "Search", "inputSchema": {}},
                {"name": "write", "description": "Write", "inputSchema": {}},
            ],
        )
        tools = client.list_all_tools()
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert "test_server__search" in names
        assert "test_server__write" in names

    def test_descriptions_prefixed_with_server_name(self):
        client = SynapseMCPClient()
        client._servers["myserver"] = MCPServerConnection(
            name="myserver",
            connected=True,
            tools=[{"name": "tool1", "description": "A tool", "inputSchema": {}}],
        )
        tools = client.list_all_tools()
        assert "[myserver]" in tools[0]["description"]


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------


class TestCallTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        client = SynapseMCPClient()
        result = await client.call_tool("nonexistent_tool", {})
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_disconnected_server_returns_error(self):
        client = SynapseMCPClient()
        client._tool_map["server__tool"] = ("server", "tool")
        client._servers["server"] = MCPServerConnection(
            name="server", connected=False
        )
        result = await client.call_tool("server__tool", {})
        data = json.loads(result)
        assert "not connected" in data["error"]

    @pytest.mark.asyncio
    async def test_successful_call_returns_text(self):
        client = SynapseMCPClient()
        client._tool_map["server__tool"] = ("server", "tool")

        mock_content = MagicMock()
        mock_content.text = "result text"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        client._servers["server"] = MCPServerConnection(
            name="server", session=mock_session, connected=True
        )

        result = await client.call_tool("server__tool", {"arg": "val"})
        assert result == "result text"

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        import asyncio

        client = SynapseMCPClient()
        client._tool_map["server__tool"] = ("server", "tool")

        mock_session = AsyncMock()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(100)

        mock_session.call_tool = slow_call

        client._servers["server"] = MCPServerConnection(
            name="server", session=mock_session, connected=True
        )

        result = await client.call_tool("server__tool", {}, timeout=0.01)
        data = json.loads(result)
        assert "timed out" in data["error"]

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        client = SynapseMCPClient()
        client._tool_map["server__tool"] = ("server", "tool")

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("boom"))

        client._servers["server"] = MCPServerConnection(
            name="server", session=mock_session, connected=True
        )

        result = await client.call_tool("server__tool", {})
        data = json.loads(result)
        assert "boom" in data["error"]


# ---------------------------------------------------------------------------
# add_server / remove_server
# ---------------------------------------------------------------------------


class TestDynamicServerManagement:
    @pytest.mark.asyncio
    async def test_add_server_already_connected(self):
        client = SynapseMCPClient()
        client._servers["existing"] = MCPServerConnection(
            name="existing", connected=True
        )
        result = await client.add_server("existing", "python", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_server_not_found(self):
        client = SynapseMCPClient()
        result = await client.remove_server("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_server_cleans_up(self):
        client = SynapseMCPClient()
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()

        client._servers["myserver"] = MCPServerConnection(
            name="myserver",
            session=mock_session,
            ctx=mock_ctx,
            connected=True,
            tools=[{"name": "tool1", "description": "t", "inputSchema": {}}],
        )
        client._tool_map["myserver__tool1"] = ("myserver", "tool1")

        result = await client.remove_server("myserver")
        assert result is True
        assert "myserver" not in client._servers
        assert "myserver__tool1" not in client._tool_map


# ---------------------------------------------------------------------------
# disconnect_all
# ---------------------------------------------------------------------------


class TestDisconnectAll:
    @pytest.mark.asyncio
    async def test_disconnect_all_clears_state(self):
        client = SynapseMCPClient()
        client._servers["a"] = MCPServerConnection(
            name="a", session=AsyncMock(), ctx=AsyncMock()
        )
        client._servers["b"] = MCPServerConnection(
            name="b", session=AsyncMock(), ctx=AsyncMock()
        )
        client._tool_map["a__t"] = ("a", "t")
        client._tool_map["b__t"] = ("b", "t")

        await client.disconnect_all()
        assert len(client._servers) == 0
        assert len(client._tool_map) == 0

    @pytest.mark.asyncio
    async def test_disconnect_all_handles_errors(self):
        client = SynapseMCPClient()
        bad_session = AsyncMock()
        bad_session.__aexit__ = AsyncMock(side_effect=RuntimeError("fail"))

        client._servers["bad"] = MCPServerConnection(
            name="bad", session=bad_session, ctx=None
        )

        # Should not raise
        await client.disconnect_all()
        assert len(client._servers) == 0


# ---------------------------------------------------------------------------
# connect_all
# ---------------------------------------------------------------------------


class TestConnectAll:
    @pytest.mark.asyncio
    async def test_connect_all_builtin_and_custom(self):
        client = SynapseMCPClient()

        mock_config = MagicMock()
        mock_builtin = MagicMock()
        mock_builtin.enabled = True
        mock_config.builtin_servers = {"memory": mock_builtin}

        mock_custom = MagicMock()
        mock_custom.command = "python"
        mock_custom.args = ["-m", "custom_server"]
        mock_custom.env = None
        mock_config.custom_servers = {"custom1": mock_custom}

        with patch.object(client, "connect_builtin_server", new_callable=AsyncMock) as mock_bi:
            with patch.object(client, "connect_custom_server", new_callable=AsyncMock) as mock_cs:
                await client.connect_all(mock_config)

        mock_bi.assert_awaited_once()
        mock_cs.assert_awaited_once()
