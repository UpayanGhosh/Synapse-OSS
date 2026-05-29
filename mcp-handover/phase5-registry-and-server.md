# Phase 5: User-Configurable Registry + Synapse as MCP Server (Week 5+)

> **Prerequisite**: Phase 4 complete. Proactive awareness working.

## Part A: Dynamic Server Registry

### Add to `SynapseMCPClient` in `mcp_client.py`:

```python
async def add_server(self, name: str, command: str, args: list[str], env: dict = None) -> bool:
    """Dynamically add and connect to a new MCP server at runtime."""
    if name in self._servers:
        logger.warning(f"Server '{name}' already connected")
        return False
    await self.connect_custom_server(name, command, args, env)
    return name in self._servers and self._servers[name].connected

async def remove_server(self, name: str) -> bool:
    """Disconnect and remove an MCP server."""
    conn = self._servers.get(name)
    if not conn:
        return False
    if conn.session:
        try: await conn.session.__aexit__(None, None, None)
        except Exception: pass
    to_remove = [k for k, (sn, _) in self._tool_map.items() if sn == name]
    for k in to_remove:
        del self._tool_map[k]
    del self._servers[name]
    return True
```

### Community MCP Servers — Just Works

Any standard MCP server can be added to `synapse.json`:

```json
"custom_servers": {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/docs"]
    },
    "postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env": { "DATABASE_URL": "postgresql://localhost/mydb" }
    },
    "brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": { "BRAVE_API_KEY": "BSA..." }
    },
    "notion": {
        "command": "npx",
        "args": ["-y", "@notionhq/mcp-server"],
        "env": { "NOTION_API_KEY": "ntn_..." }
    }
}
```

## Part B: Full Synapse as MCP Server

### File: `mcp_servers/synapse_server.py`

**Purpose**: External tools (Claude Desktop, VS Code, other agents) consume Synapse via MCP.

```python
"""
MCP Server: Full Synapse — exposes Synapse's cognitive pipeline to external MCP clients.
Run: python -m sci_fi_dashboard.mcp_servers.synapse_server
"""
import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource
from .base import setup_logging, logger

server = Server("synapse")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="chat", description="Send message through Synapse's full cognitive pipeline (memory + persona + dual cognition + LLM).",
             inputSchema={"type": "object", "properties": {"message": {"type": "string"}, "session_id": {"type": "string", "default": "mcp-default"}}, "required": ["message"]}),
        Tool(name="query_memory", description="Semantic search over Synapse's knowledge base.",
             inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}),
        Tool(name="ingest_memory", description="Store a new fact/memory.",
             inputSchema={"type": "object", "properties": {"content": {"type": "string"}, "category": {"type": "string", "default": "mcp_ingest"}}, "required": ["content"]}),
        Tool(name="get_profile", description="Get user's behavioral profile from Soul-Brain Sync.",
             inputSchema={"type": "object", "properties": {}}),
    ]

@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(uri="synapse://capabilities", name="Synapse Capabilities", description="All connected services and available tools"),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "query_memory":
        from memory_engine import MemoryEngine
        engine = MemoryEngine()
        result = engine.query(arguments["query"], arguments.get("limit", 5))
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    elif name == "ingest_memory":
        from memory_engine import MemoryEngine
        engine = MemoryEngine()
        result = engine.add_memory(arguments["content"], arguments.get("category", "mcp_ingest"))
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    elif name == "get_profile":
        from synapse_config import SynapseConfig
        from sbs.orchestrator import SBSOrchestrator
        cfg = SynapseConfig.load()
        orch = SBSOrchestrator(data_dir=str(cfg.sbs_dir))
        return [TextContent(type="text", text=json.dumps(orch.get_profile_summary(), indent=2))]
    elif name == "chat":
        # Full pipeline integration — requires gateway singletons
        # This connects to the running Synapse instance via internal API
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post("http://127.0.0.1:8000/api/chat", json={
                "message": arguments["message"],
                "session_id": arguments.get("session_id", "mcp-default"),
            })
            return [TextContent(type="text", text=resp.text)]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    setup_logging()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

### Using Synapse from Claude Desktop

Add to Claude Desktop's MCP config:

```json
{
    "mcpServers": {
        "synapse": {
            "command": "python",
            "args": ["-m", "sci_fi_dashboard.mcp_servers.synapse_server"],
            "cwd": "C:\\Users\\upayan.ghosh\\personal\\Synapse-OSS\\workspace"
        }
    }
}
```

Now Claude Desktop can:
- Search Synapse's memories: `query_memory("what does Alice prefer?")`
- Store new facts: `ingest_memory("User prefers dark mode")`
- Get personality profile: `get_profile()`
- Chat through full pipeline: `chat("What meetings do I have today?")`

## Verify Phase 5

```bash
# Test registry: add a filesystem MCP server
# Add to synapse.json custom_servers, restart Synapse
# Verify new tools appear in logs

# Test Synapse as server
mcp-inspector python -m sci_fi_dashboard.mcp_servers.synapse_server
# -> Verify: query_memory, ingest_memory, get_profile, chat tools listed

# Final regression test
cd workspace && pytest tests/ -v
# -> Verify 302+ tests pass
```

## Summary: What You've Built

```
Synapse-OSS + MCP
  |
  +--> MCP Host (manages all connections)
  |
  +--> MCP Client (connects to):
  |      +--> synapse-memory (built-in)
  |      +--> synapse-conversation (built-in)
  |      +--> synapse-tools (built-in)
  |      +--> synapse-gmail (built-in)
  |      +--> synapse-calendar (built-in)
  |      +--> synapse-slack (built-in)
  |      +--> [user-configured: notion, github, filesystem, ...]
  |
  +--> Proactive Awareness Engine
  |      Polls calendar/email/slack every 60s
  |      Injects context into SBS system prompts
  |      SBS learns which signals matter to the user
  |
  +--> MCP Server (synapse-server)
         External tools consume Synapse via MCP
         Claude Desktop, VS Code, other agents
```

A hyper-personalized AI assistant that knows your schedule, reads your emails, understands your work context, and grows with you organically.
