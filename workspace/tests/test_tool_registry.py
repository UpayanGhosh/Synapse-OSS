"""
Test Suite: ToolRegistry
========================
Unit tests for the factory-based tool registry (Phase 1).
Covers resolution, schema generation, execution, normalization,
and owner-only access gating.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.tool_registry import (
    SynapseTool,
    ToolContext,
    ToolFactory,
    ToolRegistry,
    ToolResult,
    error_result,
    json_result,
    normalize_raw_result,
    text_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry with no factories registered."""
    return ToolRegistry()


@pytest.fixture
def owner_context() -> ToolContext:
    """Context representing the owner user."""
    return ToolContext(
        chat_id="chat_001",
        sender_id="owner_123",
        sender_is_owner=True,
        workspace_dir="/tmp/synapse",
        config={},
        channel_id="whatsapp",
    )


@pytest.fixture
def guest_context() -> ToolContext:
    """Context representing a non-owner user."""
    return ToolContext(
        chat_id="chat_002",
        sender_id="guest_456",
        sender_is_owner=False,
        workspace_dir="/tmp/synapse",
        config={},
        channel_id="telegram",
    )


def _make_echo_tool(name: str = "echo") -> SynapseTool:
    """Helper: create a simple async echo tool for testing."""

    async def _execute(arguments: dict) -> ToolResult:
        return ToolResult(content=arguments.get("text", ""))

    return SynapseTool(
        name=name,
        description="Echoes the input text.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo."}
            },
            "required": ["text"],
        },
        execute=_execute,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    """Core registry behaviour."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_factory_and_resolve(self, registry, owner_context):
        """Register a factory, resolve with context, verify tool appears."""

        def factory(ctx: ToolContext) -> SynapseTool:
            return _make_echo_tool("echo")

        registry.register_factory("echo", factory)
        tools = registry.resolve(owner_context)

        assert len(tools) == 1
        assert tools[0].name == "echo"
        assert tools[0].description == "Echoes the input text."

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_factory_returns_none_excluded(self, registry, owner_context):
        """Factory returning None should exclude that tool from resolved list."""

        def always_none(_ctx: ToolContext) -> SynapseTool | None:
            return None

        def always_present(_ctx: ToolContext) -> SynapseTool:
            return _make_echo_tool("present")

        registry.register_factory("skipped", always_none)
        registry.register_factory("present", always_present)
        tools = registry.resolve(owner_context)

        assert len(tools) == 1
        assert tools[0].name == "present"

    @pytest.mark.unit
    def test_get_schemas_openai_format(self, registry, owner_context):
        """get_schemas() output must match OpenAI function-calling format."""
        echo = _make_echo_tool("echo")
        registry.register_tool(echo)
        tools = registry.resolve(owner_context)
        schemas = registry.get_schemas(tools)

        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert "function" in schema
        fn = schema["function"]
        assert fn["name"] == "echo"
        assert fn["description"] == "Echoes the input text."
        assert fn["parameters"]["type"] == "object"
        assert "text" in fn["parameters"]["properties"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self, registry, owner_context):
        """execute() for an unresolved tool must return ToolResult(is_error=True)."""
        registry.resolve(owner_context)  # resolve with no factories
        result = await registry.execute("nonexistent", {})

        assert result.is_error is True
        assert "Unknown tool" in result.content
        assert "nonexistent" in result.content

    @pytest.mark.unit
    def test_normalize_raw_result_variants(self):
        """normalize_raw_result() handles str, dict, None, and ToolResult inputs."""
        # str
        r1 = normalize_raw_result("hello")
        assert r1.content == "hello"
        assert r1.is_error is False

        # dict
        r2 = normalize_raw_result({"key": "value"})
        assert '"key"' in r2.content
        assert '"value"' in r2.content
        assert r2.is_error is False

        # None
        r3 = normalize_raw_result(None)
        assert r3.content == "(no output)"
        assert r3.is_error is False

        # ToolResult passthrough
        original = ToolResult(content="original", is_error=True)
        r4 = normalize_raw_result(original)
        assert r4 is original
        assert r4.content == "original"
        assert r4.is_error is True

        # Other type (e.g. int)
        r5 = normalize_raw_result(42)
        assert r5.content == "42"
        assert r5.is_error is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_owner_only_tool_excluded_for_guest(
        self, registry, owner_context, guest_context
    ):
        """Owner-only factory returns None for non-owners, tool for owners."""

        def owner_only_factory(ctx: ToolContext) -> SynapseTool | None:
            if not ctx.sender_is_owner:
                return None
            return _make_echo_tool("admin_tool")

        registry.register_factory("admin_tool", owner_only_factory)

        # Owner sees the tool
        owner_tools = registry.resolve(owner_context)
        assert len(owner_tools) == 1
        assert owner_tools[0].name == "admin_tool"

        # Guest does NOT see the tool
        guest_tools = registry.resolve(guest_context)
        assert len(guest_tools) == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_resolved_tool_success(self, registry, owner_context):
        """execute() on a resolved tool returns the tool's ToolResult."""
        echo = _make_echo_tool("echo")
        registry.register_tool(echo)
        registry.resolve(owner_context)

        result = await registry.execute("echo", {"text": "hello world"})
        assert result.content == "hello world"
        assert result.is_error is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_handles_tool_exception(self, registry, owner_context):
        """execute() catches exceptions from the tool and returns error result."""

        async def _broken(arguments: dict) -> ToolResult:
            raise ValueError("something broke")

        broken_tool = SynapseTool(
            name="broken",
            description="Always fails.",
            parameters={"type": "object", "properties": {}},
            execute=_broken,
        )
        registry.register_tool(broken_tool)
        registry.resolve(owner_context)

        result = await registry.execute("broken", {})
        assert result.is_error is True
        assert "something broke" in result.content

    @pytest.mark.unit
    def test_duplicate_tool_names_first_wins(self, registry, owner_context):
        """When two factories produce tools with the same name, first wins."""

        def factory_a(_ctx: ToolContext) -> SynapseTool:
            return _make_echo_tool("dup")

        def factory_b(_ctx: ToolContext) -> SynapseTool:
            tool = _make_echo_tool("dup")
            tool.description = "Second one"
            return tool

        registry.register_factory("dup_a", factory_a)
        registry.register_factory("dup_b", factory_b)
        tools = registry.resolve(owner_context)

        assert len(tools) == 1
        assert tools[0].description == "Echoes the input text."  # first factory's desc

    @pytest.mark.unit
    def test_helper_functions(self):
        """text_result, error_result, json_result produce correct ToolResults."""
        t = text_result("hello")
        assert t.content == "hello"
        assert t.is_error is False

        e = error_result("bad thing")
        assert e.is_error is True
        assert "bad thing" in e.content

        j = json_result({"a": 1})
        assert '"a"' in j.content
        assert j.is_error is False
