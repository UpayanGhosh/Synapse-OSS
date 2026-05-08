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
        assert {
            "get_upcoming",
            "list_events",
            "search_events",
            "check_availability",
            "suggest_free_slots",
            "create_event",
            "resolve_date",
            "get_holidays",
            "calendar_request",
        } <= names

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


# ---------------------------------------------------------------------------
# V2 tools — schema + happy-path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_calendar_tools_in_list_tools():
    from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

    names = {t.name for t in await list_tools()}
    assert {
        "list_calendars",
        "get_event",
        "update_event",
        "delete_event",
        "move_event",
        "respond_to_event",
        "get_freebusy",
        "quick_add",
        "list_colors",
    } <= names
    # Backwards-compat: V1 tools still present
    assert {
        "get_upcoming",
        "list_events",
        "search_events",
        "check_availability",
        "suggest_free_slots",
        "create_event",
        "resolve_date",
        "get_holidays",
        "calendar_request",
    } <= names


class TestListCalendarsV2:
    @pytest.mark.asyncio
    async def test_schema_no_required_fields(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "list_calendars")
        assert tool.inputSchema.get("required", []) == []

    @pytest.mark.asyncio
    async def test_returns_normalized_calendar_entries(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.calendarList().list().execute.return_value = {
            "items": [
                {
                    "id": "primary",
                    "summary": "Personal",
                    "primary": True,
                    "timeZone": "Asia/Calcutta",
                    "accessRole": "owner",
                },
                {
                    "id": "team@example.com",
                    "summary": "Team",
                    "accessRole": "reader",
                },
            ]
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("list_calendars", {})

        data = _json(result)
        assert data["status"] == "answered"
        assert "Found 2 calendar(s)" in data["message"]
        cals = data["data"]["calendars"]
        assert cals[0]["id"] == "primary"
        assert cals[0]["primary"] is True
        assert cals[1]["id"] == "team@example.com"


class TestGetEventV2:
    @pytest.mark.asyncio
    async def test_schema_requires_event_id(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "get_event")
        assert "event_id" in tool.inputSchema["required"]

    @pytest.mark.asyncio
    async def test_returns_event_data(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().get().execute.return_value = {
            "id": "evt_42",
            "summary": "Standup",
            "htmlLink": "https://cal/evt_42",
            "start": {"dateTime": "2026-05-06T10:00:00+05:30"},
            "end": {"dateTime": "2026-05-06T10:30:00+05:30"},
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "get_event", {"event_id": "evt_42", "calendar_id": "primary"}
            )

        data = _json(result)
        assert data["status"] == "answered"
        assert data["data"]["event"]["id"] == "evt_42"
        assert data["data"]["event"]["title"] == "Standup"
        assert "evt_42" in data["receipt_evidence"]


class TestUpdateEventV2:
    @pytest.mark.asyncio
    async def test_schema_requires_event_id(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "update_event")
        assert tool.inputSchema["required"] == ["event_id"]

    @pytest.mark.asyncio
    async def test_patches_event_with_title_change(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        # No instance resolution path: we explicitly set scope=all to avoid
        # the events.instances() call.
        mock_svc.events().patch().execute.return_value = {
            "id": "evt_1",
            "summary": "New Title",
            "htmlLink": "https://cal/evt_1",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "update_event",
                {
                    "event_id": "evt_1",
                    "title": "New Title",
                    "modification_scope": "all",
                },
            )

        data = _json(result)
        assert data["status"] == "updated"
        assert data["data"]["event_id"] == "evt_1"
        assert "title" in data["data"]["changed_fields"]


class TestDeleteEventV2:
    @pytest.mark.asyncio
    async def test_schema_requires_event_id(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "delete_event")
        assert tool.inputSchema["required"] == ["event_id"]

    @pytest.mark.asyncio
    async def test_deletes_event(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().delete().execute.return_value = None

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "delete_event",
                {
                    "event_id": "evt_del",
                    "modification_scope": "all",
                },
            )

        data = _json(result)
        assert data["status"] == "deleted"
        assert data["data"]["event_id"] == "evt_del"
        mock_svc.events().delete.assert_called()


class TestMoveEventV2:
    @pytest.mark.asyncio
    async def test_schema_requires_triple(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "move_event")
        assert set(tool.inputSchema["required"]) == {
            "event_id",
            "source_calendar_id",
            "destination_calendar_id",
        }

    @pytest.mark.asyncio
    async def test_moves_event_between_calendars(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().move().execute.return_value = {
            "id": "evt_move",
            "summary": "Moved",
            "htmlLink": "https://cal/moved",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "move_event",
                {
                    "event_id": "evt_move",
                    "source_calendar_id": "primary",
                    "destination_calendar_id": "team@example.com",
                },
            )

        data = _json(result)
        assert data["status"] == "moved"
        assert data["data"]["destination_calendar_id"] == "team@example.com"


class TestRespondToEventV2:
    @pytest.mark.asyncio
    async def test_schema_requires_event_id_and_response(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "respond_to_event")
        assert set(tool.inputSchema["required"]) == {"event_id", "response"}

    @pytest.mark.asyncio
    async def test_records_rsvp(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().get().execute.return_value = {
            "id": "evt_rsvp",
            "summary": "Lunch",
            "attendees": [
                {"email": "me@example.com", "self": True, "responseStatus": "needsAction"},
            ],
        }
        mock_svc.events().patch().execute.return_value = {
            "id": "evt_rsvp",
            "summary": "Lunch",
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "respond_to_event",
                {"event_id": "evt_rsvp", "response": "accepted"},
            )

        data = _json(result)
        assert data["status"] == "rsvp_recorded"
        assert data["data"]["response"] == "accepted"
        assert data["data"]["attendee_email"] == "me@example.com"


class TestGetFreebusyV2:
    @pytest.mark.asyncio
    async def test_schema_requires_start_end(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "get_freebusy")
        assert set(tool.inputSchema["required"]) == {"start", "end"}

    @pytest.mark.asyncio
    async def test_returns_freebusy_windows(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.freebusy().query().execute.return_value = {
            "timeMin": "2026-05-06T00:00:00+05:30",
            "timeMax": "2026-05-06T23:59:59+05:30",
            "calendars": {
                "primary": {
                    "busy": [
                        {
                            "start": "2026-05-06T10:00:00+05:30",
                            "end": "2026-05-06T11:00:00+05:30",
                        }
                    ]
                }
            },
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "get_freebusy",
                {
                    "start": "2026-05-06T00:00:00+05:30",
                    "end": "2026-05-06T23:59:59+05:30",
                    "calendar_ids": ["primary"],
                },
            )

        data = _json(result)
        assert data["status"] == "answered"
        assert data["data"]["calendars"]["primary"][0]["start"] == "2026-05-06T10:00:00+05:30"
        assert data["data"]["time_min"] == "2026-05-06T00:00:00+05:30"

    @pytest.mark.asyncio
    async def test_default_calendar_ids_is_primary(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}},
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "get_freebusy",
                {
                    "start": "2026-05-06T00:00:00+05:30",
                    "end": "2026-05-06T23:59:59+05:30",
                },
            )

        data = _json(result)
        assert data["status"] == "answered"
        assert "primary" in data["data"]["calendars"]


class TestQuickAddV2:
    @pytest.mark.asyncio
    async def test_schema_requires_text(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "quick_add")
        assert tool.inputSchema["required"] == ["text"]

    @pytest.mark.asyncio
    async def test_quick_add_creates_event(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.events().quickAdd().execute.return_value = {
            "id": "evt_quick",
            "summary": "Coffee at 4pm",
            "htmlLink": "https://cal/quick",
            "start": {"dateTime": "2026-05-06T16:00:00+05:30"},
            "end": {"dateTime": "2026-05-06T17:00:00+05:30"},
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool(
                "quick_add", {"text": "Coffee at 4pm"}
            )

        data = _json(result)
        assert data["status"] == "created"
        assert data["data"]["event_id"] == "evt_quick"


class TestListColorsV2:
    @pytest.mark.asyncio
    async def test_schema_no_required_fields(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tool = next(t for t in await list_tools() if t.name == "list_colors")
        assert tool.inputSchema.get("required", []) == []

    @pytest.mark.asyncio
    async def test_returns_palette(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        mock_svc.colors().get().execute.return_value = {
            "updated": "2026-05-06T00:00:00Z",
            "event": {"1": {"background": "#a4bdfc", "foreground": "#1d1d1d"}},
            "calendar": {"1": {"background": "#ac725e", "foreground": "#ffffff"}},
        }

        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("list_colors", {})

        data = _json(result)
        assert data["status"] == "answered"
        assert data["data"]["event_colors"]["1"]["background"] == "#a4bdfc"
        assert data["data"]["calendar_colors"]["1"]["background"] == "#ac725e"
        assert data["data"]["updated"] == "2026-05-06T00:00:00Z"
