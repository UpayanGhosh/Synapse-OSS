"""
onboard.py — Full wizard orchestration layer for Synapse-OSS onboarding.

This module wires together provider_steps and channel_steps into a linear wizard flow,
implements the questionary checkbox UI for provider/channel selection, handles migration
detection, and implements the complete non-interactive mode.

Exports:
  - run_wizard()           Top-level entry point dispatching to interactive or non-interactive
  - _check_for_legacy_install() Named helper for legacy install detection (also imported by unit tests)
"""

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

import typer

# ---------------------------------------------------------------------------
# Conditional rich import — fall back to plain print if not installed
# (Required fix: no bare module-level import of rich or questionary)
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _RICH_AVAILABLE = True
    console = Console()
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False
    Console = None  # type: ignore[assignment,misc]
    Panel = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]
    console = None  # type: ignore[assignment]


def _print(msg: str) -> None:
    """Print with Rich if available, else plain print (strips markup)."""
    if _RICH_AVAILABLE and console is not None:
        console.print(msg)
    else:
        import re  # noqa: PLC0415

        plain = re.sub(r"\[/?[^\]]*\]", "", msg)
        print(plain)


from synapse_config import write_config  # noqa: E402

from cli.channel_steps import (  # noqa: E402
    CHANNEL_LIST,  # noqa: F401 — re-exported for tests
    setup_discord,
    setup_slack,
    setup_telegram,
    setup_whatsapp,
)
from cli.provider_steps import (  # noqa: E402
    _KEY_MAP,
    PROVIDER_GROUPS,
    PROVIDER_LIST,
    github_copilot_device_flow,
    validate_ollama,
    validate_provider,
)

MAX_KEY_ATTEMPTS = 3
NETWORK_RETRY_DELAY = 5  # seconds between network-error retries

# Valid reset scopes
_RESET_SCOPES = ("config", "config+creds+sessions", "full")

# Onboarding default DM scope (matches blueprint ONBOARDING_DEFAULT_DM_SCOPE)
_ONBOARDING_DEFAULT_DM_SCOPE = "per-channel-peer"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_wizard(
    non_interactive: bool = False,
    force_interactive: bool = False,
    flow: str = "quickstart",
    accept_risk: bool = False,
    reset: str | None = None,
) -> None:
    """Entry point — dispatches to interactive or non-interactive wizard.

    Args:
        non_interactive:  Read all config from env vars; no prompts (CI/Docker use).
        force_interactive: Skip the TTY check and always run the interactive flow.
            Used by tests to exercise _run_interactive() with mocked prompter.
        flow:             "quickstart" (default) or "advanced" — controls which
            prompts are shown in interactive mode.
        accept_risk:      Must be True when non_interactive=True; guard against
            silent data loss in automated pipelines.
        reset:            If set, must be one of "config", "config+creds+sessions",
            or "full". Backed-up data before wizard starts.
    """
    if non_interactive or (not force_interactive and not _is_tty()):
        _run_non_interactive(accept_risk=accept_risk, reset=reset, flow=flow)
    else:
        _run_interactive(flow=flow, reset=reset)


def _is_tty() -> bool:
    """Return True if stdin is an interactive terminal."""
    try:
        return sys.stdin.isatty()
    except AttributeError:
        return False


# ---------------------------------------------------------------------------
# Non-interactive mode
# ---------------------------------------------------------------------------


def _run_non_interactive(
    accept_risk: bool = False,
    reset: str | None = None,
    flow: str = "quickstart",
) -> None:
    """Non-interactive wizard: reads all inputs from environment variables.

    Required env vars:
        SYNAPSE_PRIMARY_PROVIDER — which provider to configure first
        <PROVIDER>_API_KEY       — provider key (name from _KEY_MAP)

    Optional env vars:
        SYNAPSE_TELEGRAM_TOKEN
        SYNAPSE_DISCORD_TOKEN
        SYNAPSE_SLACK_BOT_TOKEN + SYNAPSE_SLACK_APP_TOKEN
        SYNAPSE_HOME             — override default ~/.synapse data root
        SYNAPSE_GATEWAY_TOKEN    — WebSocket control-plane auth token

    Exit codes:
        0 — config written successfully
        1 — required env var missing or validation failed
    """
    # --- accept-risk guard ---
    if not accept_risk:
        typer.echo(
            "ERROR: --non-interactive requires --accept-risk to confirm you understand "
            "that all configuration is read from environment variables without prompting.",
            err=True,
        )
        raise typer.Exit(1)

    # --- Data root ---
    data_root = Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse"))

    # --- Handle reset ---
    if reset is not None:
        _handle_reset(reset, data_root)

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
        dm_pol = os.environ.get("SYNAPSE_TELEGRAM_DM_POLICY", "pairing")
        config["channels"]["telegram"]["dm_policy"] = dm_pol

    ds_token = os.environ.get("SYNAPSE_DISCORD_TOKEN")
    if ds_token:
        config["channels"]["discord"] = {"token": ds_token, "allowed_channel_ids": []}
        dm_pol = os.environ.get("SYNAPSE_DISCORD_DM_POLICY", "pairing")
        config["channels"]["discord"]["dm_policy"] = dm_pol

    slk_bot = os.environ.get("SYNAPSE_SLACK_BOT_TOKEN")
    slk_app = os.environ.get("SYNAPSE_SLACK_APP_TOKEN")
    if slk_bot and slk_app:
        config["channels"]["slack"] = {"bot_token": slk_bot, "app_token": slk_app}
        dm_pol = os.environ.get("SYNAPSE_SLACK_DM_POLICY", "pairing")
        config["channels"]["slack"]["dm_policy"] = dm_pol

    # --- Gateway config (replaces bare gw_token block) ---
    from cli.gateway_steps import configure_gateway  # noqa: PLC0415

    gw_cfg = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)
    config["gateway"] = gw_cfg

    # --- Session defaults ---
    config["session"] = {"dmScope": _ONBOARDING_DEFAULT_DM_SCOPE, "identityLinks": {}}

    # --- Model mappings ---
    config["model_mappings"] = _build_model_mappings(list(config["providers"].keys()))

    # --- Write ---
    write_config(data_root, config)
    typer.echo(f"Config written to {data_root / 'synapse.json'}")

    # --- Environment validation ---
    _validate_environment(config)


