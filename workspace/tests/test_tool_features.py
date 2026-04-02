"""
Test Suite: Tool Features (Phase 5)
====================================
Tests the user-facing tool layer: footer formatting, model override store,
built-in tool handlers, command shortcuts, HTTP invocation helpers, and
tool catalog builder.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.tool_features import (
    CommandResult,
    ToolInvokeRequest,
    ToolInvokeResponse,
    UserToolDef,
    build_tool_catalog,
    clear_model_override,
    format_tool_footer,
    get_import_memory_tool,
    get_list_tools_tool,
    get_model_override,
    get_switch_model_tool,
    handle_tool_invoke,
    parse_command_shortcut,
    set_model_override,
)


# ---------------------------------------------------------------------------
# Helper: reset global override store between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Ensure a clean override store for every test."""
    from sci_fi_dashboard import tool_features

    tool_features._model_overrides.clear()
    yield
    tool_features._model_overrides.clear()


# ---------------------------------------------------------------------------
# 1. format_tool_footer
# ---------------------------------------------------------------------------


class TestToolFooter:
    """Tests for format_tool_footer."""

    @pytest.mark.unit
    def test_footer_with_tools(self):
        """Footer includes tool names, time, and round count."""
        result = format_tool_footer(
            tools_used=["web_search", "read_file"],
            total_tool_time=1.234,
            round_count=2,
        )
        assert "---" in result
        assert "web_search" in result
        assert "read_file" in result
        assert "1.2s" in result
        assert "Rounds: 2" in result

    @pytest.mark.unit
    def test_footer_empty_tools(self):
        """No tools used returns empty string."""
        result = format_tool_footer(
            tools_used=[], total_tool_time=0.0, round_count=0
        )
        assert result == ""

    @pytest.mark.unit
    def test_footer_deduplicates_tools(self):
        """Duplicate tool names are collapsed while preserving order."""
        result = format_tool_footer(
            tools_used=["web_search", "read_file", "web_search"],
            total_tool_time=2.0,
            round_count=3,
        )
        # Should appear exactly once
        assert result.count("web_search") == 1
        # read_file should still be present
        assert "read_file" in result

    @pytest.mark.unit
    def test_footer_is_ascii_safe(self):
        """Footer must be encodable to cp1252 (Windows console)."""
        result = format_tool_footer(
            tools_used=["tool_a"], total_tool_time=0.5, round_count=1
        )
        # Should not raise
        result.encode("cp1252")


# ---------------------------------------------------------------------------
# 2. Model Override Store
# ---------------------------------------------------------------------------


class TestModelOverrideStore:
    """Tests for the in-memory model override store."""

    @pytest.mark.unit
    def test_set_get_clear_cycle(self):
        """set -> get -> clear -> get returns None."""
        assert get_model_override("chat_1") is None
        set_model_override("chat_1", "code")
        assert get_model_override("chat_1") == "code"
        clear_model_override("chat_1")
        assert get_model_override("chat_1") is None

    @pytest.mark.unit
    def test_clear_nonexistent_is_noop(self):
        """Clearing a key that was never set does not raise."""
        clear_model_override("never_existed")  # should not raise


# ---------------------------------------------------------------------------
# 3. Built-in Tool Handlers
# ---------------------------------------------------------------------------


