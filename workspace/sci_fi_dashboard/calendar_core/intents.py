from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re

from .date_math import resolve_date_phrase
from .models import AvailabilityRequest, CreateEventRequest, RecurrenceRule


@dataclass(slots=True)
class CalendarIntent:
    kind: str
    create: CreateEventRequest | None = None
    availability: AvailabilityRequest | None = None
    query: str = ""
    confidence: float = 0.0


def parse_calendar_intent(
    text: str,
    *,
    base_date: date | None = None,
    timezone: str = "Asia/Calcutta",
    default_duration_minutes: int = 60,
) -> CalendarIntent:
    original = text.strip()
    normalized = _normalize(original)
    base = base_date or date.today()
    offset = _timezone_offset(timezone)
    if not normalized:
        return CalendarIntent(kind="unknown", query=original, confidence=0.0)

    if _is_holiday(normalized):
        return CalendarIntent(kind="holiday", query=_clean_query(original), confidence=0.9)

    birthday = _parse_annual_all_day(original, normalized, base)
    if birthday is not None:
        return CalendarIntent(kind="create_event", create=birthday, query=original, confidence=birthday.parse_confidence)

    if _is_availability(normalized):
        request = _availability_request(normalized, base, offset, default_duration_minutes)
        return CalendarIntent(kind="availability", availability=request, query=original, confidence=0.85)

    if _is_list_or_search(normalized):
        request = _full_day_request(normalized, base, offset)
        kind = "search_events" if _looks_like_search(normalized) else "list_events"
        return CalendarIntent(kind=kind, availability=request, query=_search_query(original), confidence=0.8)

    if _is_create(normalized):
        request = _create_request(original, normalized, base, offset, default_duration_minutes)
        if request is None:
            return CalendarIntent(kind="unknown", query=original, confidence=0.2)
        return CalendarIntent(kind="create_event", create=request, query=original, confidence=request.parse_confidence)

    return CalendarIntent(kind="unknown", query=original, confidence=0.0)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _timezone_offset(timezone: str) -> str:
    if timezone == "Asia/Calcutta":
        return "+05:30"
    return ""


def _is_holiday(text: str) -> bool:
    return bool(re.search(r"\bholidays?\b", text))


def _is_availability(text: str) -> bool:
    return bool(
        re.search(r"\bam i free\b|\bfree slot\b|\bfree slots\b|\bavailable\b", text)
        or re.search(r"\bfind me\b.*\b\d+\s*(?:min|minute|minutes)\b", text)
    )


def _is_list_or_search(text: str) -> bool:
    return bool(
        re.search(
            r"\bwhat do i have\b|\bwhat meetings\b|\bmy meetings\b|\bmy events\b|"
            r"\blist\b.*\b(events|meetings|calendar)\b|\bshow\b.*\b(events|meetings|calendar)\b",
            text,
        )
        and not _is_create(text)
    )


def _looks_like_search(text: str) -> bool:
    return bool(re.search(r"\bsearch\b|\bfind\b|\blook for\b", text))


def _is_create(text: str) -> bool:
    return bool(re.search(r"\b(add|schedule|put|create|remember)\b", text))


def _recurrence(text: str) -> RecurrenceRule | None:
    if re.search(r"\bevery\s+day\b|\bdaily\b", text):
        return RecurrenceRule("daily")
    if re.search(r"\bevery\s+year\b|\byearly\b|\bannually\b", text):
        return RecurrenceRule("yearly")
    if re.search(r"\bevery\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|\bweekly\b", text):
        return RecurrenceRule("weekly")
    if re.search(r"\bevery\s+month\b|\bmonthly\b", text):
        return RecurrenceRule("monthly")
    return None


