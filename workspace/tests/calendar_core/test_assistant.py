from __future__ import annotations

from datetime import datetime, timezone

import sci_fi_dashboard.calendar_core.assistant as assistant_module
from sci_fi_dashboard.calendar_core.assistant import handle_calendar_request
from sci_fi_dashboard.calendar_core.confirmations import PendingActionStore
from sci_fi_dashboard.calendar_core.models import (
    CalendarActionResult,
    CalendarConflict,
    CalendarEvent,
    CalendarPreferences,
    DeleteEventRequest,
    FreeBusyResult,
    FreeBusyWindow,
    QuickAddRequest,
    RsvpRequest,
    UpdateEventRequest,
)


NOW = datetime(2026, 5, 5, 9, 0, tzinfo=timezone.utc)


class FakeCalendarService:
    def __init__(
        self,
        conflicts: list[CalendarConflict] | None = None,
        *,
        search_results: list[CalendarEvent] | None = None,
        freebusy_result: FreeBusyResult | None = None,
    ) -> None:
        self.conflicts = conflicts or []
        self.search_results = search_results or []
        self.freebusy_result = freebusy_result or FreeBusyResult()
        self.created_requests = []
        self.create_calls = []
        self.conflict_calls = []
        self.list_calls = []
        self.slot_calls = []
        self.holiday_calls = []
        self.delete_calls: list[DeleteEventRequest] = []
        self.update_calls: list[UpdateEventRequest] = []
        self.move_calls = []
        self.rsvp_calls: list[RsvpRequest] = []
        self.quick_add_calls: list[QuickAddRequest] = []
        self.freebusy_calls = []

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
        return list(self.search_results)

    def delete_event(self, request):
        self.delete_calls.append(request)
        return CalendarActionResult.deleted(
            event_id=request.event_id,
            title="(deleted)",
            modification_scope=request.modification_scope,
        )

    def update_event(self, request):
        self.update_calls.append(request)
        return CalendarActionResult.updated(
            event_id=request.event_id,
            link="https://calendar/event",
            title=request.title or "(untitled)",
            modification_scope=request.modification_scope,
            changed_fields=[
                name
                for name in ("title", "start", "end", "description")
                if getattr(request, name, None) is not None
            ],
        )

    def move_event(self, request):
        self.move_calls.append(request)
        return CalendarActionResult.moved(
            event_id=request.event_id,
            link="https://calendar/event",
            title="(moved)",
            source_calendar_id=request.source_calendar_id,
            destination_calendar_id=request.destination_calendar_id,
        )

    def respond_to_event(self, request):
        self.rsvp_calls.append(request)
        return CalendarActionResult.rsvp_recorded(
            event_id=request.event_id,
            title="(rsvp)",
            response=request.response,
            attendee_email=request.attendee_email or "me@example.com",
        )

    def quick_add(self, request):
        self.quick_add_calls.append(request)
        return CalendarActionResult.created(
            event_id="evt_qa",
            link="https://calendar/event/qa",
            title=request.text,
            start="2026-05-08T13:00:00+05:30",
            end="2026-05-08T14:00:00+05:30",
        )

    def freebusy(self, request):
        self.freebusy_calls.append(request)
        return self.freebusy_result

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


# ---------------------------------------------------------------------------
# V2 confirmation flow + new intents
# ---------------------------------------------------------------------------


def _event(event_id: str, title: str, start: str, end: str, **kwargs) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        title=title,
        start=start,
        end=end,
        calendar_id=kwargs.get("calendar_id", "primary"),
        attendees=kwargs.get("attendees", []),
        recurring_event_id=kwargs.get("recurring_event_id"),
        organizer_email=kwargs.get("organizer_email", ""),
        self_response_status=kwargs.get("self_response_status", ""),
        status=kwargs.get("status", "confirmed"),
    )


def test_delete_event_parks_pending_action_and_does_not_call_service():
    service = FakeCalendarService(
        search_results=[_event("evt_1", "4 PM standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")]
    )
    store = PendingActionStore()
    result = handle_calendar_request(
        "delete the 4 PM standup",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=store,
    )

    assert result.status == "confirmation_required"
    assert service.delete_calls == []
    assert store.peek("chat_1") is not None


