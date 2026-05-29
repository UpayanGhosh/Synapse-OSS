# Phase 1: Tool Registry & Factories

> Adapted from OpenClaw Phases 1-3: factory registration, session-scoped resolution, core + plugin assembly.

## Goal

Create a unified `ToolRegistry` with factory-based tool creation. Tools are registered as factories that receive session context at resolution time — not as static objects. This enables per-session tool instances with sender identity, workspace path, and config injected.

## Dependencies

None — can start immediately. Can be developed in parallel with Phase 2.

## Files

| File | Action | Why |
|------|--------|-----|
| `sci_fi_dashboard/tool_registry.py` | **CREATE** | Central tool registry with factory pattern |
| `sci_fi_dashboard/mcp_servers/tools_server.py` | **FIX** | Broken Sentinel calls (line 65, 72) |
| `sbs/sentinel/tools.py` | READ | Reuse `agent_read_file()`, `agent_write_file()` |
| `db/tools.py` | READ | Reuse `get_tool_schemas()` pattern + `search_web()` |

## Implementation

### 1.1 — Core Data Structures

```python
from dataclasses import dataclass, field
from typing import Callable, Awaitable, Any

@dataclass
class ToolContext:
    """Session-scoped context injected into tool factories at resolution time."""
    chat_id: str
    sender_id: str
    sender_is_owner: bool
    workspace_dir: str
    config: dict                       # from synapse.json
    channel_id: str | None = None

@dataclass
class ToolResult:
    """Uniform result format — all tool returns normalize to this."""
    content: str                       # text content for LLM
    is_error: bool = False             # marks error results
    media: list[dict] = field(default_factory=list)  # [{url, mime_type, filename}]

@dataclass
class SynapseTool:
    name: str
    description: str
    parameters: dict                   # JSON Schema (top-level type: "object")
    execute: Callable[[dict], Awaitable[ToolResult]]
    owner_only: bool = False
    serial: bool = False               # if True, never run in parallel

# Factory type: receives context, returns tool instance (or None to skip)
ToolFactory = Callable[[ToolContext], SynapseTool | None]
```

### 1.2 — ToolRegistry class

```python
class ToolRegistry:
    def __init__(self):
        self._factories: list[tuple[str, ToolFactory]] = []  # (name, factory)
        self._resolved: dict[str, SynapseTool] = {}          # populated per-session

    def register_factory(self, name: str, factory: ToolFactory) -> None:
        """Register a tool factory. Resolved lazily per session."""
        self._factories.append((name, factory))

    def register_tool(self, tool: SynapseTool) -> None:
        """Register a static tool (factory that always returns the same tool)."""
        self.register_factory(tool.name, lambda _ctx: tool)

    def resolve(self, context: ToolContext) -> list[SynapseTool]:
        """Invoke all factories with session context. Returns tools for this session."""
        self._resolved.clear()
        tools = []
        for name, factory in self._factories:
            try:
                tool = factory(context)
                if tool is None:
                    continue  # factory opted out for this session
                if tool.name in self._resolved:
                    continue  # first registration wins (like OpenClaw)
                self._resolved[tool.name] = tool
                tools.append(tool)
            except Exception as e:
                logger.warning(f"Tool factory '{name}' failed: {e}")
        return tools

    def get_schemas(self, tools: list[SynapseTool]) -> list[dict]:
        """Return tools in OpenAI function-calling format."""
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
        """Execute a resolved tool by name."""
        tool = self._resolved.get(name)
        if not tool:
            return ToolResult(content=f'{{"error": "Unknown tool: {name}"}}', is_error=True)
        try:
            return await tool.execute(arguments)
        except Exception as e:
            return ToolResult(content=f'{{"error": "Tool \'{name}\' failed: {e}"}}', is_error=True)
```

### 1.3 — Register built-in tool factories

```python
def register_builtin_tools(registry: ToolRegistry, memory_engine, project_root: Path):
    """Register all built-in tool factories."""

    # web_search — always available, read-only
    def _web_search_factory(ctx: ToolContext) -> SynapseTool:
        return SynapseTool(
            name="web_search",
            description="Search the web by fetching a URL and extracting text content.",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            execute=_web_search_execute,
        )

    # query_memory — always available, read-only
    def _query_memory_factory(ctx: ToolContext) -> SynapseTool:
        return SynapseTool(
            name="query_memory",
            description="Search long-term memory for facts and context relevant to a query.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": ["query"],
            },
            execute=lambda args: _query_memory_execute(args, memory_engine),
        )

    # read_file — Sentinel-gated, available to all
    def _read_file_factory(ctx: ToolContext) -> SynapseTool:
        return SynapseTool(
            name="read_file",
            description="Read a file from the project workspace. Access is governed by security policy.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            execute=lambda args: _read_file_execute(args, project_root),
        )

    # write_file — Sentinel-gated, owner-only
    def _write_file_factory(ctx: ToolContext) -> SynapseTool:
        return SynapseTool(
            name="write_file",
            description="Write content to a file in the project workspace. Restricted to writable zones.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            execute=lambda args: _write_file_execute(args, project_root),
            owner_only=True,
        )

    registry.register_factory("web_search", _web_search_factory)
    registry.register_factory("query_memory", _query_memory_factory)
    registry.register_factory("read_file", _read_file_factory)
    registry.register_factory("write_file", _write_file_factory)
```

### 1.4 — Result normalization helpers

```python
def text_result(text: str) -> ToolResult:
    return ToolResult(content=text)

def error_result(message: str) -> ToolResult:
    return ToolResult(content=json.dumps({"error": message}), is_error=True)

def json_result(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, indent=2, default=str))

def normalize_raw_result(raw: Any) -> ToolResult:
    """Normalize heterogeneous tool returns into ToolResult (adapted from OpenClaw Phase 8)."""
    if isinstance(raw, ToolResult):
        return raw
    if isinstance(raw, str):
        return text_result(raw)
    if isinstance(raw, dict):
        return json_result(raw)
    if raw is None:
        return text_result("(no output)")
    return text_result(str(raw))
```

### 1.5 — Fix `tools_server.py` bug

**Current (broken):**
```python
result = Sentinel().agent_read_file(arguments["path"])   # line 65
result = Sentinel().agent_write_file(arguments["path"], arguments["content"])  # line 72
```

**Fixed:**
```python
from sci_fi_dashboard.sbs.sentinel.tools import agent_read_file, agent_write_file
result = agent_read_file(arguments["path"])
result = agent_write_file(arguments["path"], arguments["content"])
```

## Key Design Decision: Factories Not Instances

From OpenClaw Phase 1: "Plugins register **factories** rather than tool instances. This is deliberate — tools need session-specific context (workspace, config, session key) that is not known at plugin load time."

Synapse adapts this: a tool factory can inspect `ToolContext.sender_is_owner` and return `None` to hide owner-only tools from non-owners entirely (not just block execution). A factory can also customize tool descriptions or parameters based on session config.

## Verification

1. **Unit test**: Register factory, resolve with context, verify tool list
2. **Unit test**: Factory returns `None` → tool excluded from resolved list
3. **Unit test**: `get_schemas()` output matches OpenAI function-calling format
4. **Unit test**: `execute("unknown_tool", {})` → `ToolResult(is_error=True)`
5. **Unit test**: `normalize_raw_result()` handles str, dict, None, ToolResult
6. **Integration test**: `read_file` on CRITICAL path → Sentinel error returned as `ToolResult`

## Scope

- 1 new file (`tool_registry.py`, ~200 lines)
- 1 bug fix (`tools_server.py`, 2 lines)
- ~6 unit tests
