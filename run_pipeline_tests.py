#!/usr/bin/env python3
"""
run_pipeline_tests.py - Run the Synapse-OSS pipeline test suite with a live progress bar.

Usage (from repo root):
    python run_pipeline_tests.py                  # all 69 tests
    python run_pipeline_tests.py --phase 2        # only phase 2 (gateway)
    python run_pipeline_tests.py --slow           # include slow tests
    python run_pipeline_tests.py --phase 1 2 3    # multiple phases
    python run_pipeline_tests.py --failfast       # stop on first failure
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskID,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.text import Text
    _RICH = True
except ImportError:
    _RICH = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent
WORKSPACE = REPO_ROOT / "workspace"
PIPELINE_DIR = WORKSPACE / "tests" / "pipeline"

PHASES = {
    1: "Data Ingestion       (LanceDB + SQLiteGraph)",
    2: "Gateway Layer        (FloodGate / Dedup / Queue)",
    3: "Memory Retrieval     (MemoryEngine query + scoring)",
    4: "Dual Cognition       (classify + think() fast/std/deep)",
    5: "SBS Profile Manager  (layers / snapshots / rollback)",
    6: "End-to-End           (persona_chat() full pipeline)",
}


def _phase_file(n: int) -> Path:
    return PIPELINE_DIR / f"test_phase{n}_{'_'.join(PHASES[n].split()[0].lower().replace('(','').replace(')','').split())}.py"


def _find_phase_file(n: int) -> Path | None:
    """Return the test file for phase n, or None if not found."""
    for f in PIPELINE_DIR.glob(f"test_phase{n}_*.py"):
        return f
    return None


# ---------------------------------------------------------------------------
# Rich-based runner
# ---------------------------------------------------------------------------

def _parse_pytest_line(line: str) -> tuple[str, str] | None:
    """
    Parse a verbose pytest output line into (status, test_name).
    Returns None for non-test lines.

    Only matches lines that contain '::' (i.e. actual test node IDs like
    'tests/pipeline/test_phase1_data_ingestion.py::test_foo PASSED') so that
    pytest section separators like '=== short test summary info ===' or
    '=== 2 ERRORS ===' are never treated as test results.
    """
    line = line.strip()
    # Must contain '::' to be a real test node ID line
    if "::" not in line:
        return None
    for suffix in (" PASSED", " FAILED", " ERROR", " SKIPPED", " XFAIL", " XPASS"):
        if suffix in line:
            name = line.split("::")[-1].split(suffix)[0].strip()
            status = suffix.strip()
            return status, name
    return None


def run_with_rich(pytest_args: list[str], title: str) -> int:
    console = Console()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )

    results: list[tuple[str, str]] = []  # [(status, name)]
    started = time.time()

    task: TaskID = progress.add_task("Running tests...", total=None)

    console.rule(f"[bold cyan]{title}")

    with Live(progress, console=console, refresh_per_second=10):
        proc = subprocess.Popen(
            pytest_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(WORKSPACE),
        )

        collected_total: int | None = None

        for raw_line in proc.stdout:
            line = raw_line.rstrip()

            # Detect "N tests collected"
            if "tests collected" in line or "test collected" in line:
                try:
                    n = int(line.strip().split()[0])
                    collected_total = n
                    progress.update(task, total=n, description=f"Running {n} tests")
                except (ValueError, IndexError):
                    pass

            parsed = _parse_pytest_line(line)
            if parsed:
                status, name = parsed
                results.append((status, name))
                completed = len(results)
                total = collected_total or completed

                icon = {
                    "PASSED":  "[green]PASS[/green]",
                    "FAILED":  "[red]FAIL[/red]",
                    "ERROR":   "[red]ERR [/red]",
                    "SKIPPED": "[yellow]SKIP[/yellow]",
                    "XFAIL":   "[dim]xfail[/dim]",
                    "XPASS":   "[magenta]xpass[/magenta]",
                }.get(status, "?")

                short_name = name[:60] + "..." if len(name) > 60 else name
                progress.update(
                    task,
                    completed=completed,
                    total=total,
                    description=f"{icon} {short_name}",
                )

        proc.wait()

    # ---------------------------------------------------------------------------
    # Summary table
    # ---------------------------------------------------------------------------
    elapsed = time.time() - started
    passed  = sum(1 for s, _ in results if s == "PASSED")
    failed  = sum(1 for s, _ in results if s == "FAILED")
    errors  = sum(1 for s, _ in results if s == "ERROR")
    skipped = sum(1 for s, _ in results if s == "SKIPPED")
    total   = len(results)

    table = Table(title="Test Results", show_header=True, header_style="bold")
    table.add_column("Status", style="bold", width=8)
    table.add_column("Test", no_wrap=False)

    for status, name in results:
        color = {"PASSED":"green","FAILED":"red","ERROR":"red","SKIPPED":"yellow"}.get(status,"white")
        table.add_row(f"[{color}]{status}[/{color}]", name)

    console.print(table)

    # Headline
    if failed == 0 and errors == 0:
        headline = Text(f"PASS  {passed}/{total} passed in {elapsed:.1f}s", style="bold green")
    else:
        headline = Text(
            f"FAIL  {failed + errors} failures | {passed}/{total} passed in {elapsed:.1f}s",
            style="bold red",
        )
    console.print(Panel(headline, expand=False))

    if failed:
        console.print("\n[red]Failed tests:[/red]")
        for s, n in results:
            if s == "FAILED":
                console.print(f"  [red]-[/red] {n}")

    return proc.returncode


def run_plain(pytest_args: list[str], title: str) -> int:
    """Fallback when rich is not installed - just stream raw pytest output."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")
    result = subprocess.run(pytest_args, cwd=str(WORKSPACE))
    return result.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Synapse pipeline tests with live progress bar"
    )
    parser.add_argument(
        "--phase", "-p", type=int, nargs="+", metavar="N",
        help="Run only specific phase(s): 1-6 (default: all)"
    )
    parser.add_argument(
        "--slow", "-s", action="store_true",
        help="Include tests marked @pytest.mark.slow (disabled by default)"
    )
    parser.add_argument(
        "--failfast", "-x", action="store_true",
        help="Stop after first failure"
    )
    parser.add_argument(
        "--tb", default="short",
        choices=["short", "long", "no", "line", "auto"],
        help="Traceback style (default: short)"
    )
    parser.add_argument(
        "--lf", action="store_true",
        help="Re-run only last-failed tests"
    )
    args = parser.parse_args()

    # Build test paths
    if args.phase:
        paths: list[str] = []
        for n in args.phase:
            if n not in PHASES:
                print(f"[ERROR] Phase {n} is not valid. Choose 1-6.", file=sys.stderr)
                return 1
            f = _find_phase_file(n)
            if f is None:
                print(f"[ERROR] Could not find test file for phase {n}.", file=sys.stderr)
                return 1
            paths.append(str(f.relative_to(WORKSPACE)))
        title = f"Pipeline Tests - Phase{'s' if len(args.phase)>1 else ''} {', '.join(str(p) for p in args.phase)}"
    else:
        paths = [str(PIPELINE_DIR.relative_to(WORKSPACE))]
        title = "Pipeline Tests - All Phases (1-6)"

    # Build pytest command
    cmd = [
        sys.executable, "-m", "pytest",
        *paths,
        "-v",
        f"--tb={args.tb}",
    ]
    if not args.slow:
        cmd += ["-m", "not slow"]
    if args.failfast:
        cmd.append("-x")
    if args.lf:
        cmd.append("--lf")

    print(f"\nCommand: {' '.join(cmd)}\n")

    if _RICH:
        return run_with_rich(cmd, title)
    else:
        print("[WARN] 'rich' not installed - falling back to plain output")
        print("       Install with:  pip install rich")
        return run_plain(cmd, title)


if __name__ == "__main__":
    sys.exit(main())
