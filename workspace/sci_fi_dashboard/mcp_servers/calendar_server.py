"""
MCP Server: Google Calendar
Run standalone: python -m sci_fi_dashboard.mcp_servers.calendar_server
"""

import asyncio
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from sci_fi_dashboard.calendar_core.assistant import handle_calendar_request
from sci_fi_dashboard.calendar_core.date_math import resolve_date_phrase
from sci_fi_dashboard.calendar_core.models import (
    CalendarActionResult,
    CalendarPreferences,
    CreateEventRequest,
    RecurrenceRule,
)
from sci_fi_dashboard.calendar_core.service import GoogleCalendarService

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
            name="search_events",
            description="Search events in a date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["query", "start", "end"],
            },
        ),
        Tool(
            name="check_availability",
            description="Check conflicts and free slots for a time window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["start", "end"],
            },
        ),
        Tool(
            name="suggest_free_slots",
            description="Suggest free slots in a bounded window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "day_start": {"type": "string"},
                    "day_end": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["day_start", "day_end", "duration_minutes"],
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
                    "all_day": {"type": "boolean", "default": False},
                    "recurrence": {
                        "oneOf": [
                            {"type": "object"},
                            {"type": "string"},
                        ]
                    },
                    "calendar_id": {"type": "string", "default": "primary"},
                },
                "required": ["summary", "start", "end"],
            },
        ),
        Tool(
            name="resolve_date",
            description="Resolve a natural-language date phrase.",
            inputSchema={
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "base_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["phrase"],
            },
        ),
        Tool(
            name="get_holidays",
            description="Find holiday events or deterministic locale fallback.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "locale_country": {"type": "string", "default": "IN"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="calendar_request",
            description="Handle a natural-language calendar request.",
            inputSchema={
                "type": "object",
                "properties": {
                    "request": {"type": "string"},
                    "text": {"type": "string"},
                },
                "anyOf": [
                    {"required": ["request"]},
                    {"required": ["text"]},
                ],
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
    offset = _timezone_offset(CalendarPreferences().timezone)
    day_start = datetime.fromisoformat(f"{date_str}T00:00:00{offset}")
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


def _as_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _as_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_jsonable(item) for item in value]
    return value


def _text_json(value: Any, *, indent: int | None = None) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(_as_jsonable(value), indent=indent))]


def _structured(
    *,
    status: str,
    message: str,
    receipt_evidence: str,
    data: dict[str, Any],
) -> list[TextContent]:
    return _text_json(
        {
            "status": status,
            "message": message,
            "receipt_evidence": receipt_evidence,
            "data": data,
        }
    )


def _error(message: str, error: str | None = None) -> list[TextContent]:
    return _structured(
        status="failed",
        message=message,
        receipt_evidence="",
        data={"error": error or message},
    )


def _action_result(
    result: CalendarActionResult, extra: dict[str, Any] | None = None
) -> list[TextContent]:
    payload = {
        "status": result.status,
        "message": result.user_message,
        "receipt_evidence": result.receipt_evidence,
        "data": result.data,
    }
    if result.confirmation is not None:
        payload["confirmation"] = result.confirmation
    if extra:
        payload.update(extra)
    return _text_json(payload)


def _parse_recurrence(value: Any) -> RecurrenceRule | None:
    if value is None:
        return None
    if isinstance(value, dict):
        frequency = value.get("frequency") or value.get("freq")
        if not frequency:
            raise ValueError("recurrence must include a supported frequency")
        return RecurrenceRule(
            str(frequency).lower(),
            until=value.get("until"),
            count=value.get("count"),
        )
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("recurrence must not be blank")
        normalized = value.upper()
        if "FREQ=" in normalized:
            frequency = normalized.split("FREQ=", 1)[1].split(";", 1)[0]
        else:
            frequency = normalized
        return RecurrenceRule(frequency.lower())
    raise ValueError("recurrence must be an object or string")


def _timezone_offset(timezone_name: str) -> str:
    if timezone_name == "Asia/Calcutta":
        return "+05:30"
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", timezone_name)
    if match:
        return timezone_name
    return (
        datetime.now().astimezone().strftime("%z")[:3]
        + ":"
        + datetime.now().astimezone().strftime("%z")[3:]
    )


def _event_data(events: list[Any]) -> list[dict[str, Any]]:
    return [_as_jsonable(event) for event in events]


def _create_event(svc, arguments: dict) -> list[TextContent]:
    calendar = GoogleCalendarService(svc)
    request = CreateEventRequest(
        title=arguments["summary"],
        start=arguments["start"],
        end=arguments["end"],
        calendar_id=arguments.get("calendar_id", "primary"),
        description=arguments.get("description", ""),
        attendees=list(arguments.get("attendees") or []),
        all_day=bool(arguments.get("all_day", False)),
        recurrence=_parse_recurrence(arguments.get("recurrence")),
    )
    result = calendar.create_event(request, calendar_id=request.calendar_id)
    return _action_result(
        result,
        extra={
            "id": result.data.get("event_id", ""),
            "link": result.data.get("link", ""),
        },
    )


