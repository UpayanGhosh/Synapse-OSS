"""Synapse-OSS root CLI entry point.

Exposes onboard, chat, ingest, vacuum, verify, daemon-install, daemon-uninstall
as Typer subcommands.

Run from the workspace/ directory:

    python synapse_cli.py --help
    python synapse_cli.py onboard
    python synapse_cli.py onboard --flow advanced
    python synapse_cli.py chat
"""

from datetime import UTC

import typer

app = typer.Typer(
    name="synapse",
    help="Synapse-OSS CLI",
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# WhatsApp subcommand group
# ---------------------------------------------------------------------------
wa_app = typer.Typer(name="whatsapp", help="WhatsApp channel management", no_args_is_help=True)
app.add_typer(wa_app)


@wa_app.command("status")
def whatsapp_status(
    port: int = typer.Option(8000, "--port", help="Gateway port"),
) -> None:
    """Show WhatsApp connection state, uptime, and auth age."""
    from cli.whatsapp_commands import status_command  # noqa: PLC0415

    status_command(port=port)


@wa_app.command("relink")
def whatsapp_relink(
    port: int = typer.Option(8000, "--port", help="Gateway port"),
) -> None:
    """Force a fresh QR scan — wipes saved credentials and restarts socket."""
    from cli.whatsapp_commands import relink_command  # noqa: PLC0415

    relink_command(port=port)


@wa_app.command("logout")
def whatsapp_logout(
    port: int = typer.Option(8000, "--port", help="Gateway port"),
) -> None:
    """Deregister linked device and wipe WhatsApp session."""
    from cli.whatsapp_commands import logout_command  # noqa: PLC0415

    logout_command(port=port)


# ---------------------------------------------------------------------------
# Google Antigravity OAuth subcommand group
# ---------------------------------------------------------------------------
ag_app = typer.Typer(
    name="antigravity",
    help="Google Antigravity (Gemini 3 via OAuth) — login / status / logout",
    no_args_is_help=True,
)
app.add_typer(ag_app)


@ag_app.command("login")
def antigravity_login() -> None:
    """Run the Google Antigravity OAuth flow and store credentials.

    Opens a browser for Google sign-in, captures the redirect on
    localhost:8085, exchanges the code for access + refresh tokens, and
    saves them to ~/.synapse/state/google-oauth.json.
    """
    import asyncio  # noqa: PLC0415

    from cli.provider_steps import google_antigravity_oauth_flow  # noqa: PLC0415
    from rich.console import Console  # noqa: PLC0415

    console = Console()
    metadata = asyncio.run(google_antigravity_oauth_flow(console))
    if not metadata:
        raise typer.Exit(1)
    typer.echo(
        f"Logged in as {metadata.get('email') or '(unknown)'} "
        f"on tier '{metadata.get('tier') or 'unknown'}', "
        f"project '{metadata.get('project_id') or 'unknown'}'."
    )


@ag_app.command("status")
def antigravity_status() -> None:
    """Show the email, tier, and expiry of the saved Antigravity credentials."""
    from datetime import datetime  # noqa: PLC0415

    from sci_fi_dashboard import google_oauth  # noqa: PLC0415

    creds = google_oauth.load_credentials()
    if creds is None:
        typer.echo("No Google Antigravity credentials saved.")
        raise typer.Exit(1)
    expires_at = datetime.fromtimestamp(creds.expires_at, tz=UTC)
    typer.echo(f"email:       {creds.email or '(unknown)'}")
    typer.echo(f"project_id:  {creds.project_id}")
    typer.echo(f"tier:        {creds.tier or '(unknown)'}")
    typer.echo(f"expires_at:  {expires_at.isoformat()}")
    typer.echo(f"is_expired:  {creds.is_expired()}")


@ag_app.command("logout")
def antigravity_logout() -> None:
    """Delete the saved Antigravity credentials from disk."""
    from sci_fi_dashboard import google_oauth  # noqa: PLC0415

    if google_oauth.delete_credentials():
        typer.echo("Google Antigravity credentials wiped.")
    else:
        typer.echo("No saved credentials to remove.")


@app.command()
def onboard(
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        envvar="SYNAPSE_NON_INTERACTIVE",
        help="Read all inputs from env vars; no prompts (CI/Docker use).",
    ),
    flow: str = typer.Option(
        "quickstart",
        "--flow",
        envvar="SYNAPSE_FLOW",
        help="Wizard flow: 'quickstart' (default, minimal prompts) or 'advanced' (all options).",
    ),
    accept_risk: bool = typer.Option(
        False,
        "--accept-risk",
        envvar="SYNAPSE_ACCEPT_RISK",
        help="Required with --non-interactive. Confirms config is read from env vars.",
    ),
    reset: str | None = typer.Option(
        None,
        "--reset",
        envvar="SYNAPSE_RESET",
        help=(
            "Back up existing data before wizard starts. "
            "Values: config | config+creds+sessions | full"
        ),
    ),
) -> None:
    """Interactive setup wizard — configure LLM providers, channels, and write synapse.json."""
    from cli.onboard import run_wizard

    run_wizard(
        non_interactive=non_interactive,
        flow=flow,
        accept_risk=accept_risk,
        reset=reset,
    )


