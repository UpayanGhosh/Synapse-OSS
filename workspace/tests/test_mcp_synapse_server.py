"""
Tests for sci_fi_dashboard.mcp_servers.synapse_server — full cognitive pipeline MCP.
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
    async def test_lists_all_four_tools(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"chat", "query_memory", "ingest_memory", "get_profile"}

    @pytest.mark.asyncio
    async def test_chat_requires_message(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import list_tools

        tools = await list_tools()
        chat_tool = next(t for t in tools if t.name == "chat")
        assert "message" in chat_tool.inputSchema.get("required", [])


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    @pytest.mark.asyncio
    async def test_lists_capabilities_resource(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import list_resources

        resources = await list_resources()
        assert len(resources) == 1
        assert "capabilities" in str(resources[0].uri)


# ---------------------------------------------------------------------------
# query_memory
# ---------------------------------------------------------------------------


class TestQueryMemory:
    @pytest.mark.asyncio
    async def test_query_memory_delegates_to_engine(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        mock_engine = MagicMock()
        mock_engine.query.return_value = [{"text": "result", "score": 0.9}]

        mock_mod = MagicMock()
        mock_mod.MemoryEngine.return_value = mock_engine

        with patch.dict("sys.modules", {"memory_engine": mock_mod}):
            result = await call_tool("query_memory", {"query": "test"})

        data = json.loads(_text(result))
        assert len(data) == 1


# ---------------------------------------------------------------------------
# ingest_memory
# ---------------------------------------------------------------------------


class TestIngestMemory:
    @pytest.mark.asyncio
    async def test_ingest_memory_stores_fact(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        mock_engine = MagicMock()
        mock_engine.add_memory.return_value = {"id": "mem_1"}

        mock_mod = MagicMock()
        mock_mod.MemoryEngine.return_value = mock_engine

        with patch.dict("sys.modules", {"memory_engine": mock_mod}):
            result = await call_tool(
                "ingest_memory",
                {"content": "A fact", "category": "user_input"},
            )

        data = json.loads(_text(result))
        assert "id" in data

    @pytest.mark.asyncio
    async def test_ingest_memory_default_category(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        mock_engine = MagicMock()
        mock_engine.add_memory.return_value = {}

        mock_mod = MagicMock()
        mock_mod.MemoryEngine.return_value = mock_engine

        with patch.dict("sys.modules", {"memory_engine": mock_mod}):
            await call_tool("ingest_memory", {"content": "fact"})

        mock_engine.add_memory.assert_called_once_with("fact", "mcp_ingest")


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_get_profile_returns_summary(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        mock_orch = MagicMock()
        mock_orch.get_profile_summary.return_value = {
            "mood": "happy",
            "message_count": 42,
        }

        mock_cfg = MagicMock()
        mock_cfg.sbs_dir = "/tmp/sbs"

        mock_config_mod = MagicMock()
        mock_config_mod.SynapseConfig.load.return_value = mock_cfg

        mock_sbs_mod = MagicMock()
        mock_sbs_mod.SBSOrchestrator.return_value = mock_orch

        with patch.dict("sys.modules", {
            "synapse_config": mock_config_mod,
            "sbs.orchestrator": mock_sbs_mod,
        }):
            result = await call_tool("get_profile", {})

        data = json.loads(_text(result))
        assert data["mood"] == "happy"
        assert data["message_count"] == 42


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_posts_to_local_endpoint(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        mock_resp = MagicMock()
        mock_resp.text = '{"response": "Hi!"}'

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await call_tool("chat", {"message": "hello"})

        assert "Hi!" in _text(result)
        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://127.0.0.1:8000/chat"
        assert call_args[1]["json"]["message"] == "hello"


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        from sci_fi_dashboard.mcp_servers.synapse_server import call_tool

        result = await call_tool("not_a_tool", {})
        assert "Unknown tool" in _text(result)