# ---------------------------------------------------------------------------
# Reset handler
# ---------------------------------------------------------------------------


def _handle_reset(reset_scope: str, data_root: Path) -> None:
    """Back up existing config/credentials/sessions per the requested scope.

    Validates reset_scope before touching any files. Uses shutil.move to
    move matching paths into a timestamped backup directory.

    Args:
        reset_scope: One of "config", "config+creds+sessions", or "full".
        data_root:   The ~/.synapse (or SYNAPSE_HOME) data root.

    Raises:
        typer.Exit(1) on invalid scope (before any shutil.move call).
    """
    if reset_scope not in _RESET_SCOPES:
        typer.echo(
            f"ERROR: Invalid --reset scope {reset_scope!r}. "
            f"Valid values: {', '.join(_RESET_SCOPES)}",
            err=True,
        )
        raise typer.Exit(1)

    from datetime import UTC, datetime  # noqa: PLC0415

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = data_root / "backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    def _move_if_exists(path: Path) -> None:
        if path.exists():
            dest = backup_dir / path.name
            shutil.move(str(path), str(dest))
            _print(f"[yellow]Moved {path} → {dest}[/]")

    if reset_scope == "config":
        _move_if_exists(data_root / "synapse.json")

    elif reset_scope == "config+creds+sessions":
        _move_if_exists(data_root / "synapse.json")
        _move_if_exists(data_root / "credentials")
        _move_if_exists(data_root / "sessions")

    elif reset_scope == "full":
        # Move the entire data root contents (except the backups dir itself)
        for child in data_root.iterdir():
            if child.name == "backups":
                continue
            _move_if_exists(child)

    _print(f"[green]Reset complete. Backup at: {backup_dir}[/]")


# ---------------------------------------------------------------------------
# Model mapping builder
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Known models per provider (curated list — update when providers add models)
# ---------------------------------------------------------------------------