def test_affirmation_after_delete_parking_executes_delete():
    target = _event("evt_1", "4 PM standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    store = PendingActionStore()

    handle_calendar_request(
        "delete the 4 PM standup",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=store,
    )
    confirm = handle_calendar_request(
        "yes",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=store,
    )

    assert confirm.status == "deleted"
    assert len(service.delete_calls) == 1
    assert service.delete_calls[0].event_id == "evt_1"
    assert store.peek("chat_1") is None


def test_negation_cancels_pending_action_without_service_call():
    target = _event("evt_1", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    store = PendingActionStore()
    handle_calendar_request(
        "delete the standup",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=store,
    )

    cancel = handle_calendar_request(
        "cancel",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=store,
    )

    assert cancel.status == "answered"
    assert "cancelled" in cancel.user_message.lower()
    assert service.delete_calls == []
    assert store.peek("chat_1") is None


def test_delete_with_no_match_returns_answered_no_match():
    service = FakeCalendarService(search_results=[])
    result = handle_calendar_request(
        "delete the 4 PM standup",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "answered"
    assert "could not find" in result.user_message.lower()
    assert service.delete_calls == []


def test_delete_with_multiple_matches_asks_for_disambiguation():
    matches = [
        _event("evt_1", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30"),
        _event("evt_2", "standup", "2026-05-07T16:00:00+05:30", "2026-05-07T16:30:00+05:30"),
    ]
    service = FakeCalendarService(search_results=matches)
    result = handle_calendar_request(
        "delete the standup",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "confirmation_required"
    assert "ambiguous_target" in (result.confirmation.reasons if result.confirmation else [])
    assert len(result.data["candidates"]) == 2
    assert service.delete_calls == []


def test_move_event_parks_pending_with_new_time():
    target = _event("evt_1", "call", "2026-05-06T17:00:00+05:30", "2026-05-06T18:00:00+05:30")
    service = FakeCalendarService(search_results=[target])
    store = PendingActionStore()
    result = handle_calendar_request(
        "move tomorrow's call to Friday at 5 pm",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=store,
    )
    assert result.status == "confirmation_required"

    confirm = handle_calendar_request(
        "yes",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=store,
    )
    assert confirm.status == "updated"
    assert len(service.update_calls) == 1
    assert service.update_calls[0].start.startswith("2026-05-08T17:00:00")


def test_rsvp_calls_service_directly_without_confirmation():
    target = _event("evt_1", "Budget review", "2026-05-08T15:00:00+05:30", "2026-05-08T16:00:00+05:30")
    service = FakeCalendarService(search_results=[target])
    result = handle_calendar_request(
        "RSVP yes to budget review",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "rsvp_recorded"
    assert len(service.rsvp_calls) == 1
    assert service.rsvp_calls[0].response == "accepted"


def test_quick_add_routes_to_service_quick_add():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "quick add: lunch with Aman thursday 1pm",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "created"
    assert len(service.quick_add_calls) == 1
    assert service.quick_add_calls[0].text == "lunch with Aman thursday 1pm"


def test_freebusy_intent_calls_freebusy_with_default_calendar():
    fb_result = FreeBusyResult(
        calendars={"primary": [FreeBusyWindow(start="2026-05-08T14:00:00+05:30", end="2026-05-08T15:00:00+05:30")]},
        time_min="2026-05-08T12:00:00+05:30",
        time_max="2026-05-08T17:00:00+05:30",
    )
    service = FakeCalendarService(freebusy_result=fb_result)
    result = handle_calendar_request(
        "Am I free Friday afternoon across both calendars?",
        service,
        CalendarPreferences(),
        now=NOW,
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "answered"
    assert len(service.freebusy_calls) == 1
    assert "1 busy window" in result.user_message


def test_affirmation_when_no_pending_action_is_polite():
    service = FakeCalendarService()
    result = handle_calendar_request(
        "yes",
        service,
        CalendarPreferences(),
        chat_id="chat_1",
        pending_store=PendingActionStore(),
    )
    assert result.status == "answered"
    assert "no pending" in result.user_message.lower()
    assert service.delete_calls == [] and service.update_calls == []


def test_pending_action_isolation_per_chat_id():
    target = _event("evt_1", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    store = PendingActionStore()
    handle_calendar_request(
        "delete the standup",
        service,
        CalendarPreferences(),
        chat_id="chat_a",
        pending_store=store,
    )
    confirm_other = handle_calendar_request(
        "yes",
        service,
        CalendarPreferences(),
        chat_id="chat_b",
        pending_store=store,
    )
    assert confirm_other.status == "answered"
    assert service.delete_calls == []
    assert store.peek("chat_a") is not None


def test_delete_without_chat_id_still_returns_confirmation_without_parking():
    target = _event("evt_1", "standup", "2026-05-06T16:00:00+05:30", "2026-05-06T16:30:00+05:30")
    service = FakeCalendarService(search_results=[target])
    store = PendingActionStore()
    result = handle_calendar_request(
        "delete the standup",
        service,
        CalendarPreferences(),
        chat_id=None,
        pending_store=store,
    )
    assert result.status == "confirmation_required"
    assert len(store) == 0
    assert service.delete_calls == []
