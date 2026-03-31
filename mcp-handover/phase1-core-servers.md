# Phase 1: Core MCP Servers (Week 1)

> **Prerequisite**: Phase 0 complete. `mcp>=1.0.0` installed, `mcp_config.py` exists.

## Directory Structure

Create: `workspace/sci_fi_dashboard/mcp_servers/`

## File 1: `mcp_servers/__init__.py`

```python
"""MCP servers package for Synapse-OSS."""
```

## File 2: `mcp_servers/base.py`

```python
"""Base utilities for Synapse MCP servers."""
import logging
import sys
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD = os.path.abspath(os.path.join(_DIR, ".."))
_WORKSPACE = os.path.abspath(os.path.join(_DASHBOARD, ".."))
for p in (_DASHBOARD, _WORKSPACE):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("synapse.mcp")

def setup_logging():
    """Configure logging to stderr (stdout reserved for MCP stdio transport)."""
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s", stream=sys.stderr)
```

## File 3: `mcp_servers/memory_server.py`

**Wraps**: `MemoryEngine` from `memory_engine.py`
- `MemoryEngine.query(text, limit, with_graph)` at line 168 — returns `{"results": [...], "tier": ..., "entities": [...]}`
- `MemoryEngine.add_memory(content, category)` at line 278 — returns `{"status": "queued", "id": ...}`

```python
"""
MCP Server: Synapse Memory Query
Run standalone: python -m sci_fi_dashboard.mcp_servers.memory_server
"""
import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ResourceTemplate

from .base import setup_logging, logger

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        from memory_engine import MemoryEngine
        _engine = MemoryEngine()
    return _engine

server = Server("synapse-memory")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_memory",
            description="Semantic search over Synapse's knowledge base. Returns ranked results with scores, entities, and graph context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "with_graph": {"type": "boolean", "default": True}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="add_memory",
            description="Store a new memory/fact in the knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "default": "direct_entry"}
                },
                "required": ["content"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    engine = _get_engine()
    if name == "query_memory":
        result = engine.query(
            text=arguments["query"],
            limit=arguments.get("limit", 5),
            with_graph=arguments.get("with_graph", True),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    elif name == "add_memory":
        result = engine.add_memory(arguments["content"], arguments.get("category", "direct_entry"))
        return [TextContent(type="text", text=json.dumps(result, default=str))]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [ResourceTemplate(uriTemplate="synapse://memory/search?q={query}", name="Memory Search", description="Search memories by query")]

async def main():
    setup_logging()
    logger.info("Starting Synapse Memory MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## File 4: `mcp_servers/conversation_server.py`

**Wraps**: `SBSOrchestrator` from `sbs/orchestrator.py`
- `SBSOrchestrator.get_profile_summary()` at line 136
- `SBSOrchestrator.get_system_prompt()` at line 119

```python
"""
MCP Server: Synapse Conversation History & Profile
Run standalone: python -m sci_fi_dashboard.mcp_servers.conversation_server
"""
import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .base import setup_logging, logger

_orchestrator = None

def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from synapse_config import SynapseConfig
        from sbs.orchestrator import SBSOrchestrator
        cfg = SynapseConfig.load()
        _orchestrator = SBSOrchestrator(data_dir=str(cfg.sbs_dir))
    return _orchestrator

server = Server("synapse-conversation")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="get_profile_summary", description="Get user's behavioral profile: mood, sentiment, language, vocab size, message count.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_system_prompt", description="Get compiled SBS persona prompt.", inputSchema={"type": "object", "properties": {"base_instructions": {"type": "string", "default": ""}}})
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    orch = _get_orchestrator()
    if name == "get_profile_summary":
        return [TextContent(type="text", text=json.dumps(orch.get_profile_summary(), indent=2, default=str))]
    elif name == "get_system_prompt":
        return [TextContent(type="text", text=orch.get_system_prompt(arguments.get("base_instructions", "")))]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    setup_logging()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## File 5: `mcp_servers/tools_server.py`

**Wraps**: `ToolRegistry.search_web()` from `db/tools.py` and `Sentinel` from `sbs/sentinel/gateway.py`

```python
"""
MCP Server: Synapse Tool Registry — web browsing + Sentinel-gated file ops
Run standalone: python -m sci_fi_dashboard.mcp_servers.tools_server
"""
import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .base import setup_logging, logger

server = Server("synapse-tools")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="web_search", description="Fetch and extract content from a URL as clean markdown.", inputSchema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
        Tool(name="read_file", description="Read file contents (Sentinel-gated).", inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
        Tool(name="write_file", description="Write to file (Sentinel-gated, audit logged).", inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "web_search":
        try:
            from db.tools import ToolRegistry
            content = ToolRegistry.search_web(arguments["url"])
            return [TextContent(type="text", text=content)]
        except Exception as e:
            return [TextContent(type="text", text=f"Web search error: {e}")]
    elif name == "read_file":
        try:
            from sbs.sentinel.gateway import Sentinel
            result = Sentinel().agent_read_file(arguments["path"])
            return [TextContent(type="text", text=result if result else "DENIED: Sentinel blocked read")]
        except Exception as e:
            return [TextContent(type="text", text=f"Read error: {e}")]
    elif name == "write_file":
        try:
            from sbs.sentinel.gateway import Sentinel
            success = Sentinel().agent_write_file(arguments["path"], arguments["content"])
            return [TextContent(type="text", text="Written" if success else "DENIED: Sentinel blocked write")]
        except Exception as e:
            return [TextContent(type="text", text=f"Write error: {e}")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    setup_logging()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## Verify Phase 1

```bash
cd workspace
# Test each server (requires MCP Inspector: pip install mcp-inspector)
mcp-inspector python -m sci_fi_dashboard.mcp_servers.memory_server
mcp-inspector python -m sci_fi_dashboard.mcp_servers.conversation_server
mcp-inspector python -m sci_fi_dashboard.mcp_servers.tools_server

# Unit tests
pytest tests/test_mcp_servers.py -v
```
