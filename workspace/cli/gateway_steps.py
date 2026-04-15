"""
gateway_steps.py — Gateway configuration wizard step for Synapse-OSS onboarding.

Provides configure_gateway() which collects port, bind mode, and auth token
for the WebSocket control-plane gateway.  Works in three modes:

  1. Non-interactive: reads SYNAPSE_GATEWAY_PORT / SYNAPSE_GATEWAY_BIND /
     SYNAPSE_GATEWAY_AUTH_MODE / SYNAPSE_GATEWAY_TOKEN env vars.
  2. QuickStart: keeps existing token (or auto-generates one); skips all prompts.
  3. Advanced interactive: prompts for each setting via WizardPrompter.

Returns a flat dict: {"port": int, "bind": str, "token": str | None}
This matches the existing gateway_token() read path at synapse_config.py which
reads config.gateway.get("token") as a flat key — no nested auth sub-dict.
"""

from __future__ import annotations

import os
import secrets

# ---------------------------------------------------------------------------
# Conditional rich import — fall back to plain print if not installed
# ---------------------------------------------------------------------------
try:
    from rich.console import Console

    _RICH_AVAILABLE = True
    _console = Console()
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False
    _console = None  # type: ignore[assignment]


def _print(msg: str) -> None:
    if _RICH_AVAILABLE and _console is not None:
        _console.print(msg)
    else:
        # Strip rich markup for plain print fallback
        import re

        plain = re.sub(r"\[/?[^\]]*\]", "", msg)
        print(plain)


# ---------------------------------------------------------------------------
# Bind mode choices
# ---------------------------------------------------------------------------

_BIND_CHOICES: list[str] = ["loopback", "lan", "auto"]
_DEFAULT_PORT: int = 8000
_DEFAULT_BIND: str = "loopback"
_DEFAULT_AUTH_MODE: str = "token"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_gateway(
    flow: str,
    existing_gateway: dict,
    non_interactive: bool,
    prompter: object | None = None,
) -> dict:
    """Collect gateway port, bind mode, and auth token.

    Args:
        flow:             "quickstart" or "advanced".
        existing_gateway: The gateway dict already in the loaded config (may be {}).
        non_interactive:  If True, read from env vars; ignore flow and prompter.
        prompter:         WizardPrompter instance. If None and interactive, uses
                          questionary directly.  Unused in non_interactive mode.

    Returns:
        Flat dict: {"port": int, "bind": str, "token": str | None}
        The "token" key is None when auth is disabled.
    """
    if non_interactive:
        return _configure_non_interactive(existing_gateway)

    if flow == "quickstart":
        return _configure_quickstart(existing_gateway)

    # Advanced interactive
    return _configure_advanced(existing_gateway, prompter)


# ---------------------------------------------------------------------------
# Non-interactive path
# ---------------------------------------------------------------------------


def _configure_non_interactive(existing_gateway: dict) -> dict:
    """Read gateway config from environment variables."""
    port_raw = os.environ.get("SYNAPSE_GATEWAY_PORT", "").strip()
    try:
        port = int(port_raw) if port_raw else _DEFAULT_PORT
    except ValueError:
        _print(
            f"[yellow]SYNAPSE_GATEWAY_PORT={port_raw!r} is not a valid integer. "
            f"Using default {_DEFAULT_PORT}.[/yellow]"
        )
        port = _DEFAULT_PORT

    bind = os.environ.get("SYNAPSE_GATEWAY_BIND", _DEFAULT_BIND).strip()
    if bind not in _BIND_CHOICES:
        _print(
            f"[yellow]SYNAPSE_GATEWAY_BIND={bind!r} is not valid "
            f"({', '.join(_BIND_CHOICES)}). Using '{_DEFAULT_BIND}'.[/yellow]"
        )
        bind = _DEFAULT_BIND

    auth_mode = os.environ.get("SYNAPSE_GATEWAY_AUTH_MODE", _DEFAULT_AUTH_MODE).strip()
    if auth_mode not in ("token", "disabled"):
        auth_mode = _DEFAULT_AUTH_MODE

    if auth_mode == "disabled":
        token: str | None = None
    else:
        token = os.environ.get("SYNAPSE_GATEWAY_TOKEN", "").strip() or None
        if token is None:
            token = _auto_generate_token()

    return {"port": port, "bind": bind, "token": token}


