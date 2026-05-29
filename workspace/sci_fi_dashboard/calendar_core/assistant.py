from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone as fixed_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .confirmations import PendingAction, PendingActionStore, default_store
from .intents import CalendarIntent, parse_calendar_intent
from .models import (
    CalendarActionResult,
    CalendarEvent,
    CalendarPreferences,
    ConfirmationRequired,
    DeleteEventRequest,
    FreeBusyRequest,
    MoveEventRequest,
    RsvpRequest,
    UpdateEventRequest,
)
from .policy import (
    evaluate_create_policy,
    evaluate_delete_policy,
    evaluate_move_policy,
    evaluate_update_policy,
)


_INDIA_TIMEZONE_ALIASES = {"Asia/Calcutta", "Asia/Kolkata"}
_INDIA_FIXED_OFFSET = fixed_timezone(timedelta(hours=5, minutes=30))


def handle_calendar_request(
    text: str,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    chat_id: str | None = None,
    now: datetime | None = None,
    pending_store: PendingActionStore | None = None,
) -> CalendarActionResult:
    base_date = _base_date(now, preferences.timezone)
    intent = parse_calendar_intent(
        text,
        base_date=base_date,
        timezone=preferences.timezone,
        default_duration_minutes=preferences.default_event_duration_minutes,
    )

    store = pending_store or default_store()

    if chat_id and intent.kind == "affirm_yes":
        return _consume_pending(chat_id, store, calendar_service, preferences)
    if chat_id and intent.kind == "affirm_no":
        return _abandon_pending(chat_id, store)

    if intent.kind == "create_event" and intent.create is not None:
        return _handle_create(intent, calendar_service, preferences, chat_id=chat_id, store=store)
    if intent.kind == "availability" and intent.availability is not None:
        return _handle_availability(intent, calendar_service, preferences)
    if intent.kind == "freebusy" and intent.freebusy is not None:
        return _handle_freebusy(intent, calendar_service, preferences)
    if intent.kind in {"list_events", "search_events"} and intent.availability is not None:
        return _handle_read(intent, calendar_service, preferences)
    if intent.kind == "holiday":
        return calendar_service.find_holidays(intent.query or text, preferences)
    if intent.kind == "quick_add" and intent.quick_add is not None:
        return _handle_quick_add(intent, calendar_service, preferences)
    if intent.kind == "delete_event":
        return _handle_delete(intent, calendar_service, preferences, chat_id=chat_id, store=store)
    if intent.kind == "move_event":
        return _handle_move(intent, calendar_service, preferences, chat_id=chat_id, store=store)
    if intent.kind == "update_event":
        return _handle_update(intent, calendar_service, preferences, chat_id=chat_id, store=store)
    if intent.kind == "rsvp" and intent.rsvp_response is not None:
        return _handle_rsvp(intent, calendar_service, preferences, chat_id=chat_id, store=store)

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
    *,
    chat_id: str | None,
    store: PendingActionStore,
) -> CalendarActionResult:
    request = intent.create
    assert request is not None
    request = replace(request, calendar_id=preferences.default_calendar_id)
    conflicts = calendar_service.check_conflicts(request.start, request.end, calendar_id=request.calendar_id)
    decision = evaluate_create_policy(request, preferences, conflicts)
    if not decision.can_create_now:
        return _park_or_block(
            kind="create_event",
            payload=request,
            chat_id=chat_id,
            store=store,
            reasons=list(decision.reasons),
            conflicts=list(conflicts),
            user_message=(
                f"Please confirm before I create '{request.title}' because: "
                f"{', '.join(decision.reasons) or 'confirmation_required'}."
            ),
            evidence=(
                f"Pending create '{request.title}' from {request.start} to {request.end}"
            ),
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


def _handle_freebusy(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    fb = intent.freebusy
    assert fb is not None
    if not fb.calendar_ids:
        fb = FreeBusyRequest(
            start=fb.start,
            end=fb.end,
            calendar_ids=[preferences.default_calendar_id],
        )
    result = calendar_service.freebusy(fb)
    busy_count = sum(len(windows) for windows in result.calendars.values())
    return CalendarActionResult(
        status="answered",
        user_message=(
            f"Free/busy across {len(result.calendars)} calendar(s): "
            f"{busy_count} busy window(s)."
        ),
        receipt_evidence=(
            f"Queried freebusy for calendars={list(result.calendars.keys())} "
            f"between {fb.start} and {fb.end}"
        ),
        data={
            "calendars": {
                cid: [asdict(window) for window in windows]
                for cid, windows in result.calendars.items()
            },
            "errors": dict(result.errors),
            "request": _as_data(fb),
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


def _handle_quick_add(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    qa = intent.quick_add
    assert qa is not None
    qa = replace(qa, calendar_id=preferences.default_calendar_id)
    return calendar_service.quick_add(qa)


def _handle_delete(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    chat_id: str | None,
    store: PendingActionStore,
) -> CalendarActionResult:
    target = (intent.target_query or intent.query).strip()
    candidates = _find_target_events(target, calendar_service, preferences)
    if not candidates:
        return CalendarActionResult(
            status="answered",
            user_message=(
                f"I could not find a matching event for '{target}'. "
                "Tell me the title or rough date and I'll try again."
            ),
            data={"target": target, "matches": []},
        )
    if len(candidates) > 1:
        return _disambiguation_result("delete", target, candidates)

    event = candidates[0]
    request = DeleteEventRequest(
        event_id=event.id,
        calendar_id=event.calendar_id or preferences.default_calendar_id,
        modification_scope="thisEventOnly" if event.recurring_event_id else "thisEventOnly",
    )
    decision = evaluate_delete_policy(request, event, preferences, force=False)
    return _park_or_block(
        kind="delete_event",
        payload=(request, event),
        chat_id=chat_id,
        store=store,
        reasons=list(decision.reasons),
        conflicts=[],
        user_message=(
            f"Confirm delete of '{event.title}' (id={event.id}) — "
            f"reasons: {', '.join(decision.reasons) or 'destructive_default'}."
        ),
        evidence=f"Pending delete event_id={event.id} title='{event.title}'",
    )


def _handle_move(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    chat_id: str | None,
    store: PendingActionStore,
) -> CalendarActionResult:
    target = (intent.target_query or intent.query).strip()
    candidates = _find_target_events(target, calendar_service, preferences)
    if not candidates:
        return CalendarActionResult(
            status="answered",
            user_message=f"I could not find a matching event for '{target}'.",
            data={"target": target, "matches": []},
        )
    if len(candidates) > 1:
        return _disambiguation_result("move", target, candidates)

    event = candidates[0]
    new_start = intent.new_start
    new_end = intent.new_end
    if not new_start or not new_end:
        return CalendarActionResult(
            status="answered",
            user_message=(
                f"I found '{event.title}' but could not parse the new time. "
                "Tell me the new start (e.g. 'to Friday at 5 pm')."
            ),
            data={"event": _as_data(event), "missing": "new_start"},
        )
    update_request = UpdateEventRequest(
        event_id=event.id,
        calendar_id=event.calendar_id or preferences.default_calendar_id,
        start=new_start,
        end=new_end,
        modification_scope="thisEventOnly" if event.recurring_event_id else "thisEventOnly",
    )
    decision = evaluate_update_policy(update_request, preferences, event, conflicts=[])
    return _park_or_block(
        kind="reschedule_event",
        payload=(update_request, event),
        chat_id=chat_id,
        store=store,
        reasons=list(decision.reasons) or ["destructive_default"],
        conflicts=[],
        user_message=(
            f"Confirm rescheduling '{event.title}' to {new_start} — {new_end}."
        ),
        evidence=(
            f"Pending reschedule event_id={event.id} from='{event.start}' to='{new_start}'"
        ),
    )


def _handle_update(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    chat_id: str | None,
    store: PendingActionStore,
) -> CalendarActionResult:
    target = (intent.target_query or intent.query).strip()
    candidates = _find_target_events(target, calendar_service, preferences)
    if not candidates:
        return CalendarActionResult(
            status="answered",
            user_message=f"I could not find a matching event for '{target}'.",
            data={"target": target, "matches": []},
        )
    if len(candidates) > 1:
        return _disambiguation_result("update", target, candidates)

    event = candidates[0]
    new_title = intent.new_title or None
    new_start = intent.new_start or None
    new_end = intent.new_end or None
    if not (new_title or new_start or new_end):
        return CalendarActionResult(
            status="answered",
            user_message=(
                f"Tell me what to change on '{event.title}' — title, time, or description?"
            ),
            data={"event": _as_data(event), "missing": "change_field"},
        )
    update_request = UpdateEventRequest(
        event_id=event.id,
        calendar_id=event.calendar_id or preferences.default_calendar_id,
        title=new_title,
        start=new_start,
        end=new_end,
        modification_scope="thisEventOnly" if event.recurring_event_id else "thisEventOnly",
    )
    decision = evaluate_update_policy(update_request, preferences, event, conflicts=[])
    if decision.can_create_now:
        return calendar_service.update_event(update_request)
    return _park_or_block(
        kind="update_event",
        payload=(update_request, event),
        chat_id=chat_id,
        store=store,
        reasons=list(decision.reasons),
        conflicts=[],
        user_message=(
            f"Confirm update of '{event.title}' — reasons: "
            f"{', '.join(decision.reasons) or 'confirmation_required'}."
        ),
        evidence=f"Pending update event_id={event.id} title='{event.title}'",
    )


def _handle_rsvp(
    intent: CalendarIntent,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    chat_id: str | None,
    store: PendingActionStore,
) -> CalendarActionResult:
    target = (intent.target_query or intent.query).strip()
    candidates = _find_target_events(target, calendar_service, preferences)
    if not candidates:
        return CalendarActionResult(
            status="answered",
            user_message=f"I could not find a matching event for '{target}' to RSVP.",
            data={"target": target, "matches": []},
        )
    if len(candidates) > 1:
        return _disambiguation_result("rsvp", target, candidates)

    event = candidates[0]
    response = intent.rsvp_response
    assert response is not None
    request = RsvpRequest(
        event_id=event.id,
        response=response,
        calendar_id=event.calendar_id or preferences.default_calendar_id,
    )
    return calendar_service.respond_to_event(request)


# ---------------------------------------------------------------------------
# Pending-action plumbing
# ---------------------------------------------------------------------------


def _park_or_block(
    *,
    kind: str,
    payload: Any,
    chat_id: str | None,
    store: PendingActionStore,
    reasons: list[str],
    conflicts: list[Any],
    user_message: str,
    evidence: str,
) -> CalendarActionResult:
    if not chat_id:
        return CalendarActionResult(
            status="confirmation_required",
            user_message=user_message,
            confirmation=ConfirmationRequired(
                message=user_message,
                reasons=reasons,
                conflicts=list(conflicts),
            ),
            data={
                "reasons": reasons,
                "conflicts": [_as_data(item) for item in conflicts],
                "kind": kind,
                "evidence": evidence,
            },
        )
    pending = store.put(chat_id=chat_id, kind=kind, payload=payload, evidence=evidence)
    return CalendarActionResult(
        status="confirmation_required",
        user_message=(
            f"{user_message} Reply 'yes' or 'cancel' within 10 minutes "
            f"(confirmation_id={pending.confirmation_id})."
        ),
        confirmation=ConfirmationRequired(
            message=user_message,
            reasons=reasons,
            conflicts=list(conflicts),
        ),
        data={
            "reasons": reasons,
            "conflicts": [_as_data(item) for item in conflicts],
            "kind": kind,
            "confirmation_id": pending.confirmation_id,
            "evidence": evidence,
        },
    )


def _consume_pending(
    chat_id: str,
    store: PendingActionStore,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    pending = store.get_and_clear(chat_id)
    if pending is None:
        return CalendarActionResult(
            status="answered",
            user_message="There is no pending calendar action to confirm.",
            data={"reason": "no_pending"},
        )
    return _execute_pending(pending, calendar_service, preferences)


def _abandon_pending(chat_id: str, store: PendingActionStore) -> CalendarActionResult:
    discarded = store.discard(chat_id)
    return CalendarActionResult(
        status="answered",
        user_message=(
            "Cancelled the pending calendar action."
            if discarded
            else "There was nothing pending to cancel."
        ),
        data={"discarded": discarded},
    )


def _execute_pending(
    pending: PendingAction,
    calendar_service: Any,
    preferences: CalendarPreferences,
) -> CalendarActionResult:
    if pending.kind == "create_event":
        return calendar_service.create_event(pending.payload, calendar_id=pending.payload.calendar_id)
    if pending.kind == "delete_event":
        request, event = pending.payload
        # On confirmation, force=True; assistant gathered evidence already.
        forced_decision = evaluate_delete_policy(request, event, preferences, force=True)
        result = calendar_service.delete_event(request)
        result.data.setdefault("policy_reasons", list(forced_decision.reasons))
        return result
    if pending.kind == "reschedule_event":
        request, _event = pending.payload
        return calendar_service.update_event(request)
    if pending.kind == "update_event":
        request, _event = pending.payload
        return calendar_service.update_event(request)
    if pending.kind == "move_event":
        request, _event = pending.payload
        return calendar_service.move_event(request)
    return CalendarActionResult(
        status="failed",
        user_message=f"Unknown pending kind: {pending.kind}",
        data={"kind": pending.kind},
    )


def _find_target_events(
    target: str,
    calendar_service: Any,
    preferences: CalendarPreferences,
    *,
    window_days: int = 14,
) -> list[CalendarEvent]:
    if not target:
        return []
    today = date.today()
    start = f"{today.isoformat()}T00:00:00{_offset(preferences.timezone)}"
    end = f"{(today + timedelta(days=window_days)).isoformat()}T00:00:00{_offset(preferences.timezone)}"
    return calendar_service.search_events(
        target, start, end, calendar_id=preferences.default_calendar_id
    )


def _disambiguation_result(action: str, target: str, candidates: list[CalendarEvent]) -> CalendarActionResult:
    summaries = [
        {
            "id": event.id,
            "title": event.title,
            "start": event.start,
            "end": event.end,
        }
        for event in candidates[:5]
    ]
    return CalendarActionResult(
        status="confirmation_required",
        user_message=(
            f"Multiple events match '{target}' for {action}. "
            "Tell me which one (by title or time)."
        ),
        confirmation=ConfirmationRequired(
            message=f"Multiple events match '{target}'.",
            reasons=["ambiguous_target"],
        ),
        data={"action": action, "target": target, "candidates": summaries},
    )


def _offset(timezone: str) -> str:
    if timezone in _INDIA_TIMEZONE_ALIASES:
        return "+05:30"
    return ""


def _as_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    return value
