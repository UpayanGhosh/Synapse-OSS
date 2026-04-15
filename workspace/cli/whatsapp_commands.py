"""
whatsapp_commands.py — CLI implementations for `synapse whatsapp` subcommands.

Commands:
  synapse whatsapp status  — show connection state, uptime, auth age
  synapse whatsapp relink  — force fresh QR cycle (wipe creds, restart socket)
  synapse whatsapp logout  — deregister linked device + wipe session

These are thin wrappers that call the API gateway. The gateway must be running.
"""

from __future__ import annotations

import sys

import httpx
import typer

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _RICH = True
except ImportError:
    _RICH = False


def _gateway_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _print_error(msg: str) -> None:
    if _RICH:
        Console(stderr=True).print(f"[red]{msg}[/]")
    else:
        print(f"ERROR: {msg}", file=sys.stderr)


def status_command(port: int = 8000) -> None:
    """GET /channels/whatsapp/status and pretty-print."""
    url = f"{_gateway_url(port)}/channels/whatsapp/status"
    try:
        r = httpx.get(url, timeout=5.0)
        r.raise_for_status()
        data = r.json()
    except httpx.ConnectError:
        _print_error(f"Gateway not reachable at port {port}. Is Synapse running?")
        raise typer.Exit(1) from None
    except httpx.HTTPStatusError as exc:
        _print_error(f"Gateway returned {exc.response.status_code}: {exc.response.text}")
        raise typer.Exit(1) from None

    if _RICH:
        console = Console()
        state = data.get("connection_state", "unknown")
        bridge = data.get("bridge", {})
        state_color = {
            "connected": "green",
            "awaiting_qr": "yellow",
            "reconnecting": "yellow",
            "logged_out": "red",
            "disconnected": "red",
        }.get(state, "dim")

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Field", style="bold")
        table.add_column("Value")

        table.add_row("Connection", f"[{state_color}]{state}[/]")
        table.add_row("Bridge status", data.get("bridge_status", "unknown"))
        table.add_row("Bridge PID", str(data.get("bridge_pid") or "—"))

        if data.get("connected_since"):
            table.add_row("Connected since", data["connected_since"])

        if data.get("auth_timestamp"):
            table.add_row("First authenticated", data["auth_timestamp"])

        uptime = bridge.get("uptimeSeconds")
        if uptime is not None:
            h, m, s = int(uptime) // 3600, (int(uptime) % 3600) // 60, int(uptime) % 60
            table.add_row("Bridge uptime", f"{h}h {m}m {s}s")

        restarts = bridge.get("restartCount", data.get("restart_count", 0))
        table.add_row("Restart count", str(restarts))

        if data.get("last_disconnect_reason") and data["last_disconnect_reason"] != "null":
            table.add_row("Last disconnect", data["last_disconnect_reason"])

        console.print(Panel(table, title="WhatsApp Status", border_style=state_color, expand=False))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def relink_command(port: int = 8000) -> None:
    """POST /channels/whatsapp/relink — force fresh QR cycle."""
    url = f"{_gateway_url(port)}/channels/whatsapp/relink"
    if _RICH:
        console = Console()
        console.print("[cyan]Requesting WhatsApp relink...[/]")
    else:
        print("Requesting WhatsApp relink...")

    try:
        r = httpx.post(url, timeout=10.0)
        r.raise_for_status()
    except httpx.ConnectError:
        _print_error(f"Gateway not reachable at port {port}. Is Synapse running?")
        raise typer.Exit(1) from None
    except httpx.HTTPStatusError as exc:
        _print_error(f"Relink failed: {exc.response.status_code} — {exc.response.text}")
        raise typer.Exit(1) from None

    msg = (
        "WhatsApp socket restarted. A fresh QR code is being generated.\n"
        "Run the onboarding wizard or scan via: synapse whatsapp status"
    )
    if _RICH:
        Console().print(Panel(f"[green]{msg}[/]", border_style="green", expand=False))
    else:
        print(f"OK: {msg}")


def logout_command(port: int = 8000) -> None:
    """POST /channels/whatsapp/logout — deregister device and wipe session."""
    if _RICH:
        Console()
        confirmed = typer.confirm(
            "This will disconnect WhatsApp and wipe the saved session. Continue?",
            default=False,
        )
    else:
        confirmed = typer.confirm(
            "This will disconnect WhatsApp and wipe the saved session. Continue?",
            default=False,
        )

    if not confirmed:
        print("Aborted.")
        raise typer.Exit(0) from None

    url = f"{_gateway_url(port)}/channels/whatsapp/logout"
    try:
        r = httpx.post(url, timeout=15.0)
        r.raise_for_status()
    except httpx.ConnectError:
        _print_error(f"Gateway not reachable at port {port}. Is Synapse running?")
        raise typer.Exit(1) from None
    except httpx.HTTPStatusError as exc:
        _print_error(f"Logout failed: {exc.response.status_code} — {exc.response.text}")
        raise typer.Exit(1) from None

    msg = "WhatsApp logged out and session cleared. Run the onboarding wizard to re-pair."
    if _RICH:
        Console().print(Panel(f"[green]{msg}[/]", border_style="green", expand=False))
    else:
        print(f"OK: {msg}")
