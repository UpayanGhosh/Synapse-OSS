"""Integrations Hub onboarding step.

Plugs into the main wizard between gateway/model setup and the final
summary. Lets the user connect Google Calendar (and any other
``oauth2_desktop`` integration) inline — browser opens, consent,
done. No CLI exit-and-rerun required.

The function is defensive: if google libs are missing, if the bundled
OAuth client_id is still a placeholder and the user has no override
JSON path, or if the OAuth flow itself errors, we record the issue
and continue. Onboarding never blocks on an integration failing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _print(msg: str) -> None:
    """Mirror the lightweight printer used by ``cli/onboard.py``."""
    try:
        from rich import print as rich_print  # noqa: PLC0415

        rich_print(msg)
    except Exception:  # pragma: no cover - rich missing
        print(msg)


def _has_placeholder_bundled_client() -> bool:
    try:
        from sci_fi_dashboard.integrations.registry import (  # noqa: PLC0415
            SYNAPSE_GOOGLE_OAUTH_CLIENT,
        )
    except Exception:
        return True
    installed = SYNAPSE_GOOGLE_OAUTH_CLIENT.get("installed", {}) if isinstance(
        SYNAPSE_GOOGLE_OAUTH_CLIENT, dict
    ) else {}
    return "PLACEHOLDER" in str(installed.get("client_id", "")).upper()


def _resolve_oauth_client_path(
    prompter: Any,
    integration_display_name: str,
) -> Path | None:
    """Return a Path to a real client_secret.json or None to skip.

    Tries (in order):
      1. SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH env var (or legacy
         SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET).
      2. The bundled client (silently skipped if still a placeholder).
      3. Interactive prompt asking the user to paste a JSON path.
    """
    env_path = (
        os.environ.get("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH")
        or os.environ.get("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET")
        or ""
    ).strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.exists():
            return path
        _print(f"  [yellow]OAuth client path from env var not found: {path}[/]")

    if not _has_placeholder_bundled_client():
        return None  # bundled client is real — manager.connect uses it

    _print(
        "  [yellow]Synapse's bundled OAuth client_id is a placeholder until Google "
        "verification ships.[/]\n"
        "  Until then, paste the path to your own Google client_secret JSON "
        f"(downloaded from Google Cloud Console for {integration_display_name})."
    )
    raw = prompter.text(  # type: ignore[attr-defined]
        f"  client_secret JSON path (blank to skip {integration_display_name}):",
        default="",
    )
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.exists():
        _print(f"  [red]File not found: {path}. Skipping.[/]")
        return None
    return path


def _summarize_details(details: dict[str, Any]) -> str:
    keep = ("email_address", "calendar_count", "upcoming_count", "messages_total")
    parts = [f"{k}={details[k]}" for k in keep if k in details]
    return ", ".join(parts)


def setup_integrations_wizard(
    prompter: Any,
    *,
    data_root: Path,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Optional onboarding step: connect Google integrations inline.

    Returns a ``{integration_name: status}`` map for the summary panel
    where status is one of ``"connected"``, ``"failed"``, ``"skipped"``.
    """
    results: dict[str, str] = {}

    try:
        from sci_fi_dashboard.integrations import (  # noqa: PLC0415
            IntegrationError,
            connect,
            list_definitions,
        )
    except Exception as exc:  # noqa: BLE001
        _print(f"[yellow]Integrations Hub unavailable ({exc}); skipping integration step.[/]")
        return results

    available = [
        d
        for d in list_definitions(include_unavailable=False)
        if d.auth_type == "oauth2_desktop"
    ]
    if not available:
        return results

    _print("\n[bold cyan]--- Optional integrations ---[/]")
    _print(
        "Synapse can connect to Google Calendar, Gmail, and more. Each connection "
        "opens your browser for a one-time Google sign-in."
    )

    if not prompter.confirm(  # type: ignore[attr-defined]
        "Connect any Google services now? (You can do this later with "
        "'synapse integrations connect <name>'.)",
        default=True,
    ):
        for d in available:
            results[d.name] = "skipped"
        return results

    for definition in available:
        prompt_default = definition.name == "google_calendar"
        if not prompter.confirm(  # type: ignore[attr-defined]
            f"Connect {definition.display_name}?",
            default=prompt_default,
        ):
            results[definition.name] = "skipped"
            continue

        client_path = _resolve_oauth_client_path(prompter, definition.display_name)
        if _has_placeholder_bundled_client() and client_path is None:
            results[definition.name] = "skipped"
            continue

        _print(
            f"  Opening browser for {definition.display_name} consent... "
            "(if you see 'Google hasn't verified this app', click "
            "[bold]Advanced → Go to Synapse (unsafe) → Continue[/])"
        )
        try:
            result = connect(
                definition.name,
                data_root=data_root,
                override_client_path=client_path,
            )
        except IntegrationError as exc:
            _print(f"  [red]✗ {definition.display_name} failed: {exc}[/]")
            results[definition.name] = "failed"
            continue
        except Exception as exc:  # noqa: BLE001
            _print(f"  [red]✗ {definition.display_name} crashed: {exc}[/]")
            results[definition.name] = "failed"
            continue

        account = result.account_email or "(unknown account)"
        details_summary = _summarize_details(result.details or {})
        if details_summary:
            _print(f"  [green]✓ {definition.display_name} connected as {account} ({details_summary})[/]")
        else:
            _print(f"  [green]✓ {definition.display_name} connected as {account}[/]")
        results[definition.name] = "connected"

        if config is not None:
            config.setdefault("integrations_connected", []).append(definition.name)

    return results


__all__ = ["setup_integrations_wizard"]
