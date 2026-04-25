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
import contextlib
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
    google_antigravity_oauth_flow,
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

    Optional SBS persona env vars (all optional — absent means use defaults silently):
        SYNAPSE_COMMUNICATION_STYLE  — preferred comm style
                                       (casual_and_witty, formal_and_precise,
                                        technical_depth, creative_and_playful)
        SYNAPSE_ENERGY_LEVEL         — energy/mood baseline
                                       (high_energy, calm_and_steady, adaptive)
        SYNAPSE_INTERESTS            — comma-separated topic list
                                       (technology, music, wellness, finance,
                                        science, arts, sports, cooking)
        SYNAPSE_PRIVACY_LEVEL        — privacy sensitivity
                                       (open, selective, private)

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

    # --- Prefetch embedding model (quiet in non-interactive mode — best-effort) ---
    with contextlib.suppress(Exception):
        _prefetch_embedding_models(list(config["providers"].keys()))

    # --- Write ---
    write_config(data_root, config)
    typer.echo(f"Config written to {data_root / 'synapse.json'}")

    # --- SBS profile seeding from env vars (all optional) ---
    communication_style = os.environ.get("SYNAPSE_COMMUNICATION_STYLE", "").strip()
    energy_level = os.environ.get("SYNAPSE_ENERGY_LEVEL", "").strip()
    interests_raw = os.environ.get("SYNAPSE_INTERESTS", "").strip()
    privacy_level = os.environ.get("SYNAPSE_PRIVACY_LEVEL", "").strip()

    if any([communication_style, energy_level, interests_raw, privacy_level]):
        try:
            from cli.sbs_profile_init import (  # noqa: PLC0415
                ENERGY_CHOICES,
                INTEREST_CHOICES,
                PRIVACY_CHOICES,
                STYLE_CHOICES,
                initialize_sbs_from_wizard,
            )

            # Validate communication_style
            if communication_style and communication_style not in STYLE_CHOICES:
                typer.echo(
                    f"WARNING: SYNAPSE_COMMUNICATION_STYLE='{communication_style}' is not valid. "
                    f"Valid: {', '.join(STYLE_CHOICES)}. Using default 'casual_and_witty'.",
                    err=True,
                )
                communication_style = "casual_and_witty"

            # Validate energy_level
            if energy_level and energy_level not in ENERGY_CHOICES:
                typer.echo(
                    f"WARNING: SYNAPSE_ENERGY_LEVEL='{energy_level}' is not valid. "
                    f"Valid: {', '.join(ENERGY_CHOICES)}. Using default 'calm_and_steady'.",
                    err=True,
                )
                energy_level = "calm_and_steady"

            # Validate privacy_level
            if privacy_level and privacy_level not in PRIVACY_CHOICES:
                typer.echo(
                    f"WARNING: SYNAPSE_PRIVACY_LEVEL='{privacy_level}' is not valid. "
                    f"Valid: {', '.join(PRIVACY_CHOICES)}. Using default 'selective'.",
                    err=True,
                )
                privacy_level = "selective"

            # Parse and validate interests (comma-separated, filter unknowns)
            parsed_interests = [i.strip().lower() for i in interests_raw.split(",") if i.strip()]
            unknown_interests = [i for i in parsed_interests if i not in INTEREST_CHOICES]
            if unknown_interests:
                typer.echo(
                    f"WARNING: Unknown interests ignored: {', '.join(unknown_interests)}. "
                    f"Valid: {', '.join(INTEREST_CHOICES)}",
                    err=True,
                )
                parsed_interests = [i for i in parsed_interests if i in INTEREST_CHOICES]

            initialize_sbs_from_wizard(
                {
                    "communication_style": communication_style or "casual_and_witty",
                    "energy_level": energy_level or "calm_and_steady",
                    "interests": parsed_interests,
                    "privacy_level": privacy_level or "selective",
                },
                data_root=data_root,
            )
            typer.echo("SBS profile initialized from environment variables.")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"WARNING: SBS profile initialization failed: {exc}", err=True)

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
# Live model discovery — hit each provider's /models endpoint with the user's key.
# No curated defaults; the wizard only falls back to _KNOWN_MODELS when the API
# is unreachable (offline, rate-limited, bad key).
#
# Each entry returned by _fetch_provider_models carries:
#   value:           litellm-compatible "<prefix>/<model_id>" (used at runtime)
#   label:           display name (usually the bare model_id, sometimes display_name)
#   context_window:  int tokens — None when provider doesn't expose it
#   capabilities:    list of tags like ["reasoning", "vision", "code"]
#   hint:            pre-built display hint string (openclaw-style "ctx 128k · reasoning")
# ---------------------------------------------------------------------------

_OPENAI_COMPAT_MODELS_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "xai": "https://api.x.ai/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "togetherai": "https://api.together.xyz/v1/models",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1/models",
    "moonshot": "https://api.moonshot.ai/v1/models",
    "zai": "https://open.bigmodel.cn/api/paas/v4/models",
}

# litellm prefixes differ from our internal provider keys for a few providers.
_LITELLM_PREFIX: dict[str, str] = {"togetherai": "together_ai"}


