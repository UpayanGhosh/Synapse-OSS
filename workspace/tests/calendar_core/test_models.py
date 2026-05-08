from sci_fi_dashboard.calendar_core.models import (
    AvailabilityRequest,
    CalendarActionResult,
    CalendarConflict,
    CalendarPreferences,
    ConfirmationRequired,
    CreateEventRequest,
    RecurrenceRule,
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
