"""Per-integration verification handlers.

Each handler receives a refreshed Google ``Credentials`` instance (or an
equivalent auth object) and returns a dict that the manager merges into the
``ConnectionResult.details`` for display. Handlers should be cheap, fail
loud, and never modify state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from .errors import IntegrationError


VerifyHandler = Callable[[Any], dict[str, Any]]


def _verify_google_calendar(credentials: Any) -> dict[str, Any]:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise IntegrationError(
            "google-api-python-client is not installed. Install Synapse calendar extras."
        ) from exc

    service = build("calendar", "v3", credentials=credentials)
    calendars = (
        service.calendarList().list(maxResults=10).execute().get("items", []) or []
    )
    primary_id = next(
        (item.get("id") for item in calendars if item.get("primary")),
        "primary",
    )
    now = datetime.now(UTC).isoformat()
    upcoming = (
        service.events()
        .list(
            calendarId=primary_id,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
        or []
    )
    return {
        "calendar_count": len(calendars),
        "upcoming_count": len(upcoming),
        "primary_calendar_id": primary_id,
    }


def _verify_gmail(credentials: Any) -> dict[str, Any]:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise IntegrationError(
            "google-api-python-client is not installed. Install Synapse Gmail extras."
        ) from exc

    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute() or {}
    return {
        "email_address": profile.get("emailAddress", ""),
        "messages_total": profile.get("messagesTotal", 0),
        "threads_total": profile.get("threadsTotal", 0),
    }


_HANDLERS: dict[str, VerifyHandler] = {
    "google_calendar": _verify_google_calendar,
    "gmail": _verify_gmail,
}


def verify_handler_for(integration_name: str) -> VerifyHandler | None:
    return _HANDLERS.get(integration_name)


def register_verify_handler(integration_name: str, handler: VerifyHandler) -> None:
    """Tests use this to inject a verify handler without touching real Google APIs."""
    _HANDLERS[integration_name] = handler
