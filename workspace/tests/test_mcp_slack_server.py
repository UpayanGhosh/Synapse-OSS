"""
Tests for sci_fi_dashboard.mcp_servers.slack_server — Slack MCP integration.
"""
from __future__ import annotations

import json
import os
import sys
import time
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
    async def test_lists_all_slack_tools(self):
        from sci_fi_dashboard.mcp_servers.slack_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"list_channels", "read_messages", "get_mentions", "send_message"}

    @pytest.mark.asyncio
    async def test_send_message_requires_channel_and_text(self):
        from sci_fi_dashboard.mcp_servers.slack_server import list_tools

        tools = await list_tools()
        send_tool = next(t for t in tools if t.name == "send_message")
        required = send_tool.inputSchema.get("required", [])
        assert "channel_id" in required
        assert "text" in required


# ---------------------------------------------------------------------------
# list_channels
# ---------------------------------------------------------------------------


class TestListChannels:
    @pytest.mark.asyncio
    async def test_returns_channel_summaries(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        mock_bot = AsyncMock()
        mock_bot.conversations_list = AsyncMock(return_value={
            "channels": [
                {"id": "C001", "name": "general", "topic": {"value": "General chat"}},
                {"id": "C002", "name": "dev", "topic": {"value": "Dev talk"}},
            ]
        })
        mock_clients = {"bot": mock_bot, "user": None}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool("list_channels", {"limit": 50})

        data = json.loads(_text(result))
        assert len(data) == 2
        assert data[0]["name"] == "general"
        assert data[1]["topic"] == "Dev talk"


# ---------------------------------------------------------------------------
# read_messages
# ---------------------------------------------------------------------------


class TestReadMessages:
    @pytest.mark.asyncio
    async def test_returns_message_list(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        mock_bot = AsyncMock()
        mock_bot.conversations_history = AsyncMock(return_value={
            "messages": [
                {"user": "U001", "text": "Hello", "ts": "1700000001.000"},
                {"user": "U002", "text": "Hi", "ts": "1700000002.000"},
            ]
        })
        mock_clients = {"bot": mock_bot, "user": None}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool(
                "read_messages", {"channel_id": "C001", "limit": 10}
            )

        data = json.loads(_text(result))
        assert len(data) == 2
        assert data[0]["text"] == "Hello"


# ---------------------------------------------------------------------------
# get_mentions
# ---------------------------------------------------------------------------


class TestGetMentions:
    @pytest.mark.asyncio
    async def test_returns_recent_mentions(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        now_ts = str(time.time())

        mock_bot = AsyncMock()
        mock_bot.auth_test = AsyncMock(return_value={"user_id": "U_BOT"})
        mock_bot.search_messages = AsyncMock(return_value={
            "messages": {
                "matches": [
                    {
                        "channel": {"name": "general"},
                        "username": "alice",
                        "text": "Hey <@U_BOT> help me",
                        "ts": now_ts,
                    },
                ]
            }
        })
        mock_clients = {"bot": mock_bot, "user": None}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool("get_mentions", {"since_hours": 1})

        data = json.loads(_text(result))
        assert len(data) == 1
        assert data[0]["user"] == "alice"

    @pytest.mark.asyncio
    async def test_old_mentions_filtered_out(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        old_ts = str(time.time() - 7200)  # 2 hours ago

        mock_bot = AsyncMock()
        mock_bot.auth_test = AsyncMock(return_value={"user_id": "U_BOT"})
        mock_bot.search_messages = AsyncMock(return_value={
            "messages": {
                "matches": [
                    {
                        "channel": {"name": "general"},
                        "username": "bob",
                        "text": "Old mention",
                        "ts": old_ts,
                    },
                ]
            }
        })
        mock_clients = {"bot": mock_bot, "user": None}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool("get_mentions", {"since_hours": 1})

        data = json.loads(_text(result))
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_uses_user_client_if_available(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        mock_bot = AsyncMock()
        mock_bot.auth_test = AsyncMock(return_value={"user_id": "U_BOT"})

        mock_user = AsyncMock()
        mock_user.search_messages = AsyncMock(return_value={
            "messages": {"matches": []}
        })

        mock_clients = {"bot": mock_bot, "user": mock_user}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            await slack_srv.call_tool("get_mentions", {"since_hours": 1})

        mock_user.search_messages.assert_awaited_once()
        mock_bot.search_messages.assert_not_awaited()


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_sends_message_to_channel(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        mock_bot = AsyncMock()
        mock_bot.chat_postMessage = AsyncMock()
        mock_clients = {"bot": mock_bot, "user": None}

        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool(
                "send_message", {"channel_id": "C001", "text": "Hello!"}
            )

        assert "Message sent" in _text(result)
        mock_bot.chat_postMessage.assert_awaited_once_with(
            channel="C001", text="Hello!"
        )


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        import sci_fi_dashboard.mcp_servers.slack_server as slack_srv

        mock_clients = {"bot": AsyncMock(), "user": None}
        with patch.object(slack_srv, "_get_slack_client", return_value=mock_clients):
            result = await slack_srv.call_tool("nonexistent", {})

        assert "Unknown tool" in _text(result)
