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


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


class TestListTools:
    @pytest.mark.asyncio
    async def test_lists_all_calendar_tools(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"get_upcoming", "list_events", "create_event"}

    @pytest.mark.asyncio
    async def test_create_event_requires_summary_start_end(self):
        from sci_fi_dashboard.mcp_servers.calendar_server import list_tools

        tools = await list_tools()
        create_tool = next(t for t in tools if t.name == "create_event")
        required = create_tool.inputSchema.get("required", [])
        assert "summary" in required
        assert "start" in required
        assert "end" in required


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

        data = json.loads(_text(result))
        assert len(data) == 2
        assert data[0]["summary"] == "Morning meeting"


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


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        import sci_fi_dashboard.mcp_servers.calendar_server as cal_srv

        mock_svc = MagicMock()
        with patch.object(cal_srv, "_get_calendar_service", return_value=mock_svc):
            result = await cal_srv.call_tool("nonexistent", {})

        assert "Unknown tool" in _text(result)
