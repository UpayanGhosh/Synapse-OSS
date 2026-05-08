from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re


@dataclass(slots=True)
class DateResolution:
    date: date | None
    start: datetime | None
    end: datetime | None
    confidence: float
    source: str


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}

DAYPARTS = {
    "morning": (time(9, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(21, 0)),
    "night": (time(21, 0), time(23, 59)),
}


def resolve_date_phrase(phrase: str, *, base_date: date | None = None) -> DateResolution:
    base = base_date or date.today()
    normalized = _normalize(phrase)
    if not normalized:
        return _unrecognized()

    resolved = (
        _resolve_iso_date(normalized)
        or _resolve_ordinal_weekday_of_month(normalized, base)
        or _resolve_month_day(normalized, base)
        or _resolve_relative_day(normalized, base)
        or _resolve_weekday(normalized, base)
    )
    if resolved is None:
        return _unrecognized()

    daypart = _find_daypart(normalized)
    if daypart is not None:
        start_time, end_time = daypart
        return DateResolution(
            date=resolved.date,
            start=datetime.combine(resolved.date, start_time),
            end=datetime.combine(resolved.date, end_time),
            confidence=min(1.0, resolved.confidence + 0.05),
            source=f"{resolved.source}+daypart",
        )
    return resolved


def _normalize(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase.strip().lower())


def _unrecognized() -> DateResolution:
    return DateResolution(date=None, start=None, end=None, confidence=0.0, source="unrecognized")


def _date_only(resolved_date: date, confidence: float, source: str) -> DateResolution:
    return DateResolution(
        date=resolved_date,
        start=None,
        end=None,
        confidence=confidence,
        source=source,
    )


def _resolve_iso_date(phrase: str) -> DateResolution | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", phrase)
    if not match:
        return None
    try:
        return _date_only(date.fromisoformat(match.group(1)), 1.0, "iso_date")
    except ValueError:
        return None


def _resolve_relative_day(phrase: str, base: date) -> DateResolution | None:
    relative_days = {
        "today": 0,
        "tomorrow": 1,
        "yesterday": -1,
    }
    for word, offset in relative_days.items():
        if re.search(rf"\b{word}\b", phrase):
            return _date_only(base + timedelta(days=offset), 0.95, word)
    return None


def _resolve_weekday(phrase: str, base: date) -> DateResolution | None:
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\bnext\s+{name}\b", phrase):
            days_ahead = (weekday - base.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return _date_only(base + timedelta(days=days_ahead), 0.9, "next_weekday")

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", phrase):
            days_ahead = (weekday - base.weekday()) % 7
            return _date_only(base + timedelta(days=days_ahead), 0.8, "weekday")
    return None


def _resolve_ordinal_weekday_of_month(phrase: str, base: date) -> DateResolution | None:
    match = re.search(
        r"\b(first|second|third|fourth|last)\s+"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+"
        r"of\s+([a-z]+)\b",
        phrase,
    )
    if not match:
        return None

    ordinal, weekday_name, month_name = match.groups()
    month = MONTHS.get(month_name)
    if month is None:
        return None

    year = base.year if month >= base.month else base.year + 1
    weekday = WEEKDAYS[weekday_name]
    if ordinal == "last":
        resolved = _last_weekday_of_month(year, month, weekday)
    else:
        resolved = _nth_weekday_of_month(year, month, weekday, ORDINALS[ordinal])
    if resolved is None:
        return None
    if resolved < base:
        if ordinal == "last":
            resolved = _last_weekday_of_month(year + 1, month, weekday)
        else:
            resolved = _nth_weekday_of_month(year + 1, month, weekday, ORDINALS[ordinal])
        if resolved is None:
            return None
    return _date_only(resolved, 0.9, "ordinal_weekday_of_month")


def _nth_weekday_of_month(year: int, month: int, weekday: int, ordinal: int) -> date | None:
    current = date(year, month, 1)
    days_ahead = (weekday - current.weekday()) % 7
    resolved = current + timedelta(days=days_ahead + (ordinal - 1) * 7)
    if resolved.month != month:
        return None
    return resolved


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    current = date(year, month, monthrange(year, month)[1])
    days_back = (current.weekday() - weekday) % 7
    return current - timedelta(days=days_back)


def _resolve_month_day(phrase: str, base: date) -> DateResolution | None:
    month_pattern = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", phrase)
    if not match:
        return None

    month_name, day_text = match.groups()
    month = MONTHS[month_name]
    day = int(day_text)
    try:
        resolved = date(base.year, month, day)
    except ValueError:
        return None
    if resolved < base:
        resolved = date(base.year + 1, month, day)
    return _date_only(resolved, 0.85, "month_day")


def _find_daypart(phrase: str) -> tuple[time, time] | None:
    for name, value in DAYPARTS.items():
        if re.search(rf"\b{name}\b", phrase):
            return value
    return None
