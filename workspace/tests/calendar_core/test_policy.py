from sci_fi_dashboard.calendar_core.models import (
    CalendarConflict,
    CalendarEvent,
    CalendarPreferences,
    CreateEventRequest,
    DeleteEventRequest,
    MoveEventRequest,
    RecurrenceRule,
    UpdateEventRequest,
)
from sci_fi_dashboard.calendar_core.policy import (
    evaluate_create_policy,
    evaluate_delete_policy,
    evaluate_move_policy,
    evaluate_update_policy,
)


def _make_event(**overrides) -> CalendarEvent:
    base = dict(
        id="evt_1",
        title="Gym",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T20:00:00+05:30",
        calendar_id="primary",
    )
    base.update(overrides)
    return CalendarEvent(**base)


def _make_update(**overrides) -> UpdateEventRequest:
    base = dict(event_id="evt_1", title="Gym renamed")
    base.update(overrides)
    return UpdateEventRequest(**base)


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


# --- Update policy ---------------------------------------------------------


def test_update_safe_single_instance_quick_allows():
    decision = evaluate_update_policy(
        _make_update(),
        CalendarPreferences(),
        _make_event(),
    )

    assert decision.can_create_now is True
    assert decision.reasons == []


def test_update_attendee_delta_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(attendees=["new@example.com"]),
        CalendarPreferences(),
        _make_event(attendees=["old@example.com"]),
    )

    assert decision.can_create_now is False
    assert "attendee_change" in decision.reasons


def test_update_existing_attendees_force_confirmation():
    decision = evaluate_update_policy(
        _make_update(),
        CalendarPreferences(),
        _make_event(attendees=["a@example.com", "b@example.com"]),
    )

    assert decision.can_create_now is False
    assert "existing_attendees" in decision.reasons


def test_update_low_parse_confidence_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(parse_confidence=0.5),
        CalendarPreferences(),
        _make_event(),
    )

    assert decision.can_create_now is False
    assert "low_confidence" in decision.reasons


def test_update_non_default_calendar_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(calendar_id="work"),
        CalendarPreferences(),
        _make_event(calendar_id="work"),
    )

    assert decision.can_create_now is False
    assert "non_default_calendar" in decision.reasons


def test_update_conflict_forces_confirmation():
    conflict = CalendarConflict(
        title="Standup",
        start="2026-05-06T19:00:00+05:30",
        end="2026-05-06T19:30:00+05:30",
    )

    decision = evaluate_update_policy(
        _make_update(),
        CalendarPreferences(),
        _make_event(),
        conflicts=[conflict],
    )

    assert decision.can_create_now is False
    assert "conflict" in decision.reasons
    assert decision.conflicts == [conflict]


def test_update_recurring_master_scope_all_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(modification_scope="all"),
        CalendarPreferences(),
        _make_event(recurring_event_id="rec_1"),
    )

    assert decision.can_create_now is False
    assert "recurring_scope" in decision.reasons


def test_update_recurring_instance_this_event_only_allowed():
    decision = evaluate_update_policy(
        _make_update(modification_scope="thisEventOnly"),
        CalendarPreferences(),
        _make_event(recurring_event_id="rec_1"),
    )

    assert decision.can_create_now is True
    assert decision.reasons == []


def test_update_send_updates_all_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(send_updates="all"),
        CalendarPreferences(),
        _make_event(),
    )

    assert decision.can_create_now is False
    assert "send_updates_all" in decision.reasons


def test_update_trusted_quick_add_disabled_forces_confirmation():
    decision = evaluate_update_policy(
        _make_update(),
        CalendarPreferences(trusted_quick_add=False),
        _make_event(),
    )

    assert decision.can_create_now is False
    assert "trusted_quick_add_disabled" in decision.reasons


# --- Delete policy ---------------------------------------------------------


def test_delete_without_force_always_blocks():
    decision = evaluate_delete_policy(
        DeleteEventRequest(event_id="evt_1"),
        _make_event(),
        CalendarPreferences(),
    )

    assert decision.can_create_now is False
    assert "destructive_default" in decision.reasons


def test_delete_with_force_allows():
    decision = evaluate_delete_policy(
        DeleteEventRequest(event_id="evt_1"),
        _make_event(),
        CalendarPreferences(),
        force=True,
    )

    assert decision.can_create_now is True
    assert "force" in decision.reasons


def test_delete_with_force_records_existing_attendees():
    decision = evaluate_delete_policy(
        DeleteEventRequest(event_id="evt_1"),
        _make_event(attendees=["a@example.com", "b@example.com"]),
        CalendarPreferences(),
        force=True,
    )

    assert decision.can_create_now is True
    assert "force" in decision.reasons
    assert "existing_attendees" in decision.reasons


def test_delete_force_recurring_master_scope_all_records_recurring_master():
    decision = evaluate_delete_policy(
        DeleteEventRequest(event_id="evt_1", modification_scope="all"),
        _make_event(recurring_event_id="rec_1"),
        CalendarPreferences(),
        force=True,
    )

    assert decision.can_create_now is True
    assert "recurring_master" in decision.reasons


def test_delete_without_force_send_updates_all_recorded():
    decision = evaluate_delete_policy(
        DeleteEventRequest(event_id="evt_1", send_updates="all"),
        _make_event(),
        CalendarPreferences(),
    )

    assert decision.can_create_now is False
    assert "send_updates_all" in decision.reasons


# --- Move policy -----------------------------------------------------------


def test_move_without_force_always_blocks():
    decision = evaluate_move_policy(
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id="work",
        ),
        _make_event(),
        CalendarPreferences(),
    )

    assert decision.can_create_now is False
    assert "destructive_default" in decision.reasons


def test_move_with_force_allows():
    decision = evaluate_move_policy(
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="work",
            destination_calendar_id="primary",
        ),
        _make_event(),
        CalendarPreferences(),
        force=True,
    )

    assert decision.can_create_now is True
    assert "force" in decision.reasons


def test_move_non_default_destination_recorded():
    decision = evaluate_move_policy(
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id="work",
        ),
        _make_event(),
        CalendarPreferences(),
        force=True,
    )

    assert "non_default_destination" in decision.reasons


def test_move_existing_attendees_recorded():
    decision = evaluate_move_policy(
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id="work",
        ),
        _make_event(attendees=["a@example.com", "b@example.com"]),
        CalendarPreferences(),
        force=True,
    )

    assert "existing_attendees" in decision.reasons


def test_move_recurring_event_recorded():
    decision = evaluate_move_policy(
        MoveEventRequest(
            event_id="evt_1",
            source_calendar_id="primary",
            destination_calendar_id="work",
        ),
        _make_event(recurring_event_id="rec_1"),
        CalendarPreferences(),
        force=True,
    )

    assert "recurring_event" in decision.reasons
