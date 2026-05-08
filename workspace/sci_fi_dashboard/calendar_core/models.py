from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal

RecurrenceFrequency = Literal["daily", "weekly", "monthly", "yearly"]
ActionStatus = Literal[
    "created",
    "answered",
    "confirmation_required",
    "updated",
    "deleted",
    "moved",
    "rsvp_recorded",
    "failed",
]
ModificationScope = Literal["thisEventOnly", "thisAndFollowing", "all"]
SendUpdates = Literal["all", "externalOnly", "none"]
RsvpResponse = Literal["accepted", "declined", "tentative", "needsAction"]


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
    send_updates: SendUpdates = "none"

    def __post_init__(self) -> None:
        _require_nonblank(self.title, "title")
        _require_nonblank(self.start, "start")
        _require_nonblank(self.end, "end")
        if not 0.0 <= self.parse_confidence <= 1.0:
            raise ValueError("parse_confidence must be between 0.0 and 1.0")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")
        _validate_ordered_range(self.start, self.end)


@dataclass(slots=True)
class UpdateEventRequest:
    event_id: str
    calendar_id: str = "primary"
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    attendees: list[str] | None = None
    all_day: bool | None = None
    recurrence: RecurrenceRule | None = None
    modification_scope: ModificationScope = "thisEventOnly"
    instance_id: str | None = None
    send_updates: SendUpdates = "none"
    parse_confidence: float = 1.0

    def __post_init__(self) -> None:
        _require_nonblank(self.event_id, "event_id")
        _require_nonblank(self.calendar_id, "calendar_id")
        if self.title is not None and not self.title.strip():
            raise ValueError("title must not be blank when provided")
        if self.modification_scope not in {"thisEventOnly", "thisAndFollowing", "all"}:
            raise ValueError(f"Unsupported modification_scope: {self.modification_scope}")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")
        if not 0.0 <= self.parse_confidence <= 1.0:
            raise ValueError("parse_confidence must be between 0.0 and 1.0")
        if self.start is not None and self.end is not None:
            _validate_ordered_range(self.start, self.end)
        if (
            self.modification_scope in {"thisEventOnly", "thisAndFollowing"}
            and self.instance_id is None
            and (self.start is not None or self.end is not None)
        ):
            # instance_id is preferred for scope=thisEventOnly; allow callers
            # to pass start/end and let service.update_event resolve the
            # instance via events.instances. Fail-fast guard: at least one
            # locator must exist.
            pass
        if not any(
            field_value is not None
            for field_value in (
                self.title,
                self.start,
                self.end,
                self.description,
                self.attendees,
                self.all_day,
                self.recurrence,
            )
        ):
            raise ValueError("UpdateEventRequest must specify at least one field to change")


@dataclass(slots=True)
class DeleteEventRequest:
    event_id: str
    calendar_id: str = "primary"
    modification_scope: ModificationScope = "thisEventOnly"
    instance_id: str | None = None
    send_updates: SendUpdates = "none"

    def __post_init__(self) -> None:
        _require_nonblank(self.event_id, "event_id")
        _require_nonblank(self.calendar_id, "calendar_id")
        if self.modification_scope not in {"thisEventOnly", "thisAndFollowing", "all"}:
            raise ValueError(f"Unsupported modification_scope: {self.modification_scope}")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")


@dataclass(slots=True)
class MoveEventRequest:
    event_id: str
    source_calendar_id: str
    destination_calendar_id: str
    send_updates: SendUpdates = "none"

    def __post_init__(self) -> None:
        _require_nonblank(self.event_id, "event_id")
        _require_nonblank(self.source_calendar_id, "source_calendar_id")
        _require_nonblank(self.destination_calendar_id, "destination_calendar_id")
        if self.source_calendar_id == self.destination_calendar_id:
            raise ValueError("source and destination calendars must differ")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")


@dataclass(slots=True)
class RsvpRequest:
    event_id: str
    response: RsvpResponse
    calendar_id: str = "primary"
    attendee_email: str | None = None
    send_updates: SendUpdates = "none"

    def __post_init__(self) -> None:
        _require_nonblank(self.event_id, "event_id")
        _require_nonblank(self.calendar_id, "calendar_id")
        if self.response not in {"accepted", "declined", "tentative", "needsAction"}:
            raise ValueError(f"Unsupported RSVP response: {self.response}")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")


