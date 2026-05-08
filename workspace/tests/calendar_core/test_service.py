from unittest.mock import MagicMock

from sci_fi_dashboard.calendar_core.models import (
    CalendarPreferences,
    CreateEventRequest,
    DeleteEventRequest,
    FreeBusyRequest,
    MoveEventRequest,
    QuickAddRequest,
    RecurrenceRule,
    RsvpRequest,
    UpdateEventRequest,
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


def test_list_calendars_normalizes_response():
    svc = MagicMock()
    svc.calendarList().list().execute.return_value = {
        "items": [
            {
                "id": "primary",
                "summary": "Personal",
                "primary": True,
                "timeZone": "Asia/Calcutta",
                "accessRole": "owner",
                "backgroundColor": "#fff",
                "foregroundColor": "#000",
                "selected": True,
            },
            {
                "id": "team@group.calendar.google.com",
                "summary": "Team",
                "accessRole": "reader",
            },
        ]
    }
    calendar = GoogleCalendarService(svc)

    entries = calendar.list_calendars()

    assert len(entries) == 2
    assert entries[0].id == "primary"
    assert entries[0].primary is True
    assert entries[0].access_role == "owner"
    assert entries[0].time_zone == "Asia/Calcutta"
    assert entries[1].id == "team@group.calendar.google.com"
    assert entries[1].primary is False
    assert entries[1].access_role == "reader"


def test_get_event_returns_calendar_event_with_v2_fields():
    svc = MagicMock()
    svc.events().get().execute.return_value = {
        "id": "evt_42",
        "summary": "Sync",
        "status": "confirmed",
        "recurringEventId": "master_42",
        "htmlLink": "https://calendar/event/42",
        "start": {"dateTime": "2026-05-08T10:00:00+05:30"},
        "end": {"dateTime": "2026-05-08T10:30:00+05:30"},
        "organizer": {"email": "boss@example.com"},
        "attendees": [
            {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "other@example.com", "responseStatus": "needsAction"},
        ],
    }
    calendar = GoogleCalendarService(svc)

    event = calendar.get_event("evt_42", calendar_id="primary")

    assert event.id == "evt_42"
    assert event.recurring_event_id == "master_42"
    assert event.organizer_email == "boss@example.com"
    assert event.self_response_status == "accepted"
    assert event.status == "confirmed"
    call = svc.events().get.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["eventId"] == "evt_42"


def test_update_event_scope_all_patches_master():
    svc = MagicMock()
    svc.events().patch().execute.return_value = {
        "id": "master_1",
        "summary": "Renamed",
        "htmlLink": "https://calendar/master_1",
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.update_event(
        UpdateEventRequest(
            event_id="master_1",
            title="Renamed",
            modification_scope="all",
        )
    )

    call = svc.events().patch.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["eventId"] == "master_1"
    assert call["body"] == {"summary": "Renamed"}
    assert "sendUpdates" not in call
    assert result.status == "updated"
    assert result.data["modification_scope"] == "all"
    assert "title" in result.data["changed_fields"]


def test_update_event_this_event_only_with_explicit_instance():
    svc = MagicMock()
    svc.events().patch().execute.return_value = {
        "id": "master_1_20260601T090000Z",
        "summary": "Edited",
        "htmlLink": "",
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.update_event(
        UpdateEventRequest(
            event_id="master_1",
            title="Edited",
            modification_scope="thisEventOnly",
            instance_id="master_1_20260601T090000Z",
        )
    )

    call = svc.events().patch.call_args.kwargs
    assert call["eventId"] == "master_1_20260601T090000Z"
    assert result.status == "updated"


def test_update_event_this_event_only_resolves_instance_when_id_missing():
    svc = MagicMock()
    svc.events().patch().execute.return_value = {
        "id": "resolved_inst",
        "summary": "Edited",
    }
    calendar = GoogleCalendarService(svc)
    calendar._resolve_instance_id = MagicMock(return_value="resolved_inst")

    calendar.update_event(
        UpdateEventRequest(
            event_id="master_1",
            title="Edited",
            start="2026-06-01T09:00:00+05:30",
            end="2026-06-01T10:00:00+05:30",
            modification_scope="thisEventOnly",
        )
    )

    calendar._resolve_instance_id.assert_called_once_with(
        "master_1", "primary", "2026-06-01T09:00:00+05:30"
    )
    call = svc.events().patch.call_args.kwargs
    assert call["eventId"] == "resolved_inst"


def test_update_event_this_and_following_without_recurrence_returns_failed():
    svc = MagicMock()
    calendar = GoogleCalendarService(svc)

    result = calendar.update_event(
        UpdateEventRequest(
            event_id="master_1",
            title="Series rename",
            modification_scope="thisAndFollowing",
        )
    )

    assert result.status == "failed"
    assert "thisAndFollowing requires explicit recurrence cutoff" in result.user_message
    assert result.data["modification_scope"] == "thisAndFollowing"


def test_update_event_passes_send_updates_all():
    svc = MagicMock()
    svc.events().patch().execute.return_value = {"id": "evt_9", "summary": "Edited"}
    calendar = GoogleCalendarService(svc)

    calendar.update_event(
        UpdateEventRequest(
            event_id="evt_9",
            title="Edited",
            modification_scope="all",
            send_updates="all",
        )
    )

    call = svc.events().patch.call_args.kwargs
    assert call["sendUpdates"] == "all"


def test_delete_event_non_recurring_calls_master_delete():
    svc = MagicMock()
    svc.events().delete().execute.return_value = None
    calendar = GoogleCalendarService(svc)

    result = calendar.delete_event(
        DeleteEventRequest(event_id="evt_solo", modification_scope="all")
    )

    call = svc.events().delete.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["eventId"] == "evt_solo"
    assert "sendUpdates" not in call
    assert result.status == "deleted"
    assert result.data["modification_scope"] == "all"


def test_delete_event_this_event_only_deletes_resolved_instance():
    svc = MagicMock()
    svc.events().delete().execute.return_value = None
    calendar = GoogleCalendarService(svc)
    calendar._resolve_instance_id = MagicMock(return_value="inst_xyz")

    calendar.delete_event(
        DeleteEventRequest(
            event_id="master_1",
            modification_scope="thisEventOnly",
            send_updates="externalOnly",
        )
    )

    calendar._resolve_instance_id.assert_called_once_with("master_1", "primary", None)
    call = svc.events().delete.call_args.kwargs
    assert call["eventId"] == "inst_xyz"
    assert call["sendUpdates"] == "externalOnly"


def test_move_event_calls_events_move_with_destination_and_send_updates():
    svc = MagicMock()
    svc.events().move().execute.return_value = {
        "id": "evt_m",
        "htmlLink": "https://calendar/move",
        "summary": "Moved",
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.move_event(
        MoveEventRequest(
            event_id="evt_m",
            source_calendar_id="primary",
            destination_calendar_id="team@group.calendar.google.com",
            send_updates="all",
        )
    )

    call = svc.events().move.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["eventId"] == "evt_m"
    assert call["destination"] == "team@group.calendar.google.com"
    assert call["sendUpdates"] == "all"
    assert result.status == "moved"


def test_respond_to_event_patches_attendees_with_self_response():
    svc = MagicMock()
    svc.events().get().execute.return_value = {
        "id": "evt_rsvp",
        "summary": "Lunch",
        "attendees": [
            {"email": "boss@example.com", "responseStatus": "accepted"},
            {"email": "me@example.com", "self": True, "responseStatus": "needsAction"},
        ],
    }
    svc.events().patch().execute.return_value = {"id": "evt_rsvp", "summary": "Lunch"}
    calendar = GoogleCalendarService(svc)

    result = calendar.respond_to_event(
        RsvpRequest(
            event_id="evt_rsvp",
            response="accepted",
            attendee_email="me@example.com",
        )
    )

    body = svc.events().patch.call_args.kwargs["body"]
    matched = [a for a in body["attendees"] if a.get("email") == "me@example.com"]
    assert matched and matched[0]["responseStatus"] == "accepted"
    assert result.status == "rsvp_recorded"
    assert result.data["attendee_email"] == "me@example.com"


def test_respond_to_event_auto_detects_self_attendee_when_email_missing():
    svc = MagicMock()
    svc.events().get().execute.return_value = {
        "id": "evt_rsvp",
        "summary": "Lunch",
        "attendees": [
            {"email": "boss@example.com", "responseStatus": "accepted"},
            {"email": "self@example.com", "self": True, "responseStatus": "needsAction"},
        ],
    }
    svc.events().patch().execute.return_value = {"id": "evt_rsvp", "summary": "Lunch"}
    calendar = GoogleCalendarService(svc)

    result = calendar.respond_to_event(
        RsvpRequest(event_id="evt_rsvp", response="declined")
    )

    body = svc.events().patch.call_args.kwargs["body"]
    matched = [a for a in body["attendees"] if a.get("email") == "self@example.com"]
    assert matched and matched[0]["responseStatus"] == "declined"
    assert result.data["attendee_email"] == "self@example.com"


def test_freebusy_single_call_returns_windows_per_calendar():
    svc = MagicMock()
    svc.freebusy().query().execute.return_value = {
        "timeMin": "2026-05-08T00:00:00Z",
        "timeMax": "2026-05-09T00:00:00Z",
        "calendars": {
            "primary": {
                "busy": [
                    {"start": "2026-05-08T09:00:00Z", "end": "2026-05-08T10:00:00Z"}
                ]
            },
            "team@group.calendar.google.com": {"busy": []},
        },
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.freebusy(
        FreeBusyRequest(
            start="2026-05-08T00:00:00Z",
            end="2026-05-09T00:00:00Z",
            calendar_ids=["primary", "team@group.calendar.google.com"],
        )
    )

    body = svc.freebusy().query.call_args.kwargs["body"]
    assert body["items"] == [
        {"id": "primary"},
        {"id": "team@group.calendar.google.com"},
    ]
    assert len(result.calendars["primary"]) == 1
    assert result.calendars["primary"][0].start == "2026-05-08T09:00:00Z"
    assert result.calendars["team@group.calendar.google.com"] == []


def test_freebusy_preserves_per_calendar_errors():
    svc = MagicMock()
    svc.freebusy().query().execute.return_value = {
        "calendars": {
            "primary": {"busy": []},
            "broken@example.com": {
                "errors": [{"reason": "notFound", "domain": "global"}]
            },
        }
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.freebusy(
        FreeBusyRequest(
            start="2026-05-08T00:00:00Z",
            end="2026-05-09T00:00:00Z",
            calendar_ids=["primary", "broken@example.com"],
        )
    )

    assert result.errors == {"broken@example.com": "notFound"}
    assert result.calendars["broken@example.com"] == []


def test_quick_add_returns_created_with_event_id():
    svc = MagicMock()
    svc.events().quickAdd().execute.return_value = {
        "id": "evt_quick",
        "summary": "Dentist",
        "htmlLink": "https://calendar/quick",
        "start": {"dateTime": "2026-05-09T15:00:00+05:30"},
        "end": {"dateTime": "2026-05-09T16:00:00+05:30"},
    }
    calendar = GoogleCalendarService(svc)

    result = calendar.quick_add(
        QuickAddRequest(text="Dentist tomorrow at 3pm", send_updates="all")
    )

    call = svc.events().quickAdd.call_args.kwargs
    assert call["calendarId"] == "primary"
    assert call["text"] == "Dentist tomorrow at 3pm"
    assert call["sendUpdates"] == "all"
    assert result.status == "created"
    assert result.data["event_id"] == "evt_quick"


def test_list_colors_splits_event_and_calendar_palette():
    svc = MagicMock()
    svc.colors().get().execute.return_value = {
        "updated": "2026-05-01T00:00:00Z",
        "event": {"1": {"background": "#a4bdfc", "foreground": "#1d1d1d"}},
        "calendar": {"1": {"background": "#ac725e", "foreground": "#1d1d1d"}},
    }
    calendar = GoogleCalendarService(svc)

    palette = calendar.list_colors()

    assert palette.updated == "2026-05-01T00:00:00Z"
    assert palette.event_colors["1"]["background"] == "#a4bdfc"
    assert palette.calendar_colors["1"]["background"] == "#ac725e"