@app.command()
def setup(
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        envvar="SYNAPSE_NON_INTERACTIVE",
        help="Read all inputs from env vars; no prompts (CI/Docker use).",
    ),
    flow: str = typer.Option(
        "quickstart",
        "--flow",
        envvar="SYNAPSE_FLOW",
        help="Wizard flow: 'quickstart' (default) or 'advanced'.",
    ),
    accept_risk: bool = typer.Option(
        False,
        "--accept-risk",
        envvar="SYNAPSE_ACCEPT_RISK",
        help="Required with --non-interactive.",
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Verify existing config — test each provider and channel.",
    ),
    reset: str | None = typer.Option(
        None,
        "--reset",
        envvar="SYNAPSE_RESET",
        help=(
            "Back up existing data before wizard starts. "
            "Values: config | config+creds+sessions | full"
        ),
    ),
) -> None:
    """Setup Synapse — configure providers, channels, and persona profile."""
    if verify:
        from cli.verify_steps import run_verify  # noqa: PLC0415

        raise typer.Exit(run_verify(non_interactive=non_interactive))
    else:
        from cli.onboard import run_wizard  # noqa: PLC0415

        run_wizard(
            non_interactive=non_interactive,
            flow=flow,
            accept_risk=accept_risk,
            reset=reset,
        )


@app.command()
def chat() -> None:
    """Start the AI Gateway interactive chat interface."""
    from main import start_chat

    start_chat()


@app.command()
def ingest() -> None:
    """Ingest new memories via atomic shadow tables."""
    from main import ingest_data

    ingest_data()


@app.command()
def vacuum() -> None:
    """Run database vacuum optimization."""
    from main import optimized_vacuum

    optimized_vacuum()


@app.command()
def verify() -> None:
    """Run system health and integrity checks."""
    from main import verify_system

    verify_system()


@app.command()
def daemon_install() -> None:
    """Install the Synapse gateway as a persistent background service."""
    from cli.daemon import build_gateway_install_plan, resolve_gateway_service
    from synapse_config import SynapseConfig

    try:
        svc = resolve_gateway_service()
        config = SynapseConfig.load()
        opts = build_gateway_install_plan(config)
        svc.install(opts)
        typer.echo("Gateway daemon installed successfully.")
    except NotImplementedError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def daemon_uninstall() -> None:
    """Uninstall the Synapse gateway background service."""
    from cli.daemon import resolve_gateway_service

    try:
        svc = resolve_gateway_service()
        svc.uninstall()
        typer.echo("Gateway daemon uninstalled.")
    except NotImplementedError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def doctor(
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Attempt to auto-fix detected issues (e.g., generate missing gateway token).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        envvar="SYNAPSE_NON_INTERACTIVE",
        help="Use shorter timeouts (suitable for CI / scripted checks).",
    ),
) -> None:
    """Run system health checks — config, providers, gateway, workspace."""
    from cli.doctor import doctor_command  # noqa: PLC0415

    failures = doctor_command(fix=fix, non_interactive=non_interactive)
    raise typer.Exit(failures)


@app.command()
def health(
    port: int = typer.Option(
        8000,
        "--port",
        help="Gateway port to probe.",
    ),
) -> None:
    """Check if the Synapse gateway is reachable and display status."""
    from cli.health import health_command  # noqa: PLC0415
    from synapse_config import SynapseConfig  # noqa: PLC0415

    config = SynapseConfig.load()
    token = config.gateway.get("token") if config.gateway else None
    data = health_command(port=port, token=token)
    if "error" in data:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
