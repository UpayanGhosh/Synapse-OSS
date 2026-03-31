"""
MCP Server: Google Gmail
Run standalone: python -m sci_fi_dashboard.mcp_servers.gmail_server
"""
import asyncio
import json
import base64
import email.mime.text
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .base import setup_logging, logger

_gmail_service = None


def _get_gmail_service():
    global _gmail_service
    if _gmail_service is None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from synapse_config import SynapseConfig
        from mcp_config import load_mcp_config
        cfg = SynapseConfig.load()
        mcp_cfg = load_mcp_config(cfg.mcp)
        gmail_cfg = mcp_cfg.builtin_servers.get("gmail")
        if not gmail_cfg:
            raise RuntimeError("Gmail not configured in synapse.json mcp.builtin_servers.gmail")
        token_path = str(Path(gmail_cfg.token_path).expanduser())
        creds = Credentials.from_authorized_user_file(token_path, [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ])
        _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


server = Server("synapse-gmail")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_emails",
            description="Search Gmail inbox. Returns subject, from, snippet, date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="read_email",
            description="Read full email by message ID.",
            inputSchema={
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"],
            },
        ),
        Tool(
            name="get_unread",
            description="Get unread emails (for proactive awareness).",
            inputSchema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 5}},
            },
        ),
        Tool(
            name="send_email",
            description="Send email via Gmail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    svc = _get_gmail_service()
    if name == "search_emails":
        results = svc.users().messages().list(
            userId="me", q=arguments["query"], maxResults=arguments.get("max_results", 10)
        ).execute()
        summaries = []
        for msg in results.get("messages", []):
            detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            summaries.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            })
        return [TextContent(type="text", text=json.dumps(summaries, indent=2))]
    elif name == "read_email":
        msg = svc.users().messages().get(userId="me", id=arguments["message_id"], format="full").execute()
        payload = msg.get("payload", {})
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    break
        elif "body" in payload and "data" in payload["body"]:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        return [TextContent(type="text", text=json.dumps({
            "from": headers.get("From"),
            "subject": headers.get("Subject"),
            "date": headers.get("Date"),
            "body": body[:3000],
        }, indent=2))]
    elif name == "get_unread":
        results = svc.users().messages().list(
            userId="me", q="is:unread", maxResults=arguments.get("limit", 5)
        ).execute()
        summaries = []
        for msg in results.get("messages", []):
            detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            summaries.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "snippet": detail.get("snippet", ""),
            })
        return [TextContent(type="text", text=json.dumps(summaries, indent=2))]
    elif name == "send_email":
        mime_msg = email.mime.text.MIMEText(arguments["body"])
        mime_msg["to"] = arguments["to"]
        mime_msg["subject"] = arguments["subject"]
        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return [TextContent(type="text", text="Email sent")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    setup_logging()
    logger.info("Starting Synapse Gmail MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
