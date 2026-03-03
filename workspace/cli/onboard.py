"""
onboard.py — Full wizard orchestration layer for Synapse-OSS onboarding.

This module wires together provider_steps and channel_steps into a linear wizard flow,
implements the questionary checkbox UI for provider/channel selection, handles migration
detection, and implements the complete non-interactive mode.

Exports:
  - run_wizard()           Top-level entry point dispatching to interactive or non-interactive
  - _check_for_openclaw() Named helper for ~/.openclaw/ detection (also imported by unit tests)
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from synapse_config import write_config

from cli.channel_steps import (
    CHANNEL_LIST,  # noqa: F401 — re-exported for tests
    setup_discord,
    setup_slack,
    setup_telegram,
    setup_whatsapp,
)
from cli.provider_steps import (
    _KEY_MAP,
    PROVIDER_GROUPS,
    PROVIDER_LIST,
    github_copilot_device_flow,
    validate_ollama,
    validate_provider,
)

console = Console()

MAX_KEY_ATTEMPTS = 3
NETWORK_RETRY_DELAY = 5  # seconds between network-error retries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_wizard(non_interactive: bool = False, force_interactive: bool = False) -> None:
    """Entry point — dispatches to interactive or non-interactive wizard.

    Args:
        non_interactive: Read all config from env vars; no prompts (CI/Docker use).
        force_interactive: Skip the TTY check and always run the interactive flow.
            Used by tests to exercise _run_interactive() with mocked questionary.
    """
    if non_interactive or (not force_interactive and not _is_tty()):
        _run_non_interactive()
    else:
        _run_interactive()


def _is_tty() -> bool:
    """Return True if stdin is an interactive terminal."""
    try:
        return sys.stdin.isatty()
    except AttributeError:
        return False


# ---------------------------------------------------------------------------
# Non-interactive mode
# ---------------------------------------------------------------------------


def _run_non_interactive() -> None:
    """Non-interactive wizard: reads all inputs from environment variables.

    Required env vars:
        SYNAPSE_PRIMARY_PROVIDER — which provider to configure first
        <PROVIDER>_API_KEY       — provider key (name from _KEY_MAP)

    Optional env vars:
        SYNAPSE_TELEGRAM_TOKEN
        SYNAPSE_DISCORD_TOKEN
        SYNAPSE_SLACK_BOT_TOKEN + SYNAPSE_SLACK_APP_TOKEN
        SYNAPSE_HOME             — override default ~/.synapse data root

    Exit codes:
        0 — config written successfully
        1 — required env var missing or validation failed
    """
    # --- Primary provider ---
    provider = os.environ.get("SYNAPSE_PRIMARY_PROVIDER", "").strip()
    if not provider:
        typer.echo(
            "ERROR: SYNAPSE_PRIMARY_PROVIDER is required in non-interactive mode.\n"
            f"Valid values: {', '.join(PROVIDER_LIST)}",
            err=True,
        )
        raise typer.Exit(1)

    if provider not in PROVIDER_LIST:
        typer.echo(
            f"ERROR: Unknown provider '{provider}'. Valid: {', '.join(PROVIDER_LIST)}",
            err=True,
        )
        raise typer.Exit(1)

    # --- Data root ---
    data_root = Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse"))

    # --- Build config ---
    config: dict = {"providers": {}, "model_mappings": {}, "channels": {}}

    if provider == "ollama":
        api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434").strip()
        result = validate_ollama(api_base)
        if result.ok:
            config["providers"]["ollama"] = {"api_base": api_base}
        else:
            typer.echo(
                f"ERROR: Ollama not reachable at {api_base}: {result.error} — {result.detail}",
                err=True,
            )
            raise typer.Exit(1)

    else:
        env_var = _KEY_MAP.get(provider, f"{provider.upper()}_API_KEY")
        api_key = os.environ.get(env_var, "").strip()
        if not api_key:
            typer.echo(
                f"ERROR: {env_var} is required for provider '{provider}' in non-interactive mode.",
                err=True,
            )
            raise typer.Exit(1)

        result = validate_provider(provider, api_key)
        if not result.ok and result.error != "quota_exceeded":
            typer.echo(
                f"ERROR: Provider validation failed: {result.error} — {result.detail}",
                err=True,
            )
            raise typer.Exit(1)

        config["providers"][provider] = {"api_key": api_key}

    # --- Optional channel secrets ---
    tg_token = os.environ.get("SYNAPSE_TELEGRAM_TOKEN")
    if tg_token:
        config["channels"]["telegram"] = {"token": tg_token}

    ds_token = os.environ.get("SYNAPSE_DISCORD_TOKEN")
    if ds_token:
        config["channels"]["discord"] = {"token": ds_token, "allowed_channel_ids": []}

    slk_bot = os.environ.get("SYNAPSE_SLACK_BOT_TOKEN")
    slk_app = os.environ.get("SYNAPSE_SLACK_APP_TOKEN")
    if slk_bot and slk_app:
        config["channels"]["slack"] = {"bot_token": slk_bot, "app_token": slk_app}

    # --- Model mappings ---
    config["model_mappings"] = _build_model_mappings(list(config["providers"].keys()))

    # --- Write ---
    write_config(data_root, config)
    typer.echo(f"Config written to {data_root / 'synapse.json'}")


# ---------------------------------------------------------------------------
# Model mapping builder
# ---------------------------------------------------------------------------


def _build_model_mappings(providers: list[str]) -> dict:
    """Generate sensible model_mappings based on which providers were configured."""
    mappings: dict = {}

    # casual: gemini > openai > groq > anthropic
    for cand, model in [
        ("gemini", "gemini/gemini-2.0-flash"),
        ("openai", "openai/gpt-4o-mini"),
        ("groq", "groq/llama-3.3-70b-versatile"),
        ("anthropic", "anthropic/claude-haiku-4-5"),
    ]:
        if cand in providers:
            mappings["casual"] = {"model": model, "fallback": None}
            break

    # code: anthropic > openai > groq
    for cand, model in [
        ("anthropic", "anthropic/claude-sonnet-4-6"),
        ("openai", "openai/gpt-4o"),
        ("groq", "groq/llama-3.3-70b-versatile"),
    ]:
        if cand in providers:
            mappings["code"] = {"model": model, "fallback": None}
            break

    # vault: always ollama (local-only by design)
    if "ollama" in providers:
        mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}

    return mappings


# ---------------------------------------------------------------------------
# OpenClaw migration detection
# ---------------------------------------------------------------------------


def _check_for_openclaw(openclaw_root: Path | None = None) -> Path | None:
    """Check whether an existing ~/.openclaw/ directory is present.

    Args:
        openclaw_root: Override the default ~/.openclaw path. Used by tests
                       to inject a fake directory without touching the real home.

    Returns:
        The Path if it exists and is a directory, otherwise None.
    """
    root = openclaw_root if openclaw_root is not None else Path.home() / ".openclaw"
    return root if root.exists() and root.is_dir() else None


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def _run_migration(openclaw_root: Path, dest_root: Path) -> None:
    """Import and run the migrate_openclaw migration script.

    Calls mod.migrate(source_root=openclaw_root, dest_root=dest_root) using the
    actual keyword argument names from migrate_openclaw.py's function signature.

    Falls back to a user-readable error with manual instructions on any failure.
    """
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "migrate_openclaw",
            Path(__file__).resolve().parent.parent / "scripts" / "migrate_openclaw.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        mod.migrate(source_root=openclaw_root, dest_root=dest_root)
        console.print("[green]Migration complete.[/]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Migration failed: {exc}[/]")
        console.print(
            "You can run migration manually: python workspace/scripts/migrate_openclaw.py"
        )


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


def _run_interactive() -> None:  # noqa: C901 — linear wizard, complexity is intentional
    """Full interactive wizard flow with questionary prompts.

    Steps:
      1. Welcome banner
      2. Check for existing config
      3. Migration detection (ONB-08)
      4. Provider selection with grouped checkbox (ONB-02)
      5. Per-provider key collection + validation (ONB-03 + ONB-10)
      6. Channel selection
      7. Per-channel setup (ONB-05, ONB-06)
      8. Generate model_mappings
      9. Write config (ONB-07) and show summary panel
    """
    # --- Step 1: Welcome banner ---
    console.print(Panel("[bold blue]Synapse-OSS Setup Wizard[/]", expand=False))
    console.print("This wizard will configure your LLM providers and messaging channels.")

    # --- Step 2: Check for existing config ---
    data_root = Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse"))
    config_path = data_root / "synapse.json"
    if config_path.exists():
        ans = questionary.confirm("synapse.json already exists. Reconfigure?", default=False).ask()
        if not ans:
            raise typer.Exit(0)

    # --- Step 3: Migration detection (ONB-08) ---
    detected = _check_for_openclaw()
    if detected:
        console.print("[yellow]Found existing ~/.openclaw/ data.[/]")
        do_migrate = questionary.confirm("Migrate data to ~/.synapse/ now?", default=True).ask()
        if do_migrate is None:
            raise typer.Exit(1)  # Ctrl+C
        if do_migrate:
            _run_migration(detected, data_root)

    # --- Step 4: Provider selection (ONB-02) ---
    choices: list = []
    for group in PROVIDER_GROUPS:
        choices.append(questionary.Separator(group["separator"]))
        for p in group["providers"]:
            choices.append(questionary.Choice(p["label"], value=p["key"]))

    selected_providers = questionary.checkbox(
        "Select LLM providers to configure (Space to toggle, Enter to confirm):",
        choices=choices,
    ).ask()

    if selected_providers is None:
        console.print("[yellow]Aborted.[/]")
        raise typer.Exit(1)
    if not selected_providers:
        console.print("[yellow]No providers selected. Exiting.[/]")
        raise typer.Exit(0)

    # --- Step 5: Per-provider key collection + validation (ONB-03 + ONB-10) ---
    config: dict = {"providers": {}, "model_mappings": {}, "channels": {}}

    for provider in selected_providers:
        console.print(f"\n[bold cyan]--- {provider} ---[/]")

        # ONB-10: GitHub Copilot — device flow instead of password prompt
        if provider == "github_copilot":
            token = asyncio.run(github_copilot_device_flow(console))
            if token:
                config["providers"]["github_copilot"] = {"token": token}
            else:
                console.print("[yellow]  Skipping GitHub Copilot (auth failed or timed out).[/]")
            continue

        # Ollama — api_base + httpx health check
        if provider == "ollama":
            api_base = questionary.text("Ollama api_base:", default="http://localhost:11434").ask()
            if api_base is None:
                continue
            with console.status(f"[yellow]Checking Ollama at {api_base}...[/]"):
                result = validate_ollama(api_base)
            if result.ok:
                console.print(f"  [green]Ollama {result.detail}[/]")
                config["providers"]["ollama"] = {"api_base": api_base}
            else:
                console.print(f"  [red]Ollama not reachable: {result.error}[/]")
                console.print("  Tip: Start Ollama first (https://ollama.com) then re-run.")
            continue

        # vLLM — api_base only (no validation call)
        if provider == "vllm":
            api_base = questionary.text("vLLM api_base:").ask()
            if api_base is None:
                continue
            config["providers"]["vllm"] = {"api_base": api_base}
            console.print(
                "  [green]vLLM configured "
                "(connectivity not validated — check /health manually).[/]"
            )
            continue

        # AWS Bedrock — 3 values before validation
        if provider == "bedrock":
            aws_key = questionary.password("AWS Access Key ID (AKIA...):").ask()
            aws_secret = questionary.password("AWS Secret Access Key:").ask()
            aws_region = questionary.text("AWS Region:", default="us-east-1").ask()
            if not all([aws_key, aws_secret, aws_region]):
                continue
            # Temporarily set env vars so litellm can pick them up
            os.environ["AWS_ACCESS_KEY_ID"] = aws_key  # type: ignore[arg-type]
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret  # type: ignore[arg-type]
            os.environ["AWS_DEFAULT_REGION"] = aws_region  # type: ignore[arg-type]
            with console.status("[yellow]Validating Bedrock credentials...[/]"):
                result = validate_provider("bedrock", aws_key)  # env vars drive the call
            if result.ok or result.error == "quota_exceeded":
                quota_note = " (quota exceeded — key accepted)" if result.error else ""
                console.print(f"  [green]Bedrock credentials valid[/]{quota_note}")
                config["providers"]["bedrock"] = {
                    "aws_access_key_id": aws_key,
                    "aws_secret_access_key": aws_secret,
                    "aws_region_name": aws_region,
                }
            else:
                console.print(f"  [red]Bedrock validation failed: {result.error}[/]")
            continue

        # Standard cloud provider: password prompt + validate_provider()
        env_var = _KEY_MAP.get(provider, f"{provider.upper()}_API_KEY")

        for attempt in range(MAX_KEY_ATTEMPTS):
            prompt_label = f"Enter {provider} API key [{env_var}]" + (
                f" (attempt {attempt + 1}/{MAX_KEY_ATTEMPTS}):" if attempt > 0 else ":"
            )
            key = questionary.password(prompt_label).ask()
            if key is None:
                break  # Ctrl+C — skip this provider
            if not key.strip():
                continue  # empty input — re-prompt

            with console.status(f"[yellow]Validating {provider} key...[/]", spinner="dots"):
                result = validate_provider(provider, key.strip())

            if result.ok:
                quota_note = (
                    " (quota exceeded — key accepted)" if result.error == "quota_exceeded" else ""
                )
                console.print(f"  [green]✓[/] {provider} key valid{quota_note}")
                config["providers"][provider] = {"api_key": key.strip()}
                break
            elif result.error == "quota_exceeded":
                console.print("  [yellow]  Key valid but quota exhausted — saving key.[/]")
                config["providers"][provider] = {"api_key": key.strip()}
                break
            elif result.error in ("timeout", "network_error") and attempt < MAX_KEY_ATTEMPTS - 1:
                console.print(
                    f"  [yellow]  {result.error} — retrying in {NETWORK_RETRY_DELAY}s...[/]"
                )
                time.sleep(NETWORK_RETRY_DELAY)
            else:
                console.print(
                    f"  [red]✗[/] {provider}: {result.error} — {result.detail or 'check key'}"
                )

    # --- Step 6: Channel selection (ONB-04) ---
    channel_choices = [
        questionary.Choice("WhatsApp (QR code scan required)", value="whatsapp"),
        questionary.Choice("Telegram (bot token)", value="telegram"),
        questionary.Choice("Discord (bot token + MESSAGE_CONTENT intent)", value="discord"),
        questionary.Choice("Slack (xoxb- + xapp- tokens)", value="slack"),
    ]
    selected_channels = questionary.checkbox(
        "Select messaging channels to configure (optional — can be added later):",
        choices=channel_choices,
    ).ask()
    if selected_channels is None:
        console.print("[yellow]Aborted.[/]")
        raise typer.Exit(1)

    # --- Step 7: Per-channel setup (ONB-05, ONB-06) ---
    # Resolve bridge_dir relative to this file or workspace root
    _this_file = Path(__file__).resolve()
    bridge_dir = _this_file.parent.parent.parent / "baileys-bridge"
    if not bridge_dir.exists():
        bridge_dir = _this_file.parent.parent / "baileys-bridge"

    channel_config_map = {
        "whatsapp": lambda: setup_whatsapp(bridge_dir, non_interactive=False),
        "telegram": lambda: setup_telegram(non_interactive=False),
        "discord": lambda: setup_discord(non_interactive=False),
        "slack": lambda: setup_slack(non_interactive=False),
    }
    for ch in selected_channels or []:
        ch_cfg = channel_config_map[ch]()
        if ch_cfg is not None:
            config["channels"][ch] = ch_cfg

    # --- Step 8: Generate model_mappings ---
    config["model_mappings"] = _build_model_mappings(list(config["providers"].keys()))

    # --- Step 9: Write config (ONB-07) ---

    write_config(data_root, config)
    cfg_file = data_root / "synapse.json"
    mode = oct(cfg_file.stat().st_mode & 0o777)
    console.print(
        Panel(
            f"[bold green]Setup complete![/]\n\n"
            f"Config: {cfg_file}\n"
            f"Permissions: {mode}\n"
            f"Providers: {', '.join(config['providers'].keys()) or '(none)'}\n"
            f"Channels: {', '.join(config['channels'].keys()) or '(none)'}",
            title="Synapse-OSS Ready",
            expand=False,
        )
    )
