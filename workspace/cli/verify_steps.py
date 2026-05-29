"""
verify_steps.py — Implementation of the ``synapse setup --verify`` subcommand.

Validates all configured providers and channels in parallel (providers) or
sequentially (channels) and reports pass/fail for each.  This is a READ-ONLY
operation — it never modifies synapse.json or any other file.

Entry point: ``run_verify(non_interactive=False) -> int``
  Returns 0 when every check passes, 1 when at least one check fails.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from synapse_config import SynapseConfig
except ImportError:  # pragma: no cover - import path is established by the CLI entrypoint
    SynapseConfig = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Conditional Rich import — matches the pattern in cli/onboard.py
# ---------------------------------------------------------------------------

try:
    from rich.console import Console
    from rich.table import Table

    _RICH_AVAILABLE = True
    console = Console()
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False
    console = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment,misc]


def _print(msg: str) -> None:
    """Print with Rich markup if available, else strip markup and plain-print."""
    if _RICH_AVAILABLE and console is not None:
        try:
            console.print(msg)
            return
        except UnicodeEncodeError:
            # Windows cp1252 terminals can fail on glyphs like "✗".
            pass

    import re  # noqa: PLC0415

    plain = re.sub(r"\[/?[^\]]*\]", "", msg)
    safe = plain.encode("ascii", errors="replace").decode("ascii")
    print(safe)


# ---------------------------------------------------------------------------
# Provider async helpers
# ---------------------------------------------------------------------------


async def _validate_provider_async(name: str, api_key: str) -> tuple[str, bool, str]:
    """Wrap sync ``validate_provider()`` so it can run inside ``asyncio.gather``.

    CRITICAL: ``validate_provider()`` returns a ``ValidationResult`` dataclass.
    We MUST access ``.ok`` for the boolean result and ``.detail`` for the error
    message.  Python truthiness on a non-None dataclass is always ``True``, so
    treating the return value as a plain bool would silently pass every provider
    regardless of the actual outcome.

    Returns:
        (name, success, error_message)
    """
    from cli.provider_steps import validate_provider  # noqa: PLC0415

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, validate_provider, name, api_key)
        # result is ValidationResult — extract .ok and .detail explicitly
        success: bool = result.ok
        error_msg: str = result.detail or result.error or ""
        return (name, success, error_msg)
    except Exception as exc:  # noqa: BLE001
        return (name, False, str(exc))


async def _validate_ollama_async(api_base: str) -> tuple[str, bool, str]:
    """Wrap sync ``validate_ollama()`` so it can run inside ``asyncio.gather``.

    ``validate_ollama()`` also returns a ``ValidationResult`` — we access ``.ok``
    and ``.detail`` explicitly (same pattern as ``_validate_provider_async``).

    Returns:
        ("ollama", success, error_message_or_empty)
    """
    from cli.provider_steps import validate_ollama  # noqa: PLC0415

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, validate_ollama, api_base)
        success: bool = result.ok
        error_msg: str = result.detail or result.error or ""
        return ("ollama", success, error_msg)
    except Exception as exc:  # noqa: BLE001
        return ("ollama", False, str(exc))


async def _validate_all_providers(
    providers: dict,
) -> list[tuple[str, bool, str]]:
    """Run all provider validations in parallel via ``asyncio.gather``.

    Subscription-backed providers are handled specially:
      - ``github_copilot``: skip API-key validation (token managed externally).
      - ``openai_codex``: validate local OAuth credential presence.

    Args:
        providers: Dict of ``{provider_name: {api_key: ..., ...}}`` from
                   ``SynapseConfig.providers``.

    Returns:
        List of ``(name, success, error_message)`` tuples - one per provider.
    """
    coros = []
    names: list[str] = []
    results: list[tuple[str, bool, str]] = []
    subscription_msg = "Subscription provider (OAuth device flow) - API-key validation skipped"

    def _validate_openai_codex_state() -> tuple[str, bool, str]:
        """Check whether OpenAI Codex OAuth credentials are present locally."""
        try:
            from sci_fi_dashboard import openai_codex_oauth  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            return ("openai_codex", False, f"OpenAI Codex OAuth module unavailable: {exc}")

        try:
            creds = openai_codex_oauth.load_credentials()
        except Exception as exc:  # noqa: BLE001
            return ("openai_codex", False, f"OpenAI Codex OAuth state unreadable: {exc}")

        if creds and getattr(creds, "access_token", "") and getattr(creds, "refresh_token", ""):
            return ("openai_codex", True, "OpenAI Codex OAuth credentials present")
        return (
            "openai_codex",
            False,
            "OpenAI Codex OAuth credentials missing - rerun `synapse setup` and complete device flow.",
        )

    for provider_name, cfg in providers.items():
        if provider_name == "github_copilot":
            results.append((provider_name, True, subscription_msg))
            continue
        if provider_name == "openai_codex":
            results.append(_validate_openai_codex_state())
            continue
        if provider_name == "ollama":
            api_base = cfg.get("api_base", "http://localhost:11434")
            coros.append(_validate_ollama_async(api_base))
            names.append("ollama")
        else:
            api_key = cfg.get("api_key", "")
            coros.append(_validate_provider_async(provider_name, api_key))
            names.append(provider_name)

    if not coros:
        return results

    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    for i, raw in enumerate(raw_results):
        if isinstance(raw, Exception):
            results.append((names[i], False, str(raw)))
        else:
            results.append(raw)  # type: ignore[arg-type]

    return results


# ---------------------------------------------------------------------------
# Channel validation helpers (synchronous — channel checks are fast)
# ---------------------------------------------------------------------------


def _validate_channels(channels: dict) -> list[tuple[str, bool, str]]:
    """Validate all configured channels sequentially.

    Returns a list of ``(name, success, message)`` tuples — one per channel.

    Network errors / bad tokens are caught per-channel so a single failure does
    not abort the remaining checks.
    """
    results: list[tuple[str, bool, str]] = []

    for channel_name, cfg in channels.items():
        if channel_name == "telegram":
            try:
                from cli.channel_steps import validate_telegram_token  # noqa: PLC0415

                info = validate_telegram_token(cfg.get("token", ""))
                username = info.get("username", "") if isinstance(info, dict) else ""
                results.append(("telegram", True, f"@{username}" if username else "Connected"))
            except ValueError as exc:
                results.append(("telegram", False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                results.append(("telegram", False, str(exc)))

        elif channel_name == "discord":
            try:
                from cli.channel_steps import validate_discord_token  # noqa: PLC0415

                info = validate_discord_token(cfg.get("token", ""))
                username = info.get("username", "") if isinstance(info, dict) else ""
                results.append(("discord", True, f"@{username}" if username else "Connected"))
            except ValueError as exc:
                results.append(("discord", False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                results.append(("discord", False, str(exc)))

        elif channel_name == "slack":
            try:
                from cli.channel_steps import validate_slack_tokens  # noqa: PLC0415

                info = validate_slack_tokens(cfg.get("bot_token", ""), cfg.get("app_token", ""))
                team = info.get("team", "") if isinstance(info, dict) else ""
                results.append(("slack", True, f"Team: {team}" if team else "Connected"))
            except ValueError as exc:
                results.append(("slack", False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                results.append(("slack", False, str(exc)))

        elif channel_name == "whatsapp":
            # WhatsApp QR pairing cannot be validated offline — always report as skipped
            results.append(
                (
                    "whatsapp",
                    True,
                    "Bridge validation requires a running server — skipped",
                )
            )

        else:
            # Unknown channel — skip gracefully
            results.append((channel_name, True, "Unknown channel type — skipped"))

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_results_rich(
    provider_results: list[tuple[str, bool, str]],
    channel_results: list[tuple[str, bool, str]],
) -> None:
    """Print a Rich table with Component / Status / Notes columns."""
    assert _RICH_AVAILABLE and Table is not None and console is not None  # noqa: S101

    tbl = Table(title="Synapse Configuration Verification", show_header=True)
    tbl.add_column("Component", style="bold")
    tbl.add_column("Status", justify="center")
    tbl.add_column("Notes")

    if provider_results:
        for name, ok, msg in provider_results:
            status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
            note = msg if not ok else (msg if msg else "")
            tbl.add_row(f"provider: {name}", status, note)

    if channel_results:
        for name, ok, msg in channel_results:
            status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
            note = msg if msg else ""
            tbl.add_row(f"channel: {name}", status, note)

    console.print(tbl)


def _print_results_plain(
    provider_results: list[tuple[str, bool, str]],
    channel_results: list[tuple[str, bool, str]],
) -> None:
    """Print plain-text results (Rich not available)."""
    print("\nSynapse Configuration Verification")
    print("-" * 50)
    print(f"{'Component':<30} {'Status':<8} Notes")
    print("-" * 50)

    all_results = [(f"provider: {n}", ok, msg) for n, ok, msg in provider_results] + [
        (f"channel: {n}", ok, msg) for n, ok, msg in channel_results
    ]

    for name, ok, msg in all_results:
        status = "PASS" if ok else "FAIL"
        print(f"{name:<30} {status:<8} {msg}")

    print("-" * 50)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_verify(non_interactive: bool = False) -> int:
    """Validate all configured providers and channels.

    This function is READ-ONLY — it never modifies synapse.json or any other
    file.

    Args:
        non_interactive: Unused; reserved for future CI integration where
                         interactive spinners must be suppressed.

    Returns:
        0 — all checks passed (or skipped, e.g. WhatsApp).
        1 — at least one check failed, or synapse.json is missing.
    """
    # ------------------------------------------------------------------
    # Guard: synapse.json must exist
    # ------------------------------------------------------------------
    if SynapseConfig is None:
        _print("[red]Error loading config: synapse_config is unavailable.[/red]")
        _print("[yellow]Run 'synapse setup' first to create synapse.json.[/yellow]")
        return 1

    try:
        config = SynapseConfig.load()
    except Exception as exc:  # noqa: BLE001
        _print(f"[red]Error loading config: {exc}[/red]")
        _print("[yellow]Run 'synapse setup' first to create synapse.json.[/yellow]")
        return 1

    config_file = config.data_root / "synapse.json"
    if not config_file.exists():
        _print("[red]No synapse.json found at " f"{config_file}.[/red]")
        _print("[yellow]Run 'synapse setup' first.[/yellow]")
        return 1

    providers: dict = config.providers
    channels: dict = config.channels

    if not providers and not channels:
        _print("[yellow]No providers or channels configured in synapse.json.[/yellow]")
        _print("Run 'synapse setup' to configure your installation.")
        return 1

    # ------------------------------------------------------------------
    # Run validations
    # ------------------------------------------------------------------
    _print("\n[bold]Verifying Synapse configuration...[/bold]\n")

    # Providers — parallel
    if providers:
        _print(f"Checking {len(providers)} provider(s)...")
        provider_results: list[tuple[str, bool, str]] = asyncio.run(
            _validate_all_providers(providers)
        )
    else:
        provider_results = []

    # Channels — sequential
    if channels:
        _print(f"Checking {len(channels)} channel(s)...")
        channel_results: list[tuple[str, bool, str]] = _validate_channels(channels)
    else:
        channel_results = []

    # ------------------------------------------------------------------
    # Print results table
    # ------------------------------------------------------------------
    if _RICH_AVAILABLE and console is not None:
        _print_results_rich(provider_results, channel_results)
    else:
        _print_results_plain(provider_results, channel_results)

    # ------------------------------------------------------------------
    # Summary line and exit code
    # ------------------------------------------------------------------
    all_results = provider_results + channel_results
    failed = [(n, msg) for n, ok, msg in all_results if not ok]

    if failed:
        _print(f"\n[red]Verification failed: {len(failed)} component(s) not passing.[/red]")
        for name, msg in failed:
            _print(f"  [red]✗[/red] {name}: {msg}")
        return 1

    _print(f"\n[green]All {len(all_results)} component(s) verified successfully.[/green]")
    return 0
