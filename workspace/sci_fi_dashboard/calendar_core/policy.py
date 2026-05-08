from __future__ import annotations

from dataclasses import dataclass, field

from .models import CalendarConflict, CalendarPreferences, CreateEventRequest

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