# ---------------------------------------------------------------------------
# QuickStart path
# ---------------------------------------------------------------------------


def _configure_quickstart(existing_gateway: dict) -> dict:
    """QuickStart: keep existing token or auto-generate; skip all prompts."""
    port = existing_gateway.get("port", _DEFAULT_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = _DEFAULT_PORT

    bind = existing_gateway.get("bind", _DEFAULT_BIND)
    if bind not in _BIND_CHOICES:
        bind = _DEFAULT_BIND

    token = existing_gateway.get("token") or _auto_generate_token()

    return {"port": port, "bind": bind, "token": token}


# ---------------------------------------------------------------------------
# Advanced interactive path
# ---------------------------------------------------------------------------


def _configure_advanced(existing_gateway: dict, prompter: object | None) -> dict:
    """Advanced: prompt for each setting via WizardPrompter or direct questionary."""
    _print("\n[bold cyan]--- Gateway Configuration ---[/]")

    default_port = existing_gateway.get("port", _DEFAULT_PORT)
    default_bind = existing_gateway.get("bind", _DEFAULT_BIND)
    if default_bind not in _BIND_CHOICES:
        default_bind = _DEFAULT_BIND

    if prompter is not None:
        # Delegate to WizardPrompter
        port_str = prompter.text(  # type: ignore[attr-defined]
            "Gateway port:", default=str(default_port)
        )
        try:
            port = int(port_str)
        except (ValueError, TypeError):
            _print(f"[yellow]Invalid port {port_str!r}, using {_DEFAULT_PORT}.[/yellow]")
            port = _DEFAULT_PORT

        bind = prompter.select(  # type: ignore[attr-defined]
            "Gateway bind mode:",
            choices=_BIND_CHOICES,
            default=default_bind,
        )

        auth_mode = prompter.select(  # type: ignore[attr-defined]
            "Gateway auth mode:",
            choices=["token", "disabled"],
            default="token",
        )
    else:
        # Lazy questionary import
        try:
            import questionary  # noqa: PLC0415
        except ImportError:
            _print("[yellow]questionary not installed — using defaults for gateway.[/yellow]")
            return _configure_quickstart(existing_gateway)

        port_str = questionary.text("Gateway port:", default=str(default_port)).ask()
        if port_str is None:
            port_str = str(default_port)
        try:
            port = int(port_str)
        except ValueError:
            port = _DEFAULT_PORT

        bind_result = questionary.select(
            "Gateway bind mode:", choices=_BIND_CHOICES, default=default_bind
        ).ask()
        bind = bind_result if bind_result is not None else default_bind

        auth_result = questionary.select(
            "Gateway auth mode:", choices=["token", "disabled"], default="token"
        ).ask()
        auth_mode = auth_result if auth_result is not None else "token"

    if auth_mode == "disabled":
        _print(
            "[yellow]Warning: gateway auth is disabled. " "Anyone on the network can control it.[/]"
        )
        token: str | None = None
    else:
        existing_token = existing_gateway.get("token", "")
        if prompter is not None:
            token_input = prompter.text(  # type: ignore[attr-defined]
                "Gateway token (leave blank to auto-generate):", default=""
            )
        else:
            try:
                import questionary  # noqa: PLC0415

                token_raw = questionary.text(
                    "Gateway token (leave blank to auto-generate):", default=""
                ).ask()
                token_input = token_raw if token_raw is not None else ""
            except ImportError:
                token_input = ""

        token_input = token_input.strip()
        if token_input:
            token = token_input
        elif existing_token:
            token = existing_token
        else:
            token = _auto_generate_token()
            _print(f"[green]Auto-generated gateway token ({len(token)} hex chars)[/]")

    return {"port": port, "bind": bind, "token": token}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auto_generate_token() -> str:
    """Generate a random 48-character hex token via secrets.token_hex(24)."""
    return secrets.token_hex(24)
