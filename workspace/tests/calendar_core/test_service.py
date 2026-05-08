from unittest.mock import MagicMock

from sci_fi_dashboard.calendar_core.models import (
    CalendarPreferences,
    CreateEventRequest,
    RecurrenceRule,
)
from sci_fi_dashboard.calendar_core.service import GoogleCalendarService


def test_list_events_returns_normalized_calendar_events():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "evt_1",
                "summary": "Standup",
                "description": "Daily sync",
                "htmlLink": "https://calendar/event/1",
                "start": {"dateTime": "2026-05-06T09:00:00+05:30"},
                "end": {"dateTime": "2026-05-06T09:30:00+05:30"},
                "attendees": [{"email": "a@example.com"}],
            }
        ]
    }
    calendar = GoogleCalendarService(svc)

    events = calendar.list_events(
        "2026-05-06T00:00:00+05:30",
        "2026-05-07T00:00:00+05:30",
        query="standup",
    )

    assert events[0].id == "evt_1"
    assert events[0].title == "Standup"
    assert events[0].start == "2026-05-06T09:00:00+05:30"
    assert events[0].end == "2026-05-06T09:30:00+05:30"
    assert events[0].attendees == ["a@example.com"]
    call = svc.events().list.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["q"] == "standup"


def test_search_events_delegates_to_list_with_query():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "evt_2",
                "summary": "Gym",
                "start": {"dateTime": "2026-05-06T19:00:00+05:30"},
                "end": {"dateTime": "2026-05-06T20:00:00+05:30"},
            }
        ]
    }
    calendar = GoogleCalendarService(svc)

    events = calendar.search_events(
        "gym",
        "2026-05-06T00:00:00+05:30",
        "2026-05-07T00:00:00+05:30",
    )

    assert [event.title for event in events] == ["Gym"]
    assert svc.events().list.call_args.kwargs["q"] == "gym"


def test_create_recurring_event_writes_google_rrule():
    svc = MagicMock()
    svc.events().insert().execute.return_value = {
        "id": "evt_1",
        "htmlLink": "https://calendar/event",
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.create_event(
        CreateEventRequest(
            title="Gym",
            start="2026-05-06T19:00:00+05:30",
            end="2026-05-06T20:00:00+05:30",
            recurrence=RecurrenceRule("daily"),
        )
    )

    body = svc.events().insert.call_args.kwargs["body"]
    assert body["recurrence"] == ["RRULE:FREQ=DAILY"]
    assert body["start"] == {"dateTime": "2026-05-06T19:00:00+05:30"}
    assert body["end"] == {"dateTime": "2026-05-06T20:00:00+05:30"}
    assert result.status == "created"
    assert result.data["event_id"] == "evt_1"


def test_create_all_day_event_uses_date_fields():
    svc = MagicMock()
    svc.events().insert().execute.return_value = {"id": "evt_3", "htmlLink": ""}
    calendar = GoogleCalendarService(svc)

    calendar.create_event(
        CreateEventRequest(
            title="Arjun birthday",
            start="2026-07-12",
            end="2026-07-13",
            all_day=True,
        )
    )

    body = svc.events().insert.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-07-12"}
    assert body["end"] == {"date": "2026-07-13"}


def test_check_conflicts_returns_overlapping_events():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "busy",
                "summary": "Standup",
                "htmlLink": "https://calendar/busy",
                "start": {"dateTime": "2026-05-06T19:15:00+05:30"},
                "end": {"dateTime": "2026-05-06T19:45:00+05:30"},
            },
            {
                "id": "free",
                "summary": "Later",
                "start": {"dateTime": "2026-05-06T21:00:00+05:30"},
                "end": {"dateTime": "2026-05-06T22:00:00+05:30"},
            },
        ]
    }
    calendar = GoogleCalendarService(svc)

    conflicts = calendar.check_conflicts(
        "2026-05-06T19:00:00+05:30",
        "2026-05-06T20:00:00+05:30",
    )

    assert len(conflicts) == 1
    assert conflicts[0].event_id == "busy"
    assert conflicts[0].title == "Standup"


def test_check_conflicts_treats_all_day_event_as_busy_for_aware_request():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "all_day",
                "summary": "Focus day",
                "start": {"date": "2026-05-06"},
                "end": {"date": "2026-05-07"},
            }
        ]
    }
    calendar = GoogleCalendarService(svc)

    conflicts = calendar.check_conflicts(
        "2026-05-06T09:00:00+05:30",
        "2026-05-06T10:00:00+05:30",
    )

    assert len(conflicts) == 1
    assert conflicts[0].event_id == "all_day"


def test_suggest_free_slots_returns_slots_around_busy_events():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "busy_1",
                "summary": "Call",
                "start": {"dateTime": "2026-05-06T10:00:00+05:30"},
                "end": {"dateTime": "2026-05-06T10:30:00+05:30"},
            },
            {
                "id": "busy_2",
                "summary": "Lunch",
                "start": {"dateTime": "2026-05-06T12:00:00+05:30"},
                "end": {"dateTime": "2026-05-06T13:00:00+05:30"},
            },
        ]
    }
    calendar = GoogleCalendarService(svc)

    slots = calendar.suggest_free_slots(
        "2026-05-06T09:00:00+05:30",
        "2026-05-06T14:00:00+05:30",
        30,
    )

    assert slots == [
        {
            "start": "2026-05-06T09:00:00+05:30",
            "end": "2026-05-06T10:00:00+05:30",
            "duration_minutes": 60,
        },
        {
            "start": "2026-05-06T10:30:00+05:30",
            "end": "2026-05-06T12:00:00+05:30",
            "duration_minutes": 90,
        },
        {
            "start": "2026-05-06T13:00:00+05:30",
            "end": "2026-05-06T14:00:00+05:30",
            "duration_minutes": 60,
        },
    ]


def test_suggest_free_slots_returns_none_when_all_day_event_covers_aware_window():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "all_day",
                "summary": "Focus day",
                "start": {"date": "2026-05-06"},
                "end": {"date": "2026-05-07"},
            }
        ]
    }
    calendar = GoogleCalendarService(svc)

    slots = calendar.suggest_free_slots(
        "2026-05-06T09:00:00+05:30",
        "2026-05-06T10:00:00+05:30",
        30,
    )

    assert slots == []


def test_find_holidays_prefers_personal_calendar_events():
    svc = MagicMock()
    svc.events().list().execute.return_value = {
        "items": [
            {
                "id": "holiday_1",
                "summary": "Diwali family day",
                "start": {"date": "2026-11-08"},
                "end": {"date": "2026-11-09"},
            }
        ]
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.find_holidays("Diwali 2026", CalendarPreferences())

    assert result.status == "answered"
    assert result.data["source"] == "personal_calendar"
    assert result.data["events"][0].title == "Diwali family day"
    assert svc.events().list.call_args.kwargs["q"] == "Diwali 2026"


def test_find_holidays_falls_back_to_labelled_in_placeholder():
    svc = MagicMock()
    svc.events().list().execute.return_value = {"items": []}
    calendar = GoogleCalendarService(svc)

    result = calendar.find_holidays("independence", CalendarPreferences(locale_country="IN"))

    assert result.status == "answered"
    assert result.data["source"] == "deterministic_locale_fallback"
    assert result.data["fallback"] is True
    assert result.data["holidays"] == [
        {"name": "Independence Day", "date": "2026-08-15", "country": "IN"}
    ]
    assert "fallback" in result.user_message.lower()
