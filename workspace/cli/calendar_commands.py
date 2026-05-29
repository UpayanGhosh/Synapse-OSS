"""Calendar connector commands for end-user OAuth setup and verification."""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from synapse_config import write_config

CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

DEFAULT_TIMEZONE = "Asia/Calcutta"
DEFAULT_LOCALE_COUNTRY = "IN"


class CalendarConnectError(RuntimeError):
    """Raised when Calendar cannot be connected or verified."""


@dataclass(slots=True)
class CalendarConnectionResult:
    connected: bool
    token_path: Path | None = None
    credentials_path: Path | None = None
    account: str = ""
    calendar_count: int = 0
    upcoming_count: int = 0
    error: str = ""


def _data_root(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    return Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse")).expanduser()


def _default_google_dir(data_root: Path) -> Path:
    return data_root / "google"


def _default_credentials_path(data_root: Path) -> Path:
    return _default_google_dir(data_root) / "calendar_credentials.json"


def _default_token_path(data_root: Path) -> Path:
    return _default_google_dir(data_root) / "calendar_token.json"


def _load_raw_config(data_root: Path) -> dict[str, Any]:
    path = data_root / "synapse.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CalendarConnectError(f"Could not read synapse.json: {exc}") from exc
    if not isinstance(payload, dict):
        raise CalendarConnectError("synapse.json must be a JSON object")
    return payload


def _resolve_client_secret_path(
    data_root: Path,
    explicit_path: str | Path | None = None,
    raw_config: dict[str, Any] | None = None,
) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())
    env_path = os.environ.get("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    mcp = (raw_config or {}).get("mcp") if isinstance(raw_config, dict) else None
    builtin = (mcp or {}).get("builtin_servers") if isinstance(mcp, dict) else None
    calendar = (builtin or {}).get("calendar") if isinstance(builtin, dict) else None
    credentials_path = (calendar or {}).get("credentials_path") if isinstance(calendar, dict) else None
    if credentials_path:
        candidates.append(Path(str(credentials_path)).expanduser())
    candidates.append(_default_credentials_path(data_root))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise CalendarConnectError(
        "Calendar OAuth client is not configured. For packaged Synapse this should be "
        "bundled by the app. For local OSS/dev installs, pass --client-secret once or set "
        "SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET. Synapse will handle token and synapse.json "
        "updates after that."
    )


def _save_token(token_path: Path, credentials: Any) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = token_path.with_suffix(".json.tmp")
    tmp.write_text(credentials.to_json(), encoding="utf-8")
    os.replace(tmp, token_path)
    with contextlib.suppress(OSError):
        os.chmod(token_path, 0o600)


def _update_calendar_config(
    *,
    data_root: Path,
    credentials_path: Path,
    token_path: Path,
    default_calendar_id: str,
    timezone: str,
    locale_country: str,
    trusted_quick_add: bool,
    default_event_duration_minutes: int,
    allow_open_ended_recurring_personal_events: bool,
) -> None:
    config = _load_raw_config(data_root)
    mcp = config.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise CalendarConnectError("synapse.json mcp section must be a JSON object")
    mcp["enabled"] = True

    builtin = mcp.setdefault("builtin_servers", {})
    if not isinstance(builtin, dict):
        raise CalendarConnectError("synapse.json mcp.builtin_servers must be a JSON object")
    calendar_cfg = builtin.setdefault("calendar", {})
    if not isinstance(calendar_cfg, dict):
        raise CalendarConnectError("synapse.json mcp.builtin_servers.calendar must be an object")
    calendar_cfg.update(
        {
            "enabled": True,
            "credentials_path": str(credentials_path),
            "token_path": str(token_path),
        }
    )

    prefs = mcp.setdefault("calendar_preferences", {})
    if not isinstance(prefs, dict):
        raise CalendarConnectError("synapse.json mcp.calendar_preferences must be an object")
    prefs.update(
        {
            "default_calendar_id": default_calendar_id,
            "timezone": timezone,
            "locale_country": locale_country,
            "trusted_quick_add": trusted_quick_add,
            "default_event_duration_minutes": int(default_event_duration_minutes),
            "allow_open_ended_recurring_personal_events": (
                allow_open_ended_recurring_personal_events
            ),
        }
    )

    write_config(data_root, config)


def _default_flow_factory(credentials_path: Path, scopes: tuple[str, ...]):
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise CalendarConnectError(
            "google-auth-oauthlib is not installed. Install Synapse calendar extras or run "
            "`pip install google-auth-oauthlib google-api-python-client google-auth-httplib2`."
        ) from exc
    return InstalledAppFlow.from_client_secrets_file(str(credentials_path), list(scopes))


def _default_service_builder(token_path: Path, scopes: tuple[str, ...]):
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise CalendarConnectError(
            "Google Calendar client libraries are not installed. Install Synapse calendar "
            "extras or run `pip install google-api-python-client google-auth-oauthlib`."
        ) from exc
    creds = Credentials.from_authorized_user_file(str(token_path), list(scopes))
    return build("calendar", "v3", credentials=creds)


def _default_credentials_loader(token_path: Path, scopes: tuple[str, ...]):
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise CalendarConnectError(
            "google-auth is not installed. Install Synapse calendar extras."
        ) from exc
    return Credentials.from_authorized_user_file(str(token_path), list(scopes))


def _default_request_factory():
    try:
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise CalendarConnectError(
            "google-auth transport requests are not installed. Install Synapse calendar extras."
        ) from exc
    return Request()


def _default_service_factory(credentials: Any):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise CalendarConnectError(
            "google-api-python-client is not installed. Install Synapse calendar extras."
        ) from exc
    return build("calendar", "v3", credentials=credentials)


def _verify_with_service(service: Any, *, default_calendar_id: str) -> tuple[int, int]:
    calendars = (
        service.calendarList()
        .list(maxResults=10)
        .execute()
        .get("items", [])
    )
    now = datetime.now(UTC).isoformat()
    events = (
        service.events()
        .list(
            calendarId=default_calendar_id,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    return len(calendars), len(events)


def _configured_calendar_token(
    data_root: Path,
    *,
    raw_config: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    config = raw_config if raw_config is not None else _load_raw_config(data_root)
    mcp = config.get("mcp") if isinstance(config, dict) else None
    builtin = (mcp or {}).get("builtin_servers") if isinstance(mcp, dict) else None
    calendar = (builtin or {}).get("calendar") if isinstance(builtin, dict) else None
    if not isinstance(calendar, dict) or not calendar.get("enabled", True):
        raise CalendarConnectError("Calendar not configured. Run `synapse calendar connect`.")
    token_path = str(calendar.get("token_path", "")).strip()
    if not token_path:
        raise CalendarConnectError("Calendar token path missing. Run `synapse calendar connect`.")
    prefs = (mcp or {}).get("calendar_preferences") if isinstance(mcp, dict) else None
    default_calendar_id = "primary"
    if isinstance(prefs, dict):
        default_calendar_id = str(prefs.get("default_calendar_id") or "primary")
    return Path(token_path).expanduser(), default_calendar_id


def connect_calendar(
    *,
    data_root: Path | None = None,
    client_secret_path: str | Path | None = None,
    default_calendar_id: str = "primary",
    timezone: str = DEFAULT_TIMEZONE,
    locale_country: str = DEFAULT_LOCALE_COUNTRY,
    trusted_quick_add: bool = True,
    default_event_duration_minutes: int = 60,
    allow_open_ended_recurring_personal_events: bool = True,
    open_browser: bool = True,
    flow_factory: Callable[[Path, tuple[str, ...]], Any] | None = None,
    service_builder: Callable[[Path, tuple[str, ...]], Any] | None = None,
) -> CalendarConnectionResult:
    """Run OAuth, persist token/config, and verify real Calendar API access."""
    root = _data_root(data_root)
    raw_config = _load_raw_config(root)
    credentials_path = _resolve_client_secret_path(root, client_secret_path, raw_config)
    token_path = _default_token_path(root)
    flow = (flow_factory or _default_flow_factory)(credentials_path, CALENDAR_SCOPES)
    try:
        credentials = flow.run_local_server(
            port=0,
            open_browser=open_browser,
            prompt="consent",
            authorization_prompt_message=(
                "Opening Google Calendar authorization in your browser..."
            ),
        )
    except Exception as exc:
        raise CalendarConnectError(f"Google Calendar OAuth failed: {exc}") from exc

    _save_token(token_path, credentials)
    _update_calendar_config(
        data_root=root,
        credentials_path=credentials_path,
        token_path=token_path,
        default_calendar_id=default_calendar_id,
        timezone=timezone,
        locale_country=locale_country,
        trusted_quick_add=trusted_quick_add,
        default_event_duration_minutes=default_event_duration_minutes,
        allow_open_ended_recurring_personal_events=allow_open_ended_recurring_personal_events,
    )

    service = (service_builder or _default_service_builder)(token_path, CALENDAR_SCOPES)
    calendar_count, upcoming_count = _verify_with_service(
        service,
        default_calendar_id=default_calendar_id,
    )
    return CalendarConnectionResult(
        connected=True,
        token_path=token_path,
        credentials_path=credentials_path,
        account=getattr(credentials, "account", "") or "",
        calendar_count=calendar_count,
        upcoming_count=upcoming_count,
    )


def verify_calendar_connection(
    *,
    data_root: Path | None = None,
    credentials_loader: Callable[[Path, tuple[str, ...]], Any] | None = None,
    request_factory: Callable[[], Any] | None = None,
    service_factory: Callable[[Any], Any] | None = None,
) -> CalendarConnectionResult:
    """Verify configured Calendar token and refresh it if needed."""
    root = _data_root(data_root)
    try:
        token_path, default_calendar_id = _configured_calendar_token(root)
        if not token_path.exists():
            raise CalendarConnectError(
                f"Calendar token file missing at {token_path}. Run `synapse calendar connect`."
            )
        credentials = (credentials_loader or _default_credentials_loader)(
            token_path, CALENDAR_SCOPES
        )
        if getattr(credentials, "expired", False):
            refresh_token = getattr(credentials, "refresh_token", None)
            if not refresh_token:
                raise CalendarConnectError(
                    "Calendar token is expired and has no refresh token. "
                    "Run `synapse calendar connect` again."
                )
            credentials.refresh((request_factory or _default_request_factory)())
            _save_token(token_path, credentials)
        service = (service_factory or _default_service_factory)(credentials)
        calendar_count, upcoming_count = _verify_with_service(
            service,
            default_calendar_id=default_calendar_id,
        )
        return CalendarConnectionResult(
            connected=True,
            token_path=token_path,
            account=getattr(credentials, "account", "") or "",
            calendar_count=calendar_count,
            upcoming_count=upcoming_count,
        )
    except CalendarConnectError as exc:
        return CalendarConnectionResult(connected=False, error=str(exc))
    except Exception as exc:
        return CalendarConnectionResult(connected=False, error=f"Calendar verify failed: {exc}")


def calendar_status(data_root: Path | None = None) -> CalendarConnectionResult:
    """Return local Calendar config status without making network calls."""
    root = _data_root(data_root)
    try:
        token_path, _calendar_id = _configured_calendar_token(root)
        return CalendarConnectionResult(
            connected=token_path.exists(),
            token_path=token_path,
            error="" if token_path.exists() else f"Calendar token file missing at {token_path}",
        )
    except CalendarConnectError as exc:
        return CalendarConnectionResult(connected=False, error=str(exc))


def disconnect_calendar(data_root: Path | None = None) -> bool:
    """Disable Calendar MCP config and remove the saved token file when present."""
    root = _data_root(data_root)
    config = _load_raw_config(root)
    removed = False
    with contextlib.suppress(CalendarConnectError, OSError):
        token_path, _ = _configured_calendar_token(root, raw_config=config)
        if token_path.exists():
            token_path.unlink()
            removed = True
    mcp = config.get("mcp")
    if isinstance(mcp, dict):
        builtin = mcp.get("builtin_servers")
        if isinstance(builtin, dict):
            calendar = builtin.get("calendar")
            if isinstance(calendar, dict):
                calendar["enabled"] = False
    write_config(root, config)
    return removed