def _search_events(svc, arguments: dict) -> list[TextContent]:
    calendar = GoogleCalendarService(svc)
    events = calendar.search_events(
        arguments["query"],
        arguments["start"],
        arguments["end"],
        calendar_id=arguments.get("calendar_id", "primary"),
    )
    return _structured(
        status="answered",
        message=f"Found {len(events)} matching calendar event(s).",
        receipt_evidence="Searched Google Calendar through calendar service.",
        data={"events": _event_data(events)},
    )


def _check_availability(svc, arguments: dict) -> list[TextContent]:
    calendar = GoogleCalendarService(svc)
    calendar_id = arguments.get("calendar_id", "primary")
    conflicts = calendar.check_conflicts(
        arguments["start"], arguments["end"], calendar_id=calendar_id
    )
    duration = arguments.get("duration_minutes") or 60
    slots = calendar.suggest_free_slots(
        arguments["start"],
        arguments["end"],
        int(duration),
        calendar_id=calendar_id,
    )
    return _structured(
        status="answered",
        message="Availability checked.",
        receipt_evidence="Checked Google Calendar conflicts and free slots through calendar service.",
        data={
            "available": not conflicts,
            "conflicts": _event_data(conflicts),
            "slots": slots,
        },
    )


def _suggest_free_slots(svc, arguments: dict) -> list[TextContent]:
    calendar = GoogleCalendarService(svc)
    slots = calendar.suggest_free_slots(
        arguments["day_start"],
        arguments["day_end"],
        int(arguments["duration_minutes"]),
        calendar_id=arguments.get("calendar_id", "primary"),
    )
    return _structured(
        status="answered",
        message=f"Found {len(slots)} free slot(s).",
        receipt_evidence="Computed free slots through calendar service.",
        data={"slots": slots},
    )


def _resolve_date(arguments: dict) -> list[TextContent]:
    base_date = date.fromisoformat(arguments["base_date"]) if arguments.get("base_date") else None
    resolved = resolve_date_phrase(arguments["phrase"], base_date=base_date)
    return _structured(
        status="answered",
        message="Date phrase resolved." if resolved.date else "Date phrase was not recognized.",
        receipt_evidence="Resolved date phrase locally with Calendar Core date math.",
        data={
            "date": resolved.date.isoformat() if resolved.date else None,
            "start": resolved.start.isoformat() if resolved.start else None,
            "end": resolved.end.isoformat() if resolved.end else None,
            "confidence": resolved.confidence,
            "source": resolved.source,
        },
    )


def _get_holidays(svc, arguments: dict) -> list[TextContent]:
    calendar = GoogleCalendarService(svc)
    preferences = CalendarPreferences(locale_country=arguments.get("locale_country", "IN"))
    return _action_result(calendar.find_holidays(arguments["query"], preferences))


def _calendar_request(svc, arguments: dict) -> list[TextContent]:
    text = arguments.get("request") or arguments.get("text") or ""
    if not str(text).strip():
        return _error("calendar_request requires non-blank request text")
    calendar = GoogleCalendarService(svc)
    result = handle_calendar_request(text, calendar, CalendarPreferences())
    return _action_result(result)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    arguments = arguments or {}
    auth_err = check_mcp_auth(arguments)
    if auth_err:
        return _error("Calendar MCP auth failed", auth_err)

    try:
        _HANDLERS = {  # noqa: N806
            "get_upcoming": _get_upcoming,
            "list_events": _list_events,
            "search_events": _search_events,
            "check_availability": _check_availability,
            "suggest_free_slots": _suggest_free_slots,
            "create_event": _create_event,
            "get_holidays": _get_holidays,
            "calendar_request": _calendar_request,
        }
        if name == "resolve_date":
            return await asyncio.to_thread(_resolve_date, arguments)
        handler = _HANDLERS.get(name)
        if not handler:
            return _error(f"Unknown tool: {name}")
        if name == "calendar_request":
            text = arguments.get("request") or arguments.get("text") or ""
            if not str(text).strip():
                return _error("calendar_request requires non-blank request text")
        svc = _get_calendar_service()
        return await asyncio.to_thread(handler, svc, arguments)
    except Exception as e:
        logger.exception("Calendar tool %s failed", name)
        return _error(f"Calendar tool {name} failed", str(e))


async def main():
    setup_logging()
    logger.info("Starting Synapse Calendar MCP Server")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
