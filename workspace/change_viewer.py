#!/usr/bin/env python3
"""
Change Viewer -- Rich CLI for Git History

Usage:
  python3 change_viewer.py              # Last 10 commits
  python3 change_viewer.py --today      # All changes today
  python3 change_viewer.py -n 20        # Last 20 commits
  python3 change_viewer.py --file api_gateway.py   # History for one file
  python3 change_viewer.py --diff HEAD~3            # Show diff from 3 ago
  python3 change_viewer.py --branch main            # Show specific branch
"""

import os
import sys
import argparse
import subprocess
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.syntax import Syntax
from rich import box

console = Console()
WORKSPACE = os.path.join(os.path.expanduser("~/.openclaw"), "workspace")


def git(*args) -> str:
    """Run a git command, return stdout."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout.strip()


def show_log(count: int = 10, branch: str = None, file_filter: str = None, today: bool = False):
    """Show commit history in a rich table."""
    args = ["log", f"-{count}", "--format=%H|%h|%s|%ai|%an"]

    if branch:
        args.insert(1, branch)

    if today:
        today_str = datetime.now().strftime("%Y-%m-%d")
        args.extend(["--since", f"{today_str} 00:00:00"])

    if file_filter:
        args.extend(["--", file_filter])

    output = git(*args)
    if not output:
        console.print("[dim]No commits found.[/dim]")
        return

    table = Table(
        title="[HISTORY] Change History",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Hash", style="yellow", width=8)
    table.add_column("Message", style="white", ratio=3)
    table.add_column("Date", style="dim", width=18)
    table.add_column("Files", style="cyan", justify="right", width=6)

    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue

        full_hash, short_hash, subject, date_str, author = parts

        # Get file count for this commit
        stat = git("diff-tree", "--no-commit-id", "--name-only", "-r", full_hash)
        file_count = len([l for l in stat.split("\n") if l.strip()])

        # Format date
        try:
            dt = datetime.fromisoformat(date_str.strip())
            date_display = dt.strftime("%b %d %H:%M")
        except Exception:
            date_display = date_str[:16]

        # Color auto-commits differently
        msg_style = "bold green" if subject.startswith("[auto]") else "white"

        table.add_row(
            short_hash,
            Text(subject, style=msg_style),
            date_display,
            str(file_count),
        )

    console.print(table)

    # Summary
    total = len(output.split("\n"))
    current_branch = git("branch", "--show-current")
    console.print(f"\n  [dim]Branch: [cyan]{current_branch}[/cyan] | Showing {total} commits[/dim]")


def show_diff(ref: str = "HEAD~1"):
    """Show a colorized diff."""
    output = git("diff", ref, "--stat")
    if not output:
        console.print("[dim]No changes.[/dim]")
        return

    console.print(
        Panel(
            Text(output),
            title=f"[STATS] Changes since {ref}",
            border_style="cyan",
        )
    )

    # Show actual diff with syntax highlighting
    diff_output = git("diff", ref)
    if diff_output:
        console.print(
            Syntax(
                diff_output[:5000],  # Cap at 5k chars
                "diff",
                theme="monokai",
                line_numbers=False,
            )
        )


def show_file_history(filepath: str, count: int = 10):
    """Show history for a specific file."""
    console.print(f"\n  [bold cyan][DIR] History for: {filepath}[/bold cyan]\n")

    output = git("log", f"-{count}", "--format=%h|%s|%ai", "--follow", "--", filepath)
    if not output:
        console.print(f"  [dim]No history found for {filepath}[/dim]")
        return

    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        hash_short, subject, date = parts
        try:
            dt = datetime.fromisoformat(date.strip())
            date_display = dt.strftime("%b %d %H:%M")
        except Exception:
            date_display = date[:16]

        auto = "[BOT]" if "[auto]" in subject else "[USER]"
        console.print(
            f"  {auto} [yellow]{hash_short}[/yellow] {subject} [dim]({date_display})[/dim]"
        )


def show_summary():
    """Show overall workspace stats."""
    total_commits = git("rev-list", "--count", "HEAD")
    branches = git("branch", "--list").split("\n")
    current = git("branch", "--show-current")
    last_commit = git("log", "-1", "--format=%s (%ar)")

    auto_count = git("log", "--all", "--oneline", "--grep=[auto]")
    auto_commits = len([l for l in auto_count.split("\n") if l.strip()]) if auto_count else 0

    console.print(
        Panel(
            Text.from_markup(
                f"  Total commits: [bold]{total_commits}[/bold]\n"
                f"  Auto-commits:  [bold green]{auto_commits}[/bold green]\n"
                f"  Branches:      [cyan]{', '.join(b.strip() for b in branches if b.strip())}[/cyan]\n"
                f"  Current:       [bold yellow]{current}[/bold yellow]\n"
                f"  Last commit:   {last_commit}"
            ),
            title="[CHART] Repository Summary",
            border_style="blue",
        )
    )


def main():
    parser = argparse.ArgumentParser(description="Git Change Viewer -- Rich CLI")
    parser.add_argument("-n", "--count", type=int, default=10, help="Number of commits")
    parser.add_argument("--today", action="store_true", help="Show only today's commits")
    parser.add_argument("--file", type=str, help="Show history for a specific file")
    parser.add_argument("--diff", type=str, help="Show diff against a ref (e.g. HEAD~3)")
    parser.add_argument("--branch", type=str, help="Show a specific branch")
    parser.add_argument("--summary", action="store_true", help="Show repo summary")
    args = parser.parse_args()

    console.print("\n[bold blue]=== [SEARCH] CHANGE VIEWER ===[/bold blue]\n")

    if args.summary:
        show_summary()
    elif args.diff:
        show_diff(args.diff)
    elif args.file:
        show_file_history(args.file, args.count)
    else:
        show_summary()
        console.print()
        show_log(args.count, branch=args.branch, today=args.today)


if __name__ == "__main__":
    main()
