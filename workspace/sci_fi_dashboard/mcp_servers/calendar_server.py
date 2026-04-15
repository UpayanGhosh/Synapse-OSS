"""
MCP Server: Google Calendar
Run standalone: python -m sci_fi_dashboard.mcp_servers.calendar_server
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .base import check_mcp_auth, logger, setup_logging

_cal_service = None


def _get_calendar_service():
    global _cal_service
    if _cal_service is None:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from mcp_config import load_mcp_config
        from synapse_config import SynapseConfig

        cfg = SynapseConfig.load()
        mcp_cfg = load_mcp_config(cfg.mcp)
        cal_cfg = mcp_cfg.builtin_servers.get("calendar")
        if not cal_cfg:
            raise RuntimeError("Calendar not configured in synapse.json")
        token_path = str(Path(cal_cfg.token_path).expanduser())
        creds = Credentials.from_authorized_user_file(
            token_path,
            [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        )
        _cal_service = build("calendar", "v3", credentials=creds)
    return _cal_service


server = Server("synapse-calendar")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_upcoming",
            description="Events in next N minutes (proactive awareness).",
            inputSchema={
                "type": "object",
                "properties": {"minutes": {"type": "integer", "default": 30}},
            },
        ),
        Tool(
            name="list_events",
            description="Events for a specific date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "max_results": {"type": "integer", "default": 10},
                },
            },
        ),
        Tool(
            name="create_event",
            description="Create a calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "start", "end"],
            },
        ),
    ]


def _get_upcoming(svc, arguments: dict) -> list[TextContent]:
    now = datetime.now(UTC)
    end = now + timedelta(minutes=arguments.get("minutes", 30))
    events = (
        svc.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    result = [
        {
            "summary": e.get("summary", "No title"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "attendees": [a.get("email") for a in e.get("attendees", [])],
            "hangout_link": e.get("hangoutLink", ""),
        }
        for e in events
    ]
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _list_events(svc, arguments: dict) -> list[TextContent]:
    date_str = arguments.get("date", datetime.now().strftime("%Y-%m-%d"))
    day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=UTC)
    events = (
        svc.events()
        .list(
            calendarId="primary",
            timeMin=day_start.isoformat(),
            timeMax=(day_start + timedelta(days=1)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=arguments.get("max_results", 10),
        )
        .execute()
        .get("items", [])
    )
    result = [
        {
            "summary": e.get("summary"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
        }
        for e in events
    ]
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _create_event(svc, arguments: dict) -> list[TextContent]:
    body = {
        "summary": arguments["summary"],
        "start": {"dateTime": arguments["start"]},
        "end": {"dateTime": arguments["end"]},
        "description": arguments.get("description", ""),
    }
    if arguments.get("attendees"):
        body["attendees"] = [{"email": a} for a in arguments["attendees"]]
    created = svc.events().insert(calendarId="primary", body=body).execute()
    return [
        TextContent(
            type="text",
            text=json.dumps({"id": created["id"], "link": created.get("htmlLink", "")}),
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    auth_err = check_mcp_auth(arguments)
    if auth_err:
        return [TextContent(type="text", text=json.dumps({"error": auth_err}))]

    try:
        svc = _get_calendar_service()
        _HANDLERS = {  # noqa: N806
            "get_upcoming": _get_upcoming,
            "list_events": _list_events,
            "create_event": _create_event,
        }
        handler = _HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        return await asyncio.to_thread(handler, svc, arguments)
    except Exception as e:
        logger.exception("Calendar tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    setup_logging()
    logger.info("Starting Synapse Calendar MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
