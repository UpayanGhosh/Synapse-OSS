"""Generic OAuth desktop loopback flow used by every Google integration.

Reads the bundled ``IntegrationDefinition.google_client_config`` by default.
If ``SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH`` (or the legacy
``SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET``) points to a real Google client
secret JSON file, that overrides the bundled config — useful for power
users running their own Google Cloud project.

The flow is synchronous because it must wait for the user to complete the
browser consent. Callers running inside the chat gateway should run this in
a thread (``asyncio.to_thread``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import IntegrationError
from .registry import IntegrationDefinition, google_oauth_client_override_path


@dataclass(slots=True)
class OAuthResult:
    credentials: Any
    client_config: dict[str, dict[str, object]]
    used_override: bool
    account: str = ""


def _import_installed_app_flow() -> Any:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        return InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - exercised in real installs
        raise IntegrationError(
            "google-auth-oauthlib is not installed. Run "
            "`pip install google-auth-oauthlib google-api-python-client` "
            "or install Synapse calendar/gmail extras."
        ) from exc


def _resolve_client_config(
    integration: IntegrationDefinition,
    *,
    override_path: str | Path | None = None,
) -> tuple[dict[str, dict[str, object]], bool]:
    """Return (client_config, used_override)."""
    if override_path is not None:
        path = Path(override_path).expanduser()
        if not path.exists():
            raise IntegrationError(
                f"OAuth client override path not found: {path}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationError(
                f"Could not read OAuth client JSON at {path}: {exc}"
            ) from exc
        return payload, True

    env_override = google_oauth_client_override_path()
    if env_override:
        return _resolve_client_config(integration, override_path=env_override)

    if integration.google_client_config is None:
        raise IntegrationError(
            f"Integration '{integration.name}' has no bundled OAuth client "
            "and no override path was provided."
        )
    return integration.google_client_config, False


def _is_placeholder_client(client_config: dict[str, dict[str, object]]) -> bool:
    for block in client_config.values():
        client_id = str(block.get("client_id", ""))
        if "PLACEHOLDER" in client_id.upper():
            return True
    return False


def run_oauth_desktop_flow(
    integration: IntegrationDefinition,
    *,
    open_browser: bool = True,
    override_path: str | Path | None = None,
    flow_factory: Callable[[dict, list[str]], Any] | None = None,
    server_runner: Callable[[Any], Any] | None = None,
) -> OAuthResult:
    """Run the desktop OAuth loopback flow and return Google credentials.

    ``flow_factory`` and ``server_runner`` are injected by tests. Production
    code uses ``InstalledAppFlow.from_client_config`` and
    ``flow.run_local_server(port=0)``.
    """
    if integration.auth_type != "oauth2_desktop":
        raise IntegrationError(
            f"Integration '{integration.name}' is auth_type="
            f"{integration.auth_type!r}; only oauth2_desktop is supported by "
            "this helper."
        )

    client_config, used_override = _resolve_client_config(
        integration, override_path=override_path
    )

    if _is_placeholder_client(client_config) and not used_override:
        raise IntegrationError(
            "Synapse's bundled OAuth client_id is a placeholder. Either set "
            "SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH to a real Google client_secret "
            "JSON, or wait for the verified Synapse OAuth client to ship in a "
            "future release."
        )

    if flow_factory is None:
        InstalledAppFlow = _import_installed_app_flow()  # noqa: N806

        def flow_factory(config: dict, scopes: list[str]) -> Any:
            return InstalledAppFlow.from_client_config(config, scopes)

    flow = flow_factory(client_config, list(integration.scopes))

    if server_runner is None:
        def server_runner(local_flow: Any) -> Any:
            return local_flow.run_local_server(
                port=0,
                open_browser=open_browser,
                prompt="consent",
                authorization_prompt_message=(
                    f"Opening Google authorization for {integration.display_name} "
                    "in your browser..."
                ),
            )

    try:
        credentials = server_runner(flow)
    except Exception as exc:
        raise IntegrationError(
            f"{integration.display_name} OAuth failed: {exc}"
        ) from exc

    account = ""
    if hasattr(credentials, "id_token") and credentials.id_token:
        # google-auth fills id_token sometimes; otherwise account stays empty.
        account = ""
    return OAuthResult(
        credentials=credentials,
        client_config=client_config,
        used_override=used_override,
        account=account,
    )
