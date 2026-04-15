"""
Tests for sci_fi_dashboard.mcp_servers.memory_server — knowledge base query + fact ingest.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _text(results: list) -> str:
    return results[0].text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_query_and_add_memory(self):
        from sci_fi_dashboard.mcp_servers.memory_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"query_memory", "add_memory"}

    @pytest.mark.asyncio
    async def test_query_memory_schema_has_required_query(self):
        from sci_fi_dashboard.mcp_servers.memory_server import list_tools

        tools = await list_tools()
        query_tool = next(t for t in tools if t.name == "query_memory")
        assert "query" in query_tool.inputSchema.get("required", [])

    @pytest.mark.asyncio
    async def test_add_memory_schema_has_required_content(self):
        from sci_fi_dashboard.mcp_servers.memory_server import list_tools

        tools = await list_tools()
        add_tool = next(t for t in tools if t.name == "add_memory")
        assert "content" in add_tool.inputSchema.get("required", [])


# ---------------------------------------------------------------------------
# Resource templates
# ---------------------------------------------------------------------------


class TestResourceTemplates:
    @pytest.mark.asyncio
    async def test_lists_memory_search_template(self):
        from sci_fi_dashboard.mcp_servers.memory_server import list_resource_templates

        templates = await list_resource_templates()
        assert len(templates) == 1
        assert "memory/search" in templates[0].uriTemplate


# ---------------------------------------------------------------------------
# query_memory tool
# ---------------------------------------------------------------------------


class TestQueryMemory:
    @pytest.mark.asyncio
    async def test_query_returns_json_results(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        mock_engine.query.return_value = [
            {"text": "fact 1", "score": 0.95},
            {"text": "fact 2", "score": 0.80},
        ]

        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            result = await mem_srv.call_tool("query_memory", {"query": "test"})

        data = json.loads(_text(result))
        assert len(data) == 2
        assert data[0]["text"] == "fact 1"

    @pytest.mark.asyncio
    async def test_query_passes_limit_and_with_graph(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        mock_engine.query.return_value = []

        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            await mem_srv.call_tool(
                "query_memory",
                {"query": "test", "limit": 10, "with_graph": False},
            )

        mock_engine.query.assert_called_once_with(text="test", limit=10, with_graph=False)

    @pytest.mark.asyncio
    async def test_query_defaults_limit_5_graph_true(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        mock_engine.query.return_value = []

        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            await mem_srv.call_tool("query_memory", {"query": "test"})

        mock_engine.query.assert_called_once_with(text="test", limit=5, with_graph=True)


# ---------------------------------------------------------------------------
# add_memory tool
# ---------------------------------------------------------------------------


class TestAddMemory:
    @pytest.mark.asyncio
    async def test_add_memory_returns_result(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        mock_engine.add_memory.return_value = {"id": "mem_123", "status": "ok"}

        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            result = await mem_srv.call_tool(
                "add_memory", {"content": "Test fact", "category": "test"}
            )

        data = json.loads(_text(result))
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_add_memory_default_category(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        mock_engine.add_memory.return_value = {"id": "mem_456"}

        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            await mem_srv.call_tool("add_memory", {"content": "some fact"})

        mock_engine.add_memory.assert_called_once_with("some fact", "direct_entry")


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        with patch.object(mem_srv, "_get_engine", return_value=mock_engine):
            result = await mem_srv.call_tool("nonexistent", {})

        assert "Unknown tool" in _text(result)


# ---------------------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------------------


class TestEngineSingleton:
    def test_get_engine_caches_instance(self):
        import sci_fi_dashboard.mcp_servers.memory_server as mem_srv

        mock_engine = MagicMock()
        with patch.dict(
            "sys.modules", {"memory_engine": MagicMock(MemoryEngine=lambda: mock_engine)}
        ):
            mem_srv._engine = None  # reset
            e1 = mem_srv._get_engine()
            e2 = mem_srv._get_engine()
            assert e1 is e2

        # Cleanup
        mem_srv._engine = None
