"""
Tests for sci_fi_dashboard.mcp_servers.tools_server — Sentinel-gated file ops + web search.
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(results: list) -> str:
    """Extract plain text from a list of TextContent objects."""
    return results[0].text


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_returns_all_tools(self):
        from sci_fi_dashboard.mcp_servers.tools_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "web_search", "read_file", "write_file",
            "edit_file", "delete_file", "list_directory",
        }

    @pytest.mark.asyncio
    async def test_tool_schemas_have_required_fields(self):
        from sci_fi_dashboard.mcp_servers.tools_server import list_tools

        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert "type" in tool.inputSchema
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema


# ---------------------------------------------------------------------------
# web_search tool
# ---------------------------------------------------------------------------


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_web_search_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        mock_content = "# Example\nSome markdown content"
        with patch("sci_fi_dashboard.mcp_servers.tools_server.call_tool.__module__"):
            # We need to patch the import inside call_tool
            mock_registry = MagicMock()
            mock_registry.search_web = AsyncMock(return_value=mock_content)
            with patch.dict("sys.modules", {"db.tools": MagicMock(ToolRegistry=mock_registry)}):
                result = await call_tool("web_search", {"url": "https://example.com"})

        assert _text(result) == mock_content

    @pytest.mark.asyncio
    async def test_web_search_exception_returns_error(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        mock_mod = MagicMock()
        mock_mod.ToolRegistry.search_web = AsyncMock(side_effect=ConnectionError("timeout"))
        with patch.dict("sys.modules", {"db.tools": mock_mod}):
            result = await call_tool("web_search", {"url": "https://bad.example.com"})

        assert "Web search error:" in _text(result)
        assert "timeout" in _text(result)


# ---------------------------------------------------------------------------
# read_file tool
# ---------------------------------------------------------------------------


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_file_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        mock_sentinel = MagicMock()
        mock_sentinel.check_access.return_value = "/resolved/path.txt"

        paged_result = {"content": "hello", "offset": 0, "size": 5, "truncated": False}

        sentinel_mod = MagicMock()
        sentinel_mod._sentinel = mock_sentinel

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = type("SentinelError", (Exception,), {})

        paging_mod = MagicMock()
        paging_mod.read_file_paged = MagicMock(return_value=paged_result)

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.paging": paging_mod,
        }):
            result = await call_tool("read_file", {"path": "/some/file.txt"})

        data = json.loads(_text(result))
        assert data["content"] == "hello"

    @pytest.mark.asyncio
    async def test_read_file_sentinel_not_initialized(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod._sentinel = None

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = type("SentinelError", (Exception,), {})

        paging_mod = MagicMock()

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.paging": paging_mod,
        }):
            result = await call_tool("read_file", {"path": "/some/file.txt"})

        assert "ERROR:" in _text(result)

    @pytest.mark.asyncio
    async def test_read_file_permission_denied(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        SentinelError = type("SentinelError", (Exception,), {})

        sentinel_mod = MagicMock()
        sentinel_mod._sentinel = MagicMock()
        sentinel_mod._sentinel.check_access.side_effect = SentinelError("not allowed")

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = SentinelError

        paging_mod = MagicMock()

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.paging": paging_mod,
        }):
            result = await call_tool("read_file", {"path": "/etc/shadow"})

        assert "DENIED:" in _text(result)

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod._sentinel = MagicMock()
        sentinel_mod._sentinel.check_access.side_effect = FileNotFoundError("missing")

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = type("SentinelError", (Exception,), {})

        paging_mod = MagicMock()

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.paging": paging_mod,
        }):
            result = await call_tool("read_file", {"path": "/no/such/file.txt"})

        assert "NOT_FOUND:" in _text(result)

    @pytest.mark.asyncio
    async def test_read_file_passes_offset_and_page_bytes(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        mock_sentinel = MagicMock()
        mock_sentinel.check_access.return_value = "/resolved/path.txt"

        sentinel_mod = MagicMock()
        sentinel_mod._sentinel = mock_sentinel

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = type("SentinelError", (Exception,), {})

        paging_mod = MagicMock()
        paging_mod.read_file_paged = MagicMock(
            return_value={"content": "data", "offset": 100, "size": 4, "truncated": False}
        )

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.paging": paging_mod,
        }):
            result = await call_tool(
                "read_file",
                {"path": "/some/file.txt", "offset": 100, "page_bytes": 65536},
            )

        paging_mod.read_file_paged.assert_called_once_with(
            "/resolved/path.txt", offset=100, page_bytes=65536
        )


# ---------------------------------------------------------------------------
# write_file tool
# ---------------------------------------------------------------------------


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_file_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_write_file = MagicMock(return_value="Written 5 bytes")

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool(
                "write_file", {"path": "/some/file.txt", "content": "hello"}
            )

        assert "Written" in _text(result)

    @pytest.mark.asyncio
    async def test_write_file_permission_denied(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_write_file = MagicMock(side_effect=PermissionError("denied"))

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool(
                "write_file", {"path": "/root/file.txt", "content": "bad"}
            )

        assert "DENIED:" in _text(result)


# ---------------------------------------------------------------------------
# edit_file tool
# ---------------------------------------------------------------------------


class TestEditFile:
    @pytest.mark.asyncio
    async def test_edit_file_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_check_write_access = MagicMock(return_value="/resolved/file.py")

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = type("SentinelError", (Exception,), {})

        edit_mod = MagicMock()
        edit_mod.apply_edit = MagicMock(return_value={"ok": True, "replacements": 1})

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.edit": edit_mod,
        }):
            result = await call_tool(
                "edit_file",
                {"path": "/some/file.py", "old_text": "foo", "new_text": "bar"},
            )

        data = json.loads(_text(result))
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_edit_file_sentinel_denied(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        SentinelError = type("SentinelError", (Exception,), {})

        sentinel_mod = MagicMock()
        sentinel_mod.agent_check_write_access = MagicMock(
            side_effect=SentinelError("denied")
        )

        gateway_mod = MagicMock()
        gateway_mod.SentinelError = SentinelError

        edit_mod = MagicMock()

        with patch.dict("sys.modules", {
            "sbs.sentinel.tools": sentinel_mod,
            "sbs.sentinel.gateway": gateway_mod,
            "file_ops.edit": edit_mod,
        }):
            result = await call_tool(
                "edit_file",
                {"path": "/file.py", "old_text": "a", "new_text": "b"},
            )

        assert "DENIED:" in _text(result)


# ---------------------------------------------------------------------------
# delete_file tool
# ---------------------------------------------------------------------------


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_delete_file_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_delete_file = MagicMock(return_value="Deleted /file.txt")

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool("delete_file", {"path": "/file.txt"})

        assert "Deleted" in _text(result)

    @pytest.mark.asyncio
    async def test_delete_file_sentinel_denied(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_delete_file = MagicMock(
            return_value="[SENTINEL DENIED] not allowed"
        )

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool("delete_file", {"path": "/etc/passwd"})

        assert "DENIED:" in _text(result)

    @pytest.mark.asyncio
    async def test_delete_file_with_reason(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_delete_file = MagicMock(return_value="Deleted /tmp/old.txt")

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool(
                "delete_file", {"path": "/tmp/old.txt", "reason": "cleanup"}
            )

        sentinel_mod.agent_delete_file.assert_called_once_with("/tmp/old.txt", "cleanup")


# ---------------------------------------------------------------------------
# list_directory tool
# ---------------------------------------------------------------------------


class TestListDirectory:
    @pytest.mark.asyncio
    async def test_list_directory_success(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_list_directory = MagicMock(
            return_value="file1.txt\nfile2.py\n"
        )

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool("list_directory", {"path": "/some/dir"})

        assert "file1.txt" in _text(result)

    @pytest.mark.asyncio
    async def test_list_directory_sentinel_denied(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        sentinel_mod = MagicMock()
        sentinel_mod.agent_list_directory = MagicMock(
            return_value="[SENTINEL DENIED] access blocked"
        )

        with patch.dict("sys.modules", {"sbs.sentinel.tools": sentinel_mod}):
            result = await call_tool("list_directory", {"path": "/secret"})

        assert "DENIED:" in _text(result)


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from sci_fi_dashboard.mcp_servers.tools_server import call_tool

        result = await call_tool("nonexistent_tool", {})
        assert "Unknown tool: nonexistent_tool" in _text(result)
