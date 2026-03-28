"""
doctor.py — Synapse-OSS system health check command.

Runs 13 targeted checks covering config, directories, providers, gateway,
legacy state, and the ML stack.  Exits 0 when all checks pass, exits with the
count of failures when any check fails.

Checks (in order):
  1.  synapse.json exists and is valid JSON
  2.  data_root directory exists
  3.  workspace directory exists (data_root/workspace)
  4.  Required bootstrap files present (SOUL.md, AGENTS.md, USER.md, IDENTITY.md)
  5.  Gateway token is set (non-empty)
  6.  At least one LLM provider key is configured
  7.  Ollama reachable (GET http://localhost:11434/ with 2s timeout)
  8.  API gateway reachable (GET http://localhost:8000/health with 2s timeout)
  9.  workspace-state.json exists and has bootstrapSeededAt set
 10.  No legacy state dirs present (.synapse_old, .clawdbot, .moldbot)
 11.  sqlite-vec importable (required for vector memory)
 12.  sentence-transformers importable (required for ingest/embedding)
 13.  torch importable (required by sentence-transformers)

Exports:
  doctor_command()    Entry point for the synapse doctor CLI subcommand
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
        import re  # noqa: PLC0415

        plain = re.sub(r"\[/?[^\]]*\]", "", msg)
        print(plain)


# ---------------------------------------------------------------------------
# Check result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single doctor check.

    Attributes:
        passed:  True if the check passed.
        label:   Short human-readable label for this check.
        detail:  Extra detail message (shown after pass/fail icon).
    """

    passed: bool
    label: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_config_valid(data_root: Path) -> CheckResult:
    """Check 1: synapse.json exists and is valid JSON."""
    label = "synapse.json exists and is valid JSON"
    config_path = data_root / "synapse.json"

    if not config_path.exists():
        return CheckResult(False, label, f"Not found: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as fh:
            json.load(fh)
    except json.JSONDecodeError as exc:
        return CheckResult(False, label, f"JSON parse error: {exc}")

    return CheckResult(True, label)


def _check_data_root_exists(data_root: Path) -> CheckResult:
    """Check 2: data_root directory exists."""
    label = "data_root directory exists"
    if data_root.exists() and data_root.is_dir():
        return CheckResult(True, label)
    return CheckResult(False, label, f"Directory missing: {data_root}")


def _check_workspace_dir(data_root: Path) -> CheckResult:
    """Check 3: workspace directory exists (data_root/workspace)."""
    label = "workspace directory exists"
    workspace = data_root / "workspace"
    if workspace.exists() and workspace.is_dir():
        return CheckResult(True, label)
    return CheckResult(False, label, f"Directory missing: {workspace}")


_BOOTSTRAP_FILES: list[str] = ["SOUL.md", "AGENTS.md", "USER.md", "IDENTITY.md"]


def _check_bootstrap_files(data_root: Path) -> CheckResult:
    """Check 4: Required bootstrap files present in workspace."""
    label = "Required bootstrap files present"
    workspace = data_root / "workspace"
    missing = [f for f in _BOOTSTRAP_FILES if not (workspace / f).exists()]
    if not missing:
        return CheckResult(True, label)
    return CheckResult(False, label, f"Missing: {', '.join(missing)}")


def _check_gateway_token(data_root: Path) -> CheckResult:
    """Check 5: gateway.token is set (non-empty) in synapse.json."""
    label = "Gateway token configured"
    config_path = data_root / "synapse.json"

    if not config_path.exists():
        return CheckResult(False, label, "synapse.json not found")

    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return CheckResult(False, label, "Cannot read synapse.json")

    token = raw.get("gateway", {}).get("token", "")
    if token:
        return CheckResult(True, label)
    return CheckResult(False, label, "gateway.token is missing or empty")


def _check_provider_configured(data_root: Path) -> CheckResult:
    """Check 6: At least one LLM provider key is configured."""
    label = "At least one LLM provider configured"
    config_path = data_root / "synapse.json"

    if not config_path.exists():
        return CheckResult(False, label, "synapse.json not found")

    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return CheckResult(False, label, "Cannot read synapse.json")

    providers = raw.get("providers", {})
    if providers:
        return CheckResult(True, label, f"Providers: {', '.join(providers.keys())}")
    return CheckResult(False, label, "No providers configured in synapse.json")


def _check_ollama_reachable() -> CheckResult:
    """Check 7: Ollama reachable at http://localhost:11434/ (2s timeout)."""
    label = "Ollama reachable"
    try:
        import httpx  # noqa: PLC0415

        r = httpx.get("http://localhost:11434/", timeout=2.0)
        if r.status_code < 500:
            return CheckResult(True, label, f"HTTP {r.status_code}")
        return CheckResult(False, label, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, label, f"Connection failed: {exc}")


def _check_gateway_reachable(non_interactive: bool = False) -> CheckResult:
    """Check 8: API gateway reachable at http://localhost:8000/health (2s timeout)."""
    label = "API gateway reachable"
    timeout = 3.0 if non_interactive else 10.0
    try:
        import httpx  # noqa: PLC0415

        r = httpx.get("http://localhost:8000/health", timeout=timeout)
        if r.status_code == 200:
            return CheckResult(True, label, "HTTP 200")
        return CheckResult(False, label, f"HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, label, f"Connection failed: {exc}")


def _check_workspace_state(data_root: Path) -> CheckResult:
    """Check 9: workspace-state.json exists and has bootstrapSeededAt set."""
    label = "workspace-state.json seeded"
    workspace = data_root / "workspace"
    state_path = workspace / ".synapse" / "workspace-state.json"

    if not state_path.exists():
        return CheckResult(False, label, f"Not found: {state_path}")

    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return CheckResult(False, label, "Cannot parse workspace-state.json")

    if state.get("bootstrapSeededAt"):
        return CheckResult(True, label, f"Seeded at {state['bootstrapSeededAt']}")
    return CheckResult(False, label, "bootstrapSeededAt not set in workspace-state.json")


_LEGACY_STATE_DIRS: list[str] = [".synapse_old", ".clawdbot", ".moldbot"]


def _check_no_legacy_dirs() -> CheckResult:
    """Check 10: No legacy state dirs present (.synapse_old, .clawdbot, .moldbot)."""
    label = "No legacy state directories"
    home = Path.home()
    found = [d for d in _LEGACY_STATE_DIRS if (home / d).exists()]
    if not found:
        return CheckResult(True, label)
    return CheckResult(False, label, f"Found: {', '.join(str(home / d) for d in found)}")


def _check_sqlite_vec() -> CheckResult:
    """Check 11: sqlite-vec importable (required for vector memory)."""
    label = "sqlite-vec importable"
    try:
        import sqlite_vec  # noqa: F401, PLC0415

        return CheckResult(True, label)
    except ImportError:
        return CheckResult(False, label, "Run: pip install sqlite-vec")


def _check_sentence_transformers() -> CheckResult:
    """Check 12: sentence-transformers importable (required for ingest/embedding)."""
    label = "sentence-transformers importable"
    try:
        import sentence_transformers  # noqa: F401, PLC0415

        return CheckResult(True, label)
    except ImportError:
        return CheckResult(False, label, "Run: pip install sentence-transformers")


def _check_torch() -> CheckResult:
    """Check 13: torch importable (required by sentence-transformers)."""
    label = "torch importable"
    try:
        import torch  # noqa: F401, PLC0415

        return CheckResult(True, label)
    except ImportError:
        return CheckResult(False, label, "Run: pip install torch")


# ---------------------------------------------------------------------------
# Check runner and printer
# ---------------------------------------------------------------------------


def _run_check(check_fn: Callable[[], CheckResult]) -> CheckResult:
    """Run a check function, catching unexpected exceptions."""
    try:
        return check_fn()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "Unexpected error", str(exc))


def _print_result(result: CheckResult) -> None:
    """Print a single check result with colour-coded pass/fail icon."""
    if result.passed:
        icon = "[green]✓[/]"
        color = "green"
    else:
        icon = "[red]✗[/]"
        color = "red"

    detail_str = f" — {result.detail}" if result.detail else ""
    _print(f"{icon} [{color}]{result.label}[/]{detail_str}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def doctor_command(fix: bool = False, non_interactive: bool = False) -> int:
    """Run all 13 system health checks and print results.

    Args:
        fix:             If True, attempt to auto-fix certain issues (e.g., generate
                         a gateway token).  Currently informational — fix logic is a
                         no-op stub reserved for future implementation.
        non_interactive: If True, use shorter timeouts for gateway probe.

    Returns:
        The number of failed checks (0 = healthy, use as exit code).
    """
    data_root = Path(os.environ.get("SYNAPSE_HOME", Path.home() / ".synapse"))

    _print("\n[bold]Synapse-OSS Doctor[/]\n")
    _print(f"Data root: {data_root}\n")

    # Build check list — each is a zero-arg callable returning CheckResult.
    # Checks 1-7 work entirely offline; checks 8-9 require live services.
    # Checks 11-13 verify the ML stack needed for memory/ingest features.
    checks: list[Callable[[], CheckResult]] = [
        lambda: _check_config_valid(data_root),
        lambda: _check_data_root_exists(data_root),
        lambda: _check_workspace_dir(data_root),
        lambda: _check_bootstrap_files(data_root),
        lambda: _check_gateway_token(data_root),
        lambda: _check_provider_configured(data_root),
        lambda: _check_ollama_reachable(),
        lambda: _check_gateway_reachable(non_interactive=non_interactive),
        lambda: _check_workspace_state(data_root),
        lambda: _check_no_legacy_dirs(),
        _check_sqlite_vec,
        _check_sentence_transformers,
        _check_torch,
    ]

    # Run all checks and collect results
    results: list[CheckResult] = []
    for check_fn in checks:
        result = _run_check(check_fn)
        results.append(result)
        _print_result(result)

    failures = sum(1 for r in results if not r.passed)

    _print("")
    if failures == 0:
        _print("[bold green]All checks passed — system healthy.[/]")
    else:
        _print(f"[bold red]{failures} check(s) failed.[/]")
        if fix:
            _print("[yellow]--fix mode: auto-fix is not yet implemented for these checks.[/]")

    return failures
