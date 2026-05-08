from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone as fixed_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .intents import CalendarIntent, parse_calendar_intent
from .models import CalendarActionResult, CalendarPreferences, ConfirmationRequired
from .policy import evaluate_create_policy


_INDIA_TIMEZONE_ALIASES = {"Asia/Calcutta", "Asia/Kolkata"}
_INDIA_FIXED_OFFSET = fixed_timezone(timedelta(hours=5, minutes=30))


def handle_calendar_request(
    text: str,
    calendar_service: Any,
    preferences: CalendarPreferences,
    now: datetime | None = None,
) -> CalendarActionResult:
    base_date = _base_date(now, preferences.timezone)
    intent = parse_calendar_intent(
        text,
        base_date=base_date,
        timezone=preferences.timezone,
        default_duration_minutes=preferences.default_event_duration_minutes,
    )

    if intent.kind == "create_event" and intent.create is not None:
        return _handle_create(intent, calendar_service, preferences)
    if intent.kind == "availability" and intent.availability is not None:
        return _handle_availability(intent, calendar_service, preferences)
    if intent.kind in {"list_events", "search_events"} and intent.availability is not None:
        return _handle_read(intent, calendar_service, preferences)
    if intent.kind == "holiday":
        return calendar_service.find_holidays(intent.query or text, preferences)

    return CalendarActionResult(
        status="answered",
        user_message="I need a clearer calendar action and date before I can help with that.",
        data={"kind": "unknown", "request": text},
    )


def _base_date(now: datetime | None, timezone: str) -> date:
    if now is None:
        return date.today()
    if now.tzinfo is None or now.utcoffset() is None:
        return now.date()
    try:
        return now.astimezone(ZoneInfo(timezone)).date()
    except (ValueError, ZoneInfoNotFoundError):
        if timezone in _INDIA_TIMEZONE_ALIASES:
            return now.astimezone(_INDIA_FIXED_OFFSET).date()
        return now.date()


def _handle_create(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    request = intent.create
    assert request is not None
    request = replace(request, calendar_id=preferences.default_calendar_id)
    conflicts = calendar_service.check_conflicts(request.start, request.end, calendar_id=request.calendar_id)
    decision = evaluate_create_policy(request, preferences, conflicts)
    if not decision.can_create_now:
        reason_text = ", ".join(decision.reasons) or "confirmation_required"
        return CalendarActionResult(
            status="confirmation_required",
            user_message=f"Please confirm before I create '{request.title}' because: {reason_text}.",
            confirmation=ConfirmationRequired(
                message="Please confirm this calendar change.",
                reasons=list(decision.reasons),
                request=request,
                conflicts=list(conflicts),
            ),
            data={
                "request": _as_data(request),
                "conflicts": [_as_data(conflict) for conflict in conflicts],
                "reasons": list(decision.reasons),
            },
        )

    return calendar_service.create_event(request, calendar_id=request.calendar_id)


def _handle_availability(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    request = intent.availability
    assert request is not None
    request = replace(request, calendar_id=preferences.default_calendar_id)
    duration = request.duration_minutes or preferences.default_event_duration_minutes
    conflicts = calendar_service.check_conflicts(request.start, request.end, calendar_id=request.calendar_id)
    slots = calendar_service.suggest_free_slots(
        request.start,
        request.end,
        duration,
        calendar_id=request.calendar_id,
    )
    if slots:
        message = f"Found {len(slots)} free slot(s) between {request.start} and {request.end}."
    else:
        message = f"No free slot found between {request.start} and {request.end}."
    if conflicts:
        message = f"{message} Found {len(conflicts)} conflict(s)."
    return CalendarActionResult(
        status="answered",
        user_message=message,
        receipt_evidence="Checked calendar free/busy through calendar service.",
        data={
            "slots": slots,
            "conflicts": [_as_data(conflict) for conflict in conflicts],
            "request": _as_data(request),
        },
    )


def _handle_read(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    request = intent.availability
    assert request is not None
    if intent.kind == "search_events" and intent.query:
        events = calendar_service.search_events(
            intent.query,
            request.start,
            request.end,
            calendar_id=preferences.default_calendar_id,
        )
    else:
        events = calendar_service.list_events(
            request.start,
            request.end,
            calendar_id=preferences.default_calendar_id,
        )
    return CalendarActionResult(
        status="answered",
        user_message=f"Found {len(events)} calendar event(s).",
        receipt_evidence="Read calendar events through calendar service.",
        data={"events": [_as_data(event) for event in events], "request": _as_data(request)},
    )


def _as_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value
