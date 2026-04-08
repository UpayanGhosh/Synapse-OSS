"""
run_tests.py — Run the full LanceDB reliability suite with a live progress bar
and a per-test status report at the end.

Usage (from workspace/):
    python tests/lancedb_reliability/run_tests.py
    python tests/lancedb_reliability/run_tests.py --slow
    python tests/lancedb_reliability/run_tests.py phase1
    python tests/lancedb_reliability/run_tests.py phase2 phase3
    python tests/lancedb_reliability/run_tests.py --slow phase1 phase4
"""

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PHASES = {
    "phase1": "tests/lancedb_reliability/test_phase1_ingestion.py",
    "phase2": "tests/lancedb_reliability/test_phase2_retrieval.py",
    "phase3": "tests/lancedb_reliability/test_phase3_concurrency.py",
    "phase4": "tests/lancedb_reliability/test_phase4_edge_cases.py",
    "phase5": "tests/lancedb_reliability/test_phase5_semantic_accuracy.py",
}

BAR_WIDTH = 35

# ANSI colours
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
GREY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

STATUS_ICON = {
    "PASSED":  f"{GREEN}✓ PASSED {RESET}",
    "FAILED":  f"{RED}✗ FAILED {RESET}",
    "ERROR":   f"{RED}✗ ERROR  {RESET}",
    "SKIPPED": f"{YELLOW}⊘ SKIPPED{RESET}",
    "XFAIL":   f"{YELLOW}⊘ XFAIL  {RESET}",
    "XPASS":   f"{GREEN}✓ XPASS  {RESET}",
    "WARNING": f"{YELLOW}⚠ WARNING{RESET}",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    node_id: str
    short_name: str
    status: str          # PASSED / FAILED / ERROR / SKIPPED / XFAIL / WARNING
    warning_msgs: list[str] = field(default_factory=list)
    failure_detail: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def _bar(done: int, total: int) -> str:
    if total == 0:
        return "░" * BAR_WIDTH
    filled = int(BAR_WIDTH * done / total)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _render_bar(done: int, total: int, passed: int, failed: int,
                skipped: int, warnings: int, label: str) -> str:
    pct = int(100 * done / total) if total else 0
    bar = _bar(done, total)
    label = label[-42:] if len(label) > 42 else label
    warn_part = f"  {YELLOW}⚠{warnings}{RESET}" if warnings else ""
    return (
        f"\r  [{bar}] {pct:3d}%  {done:>4}/{total}"
        f"  {GREEN}✓{passed}{RESET}"
        f"  {RED}✗{failed}{RESET}"
        f"  {YELLOW}⊘{skipped}{RESET}"
        f"{warn_part}"
        f"  {GREY}{label:<42}{RESET}"
    )


def _clear_line() -> None:
    sys.stdout.write("\r" + " " * 130 + "\r")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Step 1: collect test count
# ---------------------------------------------------------------------------

def collect_count(base_cmd: list, workspace: Path) -> int:
    collect_cmd = base_cmd + ["--collect-only", "-q", "--no-header"]
    try:
        result = subprocess.run(
            collect_cmd, cwd=workspace,
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        m = re.search(r"(\d+) tests? collected", output)
        if m:
            return int(m.group(1))
        return sum(1 for line in output.splitlines()
                   if "::" in line and not line.startswith("ERROR"))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Step 2: stream run, track per-test results
# ---------------------------------------------------------------------------

_RESULT_RE = re.compile(
    r"^(tests[\\/].+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s*",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(r"^\s*\w+Warning", re.IGNORECASE)


def run_with_progress(
    cmd: list, workspace: Path, total: int
) -> tuple[int, list[TestResult]]:
    results: list[TestResult] = []
    current: TestResult | None = None
    in_failure_block = False
    failure_lines: list[str] = []

    passed = failed = skipped = warn_count = done = 0

    proc = subprocess.Popen(
        cmd, cwd=workspace,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    sys.stdout.write("\n")

    try:
        for raw_line in proc.stdout:  # type: ignore[union-attr]
            line = raw_line.rstrip()

            # --- capture failure detail block (indented or FAILED header) ---
            if re.match(r"^_+ (FAILURES|ERRORS) _+", line):
                in_failure_block = True
            if in_failure_block:
                failure_lines.append(line)
                if re.match(r"^=+ short test summary", line):
                    in_failure_block = False

            # --- detect warnings attached to current test ---
            if current and _WARNING_RE.match(line):
                current.warning_msgs.append(line.strip())
                warn_count += 1

            # --- parse per-test result line ---
            m = _RESULT_RE.match(line)
            if m:
                node_id, status = m.group(1), m.group(2).upper()
                short = node_id.split("::")[-1]
                done += 1

                current = TestResult(node_id=node_id, short_name=short, status=status)
                results.append(current)

                if status == "PASSED":
                    passed += 1
                elif status in ("FAILED", "ERROR"):
                    failed += 1
                elif status in ("SKIPPED", "XFAIL"):
                    skipped += 1
                elif status == "XPASS":
                    passed += 1

                sys.stdout.write(
                    _render_bar(done, total or done, passed, failed,
                                skipped, warn_count, short)
                )
                sys.stdout.flush()

    finally:
        proc.wait()

    # attach failure detail to matching TestResult objects
    _attach_failure_detail(results, failure_lines)

    _clear_line()
    sys.stdout.write(
        _render_bar(done, total or done, passed, failed, skipped, warn_count, "done")
    )
    sys.stdout.write("\n\n")
    sys.stdout.flush()

    return proc.returncode, results


def _attach_failure_detail(results: list[TestResult], failure_lines: list[str]) -> None:
    """Match failure block lines back to their TestResult by test name."""
    current_result: TestResult | None = None
    for line in failure_lines:
        # section header: _______ test_name _______
        header = re.match(r"^_+ (.+?) _+$", line)
        if header:
            name = header.group(1).strip()
            for r in results:
                if r.short_name in name or name in r.node_id:
                    current_result = r
                    break
            else:
                current_result = None
        elif current_result is not None:
            current_result.failure_detail.append(line)


# ---------------------------------------------------------------------------
# Step 3: print per-test report
# ---------------------------------------------------------------------------

def print_report(results: list[TestResult]) -> None:
    # Group by status
    failed  = [r for r in results if r.status in ("FAILED", "ERROR")]
    warned  = [r for r in results if r.warning_msgs and r.status == "PASSED"]
    passed  = [r for r in results if r.status == "PASSED" and not r.warning_msgs]
    skipped = [r for r in results if r.status in ("SKIPPED", "XFAIL")]
    xpassed = [r for r in results if r.status == "XPASS"]

    width = 60

    # ---- FAILED ----
    if failed:
        print(f"  {RED}{BOLD}{'─' * width}{RESET}")
        print(f"  {RED}{BOLD}  FAILED / ERROR  ({len(failed)}){RESET}")
        print(f"  {RED}{BOLD}{'─' * width}{RESET}")
        for r in failed:
            print(f"  {STATUS_ICON['FAILED']}  {r.node_id}")
            for detail_line in r.failure_detail[:8]:  # first 8 lines of traceback
                if detail_line.strip():
                    print(f"            {GREY}{detail_line.strip()[:90]}{RESET}")
        print()

    # ---- WARNING (passed but with warnings) ----
    if warned:
        print(f"  {YELLOW}{BOLD}{'─' * width}{RESET}")
        print(f"  {YELLOW}{BOLD}  PASSED WITH WARNINGS  ({len(warned)}){RESET}")
        print(f"  {YELLOW}{BOLD}{'─' * width}{RESET}")
        for r in warned:
            print(f"  {STATUS_ICON['WARNING']}  {r.node_id}")
            for w in r.warning_msgs[:3]:
                print(f"            {YELLOW}{w[:90]}{RESET}")
        print()

    # ---- SKIPPED ----
    if skipped:
        print(f"  {YELLOW}{'─' * width}{RESET}")
        print(f"  {YELLOW}  SKIPPED / XFAIL  ({len(skipped)}){RESET}")
        print(f"  {YELLOW}{'─' * width}{RESET}")
        for r in skipped:
            print(f"  {STATUS_ICON['SKIPPED']}  {GREY}{r.node_id}{RESET}")
        print()

    # ---- PASSED ----
    if passed or xpassed:
        total_ok = len(passed) + len(xpassed)
        print(f"  {GREEN}{'─' * width}{RESET}")
        print(f"  {GREEN}  PASSED  ({total_ok}){RESET}")
        print(f"  {GREEN}{'─' * width}{RESET}")
        for r in passed + xpassed:
            print(f"  {STATUS_ICON['PASSED']}  {GREY}{r.node_id}{RESET}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    slow      = "--slow"      in args
    fastembed = "--fastembed" in args
    phase_args = [a for a in args if a in PHASES]

    targets   = [PHASES[p] for p in phase_args] if phase_args else ["tests/lancedb_reliability/"]
    workspace = Path(__file__).resolve().parents[2]

    base_cmd = [sys.executable, "-m", "pytest"] + targets
    if slow:
        base_cmd.append("--run-slow")
    if fastembed:
        base_cmd += ["-m", "fastembed"]

    # ---- header ----
    print("=" * 62)
    print(f"  {BOLD}LanceDB Reliability Suite{RESET}")
    print(f"  Phases : {', '.join(phase_args) if phase_args else 'all 5 phases'}")
    print(f"  Slow   : {'on' if slow else 'off  (pass --slow to include 100k tests)'}")
    print(f"  Date   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    # ---- collect ----
    sys.stdout.write("  Collecting tests... ")
    sys.stdout.flush()
    t0 = time.perf_counter()
    total = collect_count(base_cmd, workspace)
    sys.stdout.write(f"{total} found  ({time.perf_counter() - t0:.1f}s)\n")

    # ---- run ----
    run_cmd = base_cmd + ["-v", "--tb=long", "-W", "always"]
    t_start = time.perf_counter()
    exit_code, results = run_with_progress(run_cmd, workspace, total)
    elapsed = time.perf_counter() - t_start

    # ---- per-test report ----
    print_report(results)

    # ---- footer ----
    n_failed  = sum(1 for r in results if r.status in ("FAILED", "ERROR"))
    n_warned  = sum(1 for r in results if r.warning_msgs and r.status == "PASSED")
    n_skipped = sum(1 for r in results if r.status in ("SKIPPED", "XFAIL"))
    n_passed  = sum(1 for r in results if r.status in ("PASSED", "XPASS"))

    print("=" * 62)
    status_str = (f"{GREEN}{BOLD}ALL PASSED{RESET}"
                  if exit_code == 0
                  else f"{RED}{BOLD}FAILURES DETECTED{RESET}")
    print(f"  RESULT  : {status_str}")
    print(
        f"  SUMMARY : "
        f"{GREEN}✓ {n_passed} passed{RESET}  "
        f"{RED}✗ {n_failed} failed{RESET}  "
        f"{YELLOW}⚠ {n_warned} warned  "
        f"⊘ {n_skipped} skipped{RESET}"
    )
    print(f"  TIME    : {elapsed:.1f}s")
    print("=" * 62)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()