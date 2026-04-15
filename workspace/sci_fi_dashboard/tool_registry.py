"""
Tool Registry — Factory-based tool resolution for Synapse-OSS
==============================================================
Phase 1 of the Tool Execution milestone. Provides a registry where
tool factories produce SynapseTool instances scoped to each chat session.

The LLM call site resolves tools once per request via ToolRegistry.resolve(),
then passes get_schemas() output as the `tools=` parameter. After the LLM
returns a tool_call, execute() dispatches to the matching SynapseTool.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Session-scoped context injected into tool factories at resolution time."""

    chat_id: str
    sender_id: str
    sender_is_owner: bool
    workspace_dir: str
    config: dict
    channel_id: str | None = None


@dataclass
class ToolResult:
    """Uniform result format — all tool returns normalize to this."""

    content: str
    is_error: bool = False
    media: list[dict] = field(default_factory=list)


@dataclass
class SynapseTool:
    """A fully resolved tool ready for execution."""

    name: str
    description: str
    parameters: dict  # JSON Schema (top-level type: "object")
    execute: Callable[[dict], Awaitable[ToolResult]]
    owner_only: bool = False
    serial: bool = False  # if True, never run in parallel


ToolFactory = Callable[[ToolContext], SynapseTool | None]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Factory-based tool registry with per-request resolution."""

    def __init__(self) -> None:
        self._factories: list[tuple[str, ToolFactory]] = []
        self._resolved: dict[str, SynapseTool] = {}

    def register_factory(self, name: str, factory: ToolFactory) -> None:
        """Register a factory that produces a SynapseTool (or None to skip)."""
        self._factories.append((name, factory))

    def register_tool(self, tool: SynapseTool) -> None:
        """Convenience: register a static tool as a trivial factory."""
        self.register_factory(tool.name, lambda _ctx: tool)

    def resolve(self, context: ToolContext) -> list[SynapseTool]:
        """Resolve all factories for the given session context.

        Factories may return ``None`` to exclude themselves (e.g. owner-only
        tools when ``sender_is_owner`` is False). Duplicate tool names are
        silently dropped — first registration wins.
        """
        self._resolved.clear()
        tools: list[SynapseTool] = []
        for name, factory in self._factories:
            try:
                tool = factory(context)
                if tool is None:
                    continue
                if tool.name in self._resolved:
                    continue
                self._resolved[tool.name] = tool
                tools.append(tool)
            except Exception as e:
                logger.warning(f"Tool factory '{name}' failed: {e}")
        return tools

    def get_schemas(self, tools: list[SynapseTool]) -> list[dict]:
        """Return OpenAI function-calling compatible schema list."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        """Execute a previously resolved tool by name."""
        tool = self._resolved.get(name)
        if not tool:
            return ToolResult(
                content=f'{{"error": "Unknown tool: {name}"}}',
                is_error=True,
            )
        try:
            return await tool.execute(arguments)
        except Exception as e:
            return ToolResult(
                content=f'{{"error": "Tool \'{name}\' failed: {e}"}}',
                is_error=True,
            )


# ---------------------------------------------------------------------------
# Result normalization helpers
# ---------------------------------------------------------------------------


def text_result(text: str) -> ToolResult:
    """Wrap a plain string as a successful ToolResult."""
    return ToolResult(content=text)


def error_result(message: str) -> ToolResult:
    """Wrap an error message as a failed ToolResult."""
    return ToolResult(content=json.dumps({"error": message}), is_error=True)


def json_result(payload: Any) -> ToolResult:
    """Serialize an arbitrary payload as pretty JSON."""
    return ToolResult(content=json.dumps(payload, indent=2, default=str))


def normalize_raw_result(raw: Any) -> ToolResult:
    """Convert any return value into a ToolResult."""
    if isinstance(raw, ToolResult):
        return raw
    if isinstance(raw, str):
        return text_result(raw)
    if isinstance(raw, dict):
        return json_result(raw)
    if raw is None:
        return text_result("(no output)")
    return text_result(str(raw))


# ---------------------------------------------------------------------------
# Built-in tool factories
# ---------------------------------------------------------------------------


def _web_search_factory(_ctx: ToolContext) -> SynapseTool:
    """Factory for the web_search tool (delegates to db.tools.ToolRegistry)."""

    async def _execute(arguments: dict) -> ToolResult:
        try:
            from db.tools import ToolRegistry as LegacyToolRegistry

            content = await LegacyToolRegistry.search_web(arguments["url"])
            return text_result(content)
        except Exception as e:
            return error_result(f"web_search failed: {e}")

    return SynapseTool(
        name="web_search",
        description=(
            "Fetch and extract content from a URL as clean markdown. "
            "Use for up-to-date information not in memory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to visit and extract content from.",
                }
            },
            "required": ["url"],
        },
        execute=_execute,
    )


def _query_memory_factory(memory_engine: Any) -> ToolFactory:
    """Return a factory that captures a MemoryEngine reference."""

    def _factory(_ctx: ToolContext) -> SynapseTool:
        async def _execute(arguments: dict) -> ToolResult:
            try:
                result = memory_engine.query(
                    text=arguments["query"],
                    limit=arguments.get("limit", 5),
                )
                return json_result(result)
            except Exception as e:
                return error_result(f"query_memory failed: {e}")

        return SynapseTool(
            name="query_memory",
            description=(
                "Search the knowledge base using hybrid RAG "
                "(vector + full-text + rerank). Returns ranked results."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 5).",
                    },
                },
                "required": ["query"],
            },
            execute=_execute,
        )

    return _factory


def _read_file_factory(_ctx: ToolContext) -> SynapseTool:
    """Factory for the read_file tool (Sentinel-gated)."""

    async def _execute(arguments: dict) -> ToolResult:
        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_read_file

            result = agent_read_file(arguments["path"])
            return text_result(result)
        except Exception as e:
            return error_result(f"read_file failed: {e}")

    return SynapseTool(
        name="read_file",
        description="Read file contents (Sentinel-gated).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to read.",
                }
            },
            "required": ["path"],
        },
        execute=_execute,
    )


def _write_file_factory(ctx: ToolContext) -> SynapseTool | None:
    """Factory for the write_file tool (Sentinel-gated, owner-only)."""
    if not ctx.sender_is_owner:
        return None

    async def _execute(arguments: dict) -> ToolResult:
        try:
            from sci_fi_dashboard.sbs.sentinel.tools import agent_write_file

            result = agent_write_file(arguments["path"], arguments["content"])
            return text_result(result)
        except Exception as e:
            return error_result(f"write_file failed: {e}")

    return SynapseTool(
        name="write_file",
        description="Write to a file (Sentinel-gated, audit logged). Owner only.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write to.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["path", "content"],
        },
        execute=_execute,
        owner_only=True,
    )


def register_builtin_tools(
    registry: ToolRegistry,
    memory_engine: Any,
    project_root: str,
) -> None:
    """Register all four built-in tool factories on the given registry.

    Parameters
    ----------
    registry : ToolRegistry
        The registry to populate.
    memory_engine : MemoryEngine
        A live MemoryEngine instance whose ``.query()`` method will be called.
    project_root : str
        Workspace root path (unused currently, reserved for future factories).
    """
    registry.register_factory("web_search", _web_search_factory)
    registry.register_factory("query_memory", _query_memory_factory(memory_engine))
    registry.register_factory("read_file", _read_file_factory)
    registry.register_factory("write_file", _write_file_factory)