_KNOWN_MODELS: dict[str, list[dict[str, str]]] = {
    "gemini": [
        {"value": "gemini/gemini-2.5-flash", "label": "Gemini 2.5 Flash (fast, cheap)"},
        {"value": "gemini/gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite (fastest, free tier)"},
        {"value": "gemini/gemini-2.5-pro", "label": "Gemini 2.5 Pro (best quality)"},
        {"value": "gemini/gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
    ],
    "openai": [
        {"value": "openai/gpt-4o", "label": "GPT-4o (flagship)"},
        {"value": "openai/gpt-4o-mini", "label": "GPT-4o Mini (fast, cheap)"},
        {"value": "openai/o3-mini", "label": "o3-mini (reasoning)"},
        {"value": "openai/o4-mini", "label": "o4-mini (reasoning)"},
    ],
    "github_copilot": [
        {"value": "github_copilot/gpt-4.1", "label": "GPT-4.1 (flagship)"},
        {"value": "github_copilot/gpt-4.1-mini", "label": "GPT-4.1 Mini (fast)"},
        {"value": "github_copilot/gpt-4.1-nano", "label": "GPT-4.1 Nano (fastest)"},
        {"value": "github_copilot/gpt-4o", "label": "GPT-4o"},
        {"value": "github_copilot/gpt-4o-mini", "label": "GPT-4o Mini"},
        {"value": "github_copilot/o3-mini", "label": "o3-mini (reasoning)"},
        {"value": "github_copilot/o4-mini", "label": "o4-mini (reasoning)"},
        {"value": "github_copilot/claude-sonnet-4", "label": "Claude Sonnet 4"},
        {"value": "github_copilot/gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
    ],
    "anthropic": [
        {"value": "anthropic/claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (balanced)"},
        {"value": "anthropic/claude-haiku-4-5", "label": "Claude Haiku 4.5 (fast, cheap)"},
        {"value": "anthropic/claude-opus-4-6", "label": "Claude Opus 4.6 (best quality)"},
    ],
    "groq": [
        {"value": "groq/llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile"},
        {"value": "groq/llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant (fastest)"},
    ],
    "openrouter": [
        {"value": "openrouter/auto", "label": "Auto (best available)"},
        {"value": "openrouter/google/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"value": "openrouter/anthropic/claude-sonnet-4", "label": "Claude Sonnet 4"},
    ],
    "mistral": [
        {"value": "mistral/mistral-large-latest", "label": "Mistral Large (flagship)"},
        {"value": "mistral/mistral-small-latest", "label": "Mistral Small (fast)"},
    ],
    "xai": [
        {"value": "xai/grok-3", "label": "Grok 3"},
        {"value": "xai/grok-3-mini", "label": "Grok 3 Mini (fast)"},
    ],
}

# Roles with descriptions and default preference order
_ROLES: list[tuple[str, str, list[str]]] = [
    ("casual", "Casual chat — fast, everyday", ["gemini", "openai", "github_copilot", "groq", "anthropic"]),
    ("code", "Code generation & debugging", ["anthropic", "openai", "github_copilot", "groq"]),
    ("analysis", "Analysis & deep research", ["gemini", "openai", "github_copilot", "anthropic"]),
    ("review", "Code review & critique", ["anthropic", "openai", "github_copilot", "gemini"]),
    ("kg", "Knowledge Graph extraction (background, always Gemini free tier)", ["gemini"]),
]


def _auto_pick(providers: list[str], prefs: list[str], models_map: dict) -> str | None:
    """Return the first available model for the first matching provider."""
    for prov in prefs:
        if prov in providers and prov in models_map:
            return models_map[prov][0]["value"]
    return None


def _build_model_mappings(providers: list[str]) -> dict:
    """Generate sensible model_mappings automatically (QuickStart / non-interactive)."""
    mappings: dict = {}
    for role, _desc, prefs in _ROLES:
        if role == "kg":
            continue  # handled below — always Gemini Flash-Lite
        model = _auto_pick(providers, prefs, _KNOWN_MODELS)
        if model:
            mappings[role] = {"model": model, "fallback": None}

    # vault: always ollama (local-only by design)
    if "ollama" in providers:
        mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}

    # kg: always Gemini Flash-Lite (free tier, 1000 req/day)
    # This is independent of the user's chat provider choice.
    if "gemini" in providers:
        mappings["kg"] = {
            "model": "gemini/gemini-2.5-flash-lite",
            "fallback": "gemini/gemini-2.5-flash",
        }

    return mappings


def _build_model_mappings_interactive(providers: list[str], prompter: "object") -> dict:
    """Let the user pick a model for each role from their configured providers."""
    # Build choices from all configured providers
    available: list = []
    try:
        import questionary  # noqa: PLC0415

        for prov in providers:
            models = _KNOWN_MODELS.get(prov)
            if not models:
                continue
            available.append(questionary.Separator(f"--- {prov} ---"))
            for m in models:
                available.append(questionary.Choice(m["label"], value=m["value"]))
    except ImportError:
        # No questionary — flat list of values
        for prov in providers:
            for m in _KNOWN_MODELS.get(prov, []):
                available.append(m["value"])

    if not available:
        _print("[yellow]No known models for selected providers. Using defaults.[/]")
        return _build_model_mappings(providers)

    _print("\n[bold cyan]--- Model Selection ---[/]")
    _print("Choose a model for each role. You can use the same model for multiple roles.\n")

    mappings: dict = {}
    for role, desc, prefs in _ROLES:
        if role == "kg":
            continue  # handled below — always Gemini Flash-Lite
        default = _auto_pick(providers, prefs, _KNOWN_MODELS)
        selected = prompter.select(  # type: ignore[attr-defined]
            f"{role} ({desc}):",
            choices=available,
            default=default,
        )
        mappings[role] = {"model": selected, "fallback": None}

    # vault: always ollama (local-only by design)
    if "ollama" in providers:
        mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}

    # kg: always Gemini Flash-Lite (free tier, 1000 req/day)
    # Not user-configurable — memory engine runs on Gemini regardless of chat provider.
    if "gemini" in providers:
        mappings["kg"] = {
            "model": "gemini/gemini-2.5-flash-lite",
            "fallback": "gemini/gemini-2.5-flash",
        }
        _print("[dim]   KG role auto-set to Gemini 2.5 Flash-Lite (free tier)[/]")

    return mappings


# ---------------------------------------------------------------------------
# Legacy install migration detection
# ---------------------------------------------------------------------------


def _check_for_legacy_install(legacy_root: Path | None = None) -> Path | None:
    """Check whether an existing legacy install directory is present.

    Args:
        legacy_root: Override the default ~/.openclaw path. Used by tests
                     to inject a fake directory without touching the real home.

    Returns:
        The Path if it exists and is a directory, otherwise None.
    """
    root = legacy_root if legacy_root is not None else Path.home() / ".openclaw"
    return root if root.exists() and root.is_dir() else None


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def _run_migration(legacy_root: Path, dest_root: Path) -> None:
    """Import and run the migrate_legacy migration script.

    Calls mod.migrate(source_root=legacy_root, dest_root=dest_root) using the
    actual keyword argument names from migrate_openclaw.py's function signature.

    Falls back to a user-readable error with manual instructions on any failure.
    """
    try:
        import importlib.util  # noqa: PLC0415

        spec = importlib.util.spec_from_file_location(
            "migrate_legacy",
            Path(__file__).resolve().parent.parent / "scripts" / "migrate_openclaw.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        mod.migrate(source_root=legacy_root, dest_root=dest_root)
        _print("[green]Migration complete.[/]")
    except Exception as exc:  # noqa: BLE001
        _print(f"[red]Migration failed: {exc}[/]")
        _print(
            "You can run migration manually: python workspace/scripts/migrate_legacy.py"
        )


# ---------------------------------------------------------------------------
# Interactive wizard — QuickStart flow
# ---------------------------------------------------------------------------


def _run_quickstart_flow(
    prompter: "object",
    config: dict,
    data_root: Path,
) -> None:
    """QuickStart sub-flow: auto-apply defaults, minimal prompts.

    Handles Step 4 (provider selection) and Step 5 (key collection) only.
    Channel selection defaults to none (can be added later).
    """
    _print("\n[cyan]QuickStart mode: minimal prompts, sensible defaults applied.[/]")

    # --- Step 4: Provider selection ---
    try:
        import questionary  # noqa: PLC0415

        choices: list = []
        for group in PROVIDER_GROUPS:
            choices.append(questionary.Separator(group["separator"]))
            for p in group["providers"]:
                choices.append(questionary.Choice(p["label"], value=p["key"]))
    except ImportError:
        choices = [p["key"] for group in PROVIDER_GROUPS for p in group["providers"]]

    selected_providers = prompter.multiselect(  # type: ignore[attr-defined]
        "Select LLM providers to configure (Space to toggle, Enter to confirm):",
        choices=choices,
    )

    if not selected_providers:
        _print("[yellow]No providers selected. Exiting.[/]")
        raise typer.Exit(0)

    # --- Step 5: Per-provider key collection ---
    _collect_provider_keys(prompter, config, selected_providers)


# ---------------------------------------------------------------------------
# Interactive wizard — Advanced flow
# ---------------------------------------------------------------------------


def _run_advanced_flow(
    prompter: "object",
    config: dict,
    data_root: Path,
) -> tuple[list, Path]:
    """Advanced sub-flow: prompts for workspace dir and all settings.

    Returns:
        Tuple of (selected_channels, workspace_dir).
    """
    _print("\n[cyan]Advanced mode: all settings exposed.[/]")

    # --- Workspace directory prompt ---
    default_workspace = str(data_root / "workspace")
    workspace_raw = prompter.text(  # type: ignore[attr-defined]
        "Agent workspace directory:", default=default_workspace
    )
    workspace_dir = Path(workspace_raw) if workspace_raw else data_root / "workspace"

    # --- Step 4: Provider selection ---
    try:
        import questionary  # noqa: PLC0415

        choices: list = []
        for group in PROVIDER_GROUPS:
            choices.append(questionary.Separator(group["separator"]))
            for p in group["providers"]:
                choices.append(questionary.Choice(p["label"], value=p["key"]))
    except ImportError:
        choices = [p["key"] for group in PROVIDER_GROUPS for p in group["providers"]]

    selected_providers = prompter.multiselect(  # type: ignore[attr-defined]
        "Select LLM providers to configure (Space to toggle, Enter to confirm):",
        choices=choices,
    )

    if not selected_providers:
        _print("[yellow]No providers selected. Exiting.[/]")
        raise typer.Exit(0)

    # --- Step 5: Per-provider key collection ---
    _collect_provider_keys(prompter, config, selected_providers)

    # --- Step 6: Channel selection ---
    try:
        import questionary  # noqa: PLC0415

        channel_choices = [
            questionary.Choice("Telegram (bot token)", value="telegram"),
            questionary.Choice("Discord (bot token + MESSAGE_CONTENT intent)", value="discord"),
            questionary.Choice("Slack (xoxb- + xapp- tokens)", value="slack"),
        ]
    except ImportError:
        channel_choices = ["telegram", "discord", "slack"]

    selected_channels = prompter.multiselect(  # type: ignore[attr-defined]
        "Select additional channels to configure (optional — can be added later):",
        choices=channel_choices,
    )

    return selected_channels, workspace_dir


# ---------------------------------------------------------------------------
# Provider key collection (shared between QuickStart and Advanced)
# ---------------------------------------------------------------------------


def _collect_provider_keys(
    prompter: "object",
    config: dict,
    selected_providers: list,
) -> None:
    """Collect API keys/tokens for each selected provider (Steps 5/ONB-03)."""
    if any(p in selected_providers for p in ("anthropic", "openai")):
        prompter.note(  # type: ignore[attr-defined]
            "API keys \u2260 Subscriptions\n\n"
            "Claude Pro/Max and ChatGPT Plus subscriptions do NOT include API access.\n"
            "You need a separate API key from the provider's developer console:\n\n"
            "  \u2022 Anthropic \u2192 console.anthropic.com\n"
            "  \u2022 OpenAI    \u2192 platform.openai.com/api-keys\n"
            "  \u2022 Gemini    \u2192 aistudio.google.com (free tier available)",
        )
    for provider in selected_providers:
        _print(f"\n[bold cyan]--- {provider} ---[/]")

        # ONB-10: GitHub Copilot — device flow instead of password prompt
        if provider == "github_copilot":
            token = asyncio.run(github_copilot_device_flow(console))
            if token:
                config["providers"]["github_copilot"] = {"token": token}
            else:
                _print("[yellow]  Skipping GitHub Copilot (auth failed or timed out).[/]")
            continue

        # Ollama — api_base + httpx health check
        if provider == "ollama":
            api_base = prompter.text(  # type: ignore[attr-defined]
                "Ollama api_base:", default="http://localhost:11434"
            )
            if _RICH_AVAILABLE and console is not None:
                with console.status(f"[yellow]Checking Ollama at {api_base}...[/]"):
                    result = validate_ollama(api_base)
            else:
                _print(f"Checking Ollama at {api_base}...")
                result = validate_ollama(api_base)
            if result.ok:
                _print(f"  [green]Ollama {result.detail}[/]")
                config["providers"]["ollama"] = {"api_base": api_base}
                # --- Ollama model discovery preview ---
                try:
                    from sci_fi_dashboard.models_catalog import (
                        discover_ollama_models,  # noqa: PLC0415
                    )

                    if _RICH_AVAILABLE and console is not None:
                        with console.status("[yellow]Discovering installed models...[/]"):
                            ollama_models = asyncio.run(discover_ollama_models(api_base))
                    else:
                        ollama_models = asyncio.run(discover_ollama_models(api_base))
                    if ollama_models:
                        if _RICH_AVAILABLE and Table is not None and console is not None:
                            tbl = Table(title="Installed Ollama Models")
                            tbl.add_column("Model Name")
                            tbl.add_column("Context Window")
                            for m in ollama_models:
                                ctx = (
                                    f"{m.context_window // 1024}k"
                                    if m.context_window > 0
                                    else "unknown"
                                )
                                tbl.add_row(m.name, ctx)
                            console.print(tbl)
                        else:
                            for m in ollama_models:
                                _print(f"  {m.name}")
                    else:
                        _print(
                            "  [yellow]No models found — pull one with: ollama pull llama3.3[/]"
                        )
                except Exception:  # noqa: BLE001
                    _print("  [yellow]Could not discover Ollama models (non-fatal).[/]")
            else:
                _print(f"  [red]Ollama not reachable: {result.error}[/]")
                _print("  Tip: Start Ollama first (https://ollama.com) then re-run.")
            continue

        # vLLM — api_base only (no validation call)
        if provider == "vllm":
            api_base = prompter.text("vLLM api_base:")  # type: ignore[attr-defined]
            if not api_base:
                continue
            config["providers"]["vllm"] = {"api_base": api_base}
            _print(
                "  [green]vLLM configured "
                "(connectivity not validated — check /health manually).[/]"
            )
            continue

        # AWS Bedrock — 3 values before validation
        if provider == "bedrock":
            aws_key = prompter.text(  # type: ignore[attr-defined]
                "AWS Access Key ID (AKIA...):", password=True
            )
            aws_secret = prompter.text("AWS Secret Access Key:", password=True)  # type: ignore[attr-defined]
            aws_region = prompter.text("AWS Region:", default="us-east-1")  # type: ignore[attr-defined]
            if not all([aws_key, aws_secret, aws_region]):
                continue
            os.environ["AWS_ACCESS_KEY_ID"] = aws_key
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret
            os.environ["AWS_DEFAULT_REGION"] = aws_region
            if _RICH_AVAILABLE and console is not None:
                with console.status("[yellow]Validating Bedrock credentials...[/]"):
                    result = validate_provider("bedrock", aws_key)
            else:
                result = validate_provider("bedrock", aws_key)
            if result.ok or result.error == "quota_exceeded":
                quota_note = " (quota exceeded — key accepted)" if result.error else ""
                _print(f"  [green]Bedrock credentials valid[/]{quota_note}")
                config["providers"]["bedrock"] = {
                    "aws_access_key_id": aws_key,
                    "aws_secret_access_key": aws_secret,
                    "aws_region_name": aws_region,
                }
            else:
                _print(f"  [red]Bedrock validation failed: {result.error}[/]")
            continue

        # Standard cloud provider: password prompt + validate_provider()
        env_var = _KEY_MAP.get(provider, f"{provider.upper()}_API_KEY")

        for attempt in range(MAX_KEY_ATTEMPTS):
            prompt_label = f"Enter {provider} API key [{env_var}]" + (
                f" (attempt {attempt + 1}/{MAX_KEY_ATTEMPTS}):" if attempt > 0 else ":"
            )
            key = prompter.text(prompt_label, password=True)  # type: ignore[attr-defined]
            if not key:
                break  # empty / cancelled — skip this provider
            if not key.strip():
                continue  # empty input — re-prompt

            if _RICH_AVAILABLE and console is not None:
                with console.status(
                    f"[yellow]Validating {provider} key...[/]", spinner="dots"
                ):
                    result = validate_provider(provider, key.strip())
            else:
                result = validate_provider(provider, key.strip())

            if result.ok:
                quota_note = (
                    " (quota exceeded — key accepted)" if result.error == "quota_exceeded" else ""
                )
                _print(f"  [green]checkmark[/] {provider} key valid{quota_note}")
                config["providers"][provider] = {"api_key": key.strip()}
                break
            elif result.error == "quota_exceeded":
                _print("  [yellow]  Key valid but quota exhausted — saving key.[/]")
                config["providers"][provider] = {"api_key": key.strip()}
                break
            elif result.error in ("timeout", "network_error") and attempt < MAX_KEY_ATTEMPTS - 1:
                _print(
                    f"  [yellow]  {result.error} — retrying in {NETWORK_RETRY_DELAY}s...[/]"
                )
                time.sleep(NETWORK_RETRY_DELAY)
            else:
                _print(
                    f"  [red]x[/] {provider}: {result.error} — {result.detail or 'check key'}"
                )


# ---------------------------------------------------------------------------
# Interactive wizard — main entry point
# ---------------------------------------------------------------------------


def _run_interactive(  # noqa: C901 — linear wizard, complexity is intentional
    prompter: "object | None" = None,
    flow: str = "quickstart",
    reset: str | None = None,
) -> None:
    """Full interactive wizard flow.

    Steps:
      1. Welcome banner
      2. Check for existing config
      2b. Flow selection (QuickStart vs Advanced) — if not passed via arg
      3. Migration detection (ONB-08)
      4. Provider selection (ONB-02)  [via flow sub-function]
      5. Per-provider key collection (ONB-03 + ONB-10) [via flow sub-function]
      6. Channel selection  [advanced only]
      7. Per-channel setup (ONB-05, ONB-06)
      7b. Workspace seeding
      8. Gateway configuration
      9. Generate model_mappings
      10. Write config (ONB-07)
      11. Daemon install + health poll
      12. Show summary panel
    """
    from cli.wizard_prompter import WizardCancelledError  # noqa: PLC0415

    if prompter is None:
        try:
            from cli.inquirerpy_prompter import InquirerPyPrompter  # noqa: PLC0415

            prompter = InquirerPyPrompter()
        except ImportError:
            from cli.wizard_prompter import QuestionaryPrompter  # noqa: PLC0415

            prompter = QuestionaryPrompter()

    try:
        _run_interactive_impl(prompter=prompter, flow=flow, reset=reset)
    except WizardCancelledError:
        _print("[yellow]Wizard cancelled.[/]")
        raise typer.Exit(1) from None


def _run_interactive_impl(
    prompter: "object",
    flow: str,
    reset: str | None,
) -> None:  # noqa: C901 — linear wizard, complexity is intentional
    """Inner implementation of the interactive wizard (separated for exception isolation)."""
    # --- Step 1: Welcome banner ---
    prompter.intro("Synapse-OSS Setup Wizard")  # type: ignore[attr-defined]
    _print("This wizard will configure your LLM providers and messaging channels.")

    # --- Data root ---
    data_root = Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse"))

    # --- Handle reset ---
    if reset is not None:
        _handle_reset(reset, data_root)

    # --- Step 2: Check for existing config ---
    config_path = data_root / "synapse.json"
    if config_path.exists():
        ans = prompter.confirm(  # type: ignore[attr-defined]
            "synapse.json already exists. Reconfigure?", default=False
        )
        if not ans:
            raise typer.Exit(0)

    # --- Step 2b: Flow selection (only if "quickstart" is default but user may want advanced) ---
    # workspace_dir default; advanced flow may override it in _run_advanced_flow
    workspace_dir = data_root / "workspace"

    # --- Step 3: Migration detection (ONB-08) ---
    detected = _check_for_legacy_install()
    if detected:
        _print("[yellow]Found existing legacy install data.[/]")
        do_migrate = prompter.confirm(  # type: ignore[attr-defined]
            "Migrate data to ~/.synapse/ now?", default=True
        )
        if do_migrate:
            _run_migration(detected, data_root)

    # --- Steps 4-6: Flow-specific provider + channel collection ---
    config: dict = {
        "providers": {},
        "model_mappings": {},
        "channels": {},
        "session": {"dmScope": _ONBOARDING_DEFAULT_DM_SCOPE, "identityLinks": {}},
    }
    selected_channels: list = []

    if flow == "quickstart":
        _run_quickstart_flow(prompter=prompter, config=config, data_root=data_root)
        # QuickStart: no channel prompt (user can add later)
    else:
        selected_channels, workspace_dir = _run_advanced_flow(
            prompter=prompter, config=config, data_root=data_root
        )

    # --- Step 7: Per-channel setup (ONB-05, ONB-06) ---
    _this_file = Path(__file__).resolve()
    bridge_dir = _this_file.parent.parent.parent / "baileys-bridge"
    if not bridge_dir.exists():
        bridge_dir = _this_file.parent.parent / "baileys-bridge"

    # --- Step 7a: WhatsApp (mandatory) ---
    from cli.channel_steps import NodeJsMissingError  # noqa: PLC0415

    _print("\n[bold cyan]--- WhatsApp (required) ---[/]")
    _MAX_WA_RETRIES = 3
    _wa_paired = False
    for _attempt in range(1, _MAX_WA_RETRIES + 1):
        try:
            wa_cfg = setup_whatsapp(bridge_dir, non_interactive=False)
        except NodeJsMissingError as exc:
            _print(f"\n[red bold]{exc}[/]")
            raise typer.Exit(1) from None

        if wa_cfg is not None:
            config["channels"]["whatsapp"] = wa_cfg
            _wa_paired = True
            break

        if _attempt < _MAX_WA_RETRIES:
            _retry = prompter.confirm(  # type: ignore[attr-defined]
                f"WhatsApp pairing failed (attempt {_attempt}/{_MAX_WA_RETRIES}). Retry?",
                default=True,
            )
            if not _retry:
                break

    if not _wa_paired:
        _print("[red bold]WhatsApp is required for Synapse to work. Cannot continue.[/]")
        raise typer.Exit(1)

    # --- Step 7b: Optional channels ---
    channel_config_map = {
        "telegram": lambda: setup_telegram(non_interactive=False),
        "discord": lambda: setup_discord(non_interactive=False),
        "slack": lambda: setup_slack(non_interactive=False),
    }
    for ch in selected_channels or []:
        ch_cfg = channel_config_map[ch]()
        if ch_cfg is not None:
            config["channels"][ch] = ch_cfg

    # --- Step 7b: Workspace seeding ---
    try:
        from cli.workspace_seeding import ensure_agent_workspace  # noqa: PLC0415

        seeding_state = ensure_agent_workspace(workspace_dir, ensure_bootstrap_files=True)
        if seeding_state.get("bootstrapSeededAt") and not seeding_state.get("setupCompletedAt"):
            prompter.note(  # type: ignore[attr-defined]
                f"Agent workspace seeded at {workspace_dir}\n"
                "Bootstrap templates written — agent will complete identity setup"
                " on first message.",
                title="Workspace Ready",
            )
    except Exception:  # noqa: BLE001
        _print("[yellow]Workspace seeding skipped (non-fatal).[/]")

    # --- Step 8: Gateway configuration ---
    from cli.gateway_steps import configure_gateway  # noqa: PLC0415

    existing_gw = {}  # Fresh install — no existing gateway config
    gw_cfg = configure_gateway(
        flow=flow,
        existing_gateway=existing_gw,
        non_interactive=False,
        prompter=prompter,
    )
    config["gateway"] = gw_cfg

    # --- Step 9: Generate model_mappings ---
    if flow == "advanced":
        config["model_mappings"] = _build_model_mappings_interactive(
            list(config["providers"].keys()), prompter
        )
    else:
        config["model_mappings"] = _build_model_mappings(list(config["providers"].keys()))

    # --- Step 10: Write config (ONB-07) ---
    write_config(data_root, config)
    cfg_file = data_root / "synapse.json"

    # --- Step 11: Daemon install ---
    _wizard_daemon_install(prompter=prompter, config=config, data_root=data_root, flow=flow)

    # --- Step 12: Summary panel ---
    import contextlib  # noqa: PLC0415

    mode_str = ""
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            mode_str = f"\nPermissions: {oct(cfg_file.stat().st_mode & 0o777)}"

    summary = (
        f"[bold green]Setup complete![/]\n\n"
        f"Config: {cfg_file}{mode_str}\n"
        f"Providers: {', '.join(config['providers'].keys()) or '(none)'}\n"
        f"Channels: {', '.join(config['channels'].keys()) or '(none)'}"
    )

    if _RICH_AVAILABLE and Panel is not None and console is not None:
        console.print(Panel(summary, title="Synapse-OSS Ready", expand=False))
    else:
        _print(summary)

    # --- Step 13: Environment validation ---
    _validate_environment(config)


# ---------------------------------------------------------------------------
# Environment validation (post-config check)
# ---------------------------------------------------------------------------


def _validate_environment(config: dict) -> None:
    """Run a lightweight environment check after onboarding config is written.

    Checks:
      1. sqlite-vec native extension loads correctly
      2. python-magic / python-magic-bin is available
      3. Required channel SDK present for each configured channel
      4. Ollama reachable if a local model is configured

    Failures print actionable fix commands rather than stack traces.
    """
    _print("\n[bold cyan]Checking environment...[/]")

    issues: list[str] = []

    # --- Check 1: sqlite-vec ---
    try:
        import sqlite3  # noqa: PLC0415

        import sqlite_vec  # noqa: PLC0415

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _print("  [green]✓[/] sqlite-vec: OK")
    except ImportError:
        _print("  [red]✗[/] sqlite-vec: not installed")
        issues.append("  Fix: pip install sqlite-vec")
    except Exception as exc:  # noqa: BLE001
        _print(f"  [red]✗[/] sqlite-vec: failed to load ({exc})")
        issues.append("  Fix: pip install sqlite-vec  (or reinstall native libs)")

    # --- Check 2: python-magic ---
    try:
        import magic  # noqa: F401, PLC0415

        _print("  [green]✓[/] python-magic: OK")
    except ImportError:
        _print("  [yellow]![/] python-magic: not installed (media MIME detection degraded)")
        if sys.platform == "win32":
            issues.append("  Fix: pip install python-magic-bin")
        else:
            issues.append("  Fix: pip install python-magic")
    except Exception as exc:  # noqa: BLE001
        _print(f"  [yellow]![/] python-magic: import error ({exc})")
        if sys.platform == "win32":
            issues.append("  Fix: pip install python-magic-bin  (Windows requires the -bin variant)")
        else:
            issues.append(
                "  Fix: pip install python-magic"
                "  (may also need: brew install libmagic  OR  apt install libmagic1)"
            )

    # --- Check 3: channel SDKs for configured channels ---
    _channel_sdk_map: dict[str, tuple[str, str]] = {
        "telegram": ("telegram", "pip install python-telegram-bot"),
        "discord": ("discord", "pip install discord.py"),
        "slack": ("slack_bolt", "pip install slack-bolt"),
    }
    for channel, (module_name, fix_cmd) in _channel_sdk_map.items():
        if channel in config.get("channels", {}):
            try:
                __import__(module_name)
                _print(f"  [green]✓[/] {channel} SDK ({module_name}): OK")
            except ImportError:
                _print(f"  [red]✗[/] {channel} SDK ({module_name}): not installed")
                issues.append(f"  Fix ({channel}): {fix_cmd}")

    # --- Check 4: Ollama reachable if ollama provider configured ---
    if "ollama" in config.get("providers", {}):
        from cli.doctor import _check_ollama_reachable  # noqa: PLC0415

        result = _check_ollama_reachable()
        if result.passed:
            _print(f"  [green]✓[/] Ollama: reachable ({result.detail})")
        else:
            _print(f"  [red]✗[/] Ollama: not reachable ({result.detail})")
            issues.append(
                "  Fix (Ollama): start the Ollama service — https://ollama.com"
                " — then run: synapse doctor"
            )

    # --- Summary ---
    if issues:
        _print("\n[bold yellow]Environment issues detected — fix before running synapse:[/]")
        for issue in issues:
            _print(f"[yellow]{issue}[/]")
    else:
        _print("  [bold green]All environment checks passed.[/]")


# ---------------------------------------------------------------------------
# Daemon install step (final wizard step)
# ---------------------------------------------------------------------------


def _wizard_daemon_install(
    prompter: "object",
    config: dict,
    data_root: Path,
    flow: str,
) -> None:
    """Optionally install gateway as a background daemon (final wizard step)."""
    try:
        from synapse_config import SynapseConfig  # noqa: PLC0415

        from cli.daemon import build_gateway_install_plan, resolve_gateway_service  # noqa: PLC0415

        do_install: bool
        if flow == "quickstart":
            do_install = True
        else:
            do_install = prompter.confirm(  # type: ignore[attr-defined]
                "Install gateway as background service?", default=True
            )

        if not do_install:
            return

        sc = SynapseConfig.load()
        svc = resolve_gateway_service()
        opts = build_gateway_install_plan(sc)
        svc.install(opts)
        _print("[green]Gateway daemon installed.[/]")

        # Health poll
        try:
            from cli.health import wait_for_gateway_reachable  # noqa: PLC0415

            port = config.get("gateway", {}).get("port", 8000)
            token = config.get("gateway", {}).get("token")
            reachable = wait_for_gateway_reachable(port=port, token=token, deadline_secs=15.0)
            if reachable:
                _print("[green]Gateway is reachable — setup complete![/]")
            else:
                _print(
                    "[yellow]Gateway did not respond within 15s — it may still be starting. "
                    "Run: synapse health[/]"
                )
        except Exception:  # noqa: BLE001
            pass  # Health check is non-fatal

    except NotImplementedError:
        _print("[yellow]Daemon install not supported on this platform (skipped).[/]")
    except Exception as exc:  # noqa: BLE001
        _print(f"[yellow]Daemon install failed (non-fatal): {exc}[/]")
