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
        Tool(
            name="web_search",
            description="Fetch and extract content from a URL as clean markdown.",
            inputSchema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        ),
        Tool(
            name="read_file",
            description="Read file contents (Sentinel-gated).",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        Tool(
            name="write_file",
            description="Write to file (Sentinel-gated, audit logged).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "web_search":
        try:
            from db.tools import ToolRegistry
            content = await ToolRegistry.search_web(arguments["url"])
            return [TextContent(type="text", text=content)]
        except Exception as e:
            return [TextContent(type="text", text=f"Web search error: {e}")]
    elif name == "read_file":
        try:
            from sbs.sentinel.tools import agent_read_file
            result = agent_read_file(arguments["path"])
            return [TextContent(type="text", text=result if result else "DENIED: Sentinel blocked read")]
        except Exception as e:
            return [TextContent(type="text", text=f"Read error: {e}")]
    elif name == "write_file":
        try:
            from sbs.sentinel.tools import agent_write_file
            result = agent_write_file(arguments["path"], arguments["content"])
            return [TextContent(type="text", text=result)]
        except Exception as e:
            return [TextContent(type="text", text=f"Write error: {e}")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse Tools MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
