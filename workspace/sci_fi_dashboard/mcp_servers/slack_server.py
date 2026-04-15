"""
MCP Server: Slack
Run standalone: python -m sci_fi_dashboard.mcp_servers.slack_server
"""

import asyncio
import json
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .base import logger, setup_logging

_slack_client = None


def _get_slack_client():
    global _slack_client
    if _slack_client is None:
        from mcp_config import load_mcp_config
        from slack_sdk.web.async_client import AsyncWebClient
        from synapse_config import SynapseConfig

        cfg = SynapseConfig.load()
        mcp_cfg = load_mcp_config(cfg.mcp)
        slack_cfg = mcp_cfg.builtin_servers.get("slack")
        if not slack_cfg:
            raise RuntimeError("Slack not configured in synapse.json")
        _slack_client = {
            "bot": AsyncWebClient(token=slack_cfg.bot_token),
            "user": AsyncWebClient(token=slack_cfg.user_token) if slack_cfg.user_token else None,
        }
    return _slack_client


server = Server("synapse-slack")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_channels",
            description="List accessible Slack channels.",
            inputSchema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 50}},
            },
        ),
        Tool(
            name="read_messages",
            description="Read recent messages from a channel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["channel_id"],
            },
        ),
        Tool(
            name="get_mentions",
            description="Get recent mentions of the bot (proactive awareness).",
            inputSchema={
                "type": "object",
                "properties": {"since_hours": {"type": "number", "default": 1}},
            },
        ),
        Tool(
            name="send_message",
            description="Post a message to a Slack channel.",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["channel_id", "text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    clients = _get_slack_client()
    bot = clients["bot"]
    if name == "list_channels":
        resp = await bot.conversations_list(
            limit=arguments.get("limit", 50), types="public_channel,private_channel"
        )
        channels = [
            {"id": c["id"], "name": c["name"], "topic": c.get("topic", {}).get("value", "")}
            for c in resp["channels"]
        ]
        return [TextContent(type="text", text=json.dumps(channels, indent=2))]
    elif name == "read_messages":
        resp = await bot.conversations_history(
            channel=arguments["channel_id"], limit=arguments.get("limit", 20)
        )
        messages = [
            {"user": m.get("user", ""), "text": m.get("text", ""), "ts": m.get("ts", "")}
            for m in resp.get("messages", [])
        ]
        return [TextContent(type="text", text=json.dumps(messages, indent=2))]
    elif name == "get_mentions":
        since = time.time() - (arguments.get("since_hours", 1) * 3600)
        auth_resp = await bot.auth_test()
        client = clients.get("user") or bot
        resp = await client.search_messages(
            query=f"<@{auth_resp['user_id']}>", sort="timestamp", count=20
        )
        matches = [
            m
            for m in resp.get("messages", {}).get("matches", [])
            if float(m.get("ts", "0")) >= since
        ]
        results = [
            {
                "channel": m.get("channel", {}).get("name", ""),
                "user": m.get("username", ""),
                "text": m.get("text", "")[:200],
            }
            for m in matches[:10]
        ]
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    elif name == "send_message":
        await bot.chat_postMessage(channel=arguments["channel_id"], text=arguments["text"])
        return [TextContent(type="text", text="Message sent")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse Slack MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
