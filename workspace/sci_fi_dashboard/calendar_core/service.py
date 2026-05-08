from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
import re
from typing import Any

from .models import (
    CalendarActionResult,
    CalendarConflict,
    CalendarEvent,
    CalendarPreferences,
    CreateEventRequest,
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
    attendees = [
        attendee["email"]
        for attendee in item.get("attendees", [])
        if isinstance(attendee, dict) and attendee.get("email")
    ]
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
    )


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
