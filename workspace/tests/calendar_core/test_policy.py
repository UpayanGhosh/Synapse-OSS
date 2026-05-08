from sci_fi_dashboard.calendar_core.models import (
    CalendarConflict,
    CalendarPreferences,
    CreateEventRequest,
    RecurrenceRule,
)
from sci_fi_dashboard.calendar_core.policy import evaluate_create_policy


def test_safe_personal_event_quick_adds_without_confirmation():
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])

    assert decision.can_create_now is True
    assert decision.reasons == []
    assert decision.conflicts == []


def test_attendees_require_confirmation():
    req = CreateEventRequest(
        title="Call",
        start="2026-05-06T16:00:00+05:30",
        end="2026-05-06T17:00:00+05:30",
        attendees=["a@example.com"],
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])

    assert decision.can_create_now is False
    assert "attendees" in decision.reasons


def test_conflict_requires_confirmation():
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    conflict = CalendarConflict(
        title="Standup",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T19:30:00+05:30",
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[conflict])

    assert decision.can_create_now is False
    assert "conflict" in decision.reasons
    assert decision.conflicts == [conflict]


def test_yearly_birthday_can_quick_add_when_clear():
    req = CreateEventRequest(
        title="Arjun birthday",
        start="2026-07-12",
        end="2026-07-13",
        all_day=True,
        recurrence=RecurrenceRule("yearly"),
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])

    assert decision.can_create_now is True


def test_trusted_quick_add_disabled_requires_confirmation():
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
    )
    prefs = CalendarPreferences(trusted_quick_add=False)

    decision = evaluate_create_policy(req, prefs, conflicts=[])

    assert decision.can_create_now is False
    assert "trusted_quick_add_disabled" in decision.reasons


def test_non_primary_calendar_requires_confirmation():
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        calendar_id="work",
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])

    assert decision.can_create_now is False
    assert "non_default_calendar" in decision.reasons


def test_low_parse_confidence_requires_confirmation():
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        parse_confidence=0.79,
    )

    decision = evaluate_create_policy(req, CalendarPreferences(), conflicts=[])

    assert decision.can_create_now is False
    assert "low_confidence" in decision.reasons


def test_open_ended_high_frequency_recurrence_requires_confirmation_when_disallowed():
    prefs = CalendarPreferences(allow_open_ended_recurring_personal_events=False)
    for frequency in ("daily", "weekly", "monthly"):
        req = CreateEventRequest(
            title="Gym",
            start="2026-05-06T19:00:00+05:30",
            end="2026-05-06T20:00:00+05:30",
            recurrence=RecurrenceRule(frequency),
        )

        decision = evaluate_create_policy(req, prefs, conflicts=[])

        assert decision.can_create_now is False
        assert "open_ended_recurrence" in decision.reasons


def test_bounded_high_frequency_recurrence_can_quick_add_when_clear():
    prefs = CalendarPreferences(allow_open_ended_recurring_personal_events=False)
    req = CreateEventRequest(
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        recurrence=RecurrenceRule("weekly", count=4),
    )

    decision = evaluate_create_policy(req, prefs, conflicts=[])

    assert decision.can_create_now is True