def _humanize_ctx(n: int | None) -> str | None:
    """Format context-window token counts as 'ctx 128k' / 'ctx 2M'."""
    if not n or n < 1:
        return None
    if n >= 1_000_000:
        return f"ctx {n // 1_000_000}M"
    if n >= 1000:
        return f"ctx {n // 1000}k"
    return f"ctx {n}"


def _infer_capabilities(model_id: str) -> list[str]:
    """Heuristic capability tags derived from a model ID string."""
    lid = model_id.lower()
    caps: list[str] = []
    reasoning_patterns = (
        "o1-", "o1_", "/o1", "o3-", "o3_", "/o3", "o4-", "o4_", "/o4", "o5-",
        "reasoning", "thinking", "-qwq", "qwq-", "r1", "deepseek-r", "nemotron-nano",
        "gpt-oss", "nemotron-super",
    )
    if any(p in lid for p in reasoning_patterns):
        caps.append("reasoning")
    if any(p in lid for p in ("vision", "-vl-", "-vl2", "vis-", "-multimodal")):
        caps.append("vision")
    if any(p in lid for p in ("code", "coder", "codex", "-cd-")):
        caps.append("code")
    return caps


def _build_hint(context_window: int | None, capabilities: list[str]) -> str | None:
    """Render the openclaw-style hint string: 'ctx 128k · reasoning · code'."""
    parts: list[str] = []
    ctx_str = _humanize_ctx(context_window)
    if ctx_str:
        parts.append(ctx_str)
    parts.extend(capabilities)
    return " · ".join(parts) if parts else None


def _make_entry(
    value: str,
    label: str,
    context_window: int | None = None,
    extra_caps: list[str] | None = None,
) -> dict[str, object]:
    """Build a fully-hydrated catalog entry with hints + capabilities."""
    caps = _infer_capabilities(label)
    if extra_caps:
        for c in extra_caps:
            if c not in caps:
                caps.append(c)
    return {
        "value": value,
        "label": label,
        "context_window": context_window,
        "capabilities": caps,
        "hint": _build_hint(context_window, caps),
    }


def _fetch_provider_models(
    provider: str,
    api_key: str | None = None,
    api_base: str | None = None,
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    """Query the provider's /models endpoint live and return hydrated entries.

    Returns:
      List of {value, label, context_window, capabilities, hint} on success.
      Empty list on any failure — caller falls back to curated catalog.
    """
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return []

    try:
        # --- Gemini: key as query param, custom shape ---
        if provider == "gemini":
            if not api_key:
                return []
            r = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=timeout,
            )
            r.raise_for_status()
            out: list[dict[str, object]] = []
            for m in r.json().get("models", []):
                name = m.get("name", "").replace("models/", "")
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                ctx = m.get("inputTokenLimit")
                out.append(_make_entry(f"gemini/{name}", name, context_window=ctx))
            return sorted(out, key=lambda x: str(x["label"]))

        # --- Anthropic: custom auth headers ---
        if provider == "anthropic":
            if not api_key:
                return []
            r = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            # Anthropic doesn't expose context_window in /models; heuristic by family.
            def _anthropic_ctx(mid: str) -> int | None:
                lm = mid.lower()
                if "claude-3-5" in lm or "claude-3-7" in lm or "claude-sonnet-4" in lm:
                    return 200000
                if "claude-3" in lm:
                    return 200000
                return None
            return [
                _make_entry(
                    f"anthropic/{m['id']}",
                    m.get("display_name", m["id"]),
                    context_window=_anthropic_ctx(m["id"]),
                )
                for m in data
            ]

        # --- Ollama: local /api/tags (no context metadata) ---
        if provider == "ollama":
            base = (api_base or "http://localhost:11434").rstrip("/")
            r = httpx.get(f"{base}/api/tags", timeout=5.0)
            r.raise_for_status()
            return [
                _make_entry(f"ollama_chat/{m['name']}", m["name"])
                for m in r.json().get("models", [])
            ]

        # --- vLLM: user-provided api_base + /v1/models ---
        if provider == "vllm":
            if not api_base:
                return []
            r = httpx.get(f"{api_base.rstrip('/')}/v1/models", timeout=5.0)
            r.raise_for_status()
            return [
                _make_entry(f"openai/{m['id']}", m["id"])
                for m in r.json().get("data", [])
            ]

        # --- OpenAI-compat providers ---
        url = _OPENAI_COMPAT_MODELS_ENDPOINTS.get(provider)
        if not url:
            return []
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = httpx.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        prefix = _LITELLM_PREFIX.get(provider, provider)
        out = []
        for m in r.json().get("data", []):
            mid = m.get("id", "")
            if not mid:
                continue
            # Provider-specific context_window extraction where available.
            ctx = None
            if provider == "openrouter":
                ctx = m.get("context_length")
            elif provider == "groq":
                ctx = m.get("context_window")
            elif provider == "togetherai":
                ctx = m.get("context_length")
            out.append(_make_entry(f"{prefix}/{mid}", mid, context_window=ctx))
        return out
    except Exception:  # noqa: BLE001 — any network/parse error → empty list
        return []


