"""Catalogue of supported integrations.

Each ``IntegrationDefinition`` is a static description of one connectable
service: how to authenticate it, which scopes to request, where to put the
token, and which legacy `synapse.json` keys to keep populated for
backwards-compatibility (e.g. `mcp.builtin_servers.calendar.token_path` is
still read by the existing Calendar MCP server).

The OAuth ``client_config`` is bundled by default so end users never have to
visit Google Cloud Console. It can be overridden by setting
``SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH`` to a Google-issued client secret JSON,
which lets privacy-max users / pre-verification testers swap in their own.

The shipped ``client_id`` is a placeholder until the production
Synapse-branded OAuth client is registered and verified with Google. Replace
both ``client_id`` and ``client_secret`` (the latter is not actually a secret
for installed-app desktop OAuth — see Google's installed-app docs) before
shipping a release.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

AuthType = Literal["oauth2_desktop", "oauth2_workspace", "bot_token", "api_key"]


SYNAPSE_GOOGLE_OAUTH_CLIENT: dict[str, dict[str, object]] = {
    "installed": {
        # PLACEHOLDER — replace with the verified Synapse-branded OAuth client
        # ID issued by Google Cloud Console. The "secret" for installed-app
        # desktop OAuth is not actually treated as confidential by Google;
        # it ships with the app. See:
        # https://developers.google.com/identity/protocols/oauth2/native-app
        "client_id": "PLACEHOLDER_REPLACE_BEFORE_RELEASE.apps.googleusercontent.com",
        "client_secret": "PLACEHOLDER_NOT_ACTUALLY_SECRET_FOR_INSTALLED_APPS",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"],
        "project_id": "synapse-oss-placeholder",
    }
}


CALENDAR_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)

GMAIL_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
)


@dataclass(slots=True, frozen=True)
class IntegrationDefinition:
    """Describes one connectable third-party service."""

    name: str
    display_name: str
    auth_type: AuthType
    scopes: tuple[str, ...] = ()
    google_client_config: dict[str, dict[str, object]] | None = None
    legacy_token_paths: tuple[str, ...] = ()
    legacy_synapse_json_keys: tuple[str, ...] = ()
    description: str = ""
    requires_account_email: bool = True
    available: bool = True
    setup_notes: str = ""

    def token_dirname(self) -> str:
        return self.name


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"0", "false", "no", ""})


def google_oauth_client_override_path() -> str | None:
    """Path to a user-provided Google OAuth client_secret.json, if any."""
    candidates = [
        os.environ.get("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH"),
        os.environ.get("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET"),
    ]
    for candidate in candidates:
        if candidate and candidate.strip():
            return candidate.strip()
    return None


registry: dict[str, IntegrationDefinition] = {}


def register(definition: IntegrationDefinition) -> IntegrationDefinition:
    if definition.name in registry:
        raise ValueError(f"Integration '{definition.name}' already registered")
    registry[definition.name] = definition
    return definition


def get_integration(name: str) -> IntegrationDefinition:
    try:
        return registry[name]
    except KeyError as exc:
        known = ", ".join(sorted(registry)) or "(none)"
        raise KeyError(f"Unknown integration '{name}'. Known: {known}") from exc


def list_definitions(*, include_unavailable: bool = True) -> list[IntegrationDefinition]:
    items = list(registry.values())
    if not include_unavailable:
        items = [item for item in items if item.available]
    return items


# ---------------------------------------------------------------------------
# Bundled definitions
# ---------------------------------------------------------------------------


register(
    IntegrationDefinition(
        name="google_calendar",
        display_name="Google Calendar",
        auth_type="oauth2_desktop",
        scopes=CALENDAR_SCOPES,
        google_client_config=SYNAPSE_GOOGLE_OAUTH_CLIENT,
        legacy_token_paths=("~/.synapse/google/calendar_token.json",),
        legacy_synapse_json_keys=(
            "mcp.builtin_servers.calendar.enabled",
            "mcp.builtin_servers.calendar.credentials_path",
            "mcp.builtin_servers.calendar.token_path",
        ),
        description=(
            "Read and write events on your Google Calendar. Synapse can answer "
            "availability questions, create one-off and recurring events, RSVP, "
            "delete or move events. Destructive actions always ask for "
            "confirmation."
        ),
        available=True,
    )
)

register(
    IntegrationDefinition(
        name="gmail",
        display_name="Gmail",
        auth_type="oauth2_desktop",
        scopes=GMAIL_SCOPES,
        google_client_config=SYNAPSE_GOOGLE_OAUTH_CLIENT,
        legacy_token_paths=("~/.synapse/google/gmail_token.json",),
        legacy_synapse_json_keys=(
            "mcp.builtin_servers.gmail.enabled",
            "mcp.builtin_servers.gmail.credentials_path",
            "mcp.builtin_servers.gmail.token_path",
        ),
        description=(
            "Read, send, and triage your Gmail. Synapse can summarize threads, "
            "draft replies (always confirmed), watch important threads, and "
            "search by query. Send/modify actions always ask for confirmation."
        ),
        available=True,
    )
)

register(
    IntegrationDefinition(
        name="notion",
        display_name="Notion",
        auth_type="oauth2_workspace",
        scopes=(),
        legacy_synapse_json_keys=("mcp.builtin_servers.notion.token_path",),
        description=(
            "Read and write Notion pages and databases. Workspace OAuth — "
            "Synapse will redirect you to your Notion workspace to grant access."
        ),
        available=False,
        setup_notes=(
            "Notion uses workspace OAuth, not desktop loopback. Hub support "
            "ships in a follow-up; track via ONBOARDING_BUGS.md V3 backlog."
        ),
    )
)

register(
    IntegrationDefinition(
        name="slack",
        display_name="Slack",
        auth_type="bot_token",
        scopes=(),
        legacy_synapse_json_keys=("mcp.builtin_servers.slack.bot_token",),
        description=(
            "Send messages to Slack channels and DMs. Slack uses bot tokens; "
            "you generate one at api.slack.com and paste it during setup."
        ),
        available=False,
        setup_notes=(
            "Slack bot-token flow ships in a follow-up. For now use the "
            "legacy `mcp.builtin_servers.slack.bot_token` config path."
        ),
    )
)
