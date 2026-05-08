from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

RecurrenceFrequency = Literal["daily", "weekly", "monthly", "yearly"]
ActionStatus = Literal["created", "answered", "confirmation_required", "failed"]


def _require_nonblank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _parse_iso_date_or_datetime(value: str) -> date | datetime | None:
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_ordered_range(start: str, end: str) -> None:
    parsed_start = _parse_iso_date_or_datetime(start)
    parsed_end = _parse_iso_date_or_datetime(end)
    if parsed_start is None or parsed_end is None:
        return
    if type(parsed_start) is not type(parsed_end):
        raise ValueError("start and end must use matching date/datetime formats")
    if isinstance(parsed_start, datetime) and isinstance(parsed_end, datetime):
        start_is_aware = parsed_start.tzinfo is not None and parsed_start.utcoffset() is not None
        end_is_aware = parsed_end.tzinfo is not None and parsed_end.utcoffset() is not None
        if start_is_aware != end_is_aware:
            raise ValueError("start and end datetime values must use matching timezone awareness")
    if parsed_end <= parsed_start:
        raise ValueError("end must be after start")


@dataclass(slots=True)
class CalendarPreferences:
    default_calendar_id: str = "primary"
    timezone: str = "Asia/Calcutta"
    locale_country: str = "IN"
    trusted_quick_add: bool = True
    default_event_duration_minutes: int = 60
    allow_open_ended_recurring_personal_events: bool = True


@dataclass(slots=True)
class RecurrenceRule:
    frequency: RecurrenceFrequency
    until: str | None = None
    count: int | None = None

    def __post_init__(self) -> None:
        if self.frequency not in {"daily", "weekly", "monthly", "yearly"}:
            raise ValueError(f"Unsupported recurrence frequency: {self.frequency}")
        if self.until and self.count is not None:
            raise ValueError("until and count cannot both be set")
        if self.count is not None and self.count <= 0:
            raise ValueError("count must be greater than 0")

    def to_google_rrule(self) -> list[str]:
        parts = [f"FREQ={self.frequency.upper()}"]
        if self.until:
            parts.append(f"UNTIL={self.until}")
        if self.count is not None:
            parts.append(f"COUNT={self.count}")
        return [f"RRULE:{';'.join(parts)}"]

    def summary(self) -> str:
        labels = {
            "daily": "every day",
            "weekly": "every week",
            "monthly": "every month",
            "yearly": "every year",
        }
        return labels[self.frequency]


@dataclass(slots=True)
class CreateEventRequest:
    title: str
    start: str
    end: str
    calendar_id: str = "primary"
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    all_day: bool = False
    recurrence: RecurrenceRule | None = None
    parse_confidence: float = 1.0

    def __post_init__(self) -> None:
        _require_nonblank(self.title, "title")
        _require_nonblank(self.start, "start")
        _require_nonblank(self.end, "end")
        if not 0.0 <= self.parse_confidence <= 1.0:
            raise ValueError("parse_confidence must be between 0.0 and 1.0")
        _validate_ordered_range(self.start, self.end)


@dataclass(slots=True)
class AvailabilityRequest:
    start: str
    end: str
    calendar_id: str = "primary"
    duration_minutes: int | None = None

    def __post_init__(self) -> None:
        _require_nonblank(self.start, "start")
        _require_nonblank(self.end, "end")
        if self.duration_minutes is not None and self.duration_minutes <= 0:
            raise ValueError("duration_minutes must be greater than 0")
        _validate_ordered_range(self.start, self.end)


@dataclass(slots=True)
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    calendar_id: str = "primary"
    link: str = ""
    description: str = ""
    attendees: list[str] = field(default_factory=list)
    all_day: bool = False


@dataclass(slots=True)
class CalendarConflict:
    title: str
    start: str
    end: str
    event_id: str | None = None
    link: str = ""


@dataclass(slots=True)
class ConfirmationRequired:
    message: str
    reasons: list[str] = field(default_factory=list)
    request: CreateEventRequest | None = None
    conflicts: list[CalendarConflict] = field(default_factory=list)


@dataclass(slots=True)
class CalendarActionResult:
    status: ActionStatus
    user_message: str
    receipt_evidence: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    confirmation: ConfirmationRequired | None = None

    @classmethod
    def created(
        cls,
        *,
        event_id: str,
        link: str,
        title: str,
        start: str,
        end: str,
    ) -> CalendarActionResult:
        evidence = f"Created Google Calendar event id={event_id}"
        if link:
            evidence = f"{evidence} link={link}"
        return cls(
            status="created",
            user_message=f"Created calendar event '{title}' from {start} to {end}.",
            receipt_evidence=evidence,
            data={
                "event_id": event_id,
                "link": link,
                "title": title,
                "start": start,
                "end": end,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