def _extract_provider_credentials(
    config: dict, provider: str
) -> tuple[str | None, str | None]:
    """Read api_key + api_base for a provider from the in-progress config dict."""
    prov_cfg = (config.get("providers") or {}).get(provider) or {}
    # Copilot uses 'token' not 'api_key'; Ollama/vLLM use only api_base; others use api_key
    api_key = prov_cfg.get("api_key") or prov_cfg.get("token")
    api_base = prov_cfg.get("api_base")
    return api_key, api_base


def _fetch_live_catalog(
    providers: list[str], config: dict
) -> dict[str, list[dict[str, object]]]:
    """Per-provider live model list, falling back to _KNOWN_MODELS on API failure.

    Entries returned are fully hydrated (value, label, context_window, capabilities, hint).
    """
    result: dict[str, list[dict[str, object]]] = {}
    for prov in providers:
        api_key, api_base = _extract_provider_credentials(config, prov)
        live = _fetch_provider_models(prov, api_key, api_base)
        if live:
            result[prov] = live
            _print(f"  [green]✓[/] {prov}: {len(live)} models (live from API)")
        elif prov in _KNOWN_MODELS:
            # Hydrate curated fallback so it has the same shape as live entries.
            result[prov] = [
                _make_entry(str(m["value"]), str(m["label"]))
                for m in _KNOWN_MODELS[prov]
            ]
            _print(
                f"  [yellow]![/] {prov}: /models API unavailable — "
                f"falling back to curated list ({len(_KNOWN_MODELS[prov])} models)"
            )
        else:
            _print(
                f"  [yellow]![/] {prov}: no model list available — "
                "enter model ID manually in the picker"
            )
    return result


# ---------------------------------------------------------------------------
# Openclaw-style unified flat picker helpers
# ---------------------------------------------------------------------------

_PROVIDER_FILTER_THRESHOLD = 30
_MANUAL_ENTRY_VALUE = "__manual__"