class TestSwitchModelTool:
    """Tests for the switch_model tool handler."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_role(self):
        """Valid role -> success, override stored."""
        tool = get_switch_model_tool(["casual", "code", "analysis"])
        result = await tool.handler(
            {"model_role": "code", "_chat_id": "chat_42"}
        )
        assert result["is_error"] is False
        assert "code" in result["content"]
        assert get_model_override("chat_42") == "code"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_role(self):
        """Invalid role -> error, no side-effects."""
        tool = get_switch_model_tool(["casual", "code"])
        result = await tool.handler(
            {"model_role": "nonexistent", "_chat_id": "chat_42"}
        )
        assert result["is_error"] is True
        assert "nonexistent" in result["content"]
        assert get_model_override("chat_42") is None

    @pytest.mark.unit
    def test_tool_metadata(self):
        """Tool definition has correct metadata."""
        tool = get_switch_model_tool(["casual", "code"])
        assert tool.name == "switch_model"
        assert tool.owner_only is True
        assert "casual" in tool.description
        assert tool.parameters["required"] == ["model_role"]


class TestImportMemoryTool:
    """Tests for the import_memory tool handler."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_content(self):
        """Valid content -> success with _action payload."""
        tool = get_import_memory_tool()
        result = await tool.handler(
            {"content": "Python was created by Guido", "category": "fact"}
        )
        assert result["is_error"] is False
        assert result["_action"] == "ingest_memory"
        assert result["_payload"]["category"] == "fact"
        assert "Python" in result["_payload"]["content"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty_content(self):
        """Empty content -> error."""
        tool = get_import_memory_tool()
        result = await tool.handler({"content": "   "})
        assert result["is_error"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_category(self):
        """Missing category defaults to 'general'."""
        tool = get_import_memory_tool()
        result = await tool.handler({"content": "some fact"})
        assert result["_payload"]["category"] == "general"


class TestListToolsTool:
    """Tests for the list_tools tool handler."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lists_tools(self):
        """Returns JSON listing of available tools."""
        catalog = [{"name": "web_search"}, {"name": "read_file"}]
        tool = get_list_tools_tool(catalog)
        result = await tool.handler({})
        assert result["is_error"] is False
        import json

        parsed = json.loads(result["content"])
        assert len(parsed) == 2
        assert parsed[0]["name"] == "web_search"


# ---------------------------------------------------------------------------
# 4. Command Shortcut Parser
# ---------------------------------------------------------------------------


class TestCommandShortcuts:
    """Tests for parse_command_shortcut."""

    @pytest.mark.unit
    def test_model_command_valid_role(self):
        """'/model code' -> switches model, is_command=True."""
        result = parse_command_shortcut(
            "/model code", "chat_1", ["casual", "code"]
        )
        assert result.is_command is True
        assert result.action == "switch_model"
        assert "code" in result.response
        assert get_model_override("chat_1") == "code"

    @pytest.mark.unit
    def test_model_command_invalid_role(self):
        """'/model bogus' -> error, no override stored."""
        result = parse_command_shortcut(
            "/model bogus", "chat_1", ["casual", "code"]
        )
        assert result.is_command is True
        assert "Unknown" in result.response
        assert result.action is None
        assert get_model_override("chat_1") is None

    @pytest.mark.unit
    def test_tools_command(self):
        """/tools -> is_command=True, action=list_tools."""
        result = parse_command_shortcut(
            "/tools", "chat_1", ["casual"]
        )
        assert result.is_command is True
        assert result.action == "list_tools"
        assert result.response is None

    @pytest.mark.unit
    def test_forget_command(self):
        """/forget -> clears override."""
        set_model_override("chat_1", "code")
        result = parse_command_shortcut(
            "/forget", "chat_1", ["casual", "code"]
        )
        assert result.is_command is True
        assert get_model_override("chat_1") is None
        assert "cleared" in result.response

    @pytest.mark.unit
    def test_normal_text_not_command(self):
        """Regular messages are not commands."""
        result = parse_command_shortcut(
            "Hello, how are you?", "chat_1", ["casual"]
        )
        assert result.is_command is False
        assert result.response is None
        assert result.action is None


# ---------------------------------------------------------------------------
# 5. HTTP Tool Invocation
# ---------------------------------------------------------------------------


class TestHandleToolInvoke:
    """Tests for handle_tool_invoke."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        """Requesting a tool not in available_tools -> error."""
        req = ToolInvokeRequest(tool="hack_nasa", args={})

        async def execute_fn(name, args):
            return {"content": "", "is_error": False}

        resp = await handle_tool_invoke(
            req, execute_fn, available_tools=["web_search"]
        )
        assert resp.ok is False
        assert "not found" in resp.error

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_dry_run(self):
        """dry_run=True -> no execution, response indicates dry run."""
        req = ToolInvokeRequest(
            tool="web_search", args={"q": "test"}, dry_run=True
        )

        async def execute_fn(name, args):
            raise AssertionError("should not be called")

        resp = await handle_tool_invoke(
            req, execute_fn, available_tools=["web_search"]
        )
        assert resp.ok is True
        assert resp.dry_run is True
        d = resp.to_dict()
        assert d["dry_run"] is True
        assert d["would_execute"] == "web_search"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        """Normal execution -> result returned with timing."""
        req = ToolInvokeRequest(tool="web_search", args={"q": "test"})

        async def execute_fn(name, args):
            return {"content": "found 3 results", "is_error": False}

        resp = await handle_tool_invoke(
            req, execute_fn, available_tools=["web_search"]
        )
        assert resp.ok is True
        assert resp.result["content"] == "found 3 results"
        assert resp.result["is_error"] is False
        assert resp.duration_ms >= 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hook_before_blocks(self):
        """Before-hook returning 'block' prevents execution."""
        req = ToolInvokeRequest(tool="web_search", args={"q": "test"})

        async def execute_fn(name, args):
            raise AssertionError("should not be called")

        async def hook_before(tool_name, args, ctx):
            return ("block", None)

        resp = await handle_tool_invoke(
            req,
            execute_fn,
            available_tools=["web_search"],
            hook_before=hook_before,
        )
        assert resp.ok is False
        assert "Blocked" in resp.error

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hook_before_modifies_args(self):
        """Before-hook can modify args before execution."""
        req = ToolInvokeRequest(tool="web_search", args={"q": "original"})
        captured_args = {}

        async def execute_fn(name, args):
            captured_args.update(args)
            return {"content": "ok", "is_error": False}

        async def hook_before(tool_name, args, ctx):
            return ("allow", {"q": "modified"})

        resp = await handle_tool_invoke(
            req,
            execute_fn,
            available_tools=["web_search"],
            hook_before=hook_before,
        )
        assert resp.ok is True
        assert captured_args["q"] == "modified"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hook_after_called(self):
        """After-hook receives tool name, args, result, and duration."""
        req = ToolInvokeRequest(tool="web_search", args={"q": "test"})
        hook_log: list[dict] = []

        async def execute_fn(name, args):
            return {"content": "done", "is_error": False}

        async def hook_after(tool_name, args, result, duration_ms):
            hook_log.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                    "duration_ms": duration_ms,
                }
            )

        resp = await handle_tool_invoke(
            req,
            execute_fn,
            available_tools=["web_search"],
            hook_after=hook_after,
        )
        assert resp.ok is True
        assert len(hook_log) == 1
        assert hook_log[0]["tool"] == "web_search"
        assert hook_log[0]["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# 6. ToolInvokeResponse serialization
# ---------------------------------------------------------------------------


class TestToolInvokeResponseSerialization:
    """Tests for ToolInvokeResponse.to_dict."""

    @pytest.mark.unit
    def test_success_to_dict(self):
        """Successful response serializes correctly."""
        resp = ToolInvokeResponse(
            ok=True,
            tool="web_search",
            result={"content": "ok", "is_error": False},
            duration_ms=42.567,
        )
        d = resp.to_dict()
        assert d["ok"] is True
        assert d["tool"] == "web_search"
        assert d["result"]["content"] == "ok"
        assert d["duration_ms"] == 42.6  # rounded to 1 decimal

    @pytest.mark.unit
    def test_error_to_dict(self):
        """Error response includes error field, omits result."""
        resp = ToolInvokeResponse(
            ok=False, tool="hack_nasa", error="not found"
        )
        d = resp.to_dict()
        assert d["ok"] is False
        assert d["error"] == "not found"
        assert "result" not in d


# ---------------------------------------------------------------------------
# 7. Tool Catalog Builder
# ---------------------------------------------------------------------------


class TestBuildToolCatalog:
    """Tests for build_tool_catalog."""

    @pytest.mark.unit
    def test_converts_openai_schema(self):
        """Converts OpenAI-format tool list to flat catalog entries."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"}
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
        catalog = build_tool_catalog(tools)
        assert len(catalog) == 2
        assert catalog[0]["name"] == "web_search"
        assert catalog[0]["description"] == "Search the web"
        assert "query" in catalog[0]["parameters"]["properties"]
        assert catalog[1]["name"] == "read_file"

    @pytest.mark.unit
    def test_empty_input(self):
        """Empty tools list produces empty catalog."""
        assert build_tool_catalog([]) == []

    @pytest.mark.unit
    def test_missing_function_key_graceful(self):
        """Malformed tool dict does not crash -- uses empty defaults."""
        catalog = build_tool_catalog([{"type": "function"}])
        assert len(catalog) == 1
        assert catalog[0]["name"] == ""
        assert catalog[0]["description"] == ""
        assert catalog[0]["parameters"] == {}