@dataclass(slots=True)
class FreeBusyRequest:
    start: str
    end: str
    calendar_ids: list[str] = field(default_factory=lambda: ["primary"])

    def __post_init__(self) -> None:
        _require_nonblank(self.start, "start")
        _require_nonblank(self.end, "end")
        if not self.calendar_ids:
            raise ValueError("calendar_ids must include at least one calendar")
        for cid in self.calendar_ids:
            if not cid or not cid.strip():
                raise ValueError("calendar_ids must not contain blank entries")
        _validate_ordered_range(self.start, self.end)


@dataclass(slots=True)
class QuickAddRequest:
    text: str
    calendar_id: str = "primary"
    send_updates: SendUpdates = "none"

    def __post_init__(self) -> None:
        _require_nonblank(self.text, "text")
        _require_nonblank(self.calendar_id, "calendar_id")
        if self.send_updates not in {"all", "externalOnly", "none"}:
            raise ValueError(f"Unsupported send_updates: {self.send_updates}")


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
    recurring_event_id: str | None = None
    organizer_email: str = ""
    self_response_status: str = ""
    status: str = ""


@dataclass(slots=True)
class CalendarListEntry:
    id: str
    summary: str
    primary: bool = False
    description: str = ""
    time_zone: str = ""
    access_role: str = ""
    background_color: str = ""
    foreground_color: str = ""
    selected: bool = True


@dataclass(slots=True)
class ColorPalette:
    event_colors: dict[str, dict[str, str]] = field(default_factory=dict)
    calendar_colors: dict[str, dict[str, str]] = field(default_factory=dict)
    updated: str = ""


@dataclass(slots=True)
class FreeBusyWindow:
    start: str
    end: str


@dataclass(slots=True)
class FreeBusyResult:
    calendars: dict[str, list[FreeBusyWindow]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    time_min: str = ""
    time_max: str = ""


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

    @classmethod
    def updated(
        cls,
        *,
        event_id: str,
        link: str,
        title: str,
        modification_scope: ModificationScope,
        changed_fields: list[str],
    ) -> CalendarActionResult:
        evidence = (
            f"Updated Google Calendar event id={event_id} scope={modification_scope}"
        )
        if link:
            evidence = f"{evidence} link={link}"
        return cls(
            status="updated",
            user_message=(
                f"Updated calendar event '{title}' "
                f"({', '.join(changed_fields) or 'no fields'})."
            ),
            receipt_evidence=evidence,
            data={
                "event_id": event_id,
                "link": link,
                "title": title,
                "modification_scope": modification_scope,
                "changed_fields": list(changed_fields),
            },
        )

    @classmethod
    def deleted(
        cls,
        *,
        event_id: str,
        title: str,
        modification_scope: ModificationScope,
    ) -> CalendarActionResult:
        return cls(
            status="deleted",
            user_message=f"Deleted calendar event '{title}'.",
            receipt_evidence=(
                f"Deleted Google Calendar event id={event_id} scope={modification_scope}"
            ),
            data={
                "event_id": event_id,
                "title": title,
                "modification_scope": modification_scope,
            },
        )

    @classmethod
    def moved(
        cls,
        *,
        event_id: str,
        link: str,
        title: str,
        source_calendar_id: str,
        destination_calendar_id: str,
    ) -> CalendarActionResult:
        evidence = (
            f"Moved Google Calendar event id={event_id} "
            f"from={source_calendar_id} to={destination_calendar_id}"
        )
        if link:
            evidence = f"{evidence} link={link}"
        return cls(
            status="moved",
            user_message=(
                f"Moved calendar event '{title}' from {source_calendar_id} "
                f"to {destination_calendar_id}."
            ),
            receipt_evidence=evidence,
            data={
                "event_id": event_id,
                "link": link,
                "title": title,
                "source_calendar_id": source_calendar_id,
                "destination_calendar_id": destination_calendar_id,
            },
        )

    @classmethod
    def rsvp_recorded(
        cls,
        *,
        event_id: str,
        title: str,
        response: RsvpResponse,
        attendee_email: str,
    ) -> CalendarActionResult:
        return cls(
            status="rsvp_recorded",
            user_message=f"Recorded {response} for '{title}'.",
            receipt_evidence=(
                f"Patched Google Calendar event id={event_id} "
                f"attendee={attendee_email} response={response}"
            ),
            data={
                "event_id": event_id,
                "title": title,
                "response": response,
                "attendee_email": attendee_email,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