def _flatten_catalog(
    catalog: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Flatten the per-provider catalog into a single list.

    Each entry gains a `provider` field. Sorted by (provider, label) for
    deterministic scan order when the user doesn't search.
    """
    flat: list[dict[str, object]] = []
    for prov, models in catalog.items():
        for m in models:
            entry = dict(m)
            entry["provider"] = prov
            flat.append(entry)
    return sorted(
        flat,
        key=lambda x: (str(x.get("provider", "")), str(x.get("label", "")).lower()),
    )


def _format_choice_display(entry: dict[str, object]) -> str:
    """Render an entry as 'provider/model · ctx 128k · reasoning'."""
    value = str(entry.get("value", ""))
    hint = entry.get("hint")
    return f"{value}  ·  {hint}" if hint else value


def _prompt_provider_filter(
    flat: list[dict[str, object]], prompter: object
) -> str:
    """Openclaw-style filter step — pick one provider or * for all.

    Triggered when total models > _PROVIDER_FILTER_THRESHOLD AND >1 provider configured.
    Returns the selected provider id, or '*' for no filter.
    """
    from collections import Counter  # noqa: PLC0415

    provider_counts = Counter(str(m.get("provider", "")) for m in flat)
    if len(provider_counts) <= 1 or len(flat) <= _PROVIDER_FILTER_THRESHOLD:
        return "*"

    try:
        import questionary  # noqa: PLC0415

        choices: list = [questionary.Choice("All providers", value="*")]
        for prov, n in sorted(provider_counts.items()):
            choices.append(
                questionary.Choice(f"{prov}  ({n} model{'s' if n != 1 else ''})", value=prov)
            )
    except ImportError:
        choices = ["*"] + sorted(provider_counts.keys())

    return prompter.select(  # type: ignore[attr-defined]
        f"Filter models by provider ({len(flat)} total):",
        choices=choices,
    )


def _pick_model_fuzzy(
    role: str,
    desc: str,
    flat: list[dict[str, object]],
    prompter: object,
) -> str:
    """Openclaw-style searchable picker for one role.

    Uses InquirerPy fuzzy (type-to-filter + arrow-select) when available. Falls
    back to questionary.autocomplete, then to a plain prompter.select call for
    test stubs / headless envs. Adds a [Enter manually] escape hatch always.
    """
    manual_label = "[Enter model manually]"

    # --- Preferred: InquirerPy fuzzy (best UX, matches openclaw) ---
    try:
        from InquirerPy import inquirer  # noqa: PLC0415

        choices = [{"name": manual_label, "value": _MANUAL_ENTRY_VALUE}]
        for m in flat:
            choices.append(
                {"name": _format_choice_display(m), "value": str(m["value"])}
            )
        try:
            result = inquirer.fuzzy(  # type: ignore[attr-defined]
                message=f"{role} ({desc}):",
                choices=choices,
                max_height="70%",
                border=True,
                info=True,
                match_exact=False,
            ).execute()
        except KeyboardInterrupt:
            from cli.wizard_prompter import WizardCancelledError  # noqa: PLC0415

            raise WizardCancelledError() from None
        if result is None:
            from cli.wizard_prompter import WizardCancelledError  # noqa: PLC0415

            raise WizardCancelledError()
        if result == _MANUAL_ENTRY_VALUE:
            return _prompt_manual_model(role, prompter)
        return str(result)
    except ImportError:
        pass

    # --- Fallback: questionary.autocomplete (type-to-match, no visual list) ---
    try:
        import questionary  # noqa: PLC0415

        display_to_value: dict[str, str] = {}
        choices_disp = [manual_label]
        for m in flat:
            disp = _format_choice_display(m)
            choices_disp.append(disp)
            display_to_value[disp] = str(m["value"])
        result = questionary.autocomplete(
            f"{role} ({desc}) — start typing to search:",
            choices=choices_disp,
            ignore_case=True,
            match_middle=True,
        ).ask()
        if result is None:
            from cli.wizard_prompter import WizardCancelledError  # noqa: PLC0415

            raise WizardCancelledError()
        if result == manual_label:
            return _prompt_manual_model(role, prompter)
        return display_to_value.get(result, result)
    except ImportError:
        pass

    # --- Last resort: plain select via prompter (test stubs / no TTY) ---
    plain_choices = [manual_label] + [str(m["value"]) for m in flat]
    sel = prompter.select(  # type: ignore[attr-defined]
        f"{role} ({desc}):", choices=plain_choices
    )
    if sel == manual_label:
        return _prompt_manual_model(role, prompter)
    return str(sel)


def _prompt_manual_model(role: str, prompter: object) -> str:
    """Free-text manual entry — user types provider/model directly."""
    val = prompter.text(  # type: ignore[attr-defined]
        f"{role} model (enter litellm-style provider/model_id):"
    ).strip()
    return val


# ---------------------------------------------------------------------------
# Known models per provider (FALLBACK only — used when live /models API fails).
# ---------------------------------------------------------------------------

_KNOWN_MODELS: dict[str, list[dict[str, str]]] = {
    "gemini": [
        {"value": "gemini/gemini-2.5-flash", "label": "Gemini 2.5 Flash (fast, cheap)"},
        {
            "value": "gemini/gemini-2.5-flash-lite",
            "label": "Gemini 2.5 Flash-Lite (fastest, free tier)",
        },
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
    "google_antigravity": [
        {
            "value": "google_antigravity/gemini-3-flash",
            "label": "Gemini 3 Flash (fast, balanced)",
        },
        {
            "value": "google_antigravity/gemini-3-flash-lite",
            "label": "Gemini 3 Flash-Lite (fastest, KG-friendly)",
        },
        {
            "value": "google_antigravity/gemini-3-pro-low",
            "label": "Gemini 3 Pro (low reasoning, balanced quality)",
        },
        {
            "value": "google_antigravity/gemini-3-pro-high",
            "label": "Gemini 3 Pro (high reasoning, best quality)",
        },
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
    "nvidia_nim": [
        # Meta Llama
        {
            "value": "nvidia_nim/meta/llama-3.3-70b-instruct",
            "label": "Llama 3.3 70B Instruct (newest Meta, balanced)",
        },
        {
            "value": "nvidia_nim/meta/llama-3.1-8b-instruct",
            "label": "Llama 3.1 8B Instruct (fast, cheap)",
        },
        {
            "value": "nvidia_nim/meta/llama-3.1-70b-instruct",
            "label": "Llama 3.1 70B Instruct",
        },
        {
            "value": "nvidia_nim/meta/llama-3.1-405b-instruct",
            "label": "Llama 3.1 405B Instruct (best Meta)",
        },
        # Moonshot Kimi
        {
            "value": "nvidia_nim/moonshotai/kimi-k2-instruct",
            "label": "Kimi K2 Instruct (Moonshot, long context)",
        },
        {
            "value": "nvidia_nim/moonshotai/kimi-k2-thinking",
            "label": "Kimi K2 Thinking (reasoning)",
        },
        # OpenAI GPT-OSS
        {
            "value": "nvidia_nim/openai/gpt-oss-120b",
            "label": "GPT-OSS 120B (OpenAI open-weights, flagship)",
        },
        {
            "value": "nvidia_nim/openai/gpt-oss-20b",
            "label": "GPT-OSS 20B (OpenAI open-weights, fast)",
        },
        # Qwen
        {
            "value": "nvidia_nim/qwen/qwen3-235b-a22b",
            "label": "Qwen3 235B (Alibaba, flagship)",
        },
        {
            "value": "nvidia_nim/qwen/qwen2.5-coder-32b-instruct",
            "label": "Qwen2.5 Coder 32B (code-tuned)",
        },
        # NVIDIA Nemotron
        {
            "value": "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1",
            "label": "Nemotron Super 49B (NVIDIA tuned)",
        },
        {
            "value": "nvidia_nim/nvidia/llama-3.1-nemotron-70b-instruct",
            "label": "Nemotron 70B (NVIDIA tuned)",
        },
        {
            "value": "nvidia_nim/nvidia/nemotron-nano-9b-v2",
            "label": "Nemotron Nano 9B v2 (fast, cheap)",
        },
        # DeepSeek
        {
            "value": "nvidia_nim/deepseek-ai/deepseek-r1",
            "label": "DeepSeek R1 (reasoning)",
        },
        # Mistral
        {
            "value": "nvidia_nim/mistralai/mixtral-8x22b-instruct-v0.1",
            "label": "Mixtral 8x22B Instruct",
        },
    ],
    "deepseek": [
        {"value": "deepseek/deepseek-chat", "label": "DeepSeek Chat"},
        {"value": "deepseek/deepseek-reasoner", "label": "DeepSeek Reasoner (R1)"},
    ],
    "cohere": [
        {"value": "cohere/command-r-plus", "label": "Command R+ (flagship)"},
        {"value": "cohere/command-r", "label": "Command R"},
    ],
    "togetherai": [
        {
            "value": "together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "label": "Llama 3.3 70B Turbo",
        },
        {
            "value": "together_ai/meta-llama/Llama-3.1-8B-Instruct-Turbo",
            "label": "Llama 3.1 8B Turbo (fast)",
        },
    ],
}

# Roles with descriptions and default preference order
_ROLES: list[tuple[str, str, list[str]]] = [
    (
        "casual",
        "Casual chat — fast, everyday",
        [
            "google_antigravity",
            "gemini",
            "openai",
            "github_copilot",
            "groq",
            "nvidia_nim",
            "anthropic",
        ],
    ),
    (
        "code",
        "Code generation & debugging",
        ["anthropic", "openai", "github_copilot", "nvidia_nim", "groq"],
    ),
    (
        "analysis",
        "Analysis & deep research",
        [
            "google_antigravity",
            "gemini",
            "openai",
            "github_copilot",
            "anthropic",
            "nvidia_nim",
        ],
    ),
    (
        "review",
        "Code review & critique",
        ["anthropic", "openai", "github_copilot", "google_antigravity", "gemini", "nvidia_nim"],
    ),
    (
        "kg",
        "Knowledge Graph extraction (background, Gemini free tier recommended)",
        ["google_antigravity", "gemini"],
    ),
]


def _auto_pick(providers: list[str], prefs: list[str], models_map: dict) -> str | None:
    """Return the first available model for the first matching provider (strict — no fallback)."""
    for prov in prefs:
        if prov in providers and prov in models_map:
            return models_map[prov][0]["value"]
    return None


def _auto_pick_with_fallback(
    providers: list[str], prefs: list[str], models_map: dict
) -> str | None:
    """Pick the best model from prefs; fall back to the user's first selected provider's
    first known model if no pref matches.

    This guarantees every role gets a model as long as the user picked at least one
    provider with a known catalog.
    """
    picked = _auto_pick(providers, prefs, models_map)
    if picked is not None:
        return picked
    # Fallback: first selected provider that has a known catalog
    for prov in providers:
        if prov in models_map and models_map[prov]:
            return models_map[prov][0]["value"]
    return None


def _build_model_mappings(providers: list[str]) -> dict:
    """Generate sensible model_mappings automatically (QuickStart / non-interactive).

    Every role gets a model via `_auto_pick_with_fallback` when the user's providers have
    known catalogs. The KG role prefers Gemini (free tier, background quota friendly)
    but falls back to the user's primary provider when Gemini is absent — the memory
    engine still builds, just consumes the primary provider's quota.
    """
    mappings: dict = {}
    for role, _desc, prefs in _ROLES:
        if role == "kg":
            continue  # handled below with provider-specific logic
        model = _auto_pick_with_fallback(providers, prefs, _KNOWN_MODELS)
        if model:
            mappings[role] = {"model": model, "fallback": None}

    # vault: always ollama (local-only by design, enforces zero cloud leakage for spicy)
    if "ollama" in providers:
        mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}

    # kg: Gemini Flash-Lite preferred (free tier, 1000 req/day) — falls back to user's
    # primary provider when Gemini isn't configured. Memory engine needs *some* LLM.
    if "gemini" in providers:
        mappings["kg"] = {
            "model": "gemini/gemini-2.5-flash-lite",
            "fallback": "gemini/gemini-2.5-flash",
        }
    else:
        kg_fallback = _auto_pick_with_fallback(
            providers, ["groq", "openai", "github_copilot", "nvidia_nim", "anthropic"], _KNOWN_MODELS
        )
        if kg_fallback:
            mappings["kg"] = {"model": kg_fallback, "fallback": None}

    return mappings


def _count_available_models(providers: list[str]) -> int:
    """Total number of known models across the user's selected providers."""
    return sum(len(_KNOWN_MODELS.get(p, [])) for p in providers)


def _print_mapping_summary(mappings: dict) -> None:
    """Render the final role→model assignment as a Rich table (or plain list)."""
    if not mappings:
        _print("[yellow]No model_mappings generated. Edit synapse.json manually.[/]")
        return

    if _RICH_AVAILABLE and Table is not None and console is not None:
        tbl = Table(title="Model Mappings", show_header=True, header_style="bold cyan")
        tbl.add_column("Role", style="bold")
        tbl.add_column("Model")
        tbl.add_column("Fallback", style="dim")
        for role, cfg in mappings.items():
            tbl.add_row(role, cfg.get("model", "—"), cfg.get("fallback") or "—")
        console.print(tbl)
    else:
        _print("\n[bold cyan]Model Mappings:[/]")
        for role, cfg in mappings.items():
            fb = cfg.get("fallback")
            fb_str = f"  (fallback: {fb})" if fb else ""
            _print(f"  {role:10s}  →  {cfg.get('model', '—')}{fb_str}")


def _build_model_mappings_interactive(
    providers: list[str], prompter: "object", config: dict
) -> dict:
    """Openclaw-style role picker backed by live /models catalogs.

    UX contract:
      1. Hit each provider's /models API with the user's key; fall back to
         _KNOWN_MODELS only when the API is unreachable.
      2. Present a single unified flat list of `provider/model` entries, each
         annotated with a hint (ctx window + capability flags like `reasoning`).
      3. When the catalog has >30 models AND >1 provider, ask the user to
         optionally narrow to one provider before each role pick.
      4. Use a searchable fuzzy picker (InquirerPy.fuzzy or questionary.autocomplete)
         so the user types to filter. Always include an `[Enter model manually]`
         escape hatch for models not in the catalog.
      5. No pre-selected defaults. Single-model collapse: auto-assign when
         only one model is available. `vault` role is forced to Ollama.
    """
    _print("\n[bold cyan]--- Fetching available models from providers ---[/]")
    catalog = _fetch_live_catalog(providers, config)
    flat = _flatten_catalog(catalog)

    if not flat:
        _print(
            "\n[yellow]No models available for your providers. "
            "Edit synapse.json → model_mappings manually.[/]"
        )
        return {}

    # Single-model collapse — nothing to pick
    if len(flat) == 1:
        only = flat[0]
        _print("\n[bold cyan]--- Model Selection ---[/]")
        _print(
            f"[green]Only one model available ({only['value']}) — "
            "using it for all roles.[/]"
        )
        mappings: dict = {
            role: {"model": only["value"], "fallback": None} for role, _, _ in _ROLES
        }
        if "ollama" in providers:
            mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}
        _print_mapping_summary(mappings)
        return mappings

    _print("\n[bold cyan]--- Model Selection ---[/]")
    _print(
        f"Type to search. {len(flat)} models across {len(catalog)} providers. "
        "No defaults — pick every role explicitly.\n"
    )

    # Optional provider-filter step (shown once when the catalog is large).
    active_provider: str = _prompt_provider_filter(flat, prompter)
    filtered = (
        flat if active_provider == "*" else [m for m in flat if m.get("provider") == active_provider]
    )

    mappings = {}
    for role, desc, _prefs in _ROLES:
        selected = _pick_model_fuzzy(role, desc, filtered, prompter)
        if not selected:
            # Manual entry returned blank — keep prompting for this role.
            _print(f"  [yellow]![/] {role}: empty entry, try again.")
            selected = _pick_model_fuzzy(role, desc, filtered, prompter)
        mappings[role] = {"model": selected, "fallback": None}

    # vault: always ollama (local-only by design — architectural invariant)
    if "ollama" in providers:
        mappings["vault"] = {"model": "ollama_chat/llama3.3", "fallback": None}

    _print_mapping_summary(mappings)
    return mappings


