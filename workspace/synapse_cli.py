"""Synapse-OSS root CLI entry point.

Exposes onboard, chat, ingest, vacuum, and verify as Typer subcommands.
Run from the workspace/ directory:

    python synapse_cli.py --help
    python synapse_cli.py onboard
    python synapse_cli.py chat
"""

import typer

app = typer.Typer(
    name="synapse",
    help="Synapse-OSS CLI",
    no_args_is_help=True,
)


@app.command()
def onboard(
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        envvar="SYNAPSE_NON_INTERACTIVE",
        help="Read all inputs from env vars; no prompts (CI/Docker use).",
    ),
) -> None:
    """Interactive setup wizard — configure LLM providers, channels, and write synapse.json."""
    from cli.onboard import run_wizard

    run_wizard(non_interactive=non_interactive)


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


if __name__ == "__main__":
    app()
