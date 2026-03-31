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
        Tool(
            name="get_profile_summary",
            description=(
                "Get user's behavioral profile: mood, sentiment, language, vocab size, message count."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_system_prompt",
            description="Get compiled SBS persona prompt.",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_instructions": {"type": "string", "default": ""},
                },
            },
        ),
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
    logger.info("Starting Synapse Conversation MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
