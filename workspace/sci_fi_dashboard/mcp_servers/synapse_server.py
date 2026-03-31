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
        Tool(
            name="chat",
            description=(
                "Send message through Synapse's full cognitive pipeline "
                "(memory + persona + dual cognition + LLM)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "session_id": {"type": "string", "default": "mcp-default"},
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="query_memory",
            description="Semantic search over Synapse's knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="ingest_memory",
            description="Store a new fact/memory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "default": "mcp_ingest"},
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="get_profile",
            description="Get user's behavioral profile from Soul-Brain Sync.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="synapse://capabilities",
            name="Synapse Capabilities",
            description="All connected services and available tools",
        ),
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
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://127.0.0.1:8000/api/chat",
                json={
                    "message": arguments["message"],
                    "session_id": arguments.get("session_id", "mcp-default"),
                },
            )
            return [TextContent(type="text", text=resp.text)]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse MCP Server (external-facing)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
