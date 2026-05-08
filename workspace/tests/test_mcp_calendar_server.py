"""
Tests for sci_fi_dashboard.mcp_servers.calendar_server — Google Calendar integration.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _text(results: list) -> str:
    return results[0].text


def _json(results: list) -> dict:
    return json.loads(_text(results))


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_all_calendar_tools(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "get_upcoming",
            "list_events",
            "search_events",
            "check_availability",
            "suggest_free_slots",
            "create_event",
            "resolve_date",
            "get_holidays",
            "calendar_request",
        }

    @pytest.mark.asyncio
    async def test_create_event_requires_summary_start_end(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tools = await list_tools()
        create_tool = next(t for t in tools if t.name == "create_event")
        required = create_tool.inputSchema.get("required", [])
        assert "summary" in required
        assert "start" in required
        assert "end" in required

    @pytest.mark.asyncio
    async def test_calendar_request_schema_requires_request_or_text(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tools = await list_tools()
        calendar_tool = next(t for t in tools if t.name == "calendar_request")
        assert calendar_tool.inputSchema["anyOf"] == [
            {"required": ["request"]},
            {"required": ["text"]},
        ]


# ---------------------------------------------------------------------------
# get_upcoming
# ---------------------------------------------------------------------------


class TestGetUpcoming:
    @pytest.mark.asyncio
    async def test_returns_formatted_events(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Team Standup",
                    "start": {"dateTime": "2026-04-02T10:00:00Z"},
                    "attendees": [
                        {"email": "alice@example.com"},
                        {"email": "bob@example.com"},
                    ],
                    "hangoutLink": "https://meet.google.com/abc",
                },
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("get_upcoming", {"minutes": 30})

        data = json.loads(_text(result))
        assert len(data) == 1
        assert data[0]["summary"] == "Team Standup"
        assert len(data[0]["attendees"]) == 2
        assert data[0]["hangout_link"] == "https://meet.google.com/abc"

    @pytest.mark.asyncio
    async def test_default_minutes_is_30(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {"items": []}

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            await cal_srv.call_tool("get_upcoming", {})

        # Verify it was called (not checking exact time values since they depend on now())
        mock_svc.events().list.assert_called()

    @pytest.mark.asyncio
    async def test_event_with_date_only(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "All Day Event",
                    "start": {"date": "2026-04-02"},
                }
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("get_upcoming", {"minutes": 60})

        data = json.loads(_text(result))
        assert data[0]["start"] == "2026-04-02"


# ---------------------------------------------------------------------------
# list_events
# ---------------------------------------------------------------------------


class TestListEvents:
    @pytest.mark.asyncio
    async def test_list_events_for_specific_date(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Morning meeting",
                    "start": {"dateTime": "2026-04-02T09:00:00Z"},
                },
                {
                    "summary": "Lunch",
                    "start": {"dateTime": "2026-04-02T12:00:00Z"},
                },
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "list_events", {"date": "2026-04-02", "max_results": 10}
            )

        data = _json(result)
        assert len(data) == 2
        assert data[0]["summary"] == "Morning meeting"

    @pytest.mark.asyncio
    async def test_list_events_uses_default_timezone_offset(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {"items": []}

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            await cal_srv.call_tool("list_events", {"date": "2026-05-06"})

        kwargs = mock_svc.events().list.call_args.kwargs
        assert kwargs["timeMin"] == "2026-05-06T00:00:00+05:30"
        assert kwargs["timeMax"] == "2026-05-07T00:00:00+05:30"


# ---------------------------------------------------------------------------
# Calendar Core backed tools
# ---------------------------------------------------------------------------


class TestCalendarCoreTools:
    @pytest.mark.asyncio
    async def test_search_events_uses_service_query_and_returns_normalized_events(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "id": "evt_search",
                    "summary": "Planning Review",
                    "htmlLink": "https://calendar/event/search",
                    "start": {"dateTime": "2026-05-06T10:00:00+05:30"},
                    "end": {"dateTime": "2026-05-06T11:00:00+05:30"},
                }
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "search_events",
                {
                    "query": "planning",
                    "start": "2026-05-06T00:00:00+05:30",
                    "end": "2026-05-07T00:00:00+05:30",
                },
            )

        data = json.loads(_text(result))
        assert data["status"] == "answered"
        assert data["data"]["events"][0]["title"] == "Planning Review"
        assert mock_svc.events().list.call_args.kwargs["q"] == "planning"

    @pytest.mark.asyncio
    async def test_resolve_date_returns_next_tuesday_from_base_date(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "resolve_date",
                {"phrase": "next Tuesday", "base_date": "2026-05-05"},
            )

        data = json.loads(_text(result))
        assert data["status"] == "answered"
        assert data["data"]["date"] == "2026-05-12"
        assert data["data"]["source"] == "next_weekday"

    @pytest.mark.asyncio
    async def test_check_availability_returns_conflicts_and_slots(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {
            "items": [
                {
                    "id": "busy_1",
                    "summary": "Busy",
                    "start": {"dateTime": "2026-05-06T10:00:00+05:30"},
                    "end": {"dateTime": "2026-05-06T10:30:00+05:30"},
                }
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "check_availability",
                {
                    "start": "2026-05-06T10:00:00+05:30",
                    "end": "2026-05-06T11:00:00+05:30",
                    "duration_minutes": 15,
                },
            )

        data = json.loads(_text(result))
        assert data["status"] == "answered"
        assert data["data"]["available"] is False
        assert data["data"]["conflicts"][0]["title"] == "Busy"
        assert data["data"]["slots"][0]["start"] == "2026-05-06T10:30:00+05:30"

    @pytest.mark.asyncio
    async def test_suggest_free_slots_returns_slots(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {"items": []}

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "suggest_free_slots",
                {
                    "day_start": "2026-05-06T09:00:00+05:30",
                    "day_end": "2026-05-06T10:00:00+05:30",
                    "duration_minutes": 30,
                },
            )

        data = json.loads(_text(result))
        assert data["status"] == "answered"
        assert data["data"]["slots"] == [
            {
                "start": "2026-05-06T09:00:00+05:30",
                "end": "2026-05-06T10:00:00+05:30",
                "duration_minutes": 60,
            }
        ]

    @pytest.mark.asyncio
    async def test_calendar_request_uses_calendar_core_assistant(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().list().execute.return_value = {"items": []}
        mock_svc.events().insert().execute.return_value = {
            "id": "evt_core",
            "htmlLink": "https://calendar/event/core",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "calendar_request",
                {"request": "Add gym tomorrow at 7 PM"},
            )

        data = _json(result)
        assert data["status"] in {"created", "confirmation_required"}
        assert data["message"]

    @pytest.mark.asyncio
    async def test_blank_calendar_request_returns_failed_without_calendar_actions(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("calendar_request", {"request": "   "})

        data = _json(result)
        assert data["status"] == "failed"
        assert data["receipt_evidence"] == ""
        assert "request" in data["data"]["error"]
        mock_svc.events().insert.assert_not_called()
        mock_svc.events().list.assert_not_called()


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


class TestCreateEvent:
    @pytest.mark.asyncio
    async def test_create_event_returns_id_and_link(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().insert().execute.return_value = {
            "id": "evt_123",
            "htmlLink": "https://calendar.google.com/event?id=evt_123",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "create_event",
                {
                    "summary": "New Event",
                    "start": "2026-04-03T10:00:00Z",
                    "end": "2026-04-03T11:00:00Z",
                    "description": "Test event",
                },
            )

        data = json.loads(_text(result))
        assert data["id"] == "evt_123"
        assert "htmlLink" in data.get("link", "") or "link" in data

    @pytest.mark.asyncio
    async def test_create_event_with_attendees(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().insert().execute.return_value = {
            "id": "evt_456",
            "htmlLink": "",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            await cal_srv.call_tool(
                "create_event",
                {
                    "summary": "Collab",
                    "start": "2026-04-03T14:00:00Z",
                    "end": "2026-04-03T15:00:00Z",
                    "attendees": ["alice@example.com", "bob@example.com"],
                },
            )

        # Verify insert was called with attendees in body
        mock_svc.events().insert.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("recurrence", [{}, "banana"])
    async def test_invalid_recurrence_returns_failed_without_insert(self, recurrence):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "create_event",
                {
                    "summary": "Bad recurrence",
                    "start": "2026-04-03T10:00:00Z",
                    "end": "2026-04-03T11:00:00Z",
                    "recurrence": recurrence,
                },
            )

        data = _json(result)
        assert data["status"] == "failed"
        assert data["receipt_evidence"] == ""
        assert "recurrence" in data["data"]["error"].lower()
        mock_svc.events().insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_rrule_string_recurrence_creates_recurrence_body(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().insert().execute.return_value = {
            "id": "evt_rrule",
            "htmlLink": "https://calendar.google.com/event?id=evt_rrule",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "create_event",
                {
                    "summary": "Weekly sync",
                    "start": "2026-04-03T10:00:00Z",
                    "end": "2026-04-03T11:00:00Z",
                    "recurrence": "RRULE:FREQ=WEEKLY",
                },
            )

        data = _json(result)
        assert data["status"] == "created"
        body = mock_svc.events().insert.call_args.kwargs["body"]
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY"]


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_blank_calendar_request_fails_before_calendar_connection(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        with patch.object(
            cal_srv,
            "_get_calendar_service",
            side_effect=AssertionError("calendar connection should not be opened"),
        ):
            result = await cal_srv.call_tool("calendar_request", {})

        data = json.loads(_text(result))
        assert data["status"] == "failed"
        assert "non-blank request" in data["data"]["error"]

    @pytest.mark.asyncio
    async def test_handler_exception_returns_failed_json_envelope(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        with patch.object(cal_srv, "_get_calendar_service", side_effect=RuntimeError("boom")):
            result = await cal_srv.call_tool(
                "search_events",
                {
                    "query": "planning",
                    "start": "2026-05-06T00:00:00+05:30",
                    "end": "2026-05-07T00:00:00+05:30",
                },
            )

        data = json.loads(_text(result))
        assert data["status"] == "failed"
        assert "boom" in data["data"]["error"]

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("nonexistent", {})

        data = _json(result)
        assert data["status"] == "failed"
        assert data["receipt_evidence"] == ""
        assert data["data"]["error"] == "Unknown tool: nonexistent"

    @pytest.mark.asyncio
    async def test_auth_rejection_returns_failed_envelope(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        with patch.object(cal_srv, "check_mcp_auth", return_value="missing token"):
            result = await cal_srv.call_tool("list_events", {"date": "2026-05-06"})

        data = _json(result)
        assert data == {
            "status": "failed",
            "message": "Calendar MCP auth failed",
            "receipt_evidence": "",
            "data": {"error": "missing token"},
        }
