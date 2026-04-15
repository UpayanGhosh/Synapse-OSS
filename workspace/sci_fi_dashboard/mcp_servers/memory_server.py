"""
MCP Server: Synapse Memory Query
Run standalone: python -m sci_fi_dashboard.mcp_servers.memory_server
"""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ResourceTemplate, TextContent, Tool

from .base import check_mcp_auth, logger, setup_logging

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
            description=(
                "Semantic search over Synapse's knowledge base. "
                "Returns ranked results with scores, entities, and graph context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "with_graph": {"type": "boolean", "default": True},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="add_memory",
            description="Store a new memory/fact in the knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "default": "direct_entry"},
                },
                "required": ["content"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    auth_err = check_mcp_auth(arguments)
    if auth_err:
        return [TextContent(type="text", text=json.dumps({"error": auth_err}))]

    try:
        engine = _get_engine()
        if name == "query_memory":
            result = engine.query(
                text=arguments["query"],
                limit=arguments.get("limit", 5),
                with_graph=arguments.get("with_graph", True),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        elif name == "add_memory":
            result = engine.add_memory(
                arguments["content"], arguments.get("category", "direct_entry")
            )
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception("Memory tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate="synapse://memory/search?q={query}",
            name="Memory Search",
            description="Search memories by query",
        )
    ]


async def main():
    setup_logging()
    logger.info("Starting Synapse Memory MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