def _parse_annual_all_day(original: str, normalized: str, base: date) -> CreateEventRequest | None:
    if not re.search(r"\b(birthday|anniversary)\b", normalized):
        return None
    resolved = resolve_date_phrase(normalized, base_date=base)
    if resolved.date is None:
        return None
    title_match = re.search(
        r"\b(?:remember|add|create)?\s*(.+?\b(?:birthday|anniversary))\b",
        original,
        flags=re.IGNORECASE,
    )
    title = title_match.group(1).strip() if title_match else "Annual event"
    start = resolved.date.isoformat()
    end = (resolved.date + timedelta(days=1)).isoformat()
    return CreateEventRequest(
        title=title,
        start=start,
        end=end,
        all_day=True,
        recurrence=RecurrenceRule("yearly"),
        parse_confidence=min(0.95, max(0.85, resolved.confidence)),
    )


def _availability_request(
    normalized: str,
    base: date,
    offset: str,
    default_duration_minutes: int,
) -> AvailabilityRequest:
    resolved = resolve_date_phrase(normalized, base_date=base)
    if resolved.start is not None and resolved.end is not None:
        start = _with_offset(resolved.start, offset)
        end = _with_offset(resolved.end, offset)
    else:
        day = resolved.date or base
        start = _with_offset(datetime.combine(day, time.min), offset)
        end = _with_offset(datetime.combine(day + timedelta(days=1), time.min), offset)
    duration = _duration_minutes(normalized) or default_duration_minutes
    return AvailabilityRequest(start=start, end=end, duration_minutes=duration)


def _full_day_request(normalized: str, base: date, offset: str) -> AvailabilityRequest:
    resolved = resolve_date_phrase(normalized, base_date=base)
    day = resolved.date or base
    start = _with_offset(datetime.combine(day, time.min), offset)
    end = _with_offset(datetime.combine(day + timedelta(days=1), time.min), offset)
    return AvailabilityRequest(start=start, end=end)


def _create_request(
    original: str,
    normalized: str,
    base: date,
    offset: str,
    default_duration_minutes: int,
) -> CreateEventRequest | None:
    resolved = resolve_date_phrase(normalized, base_date=base)
    event_date = resolved.date or base
    parsed_time = _parse_time(normalized)
    recurrence = _recurrence(normalized)
    title = _title_from_create(original)
    confidence = min(0.95, max(0.75, resolved.confidence or 0.75))

    if parsed_time is None:
        start_date = event_date.isoformat()
        end_date = (event_date + timedelta(days=1)).isoformat()
        return CreateEventRequest(
            title=title,
            start=start_date,
            end=end_date,
            all_day=True,
            recurrence=recurrence,
            parse_confidence=confidence,
        )

    start_dt = datetime.combine(event_date, parsed_time)
    end_dt = start_dt + timedelta(minutes=default_duration_minutes)
    return CreateEventRequest(
        title=title,
        start=_with_offset(start_dt, offset),
        end=_with_offset(end_dt, offset),
        recurrence=recurrence,
        parse_confidence=confidence,
    )


def _parse_time(text: str) -> time | None:
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        meridiem = match.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return time(hour, minute)

    match = re.search(r"\bat\s+([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if match:
        return time(int(match.group(1)), int(match.group(2)))
    return None


def _duration_minutes(text: str) -> int | None:
    match = re.search(r"\b(\d+)\s*(?:min|minute|minutes)\b", text)
    return int(match.group(1)) if match else None


def _title_from_create(original: str) -> str:
    stripped = re.sub(r"^\s*(add|schedule|put|create|remember)\s+", "", original.strip(), flags=re.IGNORECASE)
    split = re.split(
        r"\s+(?:every\s+day|daily|weekly|monthly|yearly|every\s+year|every\s+month|every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|at\s+\d|starting\s+|on\s+|tomorrow|today|next\s+)",
        stripped,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    title = split[0].strip(" .")
    return title or "Calendar event"


def _with_offset(value: datetime, offset: str) -> str:
    return f"{value.isoformat()}{offset}" if offset and value.tzinfo is None else value.isoformat()


def _clean_query(text: str) -> str:
    cleaned = re.sub(r"\b(when is|what are|show me|holiday|holidays)\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" ?") or text.strip()


def _search_query(text: str) -> str:
    cleaned = re.sub(r"\b(what do i have|what meetings do i have|show me|list|calendar|events|meetings)\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" ?")
