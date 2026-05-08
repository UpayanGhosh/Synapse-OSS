from sci_fi_dashboard.calendar_core.models import (
    AvailabilityRequest,
    CalendarActionResult,
    CalendarConflict,
    CalendarPreferences,
    ConfirmationRequired,
    CreateEventRequest,
    DeleteEventRequest,
    FreeBusyRequest,
    MoveEventRequest,
    QuickAddRequest,
    RecurrenceRule,
    RsvpRequest,
    UpdateEventRequest,
)

import pytest


def test_preferences_default_to_trusted_quick_add_enabled():
    prefs = CalendarPreferences()
    assert prefs.default_calendar_id == "primary"
    assert prefs.timezone == "Asia/Calcutta"
    assert prefs.locale_country == "IN"
    assert prefs.trusted_quick_add is True
    assert prefs.default_event_duration_minutes == 60
    assert prefs.allow_open_ended_recurring_personal_events is True


def test_recurrence_rule_supports_google_rrules_and_summaries():
    cases = [
        ("daily", "RRULE:FREQ=DAILY", "every day"),
        ("weekly", "RRULE:FREQ=WEEKLY", "every week"),
        ("monthly", "RRULE:FREQ=MONTHLY", "every month"),
        ("yearly", "RRULE:FREQ=YEARLY", "every year"),
    ]
    for frequency, rrule, summary in cases:
        rule = RecurrenceRule(frequency=frequency)
        assert rule.to_google_rrule() == [rrule]
        assert rule.summary() == summary


def test_recurrence_rule_includes_optional_until_and_count():
    assert RecurrenceRule(frequency="weekly", until="20261231").to_google_rrule() == [
        "RRULE:FREQ=WEEKLY;UNTIL=20261231"
    ]
    assert RecurrenceRule(frequency="monthly", count=3).to_google_rrule() == [
        "RRULE:FREQ=MONTHLY;COUNT=3"
    ]


def test_recurrence_rule_rejects_invalid_values():
    with pytest.raises(ValueError, match="Unsupported recurrence frequency"):
        RecurrenceRule(frequency="hourly")
    with pytest.raises(ValueError, match="count"):
        RecurrenceRule(frequency="daily", count=0)
    with pytest.raises(ValueError, match="until and count"):
        RecurrenceRule(frequency="weekly", until="20261231", count=3)


def test_mutable_attendee_lists_are_isolated():
    first = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    second = CreateEventRequest(
        title="Call",
        start="2026-05-06T21:00:00+05:30",
        end="2026-05-06T22:00:00+05:30",
    )
    first.attendees.append("a@example.com")
    assert second.attendees == []


def test_create_event_request_validates_required_values():
    with pytest.raises(ValueError, match="title"):
        CreateEventRequest(title=" ", start="2026-05-06", end="2026-05-07")
    with pytest.raises(ValueError, match="start"):
        CreateEventRequest(title="Gym", start="", end="2026-05-07")
    with pytest.raises(ValueError, match="end"):
        CreateEventRequest(title="Gym", start="2026-05-06", end=" ")
    with pytest.raises(ValueError, match="parse_confidence"):
        CreateEventRequest(
            title="Gym",
            start="2026-05-06",
            end="2026-05-07",
            parse_confidence=1.1,
        )
    with pytest.raises(ValueError, match="end"):
        CreateEventRequest(title="Gym", start="2026-05-06", end="2026-05-06")
    with pytest.raises(ValueError, match="end"):
        CreateEventRequest(
            title="Gym",
            start="2026-05-06T20:00:00+05:30",
            end="2026-05-06T19:00:00+05:30",
        )
    with pytest.raises(ValueError, match="timezone"):
        CreateEventRequest(
            title="Gym",
            start="2026-05-06T19:00:00+05:30",
            end="2026-05-06T20:00:00",
        )
    with pytest.raises(ValueError, match="date.*datetime|datetime.*date"):
        CreateEventRequest(
            title="Gym",
            start="2026-05-06",
            end="2026-05-06T20:00:00+05:30",
        )


def test_availability_request_validates_required_values():
    with pytest.raises(ValueError, match="start"):
        AvailabilityRequest(start="", end="2026-05-07")
    with pytest.raises(ValueError, match="end"):
        AvailabilityRequest(start="2026-05-06", end=" ")
    with pytest.raises(ValueError, match="duration_minutes"):
        AvailabilityRequest(
            start="2026-05-06",
            end="2026-05-07",
            duration_minutes=0,
        )
    with pytest.raises(ValueError, match="end"):
        AvailabilityRequest(start="2026-05-07", end="2026-05-06")
    with pytest.raises(ValueError, match="date.*datetime|datetime.*date"):
        AvailabilityRequest(
            start="2026-05-06",
            end="2026-05-06T20:00:00+05:30",
        )


