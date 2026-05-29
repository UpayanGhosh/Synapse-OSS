"""Generic connect / verify / status / disconnect / list operations.

Every integration goes through this single entry point. Adding a new
service is a new ``IntegrationDefinition`` in ``registry.py`` and (for
non-OAuth flows) optionally a custom auth handler — never new CLI plumbing.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from . import config as integrations_config
from .errors import IntegrationError
from .oauth_flow import run_oauth_desktop_flow
from .registry import IntegrationDefinition, get_integration, list_definitions
from .token_store import (
    data_root as _data_root,
    delete_token,
    find_existing_token,
    save_credentials,
    token_path as _token_path,
)
from .verify_handlers import verify_handler_for


@dataclass(slots=True)
class ConnectionResult:
    integration: str
    connected: bool
    token_path: Path | None = None
    account_email: str = ""
    enabled: bool = False
    auth_type: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    used_override: bool = False


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


def connect(
    integration_name: str,
    *,
    data_root: Path | None = None,
    override_client_path: str | Path | None = None,
    open_browser: bool = True,
    flow_factory: Callable[[dict, list[str]], Any] | None = None,
    server_runner: Callable[[Any], Any] | None = None,
    verify_handler: Callable[[Any], dict[str, Any]] | None = None,
) -> ConnectionResult:
    integration = get_integration(integration_name)
    root = _data_root(data_root)

    if integration.auth_type != "oauth2_desktop":
        raise IntegrationError(
            f"Connect for auth_type={integration.auth_type!r} is not yet "
            "supported by the Integrations Hub. See registry.setup_notes."
        )

    oauth_result = run_oauth_desktop_flow(
        integration,
        open_browser=open_browser,
        override_path=override_client_path,
        flow_factory=flow_factory,
        server_runner=server_runner,
    )

    token_path = save_credentials(integration, oauth_result.credentials, custom_root=root)

    handler = verify_handler or verify_handler_for(integration.name)
    details: dict[str, Any] = {}
    account_email = ""
    if handler is not None:
        try:
            details = dict(handler(oauth_result.credentials))
            account_email = str(details.get("email_address") or "")
        except IntegrationError:
            raise
        except Exception as exc:
            details = {"verify_error": str(exc)}

    integrations_config.mark_connected(
        data_root=root,
        integration=integration,
        token_path=token_path,
        account_email=account_email,
        extra={"used_override": oauth_result.used_override} if oauth_result.used_override else None,
    )

    return ConnectionResult(
        integration=integration.name,
        connected=True,
        token_path=token_path,
        account_email=account_email,
        enabled=True,
        auth_type=integration.auth_type,
        details=details,
        used_override=oauth_result.used_override,
    )


# ---------------------------------------------------------------------------
# verify (refresh + smoke check)
# ---------------------------------------------------------------------------


def verify(
    integration_name: str,
    *,
    data_root: Path | None = None,
    credentials_loader: Callable[[Path, list[str]], Any] | None = None,
    request_factory: Callable[[], Any] | None = None,
    verify_handler: Callable[[Any], dict[str, Any]] | None = None,
) -> ConnectionResult:
    integration = get_integration(integration_name)
    root = _data_root(data_root)

    try:
        token_file = find_existing_token(integration, custom_root=root)
        if token_file is None:
            raise IntegrationError(
                f"{integration.display_name} not connected — no token found."
            )

        credentials = (credentials_loader or _default_credentials_loader)(
            token_file, list(integration.scopes)
        )
        if getattr(credentials, "expired", False):
            refresh_token = getattr(credentials, "refresh_token", None)
            if not refresh_token:
                raise IntegrationError(
                    f"{integration.display_name} token expired and has no "
                    "refresh token. Re-run `synapse integrations connect "
                    f"{integration.name}`."
                )
            credentials.refresh((request_factory or _default_request_factory)())
            save_credentials(integration, credentials, custom_root=root)

        handler = verify_handler or verify_handler_for(integration.name)
        details: dict[str, Any] = {}
        account_email = ""
        if handler is not None:
            details = dict(handler(credentials))
            account_email = str(details.get("email_address") or "")

        # Token path may have moved from legacy → unified during this verify; refresh entry
        canonical_path = _token_path(integration, custom_root=root)
        if canonical_path.exists():
            integrations_config.mark_connected(
                data_root=root,
                integration=integration,
                token_path=canonical_path,
                account_email=account_email,
            )
            token_file = canonical_path

        return ConnectionResult(
            integration=integration.name,
            connected=True,
            token_path=token_file,
            account_email=account_email,
            enabled=True,
            auth_type=integration.auth_type,
            details=details,
        )
    except IntegrationError as exc:
        return ConnectionResult(
            integration=integration.name,
            connected=False,
            error=str(exc),
        )
    except Exception as exc:
        return ConnectionResult(
            integration=integration.name,
            connected=False,
            error=f"{integration.display_name} verify failed: {exc}",
        )


# ---------------------------------------------------------------------------
# status (no network)
# ---------------------------------------------------------------------------


def status(
    integration_name: str,
    *,
    data_root: Path | None = None,
) -> ConnectionResult:
    integration = get_integration(integration_name)
    root = _data_root(data_root)
    entry = integrations_config.get_entry(data_root=root, integration=integration)
    token_file = find_existing_token(integration, custom_root=root)
    enabled = bool(entry.get("enabled", False)) if entry else False
    return ConnectionResult(
        integration=integration.name,
        connected=token_file is not None,
        token_path=token_file,
        account_email=str(entry.get("account_email", "")),
        enabled=enabled,
        auth_type=integration.auth_type,
        details={"entry": entry, "has_token_file": token_file is not None},
    )


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


def disconnect(
    integration_name: str,
    *,
    data_root: Path | None = None,
) -> bool:
    integration = get_integration(integration_name)
    root = _data_root(data_root)
    removed = delete_token(integration, custom_root=root)
    with contextlib.suppress(IntegrationError):
        integrations_config.mark_disconnected(data_root=root, integration=integration)
    return removed


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def list_integrations(
    *,
    data_root: Path | None = None,
    include_unavailable: bool = True,
) -> list[ConnectionResult]:
    root = _data_root(data_root)
    results: list[ConnectionResult] = []
    for definition in list_definitions(include_unavailable=include_unavailable):
        try:
            results.append(status(definition.name, data_root=root))
        except Exception as exc:
            results.append(
                ConnectionResult(
                    integration=definition.name,
                    connected=False,
                    enabled=False,
                    auth_type=definition.auth_type,
                    error=str(exc),
                )
            )
    return results


# ---------------------------------------------------------------------------
# Default loaders (production)
# ---------------------------------------------------------------------------


def _default_credentials_loader(token_path: Path, scopes: list[str]):
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise IntegrationError(
            "google-auth is not installed. Install Synapse calendar/gmail extras."
        ) from exc
    return Credentials.from_authorized_user_file(str(token_path), scopes)


def _default_request_factory():
    try:
        from google.auth.transport.requests import Request
    except ImportError as exc:
        raise IntegrationError(
            "google-auth-transport is not installed. Install Synapse calendar/gmail extras."
        ) from exc
    return Request()


# Re-export helpful constants/types for callers
__all__ = [
    "ConnectionResult",
    "connect",
    "disconnect",
    "list_integrations",
    "status",
    "verify",
]