# ---------------------------------------------------------------------------
# Embedding prefetch — avoid surprise ~274 MB download on first memory query
# ---------------------------------------------------------------------------


def _prefetch_embedding_models(providers: list[str]) -> None:
    """Warm the embedding stack so the user doesn't wait on first chat.

    Steps:
      1. Instantiate FastEmbed to trigger ONNX model download (~274 MB CPU / ~550 MB GPU).
         This is the active runtime provider (see sci_fi_dashboard/embedding/factory.py).
      2. If Ollama is among the user's selected providers AND reachable, also pull
         `nomic-embed-text` via Ollama. Useful for users who want a fully-local backup
         embedding path or plan to run vLLM + Ollama mixed.

    Both steps are best-effort. Failure here is non-fatal — runtime will auto-download
    on first use if we can't prefetch now.
    """
    _print("\n[bold cyan]--- Embedding Model Prefetch ---[/]")

    # --- Step 1: FastEmbed (primary runtime provider) ---
    try:
        from sci_fi_dashboard.embedding.factory import (  # noqa: PLC0415
            create_provider,
            reset_provider,
        )

        if _RICH_AVAILABLE and console is not None:
            with console.status(
                "[yellow]Downloading FastEmbed model "
                "(nomic-embed-text-v1.5, ~274 MB — one-time)...[/]",
                spinner="dots",
            ):
                reset_provider()
                prov = create_provider({"embedding": {"provider": "fastembed"}})
                # Trigger actual download by requesting an embedding
                prov.embed_documents(["warmup"])
        else:
            _print("  Downloading FastEmbed model (nomic-embed-text-v1.5, ~274 MB)...")
            reset_provider()
            prov = create_provider({"embedding": {"provider": "fastembed"}})
            prov.embed_documents(["warmup"])

        _print("  [green]✓[/] FastEmbed model cached — first chat will be instant.")
    except ImportError:
        _print(
            "  [yellow]![/] fastembed not installed — embeddings will auto-download "
            "on first memory query (~274 MB). Run: pip install fastembed"
        )
    except Exception as exc:  # noqa: BLE001
        _print(
            f"  [yellow]![/] FastEmbed prefetch failed (non-fatal): {exc}\n"
            "  Runtime will download on first use."
        )

    # --- Step 2: Ollama nomic-embed-text (optional, only if user picked Ollama) ---
    if "ollama" not in providers:
        return

    try:
        from cli.provider_steps import validate_ollama  # noqa: PLC0415
    except ImportError:
        return

    # Read ollama api_base from config-in-progress (caller passes it in env-agnostic way);
    # default to localhost which matches validate_ollama's default.
    api_base = "http://localhost:11434"
    health = validate_ollama(api_base)
    if not health.ok:
        _print(
            "  [yellow]![/] Ollama not reachable — skipping nomic-embed-text pull. "
            "Start Ollama and run: ollama pull nomic-embed-text"
        )
        return

    import subprocess  # noqa: PLC0415

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        _print("  [yellow]![/] `ollama` binary not in PATH — skipping Ollama embed pull.")
        return

    try:
        if _RICH_AVAILABLE and console is not None:
            with console.status(
                "[yellow]Pulling nomic-embed-text via Ollama (offline fallback)...[/]",
                spinner="dots",
            ):
                result = subprocess.run(
                    [ollama_bin, "pull", "nomic-embed-text"],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
        else:
            _print("  Pulling nomic-embed-text via Ollama...")
            result = subprocess.run(
                [ollama_bin, "pull", "nomic-embed-text"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )

        if result.returncode == 0:
            _print("  [green]✓[/] Ollama nomic-embed-text ready (offline fallback available).")
        else:
            _print(
                f"  [yellow]![/] Ollama pull returned {result.returncode}: "
                f"{result.stderr.strip()[:200] if result.stderr else 'no detail'}"
            )
    except subprocess.TimeoutExpired:
        _print("  [yellow]![/] Ollama pull timed out after 10 min — try again manually.")
    except Exception as exc:  # noqa: BLE001
        _print(f"  [yellow]![/] Ollama pull failed (non-fatal): {exc}")


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
        _print("You can run migration manually: python workspace/scripts/migrate_legacy.py")


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

        # Google Antigravity — PKCE OAuth + localhost callback. Tokens are
        # written to ~/.synapse/state/google-oauth.json; synapse.json only
        # records the email/project metadata so other code can detect the
        # provider is configured.
        if provider == "google_antigravity":
            metadata = asyncio.run(google_antigravity_oauth_flow(console))
            if metadata:
                config["providers"]["google_antigravity"] = {
                    "oauth_email": metadata.get("email") or "",
                    "project_id": metadata.get("project_id") or "",
                    "tier": metadata.get("tier") or "",
                }
            else:
                _print("[yellow]  Skipping Google Antigravity (auth failed or declined).[/]")
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
                        _print("  [yellow]No models found — pull one with: ollama pull llama3.3[/]")
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

        # Google Vertex AI — GCP project_id + location + service-account JSON path
        # (no single api_key — auth is via GOOGLE_APPLICATION_CREDENTIALS / ADC).
        if provider == "vertex_ai":
            # Try to detect ADC first (implicit detection — matches openclaw behavior).
            existing_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if os.name == "nt" and "APPDATA" in os.environ:
                default_adc = (
                    Path(os.environ["APPDATA"]) / "gcloud" / "application_default_credentials.json"
                )
            else:
                default_adc = (
                    Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
                )
            detected_path: str | None = None
            if existing_creds and Path(existing_creds).is_file():
                detected_path = existing_creds
                _print(f"  [green]Detected GOOGLE_APPLICATION_CREDENTIALS → {existing_creds}[/]")
            elif default_adc.is_file():
                detected_path = str(default_adc)
                _print(f"  [green]Detected gcloud ADC → {default_adc}[/]")

            if detected_path:
                use_detected = prompter.confirm(  # type: ignore[attr-defined]
                    "Use detected credentials?", default=True
                )
                if use_detected:
                    creds_path = detected_path
                else:
                    creds_path = prompter.text(  # type: ignore[attr-defined]
                        "Path to service-account JSON (or gcloud ADC):"
                    )
            else:
                creds_path = prompter.text(  # type: ignore[attr-defined]
                    "Path to service-account JSON (or gcloud ADC):"
                )

            project_id = prompter.text("GCP project_id:")  # type: ignore[attr-defined]
            location = prompter.text(  # type: ignore[attr-defined]
                "GCP location:", default="us-central1"
            )

            if not all([creds_path, project_id, location]):
                continue
            if not Path(creds_path).is_file():
                _print(f"  [red]Credentials file not found: {creds_path}[/]")
                continue

            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
            os.environ["VERTEXAI_PROJECT"] = project_id
            os.environ["VERTEXAI_LOCATION"] = location
            if _RICH_AVAILABLE and console is not None:
                with console.status("[yellow]Validating Vertex AI credentials...[/]"):
                    result = validate_provider("vertex_ai", project_id)
            else:
                result = validate_provider("vertex_ai", project_id)
            if result.ok or result.error == "quota_exceeded":
                quota_note = " (quota exceeded — key accepted)" if result.error else ""
                _print(f"  [green]Vertex AI credentials valid[/]{quota_note}")
                config["providers"]["vertex_ai"] = {
                    "project_id": project_id,
                    "location": location,
                    "credentials_path": creds_path,
                }
            else:
                _print(f"  [red]Vertex AI validation failed: {result.error}[/]")
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
                with console.status(f"[yellow]Validating {provider} key...[/]", spinner="dots"):
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
                _print(f"  [yellow]  {result.error} — retrying in {NETWORK_RETRY_DELAY}s...[/]")
                time.sleep(NETWORK_RETRY_DELAY)
            else:
                _print(f"  [red]x[/] {provider}: {result.error} — {result.detail or 'check key'}")


# ---------------------------------------------------------------------------
# SBS persona-seeding step (inserted between config write and daemon install)
# ---------------------------------------------------------------------------


def _run_sbs_questions(prompter: "object", data_root: Path) -> None:
    """Collect persona-seeding answers and write to SBS profile layers.

    Called at the end of _run_interactive_impl(), after config is written
    but before the daemon install step. Failure here must never crash the wizard.

    Asks 4 targeted questions:
      1. Communication style preference
      2. Energy / mood level
      3. Topic interests (multi-select)
      4. Privacy sensitivity

    Then offers an optional WhatsApp history import.
    """
    import subprocess  # noqa: PLC0415

    from cli.sbs_profile_init import (  # noqa: PLC0415
        ENERGY_DISPLAY_MAP,
        PRIVACY_DISPLAY_MAP,
        STYLE_DISPLAY_MAP,
        initialize_sbs_from_wizard,
    )

    _print("\n[bold cyan]--- Persona Profile ---[/]")

    # --- Q1: Communication style ---
    style_display = prompter.select(  # type: ignore[attr-defined]
        "How should Synapse communicate with you by default?",
        choices=list(STYLE_DISPLAY_MAP.keys()),
        default="Casual and witty",
    )

    # --- Q2: Energy / mood level ---
    energy_display = prompter.select(  # type: ignore[attr-defined]
        "How would you describe your typical energy level?",
        choices=list(ENERGY_DISPLAY_MAP.keys()),
        default="Calm and steady",
    )

    # --- Q3: Interests (multi-select) ---
    interest_displays = prompter.multiselect(  # type: ignore[attr-defined]
        "What topics are you most interested in? (select all that apply)",
        choices=[
            "Technology",
            "Music",
            "Wellness",
            "Finance",
            "Science",
            "Arts",
            "Sports",
            "Cooking",
        ],
    )

    # --- Q4: Privacy sensitivity ---
    privacy_display = prompter.select(  # type: ignore[attr-defined]
        "How sensitive are you about personal data in conversations?",
        choices=list(PRIVACY_DISPLAY_MAP.keys()),
        default="Selective - use judgment",
    )

    # --- Map display values to internal values ---
    answers = {
        "communication_style": STYLE_DISPLAY_MAP.get(style_display, "casual_and_witty"),
        "energy_level": ENERGY_DISPLAY_MAP.get(energy_display, "calm_and_steady"),
        "interests": [topic.lower() for topic in (interest_displays or [])],
        "privacy_level": PRIVACY_DISPLAY_MAP.get(privacy_display, "selective"),
    }

    # --- Write profile layers ---
    try:
        initialize_sbs_from_wizard(answers, data_root)
        _print("[green]Persona profile seeded.[/]")
    except Exception:  # noqa: BLE001
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).warning(
            "SBS profile init failed — wizard continues", exc_info=True
        )
        _print("[yellow]Persona profile setup skipped (non-fatal).[/]")

    # --- Optional: WhatsApp history import ---
    if prompter.confirm(  # type: ignore[attr-defined]
        "Would you like to import existing WhatsApp chat history?", default=False
    ):
        wa_file = prompter.text(  # type: ignore[attr-defined]
            "Path to WhatsApp export (.txt file)", default=""
        )
        if wa_file:
            from pathlib import Path as _Path  # noqa: PLC0415

            wa_path = _Path(wa_file)
            if wa_path.exists():
                subprocess.run(
                    [sys.executable, "scripts/import_whatsapp.py", wa_file, "--hemisphere", "safe"],
                    check=False,
                )
                _print("[green]WhatsApp history import started.[/]")
            else:
                _print(f"[yellow]File not found: {wa_file} — import skipped.[/]")
        else:
            _print("[dim]No file provided — WhatsApp import skipped.[/]")


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
    _MAX_WA_RETRIES = 3  # noqa: N806
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
    # Interactive picker always runs — user picks every role from each provider's live
    # /models API. No pre-selected defaults regardless of flow. Headless path
    # (_run_non_interactive) still auto-picks from env vars for CI/Docker.
    config["model_mappings"] = _build_model_mappings_interactive(
        list(config["providers"].keys()), prompter, config
    )

    # --- Step 9b: Prefetch embedding model (avoids surprise delay on first chat) ---
    _prefetch_embedding_models(list(config["providers"].keys()))

    # --- Step 10: Write config (ONB-07) ---
    write_config(data_root, config)
    cfg_file = data_root / "synapse.json"

    # --- Step 10b: Persona profile seeding ---
    # SBS questions run after synapse.json is written so SynapseConfig.load()
    # inside initialize_sbs_from_wizard() resolves the correct profile path.
    _run_sbs_questions(prompter=prompter, data_root=data_root)

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
            issues.append(
                "  Fix: pip install python-magic-bin  (Windows requires the -bin variant)"
            )
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
