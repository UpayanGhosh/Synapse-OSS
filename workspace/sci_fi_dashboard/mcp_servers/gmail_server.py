"""
MCP Server: Google Gmail
Run standalone: python -m sci_fi_dashboard.mcp_servers.gmail_server
"""

import asyncio
import base64
import email.mime.text
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .base import check_mcp_auth, logger, setup_logging

_gmail_service = None


def _get_gmail_service():
    global _gmail_service
    if _gmail_service is None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from mcp_config import load_mcp_config
        from synapse_config import SynapseConfig

        cfg = SynapseConfig.load()
        mcp_cfg = load_mcp_config(cfg.mcp)
        gmail_cfg = mcp_cfg.builtin_servers.get("gmail")
        if not gmail_cfg:
            raise RuntimeError("Gmail not configured in synapse.json mcp.builtin_servers.gmail")
        token_path = str(Path(gmail_cfg.token_path).expanduser())
        creds = Credentials.from_authorized_user_file(
            token_path,
            [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ],
        )
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


def _search_emails(svc, arguments: dict) -> list[TextContent]:
    results = (
        svc.users()
        .messages()
        .list(userId="me", q=arguments["query"], maxResults=arguments.get("max_results", 10))
        .execute()
    )
    summaries = []
    for msg in results.get("messages", []):
        detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        summaries.append(
            {
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            }
        )
    return [TextContent(type="text", text=json.dumps(summaries, indent=2))]


def _read_email(svc, arguments: dict) -> list[TextContent]:
    msg = (
        svc.users().messages().get(userId="me", id=arguments["message_id"], format="full").execute()
    )
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
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "from": headers.get("From"),
                    "subject": headers.get("Subject"),
                    "date": headers.get("Date"),
                    "body": body[:3000],
                },
                indent=2,
            ),
        )
    ]


def _get_unread(svc, arguments: dict) -> list[TextContent]:
    results = (
        svc.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=arguments.get("limit", 5))
        .execute()
    )
    summaries = []
    for msg in results.get("messages", []):
        detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        summaries.append(
            {
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "snippet": detail.get("snippet", ""),
            }
        )
    return [TextContent(type="text", text=json.dumps(summaries, indent=2))]


def _send_email(svc, arguments: dict) -> list[TextContent]:
    mime_msg = email.mime.text.MIMEText(arguments["body"])
    mime_msg["to"] = arguments["to"]
    mime_msg["subject"] = arguments["subject"]
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return [TextContent(type="text", text="Email sent")]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    auth_err = check_mcp_auth(arguments)
    if auth_err:
        return [TextContent(type="text", text=json.dumps({"error": auth_err}))]

    try:
        svc = _get_gmail_service()
        _HANDLERS = {  # noqa: N806
            "search_emails": _search_emails,
            "read_email": _read_email,
            "get_unread": _get_unread,
            "send_email": _send_email,
        }
        handler = _HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        return await asyncio.to_thread(handler, svc, arguments)
    except Exception as e:
        logger.exception("Gmail tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    setup_logging()
    logger.info("Starting Synapse Gmail MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
