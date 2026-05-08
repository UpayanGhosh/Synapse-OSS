from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
import re
from typing import Any

from .models import (
    CalendarActionResult,
    CalendarConflict,
    CalendarEvent,
    CalendarListEntry,
    CalendarPreferences,
    ColorPalette,
    CreateEventRequest,
    DeleteEventRequest,
    FreeBusyRequest,
    FreeBusyResult,
    FreeBusyWindow,
    MoveEventRequest,
    QuickAddRequest,
    RsvpRequest,
    UpdateEventRequest,
)


class GoogleCalendarService:
    def __init__(self, svc: Any) -> None:
        self._svc = svc

    def list_events(
        self,
        start: str,
        end: str,
        calendar_id: str = "primary",
        query: str | None = None,
    ) -> list[CalendarEvent]:
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "timeMin": start,
            "timeMax": end,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if query:
            kwargs["q"] = query

        response = self._svc.events().list(**kwargs).execute()
        return [_normalize_event(item, calendar_id) for item in response.get("items", [])]

    def search_events(
        self,
        query: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
    ) -> list[CalendarEvent]:
        return self.list_events(start, end, calendar_id=calendar_id, query=query)

    def check_conflicts(
        self,
        start: str,
        end: str,
        calendar_id: str = "primary",
    ) -> list[CalendarConflict]:
        request_start = _parse_moment(start)
        request_end = _parse_moment(end, request_start.tzinfo)
        request_tz = request_start.tzinfo or request_end.tzinfo
        if request_tz and request_start.tzinfo is None:
            request_start = _parse_moment(start, request_tz)
        events = self.list_events(start, end, calendar_id=calendar_id)
        conflicts: list[CalendarConflict] = []

        for event in events:
            event_start = _parse_moment(event.start, request_tz)
            event_end = _parse_moment(event.end, request_tz)
            if event_start < request_end and event_end > request_start:
                conflicts.append(
                    CalendarConflict(
                        title=event.title,
                        start=event.start,
                        end=event.end,
                        event_id=event.id,
                        link=event.link,
                    )
                )

        return conflicts

    def suggest_free_slots(
        self,
        day_start: str,
        day_end: str,
        duration_minutes: int,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        if duration_minutes <= 0:
            raise ValueError("duration_minutes must be greater than 0")

        window_start = _parse_moment(day_start)
        window_end = _parse_moment(day_end, window_start.tzinfo)
        window_tz = window_start.tzinfo or window_end.tzinfo
        if window_tz and window_start.tzinfo is None:
            window_start = _parse_moment(day_start, window_tz)
        min_delta = timedelta(minutes=duration_minutes)
        events = [
            (_parse_moment(event.start, window_tz), _parse_moment(event.end, window_tz))
            for event in self.list_events(day_start, day_end, calendar_id=calendar_id)
        ]
        busy_ranges = sorted(
            (
                (max(event_start, window_start), min(event_end, window_end))
                for event_start, event_end in events
                if event_end > window_start and event_start < window_end
            ),
            key=lambda item: item[0],
        )

        slots: list[dict[str, Any]] = []
        cursor = window_start
        for busy_start, busy_end in busy_ranges:
            if busy_start - cursor >= min_delta:
                slots.append(_slot(cursor, busy_start))
            if busy_end > cursor:
                cursor = busy_end
        if window_end - cursor >= min_delta:
            slots.append(_slot(cursor, window_end))

        return slots[:3]

    def create_event(
        self,
        request: CreateEventRequest,
        calendar_id: str = "primary",
    ) -> CalendarActionResult:
        target_calendar_id = calendar_id if calendar_id != "primary" else request.calendar_id
        body: dict[str, Any] = {
            "summary": request.title,
            "description": request.description,
            "start": _google_time_body(request.start, all_day=request.all_day),
            "end": _google_time_body(request.end, all_day=request.all_day),
        }
        if request.attendees:
            body["attendees"] = [{"email": attendee} for attendee in request.attendees]
        if request.recurrence is not None:
            body["recurrence"] = request.recurrence.to_google_rrule()

        response = self._svc.events().insert(calendarId=target_calendar_id, body=body).execute()
        return CalendarActionResult.created(
            event_id=response.get("id", ""),
            link=response.get("htmlLink", ""),
            title=request.title,
            start=request.start,
            end=request.end,
        )

    def list_calendars(self) -> list[CalendarListEntry]:
        """Wrap calendarList.list and normalize entries."""
        response = self._svc.calendarList().list().execute()
        entries: list[CalendarListEntry] = []
        for item in response.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            entries.append(
                CalendarListEntry(
                    id=item.get("id", ""),
                    summary=item.get("summary", "") or "",
                    primary=bool(item.get("primary", False)),
                    description=item.get("description", "") or "",
                    time_zone=item.get("timeZone", "") or "",
                    access_role=item.get("accessRole", "") or "",
                    background_color=item.get("backgroundColor", "") or "",
                    foreground_color=item.get("foregroundColor", "") or "",
                    selected=bool(item.get("selected", True)),
                )
            )
        return entries

    def get_event(self, event_id: str, calendar_id: str = "primary") -> CalendarEvent:
        """Fetch a single event and normalize it (with V2 fields)."""
        response = self._svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return _normalize_event(response or {}, calendar_id)

    def update_event(self, request: UpdateEventRequest) -> CalendarActionResult:
        """events.patch with modification_scope semantics."""
        body, changed_fields = _build_update_body(request)

        scope = request.modification_scope
        target_event_id = request.event_id

        if scope == "thisEventOnly":
            instance_id = request.instance_id
            if instance_id is None:
                instance_id = self._resolve_instance_id(
                    request.event_id, request.calendar_id, request.start
                )
            if instance_id:
                target_event_id = instance_id
        elif scope == "thisAndFollowing":
            if request.recurrence is None:
                return CalendarActionResult(
                    status="failed",
                    user_message="thisAndFollowing requires explicit recurrence cutoff",
                    receipt_evidence=(
                        f"Refused to patch event id={request.event_id} "
                        "scope=thisAndFollowing without recurrence cutoff"
                    ),
                    data={
                        "event_id": request.event_id,
                        "modification_scope": scope,
                    },
                )
            body["recurrence"] = request.recurrence.to_google_rrule()
            if "recurrence" not in changed_fields:
                changed_fields.append("recurrence")

        kwargs: dict[str, Any] = {
            "calendarId": request.calendar_id,
            "eventId": target_event_id,
            "body": body,
        }
        if request.send_updates in {"all", "externalOnly"}:
            kwargs["sendUpdates"] = request.send_updates

        response = self._svc.events().patch(**kwargs).execute() or {}
        return CalendarActionResult.updated(
            event_id=response.get("id", target_event_id),
            link=response.get("htmlLink", ""),
            title=response.get("summary") or request.title or "(untitled)",
            modification_scope=scope,
            changed_fields=changed_fields,
        )

    def delete_event(self, request: DeleteEventRequest) -> CalendarActionResult:
        """events.delete with scope semantics."""
        scope = request.modification_scope
        target_event_id = request.event_id

        if scope == "thisEventOnly":
            instance_id = request.instance_id
            if instance_id is None:
                instance_id = self._resolve_instance_id(
                    request.event_id, request.calendar_id, None
                )
            if instance_id:
                target_event_id = instance_id

        kwargs: dict[str, Any] = {
            "calendarId": request.calendar_id,
            "eventId": target_event_id,
        }
        if request.send_updates in {"all", "externalOnly"}:
            kwargs["sendUpdates"] = request.send_updates

        self._svc.events().delete(**kwargs).execute()
        return CalendarActionResult.deleted(
            event_id=target_event_id,
            title="(deleted)",
            modification_scope=scope,
        )

    def move_event(self, request: MoveEventRequest) -> CalendarActionResult:
        """events.move across calendars."""
        kwargs: dict[str, Any] = {
            "calendarId": request.source_calendar_id,
            "eventId": request.event_id,
            "destination": request.destination_calendar_id,
        }
        if request.send_updates in {"all", "externalOnly"}:
            kwargs["sendUpdates"] = request.send_updates

        response = self._svc.events().move(**kwargs).execute() or {}
        return CalendarActionResult.moved(
            event_id=response.get("id", request.event_id),
            link=response.get("htmlLink", ""),
            title=response.get("summary") or "(untitled)",
            source_calendar_id=request.source_calendar_id,
            destination_calendar_id=request.destination_calendar_id,
        )

    def respond_to_event(self, request: RsvpRequest) -> CalendarActionResult:
        """Patch the attendees array with the caller's responseStatus."""
        current = (
            self._svc.events()
            .get(calendarId=request.calendar_id, eventId=request.event_id)
            .execute()
            or {}
        )
        attendees = list(current.get("attendees", []) or [])

        target_email = request.attendee_email
        if target_email is None:
            for attendee in attendees:
                if isinstance(attendee, dict) and attendee.get("self"):
                    target_email = attendee.get("email")
                    break

        rebuilt: list[dict[str, Any]] = []
        matched = False
        for attendee in attendees:
            if not isinstance(attendee, dict):
                continue
            email = attendee.get("email", "")
            new_attendee = dict(attendee)
            if target_email and email == target_email:
                new_attendee["responseStatus"] = request.response
                new_attendee["self"] = True
                matched = True
            rebuilt.append(new_attendee)
        if not matched and target_email:
            rebuilt.append(
                {
                    "email": target_email,
                    "self": True,
                    "responseStatus": request.response,
                }
            )

        kwargs: dict[str, Any] = {
            "calendarId": request.calendar_id,
            "eventId": request.event_id,
            "body": {"attendees": rebuilt},
        }
        if request.send_updates in {"all", "externalOnly"}:
            kwargs["sendUpdates"] = request.send_updates

        response = self._svc.events().patch(**kwargs).execute() or {}
        return CalendarActionResult.rsvp_recorded(
            event_id=response.get("id", request.event_id),
            title=response.get("summary") or current.get("summary") or "(untitled)",
            response=request.response,
            attendee_email=target_email or "",
        )

    def freebusy(self, request: FreeBusyRequest) -> FreeBusyResult:
        """Single freebusy.query across multiple calendars."""
        body = {
            "timeMin": request.start,
            "timeMax": request.end,
            "items": [{"id": cid} for cid in request.calendar_ids],
        }
        response = self._svc.freebusy().query(body=body).execute() or {}
        result = FreeBusyResult(
            time_min=response.get("timeMin", request.start),
            time_max=response.get("timeMax", request.end),
        )
        calendars = response.get("calendars", {}) or {}
        for cid in request.calendar_ids:
            entry = calendars.get(cid, {}) or {}
            windows = [
                FreeBusyWindow(start=item.get("start", ""), end=item.get("end", ""))
                for item in entry.get("busy", []) or []
                if isinstance(item, dict)
            ]
            result.calendars[cid] = windows
            errors = entry.get("errors") or []
            if errors:
                first = errors[0] if isinstance(errors[0], dict) else {}
                reason = first.get("reason") or first.get("message") or "unknown"
                result.errors[cid] = str(reason)
        return result

    def quick_add(self, request: QuickAddRequest) -> CalendarActionResult:
        """events.quickAdd — natural-language event creation."""
        kwargs: dict[str, Any] = {
            "calendarId": request.calendar_id,
            "text": request.text,
        }
        if request.send_updates in {"all", "externalOnly"}:
            kwargs["sendUpdates"] = request.send_updates

        response = self._svc.events().quickAdd(**kwargs).execute() or {}
        start = response.get("start", {}) or {}
        end = response.get("end", {}) or {}
        return CalendarActionResult.created(
            event_id=response.get("id", ""),
            link=response.get("htmlLink", ""),
            title=response.get("summary") or request.text,
            start=start.get("dateTime") or start.get("date") or "",
            end=end.get("dateTime") or end.get("date") or "",
        )

    def list_colors(self) -> ColorPalette:
        """colors.get — split into event_colors and calendar_colors dicts."""
        response = self._svc.colors().get().execute() or {}
        return ColorPalette(
            event_colors=dict(response.get("event", {}) or {}),
            calendar_colors=dict(response.get("calendar", {}) or {}),
            updated=response.get("updated", "") or "",
        )

    def _resolve_instance_id(
        self,
        master_id: str,
        calendar_id: str,
        target_start: str | None,
    ) -> str | None:
        """Resolve the instance id of a recurring master event, optionally by target start."""
        try:
            response = (
                self._svc.events()
                .instances(calendarId=calendar_id, eventId=master_id)
                .execute()
            )
        except Exception:
            return None
        items = (response or {}).get("items", []) or []
        if not items:
            return None
        if target_start:
            for instance in items:
                if not isinstance(instance, dict):
                    continue
                start = instance.get("start", {}) or {}
                start_value = start.get("dateTime") or start.get("date") or ""
                if start_value == target_start:
                    return instance.get("id")
            target_dt = _safe_parse_moment(target_start)
            if target_dt is not None:
                for instance in items:
                    if not isinstance(instance, dict):
                        continue
                    start = instance.get("start", {}) or {}
                    start_value = start.get("dateTime") or start.get("date") or ""
                    instance_dt = _safe_parse_moment(start_value)
                    if instance_dt is not None and instance_dt >= target_dt:
                        return instance.get("id")
        first = items[0]
        return first.get("id") if isinstance(first, dict) else None

    def find_holidays(
        self,
        name_or_range: str,
        preferences: CalendarPreferences,
    ) -> CalendarActionResult:
        start, end, year = _holiday_search_window(name_or_range, preferences.timezone)
        personal_events = self.search_events(
            name_or_range,
            start,
            end,
            calendar_id=preferences.default_calendar_id,
        )
        if personal_events:
            return CalendarActionResult(
                status="answered",
                user_message=f"Found {len(personal_events)} matching personal calendar event(s).",
                data={"source": "personal_calendar", "events": personal_events},
            )

        holidays = _locale_holiday_fallback(name_or_range, preferences.locale_country, year)
        return CalendarActionResult(
            status="answered",
            user_message="No personal calendar match found; using deterministic locale fallback.",
            data={
                "source": "deterministic_locale_fallback",
                "fallback": True,
                "locale_country": preferences.locale_country,
                "holidays": holidays,
            },
        )


def _normalize_event(item: dict[str, Any], calendar_id: str) -> CalendarEvent:
    start = item.get("start", {})
    end = item.get("end", {})
    start_value = start.get("dateTime") or start.get("date") or ""
    end_value = end.get("dateTime") or end.get("date") or start_value
    raw_attendees = item.get("attendees", []) or []
    attendees = [
        attendee["email"]
        for attendee in raw_attendees
        if isinstance(attendee, dict) and attendee.get("email")
    ]
    self_status = ""
    for attendee in raw_attendees:
        if isinstance(attendee, dict) and attendee.get("self"):
            self_status = attendee.get("responseStatus", "") or ""
            break
    organizer = item.get("organizer", {}) or {}
    return CalendarEvent(
        id=item.get("id", ""),
        title=item.get("summary") or "(untitled)",
        start=start_value,
        end=end_value,
        calendar_id=calendar_id,
        link=item.get("htmlLink", ""),
        description=item.get("description", ""),
        attendees=attendees,
        all_day="date" in start and "dateTime" not in start,
        recurring_event_id=item.get("recurringEventId"),
        organizer_email=organizer.get("email", "") if isinstance(organizer, dict) else "",
        self_response_status=self_status,
        status=item.get("status", "") or "",
    )


def _build_update_body(request: UpdateEventRequest) -> tuple[dict[str, Any], list[str]]:
    """Build a sparse patch body from only the fields the caller set."""
    body: dict[str, Any] = {}
    changed: list[str] = []
    all_day = bool(request.all_day) if request.all_day is not None else False
    if request.title is not None:
        body["summary"] = request.title
        changed.append("title")
    if request.description is not None:
        body["description"] = request.description
        changed.append("description")
    if request.start is not None:
        body["start"] = _google_time_body(request.start, all_day=all_day)
        changed.append("start")
    if request.end is not None:
        body["end"] = _google_time_body(request.end, all_day=all_day)
        changed.append("end")
    if request.attendees is not None:
        body["attendees"] = [{"email": email} for email in request.attendees]
        changed.append("attendees")
    if request.recurrence is not None:
        body["recurrence"] = request.recurrence.to_google_rrule()
        changed.append("recurrence")
    if request.all_day is not None and "all_day" not in changed:
        changed.append("all_day")
    return body, changed


def _safe_parse_moment(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return _parse_moment(value)
    except ValueError:
        return None


def _google_time_body(value: str, *, all_day: bool) -> dict[str, str]:
    if all_day:
        return {"date": value[:10]}
    return {"dateTime": value}


def _parse_moment(value: str, reference_tz: tzinfo | None = None) -> datetime:
    if "T" in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = datetime.combine(date.fromisoformat(value[:10]), time.min)
    if parsed.tzinfo is None and reference_tz is not None:
        return parsed.replace(tzinfo=reference_tz)
    return parsed


def _slot(start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": int((end - start).total_seconds() // 60),
    }


def _holiday_search_window(value: str, timezone: str) -> tuple[str, str, int]:
    match = re.search(r"\b(20\d{2})\b", value)
    year = int(match.group(1)) if match else 2026
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        year = int(value[:4])
        return f"{value}T00:00:00", f"{value}T23:59:59", year
    offset = _timezone_offset(timezone)
    return f"{year}-01-01T00:00:00{offset}", f"{year}-12-31T23:59:59{offset}", year


def _timezone_offset(timezone: str) -> str:
    if timezone == "Asia/Calcutta":
        return "+05:30"
    return ""


def _locale_holiday_fallback(query: str, country: str, year: int) -> list[dict[str, str]]:
    if country != "IN":
        return []

    holidays = [
        {"name": "Republic Day", "date": f"{year}-01-26", "country": "IN"},
        {"name": "Independence Day", "date": f"{year}-08-15", "country": "IN"},
        {"name": "Gandhi Jayanti", "date": f"{year}-10-02", "country": "IN"},
    ]
    normalized = query.strip().lower()
    if not normalized:
        return holidays
    matches = [holiday for holiday in holidays if normalized in holiday["name"].lower()]
    return matches or holidays
