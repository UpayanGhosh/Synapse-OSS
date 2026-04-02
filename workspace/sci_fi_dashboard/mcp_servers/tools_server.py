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
            description=(
                "Read file contents (Sentinel-gated). Supports adaptive paging for large files "
                "via optional offset and page_bytes parameters."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "offset": {
                        "type": "integer",
                        "description": "Byte offset to start reading from (default: 0)",
                    },
                    "page_bytes": {
                        "type": "integer",
                        "description": (
                            "Max bytes to read per call. Clamped to [50 KB, 512 KB]. "
                            "Defaults to 50 KB."
                        ),
                    },
                },
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
        Tool(
            name="edit_file",
            description=(
                "Apply a text patch to an existing file. Replaces the first N occurrences of "
                "old_text with new_text using an atomic write. Fails if old_text appears more "
                "than expected_count times (use more context to disambiguate)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_text": {"type": "string", "description": "Exact text to replace"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "expected_count": {
                        "type": "integer",
                        "description": "Expected number of occurrences to replace (default: 1)",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        ),
        Tool(
            name="delete_file",
            description="Delete a file (Sentinel-gated, audit logged).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                    "reason": {
                        "type": "string",
                        "description": "Reason for deletion (optional, used in audit log)",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="list_directory",
            description="List files in a directory (Sentinel-gated).",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"},
                },
                "required": ["path"],
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
            # FIX: use module-level agent_read_file(), not Sentinel() instance method
            from sbs.sentinel.tools import agent_read_file
            result = agent_read_file(arguments["path"])
            return [TextContent(type="text", text=result)]
        except PermissionError as e:
            return [TextContent(type="text", text=f"DENIED: {e}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"NOT_FOUND: {e}")]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "write_file":
        try:
            # FIX: use module-level agent_write_file(), not Sentinel() instance method
            from sbs.sentinel.tools import agent_write_file
            result = agent_write_file(arguments["path"], arguments["content"])
            return [TextContent(type="text", text=result)]
        except PermissionError as e:
            return [TextContent(type="text", text=f"DENIED: {e}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"NOT_FOUND: {e}")]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "edit_file":
        try:
            from sbs.sentinel.tools import agent_check_write_access
            from sbs.sentinel.gateway import SentinelError
            from file_ops.edit import apply_edit
            # Sentinel WRITE gate -- edit_file modifies the file
            resolved = agent_check_write_access(
                arguments["path"], "mcp edit_file"
            )
            # Use the resolved path for the edit to avoid TOCTOU
            result = apply_edit(
                str(resolved),
                arguments["old_text"],
                arguments["new_text"],
                expected_count=arguments.get("expected_count", 1),
            )
            return [TextContent(type="text", text=json.dumps(result))]
        except (SentinelError, PermissionError) as e:
            return [TextContent(type="text", text=f"DENIED: {e}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"NOT_FOUND: {e}")]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "delete_file":
        try:
            from sbs.sentinel.tools import agent_delete_file
            result = agent_delete_file(
                arguments["path"],
                arguments.get("reason", ""),
            )
            if result.startswith("[SENTINEL DENIED]"):
                return [TextContent(type="text", text=f"DENIED: {result}")]
            return [TextContent(type="text", text=result)]
        except PermissionError as e:
            return [TextContent(type="text", text=f"DENIED: {e}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"NOT_FOUND: {e}")]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "list_directory":
        try:
            from sbs.sentinel.tools import agent_list_directory
            result = agent_list_directory(arguments["path"])
            if result.startswith("[SENTINEL DENIED]"):
                return [TextContent(type="text", text=f"DENIED: {result}")]
            return [TextContent(type="text", text=result)]
        except PermissionError as e:
            return [TextContent(type="text", text=f"DENIED: {e}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"NOT_FOUND: {e}")]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"ERROR: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse Tools MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