def test_action_result_receipt_includes_event_evidence():
    result = CalendarActionResult.created(
        event_id="evt_123",
        link="https://calendar.google.com/event?id=evt_123",
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    assert result.status == "created"
    assert "Gym" in result.user_message
    assert "evt_123" in result.receipt_evidence


# ---------------------------------------------------------------------------
# V2 model tests
# ---------------------------------------------------------------------------


def test_update_event_request_requires_at_least_one_change():
    with pytest.raises(ValueError, match="at least one field"):
        UpdateEventRequest(event_id="evt_1", calendar_id="primary")


def test_update_event_request_validates_modification_scope():
    with pytest.raises(ValueError, match="modification_scope"):
        UpdateEventRequest(
            event_id="evt_1",
            calendar_id="primary",
            title="New",
            modification_scope="bogus",  # type: ignore[arg-type]
        )


def test_update_event_request_accepts_valid_scopes_and_send_updates():
    for scope in ("thisEventOnly", "thisAndFollowing", "all"):
        UpdateEventRequest(
            event_id="evt_1",
            calendar_id="primary",
            title="New",
            modification_scope=scope,  # type: ignore[arg-type]
        )
    for su in ("all", "externalOnly", "none"):
        UpdateEventRequest(
            event_id="evt_1",
            calendar_id="primary",
            title="New",
            send_updates=su,  # type: ignore[arg-type]
        )


def test_update_event_request_rejects_blank_title_when_provided():
    with pytest.raises(ValueError, match="title"):
        UpdateEventRequest(event_id="evt_1", calendar_id="primary", title=" ")


def test_update_event_request_validates_ordered_range_when_both_provided():
    with pytest.raises(ValueError, match="end"):
        UpdateEventRequest(
            event_id="evt_1",
            start="2026-05-06T20:00:00+05:30",
            end="2026-05-06T19:00:00+05:30",
        )


def test_delete_event_request_requires_event_id_and_valid_scope():
    with pytest.raises(ValueError, match="event_id"):
        DeleteEventRequest(event_id=" ")
    with pytest.raises(ValueError, match="modification_scope"):
        DeleteEventRequest(
            event_id="evt_1",
            modification_scope="bogus",  # type: ignore[arg-type]
        )
    DeleteEventRequest(event_id="evt_1", modification_scope="all")


def test_move_event_request_rejects_same_source_and_destination():
    with pytest.raises(ValueError, match="source and destination"):
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id="primary",
        )


def test_move_event_request_validates_blank_calendars():
    with pytest.raises(ValueError, match="source_calendar_id"):
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id=" ",
            destination_calendar_id="other",
        )
    with pytest.raises(ValueError, match="destination_calendar_id"):
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id=" ",
        )


def test_rsvp_request_validates_response_value():
    with pytest.raises(ValueError, match="RSVP response"):
        RsvpRequest(event_id="evt_1", response="maybe")  # type: ignore[arg-type]
    for value in ("accepted", "declined", "tentative", "needsAction"):
        RsvpRequest(event_id="evt_1", response=value)  # type: ignore[arg-type]


def test_freebusy_request_requires_calendars_and_ordered_range():
    with pytest.raises(ValueError, match="calendar_ids"):
        FreeBusyRequest(start="2026-05-06", end="2026-05-07", calendar_ids=[])
    with pytest.raises(ValueError, match="calendar_ids must not contain blank"):
        FreeBusyRequest(start="2026-05-06", end="2026-05-07", calendar_ids=[" "])
    with pytest.raises(ValueError, match="end"):
        FreeBusyRequest(start="2026-05-07", end="2026-05-06", calendar_ids=["primary"])


def test_quick_add_request_requires_text():
    with pytest.raises(ValueError, match="text"):
        QuickAddRequest(text=" ")
    QuickAddRequest(text="lunch with Aman thursday 1pm")


def test_create_event_request_send_updates_default_is_none_and_validated():
    request = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    assert request.send_updates == "none"
    with pytest.raises(ValueError, match="send_updates"):
        CreateEventRequest(
            title="Gym",
            start="2026-05-06T19:00:00+05:30",
            end="2026-05-06T20:00:00+05:30",
            send_updates="bogus",  # type: ignore[arg-type]
        )


def test_action_result_factories_for_v2_statuses():
    updated = CalendarActionResult.updated(
        event_id="evt_1",
        link="https://calendar/event",
        title="Gym",
        modification_scope="thisEventOnly",
        changed_fields=["title"],
    )
    assert updated.status == "updated"
    assert "title" in updated.user_message
    assert "evt_1" in updated.receipt_evidence

    deleted = CalendarActionResult.deleted(
        event_id="evt_1",
        title="Gym",
        modification_scope="all",
    )
    assert deleted.status == "deleted"
    assert "evt_1" in deleted.receipt_evidence

    moved = CalendarActionResult.moved(
        event_id="evt_1",
        link="https://calendar/event",
        title="Gym",
        source_calendar_id="primary",
        destination_calendar_id="work@x.com",
    )
    assert moved.status == "moved"
    assert "primary" in moved.receipt_evidence
    assert "work@x.com" in moved.receipt_evidence

    rsvp = CalendarActionResult.rsvp_recorded(
        event_id="evt_1",
        title="Standup",
        response="accepted",
        attendee_email="me@example.com",
    )
    assert rsvp.status == "rsvp_recorded"
    assert "accepted" in rsvp.user_message
    assert "me@example.com" in rsvp.receipt_evidence


def test_recurrence_rule_supports_byday_and_until_combination():
    rule = RecurrenceRule(frequency="weekly", until="20261231T235959Z")
    rrule = rule.to_google_rrule()
    assert rrule == ["RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z"]


def test_action_result_to_dict_serializes_nested_models():
    request = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        recurrence=RecurrenceRule("daily"),
    )
    result = CalendarActionResult(
        status="confirmation_required",
        user_message="Confirm Gym",
        confirmation=ConfirmationRequired(
            message="Confirm Gym",
            reasons=["conflict"],
            request=request,
            conflicts=[
                CalendarConflict(
                    title="Standup",
                    start="2026-05-06T19:00:00+05:30",
                    end="2026-05-06T19:30:00+05:30",
                )
            ],
        ),
    )
    data = result.to_dict()
    assert data["confirmation"]["request"]["recurrence"]["frequency"] == "daily"
    assert data["confirmation"]["conflicts"][0]["title"] == "Standup"
