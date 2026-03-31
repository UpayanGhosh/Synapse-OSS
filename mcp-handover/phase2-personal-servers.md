# Phase 2: Personal Life MCP Servers (Week 2)

> **Prerequisite**: Phase 1 complete. Core MCP servers working.
> **Auth model**: Pre-configured tokens in synapse.json (no OAuth flows yet).

## File 1: `mcp_servers/gmail_server.py`

**Tools**: search_emails, read_email, get_unread, send_email
**Deps**: `google-api-python-client`, credentials at path from `mcp.builtin_servers.gmail.token_path`

```python
"""
MCP Server: Google Gmail
Run standalone: python -m sci_fi_dashboard.mcp_servers.gmail_server
"""
import asyncio
import json
import base64
import email.mime.text

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
        token_path = gmail_cfg.token_path.replace("~", str(cfg.data_root.parent))
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
        Tool(name="search_emails", description="Search Gmail inbox. Returns subject, from, snippet, date.",
             inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}}, "required": ["query"]}),
        Tool(name="read_email", description="Read full email by message ID.",
             inputSchema={"type": "object", "properties": {"message_id": {"type": "string"}}, "required": ["message_id"]}),
        Tool(name="get_unread", description="Get unread emails (for proactive awareness).",
             inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 5}}}),
        Tool(name="send_email", description="Send email via Gmail.",
             inputSchema={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    svc = _get_gmail_service()
    if name == "search_emails":
        results = svc.users().messages().list(userId="me", q=arguments["query"], maxResults=arguments.get("max_results", 10)).execute()
        summaries = []
        for msg in results.get("messages", []):
            detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            summaries.append({"id": msg["id"], "from": headers.get("From", ""), "subject": headers.get("Subject", ""), "date": headers.get("Date", ""), "snippet": detail.get("snippet", "")})
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
        return [TextContent(type="text", text=json.dumps({"from": headers.get("From"), "subject": headers.get("Subject"), "date": headers.get("Date"), "body": body[:3000]}, indent=2))]
    elif name == "get_unread":
        results = svc.users().messages().list(userId="me", q="is:unread", maxResults=arguments.get("limit", 5)).execute()
        summaries = []
        for msg in results.get("messages", []):
            detail = svc.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            summaries.append({"id": msg["id"], "from": headers.get("From", ""), "subject": headers.get("Subject", ""), "snippet": detail.get("snippet", "")})
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
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## File 2: `mcp_servers/calendar_server.py`

**Tools**: get_upcoming, list_events, create_event

```python
"""
MCP Server: Google Calendar
Run standalone: python -m sci_fi_dashboard.mcp_servers.calendar_server
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .base import setup_logging, logger

_cal_service = None

def _get_calendar_service():
    global _cal_service
    if _cal_service is None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from synapse_config import SynapseConfig
        from mcp_config import load_mcp_config
        cfg = SynapseConfig.load()
        mcp_cfg = load_mcp_config(cfg.mcp)
        cal_cfg = mcp_cfg.builtin_servers.get("calendar")
        if not cal_cfg:
            raise RuntimeError("Calendar not configured in synapse.json")
        token_path = cal_cfg.token_path.replace("~", str(cfg.data_root.parent))
        creds = Credentials.from_authorized_user_file(token_path, [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ])
        _cal_service = build("calendar", "v3", credentials=creds)
    return _cal_service

server = Server("synapse-calendar")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="get_upcoming", description="Events in next N minutes (proactive awareness).",
             inputSchema={"type": "object", "properties": {"minutes": {"type": "integer", "default": 30}}}),
        Tool(name="list_events", description="Events for a specific date.",
             inputSchema={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}, "max_results": {"type": "integer", "default": 10}}}),
        Tool(name="create_event", description="Create a calendar event.",
             inputSchema={"type": "object", "properties": {"summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}, "description": {"type": "string", "default": ""}, "attendees": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "start", "end"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    svc = _get_calendar_service()
    if name == "get_upcoming":
        now = datetime.now(timezone.utc)
        end = now + timedelta(minutes=arguments.get("minutes", 30))
        events = svc.events().list(calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(), singleEvents=True, orderBy="startTime").execute().get("items", [])
        result = [{"summary": e.get("summary", "No title"), "start": e["start"].get("dateTime", e["start"].get("date")), "attendees": [a.get("email") for a in e.get("attendees", [])], "hangout_link": e.get("hangoutLink", "")} for e in events]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    elif name == "list_events":
        date_str = arguments.get("date", datetime.now().strftime("%Y-%m-%d"))
        day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=timezone.utc)
        events = svc.events().list(calendarId="primary", timeMin=day_start.isoformat(), timeMax=(day_start + timedelta(days=1)).isoformat(), singleEvents=True, orderBy="startTime", maxResults=arguments.get("max_results", 10)).execute().get("items", [])
        result = [{"summary": e.get("summary"), "start": e["start"].get("dateTime", e["start"].get("date"))} for e in events]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    elif name == "create_event":
        body = {"summary": arguments["summary"], "start": {"dateTime": arguments["start"]}, "end": {"dateTime": arguments["end"]}, "description": arguments.get("description", "")}
        if arguments.get("attendees"):
            body["attendees"] = [{"email": a} for a in arguments["attendees"]]
        created = svc.events().insert(calendarId="primary", body=body).execute()
        return [TextContent(type="text", text=json.dumps({"id": created["id"], "link": created.get("htmlLink", "")}))]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    setup_logging()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## File 3: `mcp_servers/slack_server.py`

**Tools**: list_channels, read_messages, get_mentions, send_message

```python
"""
MCP Server: Slack
Run standalone: python -m sci_fi_dashboard.mcp_servers.slack_server
"""
import asyncio
import json
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from .base import setup_logging, logger

_slack_client = None

def _get_slack_client():
    global _slack_client
    if _slack_client is None:
        from slack_sdk.web.async_client import AsyncWebClient
        from synapse_config import SynapseConfig
        from mcp_config import load_mcp_config
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
        Tool(name="list_channels", description="List accessible Slack channels.",
             inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}),
        Tool(name="read_messages", description="Read recent messages from a channel.",
             inputSchema={"type": "object", "properties": {"channel_id": {"type": "string"}, "limit": {"type": "integer", "default": 20}}, "required": ["channel_id"]}),
        Tool(name="get_mentions", description="Get recent mentions of the bot (proactive awareness).",
             inputSchema={"type": "object", "properties": {"since_hours": {"type": "number", "default": 1}}}),
        Tool(name="send_message", description="Post a message to a Slack channel.",
             inputSchema={"type": "object", "properties": {"channel_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel_id", "text"]}),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    clients = _get_slack_client()
    bot = clients["bot"]
    if name == "list_channels":
        resp = await bot.conversations_list(limit=arguments.get("limit", 50), types="public_channel,private_channel")
        channels = [{"id": c["id"], "name": c["name"], "topic": c.get("topic", {}).get("value", "")} for c in resp["channels"]]
        return [TextContent(type="text", text=json.dumps(channels, indent=2))]
    elif name == "read_messages":
        resp = await bot.conversations_history(channel=arguments["channel_id"], limit=arguments.get("limit", 20))
        messages = [{"user": m.get("user", ""), "text": m.get("text", ""), "ts": m.get("ts", "")} for m in resp.get("messages", [])]
        return [TextContent(type="text", text=json.dumps(messages, indent=2))]
    elif name == "get_mentions":
        since = time.time() - (arguments.get("since_hours", 1) * 3600)
        auth_resp = await bot.auth_test()
        client = clients.get("user") or bot
        resp = await client.search_messages(query=f"<@{auth_resp['user_id']}>", sort="timestamp", count=20)
        matches = [m for m in resp.get("messages", {}).get("matches", []) if float(m.get("ts", "0")) >= since]
        results = [{"channel": m.get("channel", {}).get("name", ""), "user": m.get("username", ""), "text": m.get("text", "")[:200]} for m in matches[:10]]
        return [TextContent(type="text", text=json.dumps(results, indent=2))]
    elif name == "send_message":
        await bot.chat_postMessage(channel=arguments["channel_id"], text=arguments["text"])
        return [TextContent(type="text", text="Message sent")]
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    setup_logging()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

## Verify Phase 2

```bash
# Enable gmail/calendar/slack in synapse.json (set "enabled": true)
# Place Google credentials at configured paths

mcp-inspector python -m sci_fi_dashboard.mcp_servers.gmail_server
mcp-inspector python -m sci_fi_dashboard.mcp_servers.calendar_server
mcp-inspector python -m sci_fi_dashboard.mcp_servers.slack_server
```
