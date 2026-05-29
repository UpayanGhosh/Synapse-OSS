# Phase 3: MCP Client + Gateway Integration (Week 3)

> **Prerequisite**: Phase 1+2 complete. MCP servers working standalone.

## File 1: `sci_fi_dashboard/mcp_client.py`

**Purpose**: Unified MCP client connecting to all servers. Tool disambiguation via `serverName__toolName`.

```python
"""
SynapseMCPClient — connects Synapse to all MCP servers (built-in + user-configured).
Tool routing: serverName__toolName (e.g., synapse-gmail__search_emails)
"""
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

logger = logging.getLogger("synapse.mcp.client")

@dataclass
class MCPServerConnection:
    name: str
    session: ClientSession | None = None
    tools: list[dict] = field(default_factory=list)
    connected: bool = False

class SynapseMCPClient:
    def __init__(self):
        self._servers: dict[str, MCPServerConnection] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}  # key -> (serverName, originalToolName)
        self._contexts: list = []  # track context managers for cleanup

    async def connect_builtin_server(self, name: str, module_path: str) -> None:
        server_params = StdioServerParameters(command=sys.executable, args=["-m", module_path])
        try:
            ctx = stdio_client(server_params)
            read, write = await ctx.__aenter__()
            self._contexts.append(ctx)
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools_resp.tools]
            self._servers[name] = MCPServerConnection(name=name, session=session, tools=tools, connected=True)
            for tool in tools:
                self._tool_map[f"{name}__{tool['name']}"] = (name, tool["name"])
                self._tool_map[tool["name"]] = (name, tool["name"])  # unqualified fallback
            logger.info(f"Connected to MCP server '{name}' with {len(tools)} tools")
        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{name}': {e}")

    async def connect_custom_server(self, name: str, command: str, args: list[str], env: dict = None) -> None:
        server_params = StdioServerParameters(command=command, args=args, env=env)
        try:
            ctx = stdio_client(server_params)
            read, write = await ctx.__aenter__()
            self._contexts.append(ctx)
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools_resp = await session.list_tools()
            tools = [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema} for t in tools_resp.tools]
            self._servers[name] = MCPServerConnection(name=name, session=session, tools=tools, connected=True)
            for tool in tools:
                self._tool_map[f"{name}__{tool['name']}"] = (name, tool["name"])
            logger.info(f"Connected to custom MCP server '{name}' with {len(tools)} tools")
        except Exception as e:
            logger.error(f"Failed to connect to custom MCP server '{name}': {e}")

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if tool_name not in self._tool_map:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        server_name, original_name = self._tool_map[tool_name]
        conn = self._servers.get(server_name)
        if not conn or not conn.connected or not conn.session:
            return json.dumps({"error": f"Server '{server_name}' not connected"})
        try:
            result = await conn.session.call_tool(original_name, arguments)
            return "\n".join(c.text for c in result.content if hasattr(c, "text"))
        except Exception as e:
            return json.dumps({"error": f"Tool call failed: {e}"})

    def list_all_tools(self) -> list[dict]:
        all_tools = []
        for name, conn in self._servers.items():
            for tool in conn.tools:
                all_tools.append({"name": f"{name}__{tool['name']}", "description": f"[{name}] {tool['description']}", "inputSchema": tool["inputSchema"]})
        return all_tools

    async def connect_all(self, mcp_config) -> None:
        builtin_modules = {
            "memory": "sci_fi_dashboard.mcp_servers.memory_server",
            "conversation": "sci_fi_dashboard.mcp_servers.conversation_server",
            "tools": "sci_fi_dashboard.mcp_servers.tools_server",
            "gmail": "sci_fi_dashboard.mcp_servers.gmail_server",
            "calendar": "sci_fi_dashboard.mcp_servers.calendar_server",
            "slack": "sci_fi_dashboard.mcp_servers.slack_server",
        }
        for name, cfg in mcp_config.builtin_servers.items():
            if cfg.enabled and name in builtin_modules:
                await self.connect_builtin_server(name, builtin_modules[name])
        for name, cfg in mcp_config.custom_servers.items():
            await self.connect_custom_server(name, cfg.command, cfg.args, cfg.env or None)

    async def disconnect_all(self) -> None:
        for conn in self._servers.values():
            if conn.session:
                try: await conn.session.__aexit__(None, None, None)
                except Exception: pass
        for ctx in self._contexts:
            try: await ctx.__aexit__(None, None, None)
            except Exception: pass
        self._servers.clear()
        self._tool_map.clear()
        self._contexts.clear()
```

## Modify: `api_gateway.py` (singleton init section)

Add after existing singleton initialization (brain, memory_engine, etc.):

```python
# --- MCP Client Initialization ---
from mcp_config import load_mcp_config
from mcp_client import SynapseMCPClient

mcp_config = load_mcp_config(cfg.mcp)
mcp_client = None

if mcp_config.enabled:
    mcp_client = SynapseMCPClient()
    await mcp_client.connect_all(mcp_config)
    logger.info(f"[MCP] Connected. Available tools: {len(mcp_client.list_all_tools())}")
```

Add to shutdown handler:
```python
if mcp_client:
    await mcp_client.disconnect_all()
```

## Modify: `gateway/worker.py`

Add `mcp_client` parameter to `MessageWorker.__init__()` (line 40):

```python
def __init__(self, queue, process_fn, num_workers=2, sender=None, channel_registry=None, mcp_client=None):
    # ...existing code...
    self.mcp_client = mcp_client
```

In `_handle_task()`, before the LLM call, add MCP context gathering:

```python
# After retrieving memories, before LLM call:
mcp_context = ""
if self.mcp_client:
    try:
        memory_result = await self.mcp_client.call_tool("query_memory", {"query": task.text, "limit": 5})
        mcp_context += f"\n[MCP_MEMORY]\n{memory_result}\n"
    except Exception as e:
        logger.warning(f"[MCP] Context gathering failed: {e}")
```

## Verify Phase 3

```bash
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000

# Check logs for:
# [MCP] Connected. Available tools: N

# Send a test message through any channel
# Verify MCP tools are called (check logs)
```
