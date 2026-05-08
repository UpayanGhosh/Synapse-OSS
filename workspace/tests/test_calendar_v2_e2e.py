"""End-to-end mocked exercise of Calendar Core V2.

Exercises the full V2 confirmation loop through the Calendar tool registered
on the chat-facing ``ToolRegistry``. No live Google Calendar API; the mocked
service plays both the search-events and execute-action sides.

These tests must remain green without starting Synapse — they only import
modules and run the calendar tool's ``execute()`` callable.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from sci_fi_dashboard.calendar_core.confirmations import (
    PendingActionStore,
    reset_default_store_for_tests,
)
from sci_fi_dashboard.calendar_core.models import (
    CalendarActionResult,
    CalendarEvent,
    CalendarPreferences,
)


class FakeCalendarService:
    def __init__(self, search_results: list[CalendarEvent] | None = None) -> None:
        self.search_results = search_results or []
        self.delete_calls = []
        self.update_calls = []
        self.move_calls = []
        self.create_calls = []
        self.rsvp_calls = []
        self.quick_add_calls = []
        self.freebusy_calls = []

    def search_events(self, query: str, start: str, end: str, calendar_id: str = "primary"):
        return list(self.search_results)

    def list_events(self, start: str, end: str, calendar_id: str = "primary", query=None):
        return []

    def check_conflicts(self, start: str, end: str, calendar_id: str = "primary"):
        return []

    def suggest_free_slots(self, day_start, day_end, duration_minutes, calendar_id="primary"):
        return []

    def find_holidays(self, query: str, prefs: CalendarPreferences):
        return CalendarActionResult(status="answered", user_message="ok", data={})

    def create_event(self, request, calendar_id: str = "primary"):
        self.create_calls.append((request, calendar_id))
        return CalendarActionResult.created(
            event_id="evt_new", link="https://x", title=request.title,
            start=request.start, end=request.end,
        )

    def delete_event(self, request):
        self.delete_calls.append(request)
        return CalendarActionResult.deleted(
            event_id=request.event_id, title="(deleted)",
            modification_scope=request.modification_scope,
        )

    def update_event(self, request):
        self.update_calls.append(request)
        return CalendarActionResult.updated(
            event_id=request.event_id, link="https://x", title="(updated)",
            modification_scope=request.modification_scope, changed_fields=["start"],
        )

    def move_event(self, request):
        self.move_calls.append(request)
        return CalendarActionResult.moved(
            event_id=request.event_id, link="https://x", title="(moved)",
            source_calendar_id=request.source_calendar_id,
            destination_calendar_id=request.destination_calendar_id,
        )

    def respond_to_event(self, request):
        self.rsvp_calls.append(request)
        return CalendarActionResult.rsvp_recorded(
            event_id=request.event_id, title="(rsvp)",
            response=request.response, attendee_email="me@example.com",
        )

    def quick_add(self, request):
        self.quick_add_calls.append(request)
        return CalendarActionResult.created(
            event_id="evt_qa", link="https://x", title=request.text,
            start="2026-05-08T13:00:00+05:30", end="2026-05-08T14:00:00+05:30",
        )

    def freebusy(self, request):
        from sci_fi_dashboard.calendar_core.models import FreeBusyResult

        self.freebusy_calls.append(request)
        return FreeBusyResult(calendars={"primary": []}, time_min=request.start, time_max=request.end)


def _make_calendar_tool(fake_service: FakeCalendarService, prefs: CalendarPreferences):
    """Build the calendar SynapseTool factory output without touching synapse.json."""
    from sci_fi_dashboard.tool_registry import ToolContext, _calendar_factory

    ctx = ToolContext(
        chat_id="chat_xyz",
        sender_id="user1",
        sender_is_owner=True,
        workspace_dir=".",
        config={},
        channel_id="api",
    )

    def fake_runtime():
        return fake_service, prefs

    with patch("sci_fi_dashboard.tool_registry._get_calendar_runtime", side_effect=fake_runtime):
        tool = _calendar_factory(ctx)
        # Bind the fake runtime for the tool's execute closure too
        tool._fake_runtime = fake_runtime  # type: ignore[attr-defined]
    return tool


def _exec_tool(tool, payload: dict[str, Any]):
    import asyncio

    with patch(
        "sci_fi_dashboard.tool_registry._get_calendar_runtime",
        side_effect=tool._fake_runtime,  # type: ignore[attr-defined]
    ):
        return asyncio.run(tool.execute(payload))


@pytest.fixture(autouse=True)
def _isolate_default_store():
    reset_default_store_for_tests()
    yield
    reset_default_store_for_tests()


def _event(eid: str, title: str, start: str, end: str, **extra) -> CalendarEvent:
    return CalendarEvent(
        id=eid, title=title, start=start, end=end,
        calendar_id=extra.get("calendar_id", "primary"),
        attendees=extra.get("attendees", []),
        recurring_event_id=extra.get("recurring_event_id"),
        organizer_email=extra.get("organizer_email", ""),
        self_response_status=extra.get("self_response_status", ""),
        status=extra.get("status", "confirmed"),
    )


def test_calendar_tool_registers_with_v2_description_and_parameters():
    service = FakeCalendarService()
    tool = _make_calendar_tool(service, CalendarPreferences())
    assert tool.name == "calendar"
    assert "delete" in tool.description.lower() or "destructive" in tool.description.lower()
    props = tool.parameters["properties"]
    assert "request" in props
    assert "chat_id" in props


def test_e2e_delete_confirmation_round_trip_via_tool():
    target = _event("evt_42", "4 PM standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    tool = _make_calendar_tool(service, CalendarPreferences())

    first = _exec_tool(tool, {"request": "delete the 4 PM standup", "chat_id": "chat_e2e"})
    payload = json.loads(first.content)
    assert payload["status"] == "confirmation_required"
    assert service.delete_calls == []

    second = _exec_tool(tool, {"request": "yes", "chat_id": "chat_e2e"})
    confirmed = json.loads(second.content)
    assert confirmed["status"] == "deleted"
    assert len(service.delete_calls) == 1
    assert service.delete_calls[0].event_id == "evt_42"


def test_e2e_move_confirmation_round_trip_via_tool():
    target = _event("evt_77", "call", "2026-05-06T17:00:00+05:30", "2026-05-06T18:00:00+05:30")
    service = FakeCalendarService(search_results=[target])
    tool = _make_calendar_tool(service, CalendarPreferences())

    first = _exec_tool(
        tool, {"request": "move tomorrow's call to Friday at 5 pm", "chat_id": "c"}
    )
    assert json.loads(first.content)["status"] == "confirmation_required"

    second = _exec_tool(tool, {"request": "yes", "chat_id": "c"})
    confirmed = json.loads(second.content)
    assert confirmed["status"] == "updated"
    assert len(service.update_calls) == 1


def test_e2e_quick_add_executes_immediately_no_confirmation():
    service = FakeCalendarService()
    tool = _make_calendar_tool(service, CalendarPreferences())
    out = _exec_tool(
        tool,
        {"request": "quick add: lunch with Aman thursday 1pm", "chat_id": "c"},
    )
    payload = json.loads(out.content)
    assert payload["status"] == "created"
    assert len(service.quick_add_calls) == 1


def test_e2e_rsvp_executes_immediately():
    target = _event("evt_88", "Budget review", "2026-05-08T15:00:00+05:30", "2026-05-08T16:00:00+05:30")
    service = FakeCalendarService(search_results=[target])
    tool = _make_calendar_tool(service, CalendarPreferences())
    out = _exec_tool(tool, {"request": "RSVP yes to budget review", "chat_id": "c"})
    payload = json.loads(out.content)
    assert payload["status"] == "rsvp_recorded"
    assert len(service.rsvp_calls) == 1
    assert service.rsvp_calls[0].response == "accepted"


def test_e2e_negation_aborts_pending_action():
    target = _event("evt_99", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    tool = _make_calendar_tool(service, CalendarPreferences())

    _exec_tool(tool, {"request": "delete the standup", "chat_id": "c"})
    cancel = _exec_tool(tool, {"request": "cancel", "chat_id": "c"})
    payload = json.loads(cancel.content)
    assert payload["status"] == "answered"
    assert "cancelled" in payload["user_message"].lower()
    assert service.delete_calls == []


def test_e2e_confirmation_isolation_between_chat_ids():
    target = _event("evt_a", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    tool = _make_calendar_tool(service, CalendarPreferences())

    _exec_tool(tool, {"request": "delete the standup", "chat_id": "alice"})
    other = _exec_tool(tool, {"request": "yes", "chat_id": "bob"})
    payload = json.loads(other.content)
    assert payload["status"] == "answered"
    assert "no pending" in payload["user_message"].lower()
    assert service.delete_calls == []


def test_e2e_calendar_tool_reports_disconnected_when_runtime_returns_none():
    """When mcp.builtin_servers.calendar is missing, the tool returns a clear error."""
    from sci_fi_dashboard.tool_registry import ToolContext, _calendar_factory

    ctx = ToolContext(
        chat_id="x", sender_id="x", sender_is_owner=True,
        workspace_dir=".", config={}, channel_id="api",
    )
    with patch(
        "sci_fi_dashboard.tool_registry._get_calendar_runtime",
        return_value=(None, CalendarPreferences()),
    ):
        tool = _calendar_factory(ctx)

    import asyncio

    with patch(
        "sci_fi_dashboard.tool_registry._get_calendar_runtime",
        return_value=(None, CalendarPreferences()),
    ):
        result = asyncio.run(tool.execute({"request": "am I free tomorrow?", "chat_id": "x"}))

    assert result.is_error is True
    assert "Calendar not connected" in result.content
