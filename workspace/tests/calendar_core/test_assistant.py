from __future__ import annotations

from datetime import datetime, timezone

import sci_fi_dashboard.calendar_core.assistant as assistant_module
from sci_fi_dashboard.calendar_core.assistant import handle_calendar_request
from sci_fi_dashboard.calendar_core.models import (
    CalendarActionResult,
    CalendarConflict,
    CalendarPreferences,
)


NOW = datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)


class FakeCalendarService:
    def __init__(self, conflicts: list[CalendarConflict] | None = None) -> None:
        self.conflicts = conflicts or []
        self.created_requests = []
        self.create_calls = []
        self.conflict_calls = []
        self.list_calls = []
        self.slot_calls = []
        self.holiday_calls = []

    def check_conflicts(self, start: str, end: str, calendar_id: str = "primary"):
        self.conflict_calls.append((start, end, calendar_id))
        return list(self.conflicts)

    def create_event(self, request, calendar_id: str = "primary"):
        self.created_requests.append(request)
        self.create_calls.append((request, calendar_id))
        return CalendarActionResult.created(
            event_id="evt_1",
            link="https://calendar.google.com/event?id=evt_1",
            title=request.title,
            start=request.start,
            end=request.end,
        )

    def suggest_free_slots(
        self,
        day_start: str,
        day_end: str,
        duration_minutes: int,
        calendar_id: str = "primary",
    ):
        self.slot_calls.append((day_start, day_end, duration_minutes, calendar_id))
        return [{"start": day_start, "end": day_end, "duration_minutes": duration_minutes}]

    def list_events(self, start: str, end: str, calendar_id: str = "primary", query=None):
        self.list_calls.append((start, end, calendar_id, query))
        return []

    def search_events(self, query: str, start: str, end: str, calendar_id: str = "primary"):
        self.list_calls.append((start, end, calendar_id, query))
        return []

    def find_holidays(self, name_or_range: str, preferences: CalendarPreferences):
        self.holiday_calls.append((name_or_range, preferences))
        return CalendarActionResult(
            status="answered",
            user_message="Found holiday information.",
            data={"query": name_or_range},
        )


def test_handle_create_checks_policy_then_creates_when_allowed():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "Add gym every day at 7 PM starting tomorrow",
        service,
        CalendarPreferences(),
        now=NOW,
    )

    assert result.status == "created"
    assert len(service.created_requests) == 1
    assert service.created_requests[0].title == "gym"
    assert service.created_requests[0].recurrence.frequency == "daily"


def test_handle_create_uses_default_calendar_id_without_non_default_confirmation():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "Add gym tomorrow at 7 PM",
        service,
        CalendarPreferences(default_calendar_id="work"),
        now=NOW,
    )

    assert result.status == "created"
    assert service.conflict_calls == [("2026-05-06T19:00:00+05:30", "2026-05-06T20:00:00+05:30", "work")]
    assert len(service.create_calls) == 1
    request, calendar_id = service.create_calls[0]
    assert request.calendar_id == "work"
    assert calendar_id == "work"


def test_handle_create_uses_preferences_timezone_for_base_date():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "Add gym tomorrow at 7 PM",
        service,
        CalendarPreferences(timezone="Asia/Calcutta"),
        now=datetime(2026, 5, 5, 20, 0, tzinfo=timezone.utc),
    )

    assert result.status == "created"
    request = service.created_requests[0]
    assert request.start == "2026-05-07T19:00:00+05:30"
    assert request.end == "2026-05-07T20:00:00+05:30"


def test_base_date_falls_back_to_fixed_offset_for_india_aliases(monkeypatch):
    def missing_zoneinfo(name: str):
        raise assistant_module.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(assistant_module, "ZoneInfo", missing_zoneinfo)
    now = datetime(2026, 5, 5, 20, 0, tzinfo=timezone.utc)

    assert assistant_module._base_date(now, "Asia/Calcutta").isoformat() == "2026-05-06"
    assert assistant_module._base_date(now, "Asia/Kolkata").isoformat() == "2026-05-06"


def test_handle_create_requires_confirmation_on_conflict_without_creating():
    service = FakeCalendarService(
        [CalendarConflict(title="Standup", start="2026-05-06T19:00:00+05:30", end="2026-05-06T19:30:00+05:30")]
    )
    result = handle_calendar_request(
        "Add gym every day at 7 PM starting tomorrow",
        service,
        CalendarPreferences(),
        now=NOW,
    )

    assert result.status == "confirmation_required"
    assert "conflict" in result.user_message.lower()
    assert service.created_requests == []


def test_handle_availability_uses_default_calendar_id():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "Am I free Friday afternoon?",
        service,
        CalendarPreferences(default_calendar_id="work"),
        now=NOW,
    )

    assert result.status == "answered"
    assert service.conflict_calls == [("2026-05-08T12:00:00+05:30", "2026-05-08T17:00:00+05:30", "work")]
    assert service.slot_calls == [("2026-05-08T12:00:00+05:30", "2026-05-08T17:00:00+05:30", 60, "work")]


def test_handle_availability_calls_free_slot_suggestion():
    service = FakeCalendarService()
    result = handle_calendar_request("Am I free Friday afternoon?", service, CalendarPreferences(), now=NOW)

    assert result.status == "answered"
    assert service.conflict_calls == [("2026-05-08T12:00:00+05:30", "2026-05-08T17:00:00+05:30", "primary")]
    assert service.slot_calls == [("2026-05-08T12:00:00+05:30", "2026-05-08T17:00:00+05:30", 60, "primary")]
    assert service.created_requests == []
    assert result.data["conflicts"] == []


def test_handle_availability_reports_conflicts_with_free_slot_suggestion():
    service = FakeCalendarService(
        [CalendarConflict(title="Review", start="2026-05-08T14:00:00+05:30", end="2026-05-08T14:30:00+05:30")]
    )
    result = handle_calendar_request("Am I free Friday afternoon?", service, CalendarPreferences(), now=NOW)

    assert result.status == "answered"
    assert "conflict" in result.user_message.lower()
    assert result.data["conflicts"] == [
        {
            "title": "Review",
            "start": "2026-05-08T14:00:00+05:30",
            "end": "2026-05-08T14:30:00+05:30",
            "event_id": None,
            "link": "",
        }
    ]


def test_handle_holiday_delegates_to_service():
    service = FakeCalendarService()
    result = handle_calendar_request("When is Independence Day holiday?", service, CalendarPreferences(), now=NOW)

    assert result.status == "answered"
    assert service.holiday_calls
    assert "Independence Day" in service.holiday_calls[0][0]


def test_handle_unknown_returns_safe_failure_without_service_calls():
    service = FakeCalendarService()
    result = handle_calendar_request("calendar thingy", service, CalendarPreferences(), now=NOW)

    assert result.status in {"answered", "failed"}
    assert "clearer" in result.user_message.lower()
    assert service.created_requests == []
    assert service.slot_calls == []
    assert service.holiday_calls == []
