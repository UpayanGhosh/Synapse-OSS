from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    CalendarConflict,
    CalendarEvent,
    CalendarPreferences,
    CreateEventRequest,
    DeleteEventRequest,
    MoveEventRequest,
    UpdateEventRequest,
)

LOW_CONFIDENCE_THRESHOLD = 0.8
OPEN_ENDED_CONFIRMATION_FREQUENCIES = {"daily", "weekly", "monthly"}


@dataclass(slots=True)
class PolicyDecision:
    can_create_now: bool
    reasons: list[str] = field(default_factory=list)
    conflicts: list[CalendarConflict] = field(default_factory=list)


def evaluate_create_policy(
    request: CreateEventRequest,
    preferences: CalendarPreferences,
    conflicts: list[CalendarConflict],
) -> PolicyDecision:
    reasons: list[str] = []

    if not preferences.trusted_quick_add:
        reasons.append("trusted_quick_add_disabled")
    if request.attendees:
        reasons.append("attendees")
    if request.calendar_id != preferences.default_calendar_id:
        reasons.append("non_default_calendar")
    if request.parse_confidence < LOW_CONFIDENCE_THRESHOLD:
        reasons.append("low_confidence")
    if conflicts:
        reasons.append("conflict")
    if _requires_open_ended_recurrence_confirmation(request, preferences):
        reasons.append("open_ended_recurrence")

    return PolicyDecision(
        can_create_now=not reasons,
        reasons=reasons,
        conflicts=list(conflicts),
    )


def evaluate_update_policy(
    request: UpdateEventRequest,
    preferences: CalendarPreferences,
    current_event: CalendarEvent,
    conflicts: list[CalendarConflict] | None = None,
) -> PolicyDecision:
    reasons: list[str] = []
    conflicts = conflicts or []

    if not preferences.trusted_quick_add:
        reasons.append("trusted_quick_add_disabled")
    if (
        request.calendar_id != preferences.default_calendar_id
        or current_event.calendar_id != preferences.default_calendar_id
    ):
        reasons.append("non_default_calendar")
    if request.parse_confidence < LOW_CONFIDENCE_THRESHOLD:
        reasons.append("low_confidence")
    if request.attendees is not None and set(request.attendees) != set(current_event.attendees):
        reasons.append("attendee_change")
    if len([a for a in current_event.attendees if a]) > 1:
        reasons.append("existing_attendees")
    if request.send_updates == "all":
        reasons.append("send_updates_all")
    if current_event.recurring_event_id and request.modification_scope != "thisEventOnly":
        reasons.append("recurring_scope")
    if conflicts:
        reasons.append("conflict")

    return PolicyDecision(
        can_create_now=not reasons,
        reasons=reasons,
        conflicts=list(conflicts),
    )


def evaluate_delete_policy(
    request: DeleteEventRequest,
    current_event: CalendarEvent,
    preferences: CalendarPreferences,
    *,
    force: bool = False,
) -> PolicyDecision:
    reasons: list[str] = []

    if force:
        reasons.append("force")
    else:
        reasons.append("destructive_default")

    if len(current_event.attendees) > 1:
        reasons.append("existing_attendees")
    if request.modification_scope == "all":
        reasons.append("recurring_master")
    if request.calendar_id != preferences.default_calendar_id:
        reasons.append("non_default_calendar")
    if request.send_updates == "all":
        reasons.append("send_updates_all")

    return PolicyDecision(
        can_create_now=force,
        reasons=reasons,
        conflicts=[],
    )


def evaluate_move_policy(
    request: MoveEventRequest,
    current_event: CalendarEvent,
    preferences: CalendarPreferences,
    *,
    force: bool = False,
) -> PolicyDecision:
    reasons: list[str] = []

    if force:
        reasons.append("force")
    else:
        reasons.append("destructive_default")

    if request.destination_calendar_id != preferences.default_calendar_id:
        reasons.append("non_default_destination")
    if len(current_event.attendees) > 1:
        reasons.append("existing_attendees")
    if current_event.recurring_event_id:
        reasons.append("recurring_event")
    if request.send_updates == "all":
        reasons.append("send_updates_all")

    return PolicyDecision(
        can_create_now=force,
        reasons=reasons,
        conflicts=[],
    )


def _requires_open_ended_recurrence_confirmation(
    request: CreateEventRequest,
    preferences: CalendarPreferences,
) -> bool:
    if preferences.allow_open_ended_recurring_personal_events:
        return False
    recurrence = request.recurrence
    if recurrence is None:
        return False
    if recurrence.frequency not in OPEN_ENDED_CONFIRMATION_FREQUENCIES:
        return False
    return recurrence.until is None and recurrence.count is None
