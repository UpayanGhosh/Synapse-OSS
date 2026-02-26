#!/usr/bin/env python3
"""
Change Tracker v2.0 — Hardened Git Auto-Commit Daemon

Watches the OpenClaw workspace for file changes and auto-commits them
to the `synapse-auto-updates` branch with descriptive messages.

Safety features:
  1. RegexMatchingEventHandler — .git/, .db, .log, __pycache__ excluded at OS level
  2. 30-second sliding debounce — handles LLM streaming / chunk writes
  3. Branch isolation — commits to synapse-auto-updates, never touches main
  4. Binary exclusion — skips .db, .sqlite, .gz, images, etc.
  5. Git lock detection — waits if another git process is running
  6. Kill-switch (.pause_tracking) — prevents commits during merges/manual edits
  7. Merge conflict detection — refuses to commit conflict markers

Usage:
  python3 change_tracker.py                 # Run (via launchd or foreground)
  python3 change_tracker.py --push          # Auto-push to GitHub after each commit
  python3 change_tracker.py --debounce 45   # Custom debounce (seconds)
  python3 change_tracker.py --pause         # Create .pause_tracking (kill-switch ON)
  python3 change_tracker.py --resume        # Remove .pause_tracking (kill-switch OFF)
"""

import logging
import os
import sys
import time
import signal
import argparse
import subprocess
from datetime import datetime
from threading import Timer, Lock
from watchdog.observers import Observer
from watchdog.events import RegexMatchingEventHandler

# ═══════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════

WORKSPACE = "/path/to/openclaw"
BRANCH = "synapse-auto-updates"
DEFAULT_DEBOUNCE = 30.0  # seconds of silence before commit
PAUSE_FILE = os.path.join(WORKSPACE, ".pause_tracking")
LOG_FILE = os.path.join(WORKSPACE, "logs", "change_tracker.log")

# Logging — works for both foreground and launchd
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # stdout (visible in foreground)
        logging.FileHandler(LOG_FILE),  # file (visible via launchd)
    ],
)
log = logging.getLogger("tracker")

# Patterns to IGNORE (regex, applied to full path)
IGNORE_REGEXES = [
    # ── Git internals ──
    r".*[/\\]\.git[/\\].*",  # .git/ internals — prevents infinite loop
    r".*[/\\]\.git$",  # .git directory itself
    # ── Binary / large files ──
    r".*\.db$",  # SQLite databases (memory.db = 214MB)
    r".*\.db-shm$",  # SQLite shared memory
    r".*\.db-wal$",  # SQLite write-ahead log
    r".*\.sqlite$",  # Alternative SQLite extension
    r".*\.gz$",  # Compressed files
    r".*\.jsonl$",  # Session JSONL (large, rotates)
    # ── Logs ──
    r".*\.log$",  # All log files
    r".*[/\\]logs[/\\].*",  # logs/ directories
    # ── Backups ──
    r".*\.bak$",  # Backup files
    r".*\.bak\.\d+$",  # Numbered backups (.bak.1, .bak.2, etc.)
    # ── Python ──
    r".*[/\\]__pycache__[/\\].*",  # Python cache
    r".*\.pyc$",  # Compiled Python
    r".*[/\\]\.venv[/\\].*",  # Virtual environment
    # ── macOS ──
    r".*[/\\]\.DS_Store$",  # macOS metadata
    # ── OpenClaw internals (not workspace content) ──
    r".*[/\\]agents[/\\].*[/\\]sessions[/\\].*",  # Agent session files
    r".*[/\\]browser[/\\].*",  # Browser automation data
    r".*[/\\]media[/\\].*",  # Media files
    r".*[/\\]subagents[/\\].*",  # Subagent data
    r".*[/\\]backups[/\\].*",  # Backup directory
    r".*[/\\]credentials[/\\].*",  # Credentials (sensitive!)
    r".*[/\\]devices[/\\].*",  # Device state
    r".*[/\\]completions[/\\].*",  # Completion cache
    r".*[/\\]canvas[/\\].*",  # Canvas data
    r".*[/\\]\.clawhub[/\\].*",  # ClawHub internals
    r".*[/\\]\.vscode[/\\].*",  # VS Code settings
    r".*[/\\]models[/\\].*",  # Model data
    # ── Workspace exclusions ──
    r".*[/\\]qdrant[/\\]storage[/\\].*",  # Qdrant vector storage
    r".*[/\\]_archived_memories[/\\].*",  # Archived memories
    r".*[/\\]node_modules[/\\].*",  # Node modules
    # ── Editor / misc ──
    r".*\.swp$",  # Vim swap files
    r".*~$",  # Editor backup files
    r".*\.pause_tracking$",  # Kill-switch file itself
    r".*sentinel_state\.json$",  # Sentinel state
    r".*update-check\.json$",  # Update check
]

# File categories for descriptive commit messages
CATEGORY_MAP = {
    "identity": [
        "SOUL.md",
        "CORE.md",
        "IDENTITY.md",
        "USER.md",
        "AGENTS.md",
        "INSTRUCTIONS.MD",
        "MEMORY.md",
        "HEARTBEAT.md",
    ],
    "persona": [
        "the_creator_profile.json",
        "the_partner_profile.json",
        "persona.py",
        "chat_parser.py",
        "build_persona.py",
    ],
    "gateway": ["api_gateway.py", "retriever.py", "server.py"],
    "config": ["openclaw.json", "config.py", ".gitignore", ".openclawignore"],
    "monitor": ["monitor.py", "change_tracker.py", "change_viewer.py"],
    "skills": [],  # Anything under skills/
    "memory": [],  # Anything under memory/
}


# ═══════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════


def git(*args, cwd=WORKSPACE) -> tuple[int, str]:
    """Run a git command, return (returncode, output)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "git command timed out"
    except Exception as e:
        return 1, str(e)


def is_git_locked() -> bool:
    """Check if another git process has the lock."""
    lock_file = os.path.join(WORKSPACE, ".git", "index.lock")
    return os.path.exists(lock_file)


def is_paused() -> bool:
    """Check if the kill-switch file exists."""
    return os.path.exists(PAUSE_FILE)


def has_merge_conflict() -> bool:
    """Detect an active merge or conflict markers in staged files."""
    # Check for active merge state
    merge_head = os.path.join(WORKSPACE, ".git", "MERGE_HEAD")
    if os.path.exists(merge_head):
        return True

    # Check for unmerged files
    rc, out = git("diff", "--cached", "--diff-filter=U")
    if out.strip():
        return True

    # Scan any staged files for conflict markers
    rc, staged = git("diff", "--cached", "--name-only")
    if staged.strip():
        for fname in staged.strip().split("\n"):
            fpath = os.path.join(WORKSPACE, fname)
            try:
                with open(fpath, "r", errors="ignore") as f:
                    content = f.read(50_000)  # First 50KB
                    if "<<<<<<< " in content and "=======\n" in content and ">>>>>>> " in content:
                        return True
            except Exception:
                pass

    return False


def classify_file(filepath: str) -> str:
    """Classify a file into a category for the commit message."""
    basename = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, WORKSPACE)

    for category, patterns in CATEGORY_MAP.items():
        if basename in patterns:
            return category

    # Path-based classification
    if "skills/" in relpath:
        return "skills"
    if "memory/" in relpath:
        return "memory"
    if "sci_fi_dashboard/" in relpath:
        return "gateway"
    if "personas/" in relpath:
        return "persona"

    return "workspace"


def build_commit_message(changes: dict[str, set[str]]) -> str:
    """Build a descriptive commit message from categorized changes."""
    parts = []

    for action, files in changes.items():
        if not files:
            continue

        # Group by category
        categories: dict[str, list[str]] = {}
        for f in files:
            cat = classify_file(f)
            categories.setdefault(cat, []).append(os.path.basename(f))

        for cat, filenames in categories.items():
            names = ", ".join(sorted(set(filenames))[:5])  # Max 5 per category
            extra = f" +{len(filenames) - 5} more" if len(filenames) > 5 else ""
            parts.append(f"{action} [{cat}]: {names}{extra}")

    if not parts:
        return "[auto] Minor workspace changes"

    timestamp = datetime.now().strftime("%H:%M")
    summary = " | ".join(parts[:3])
    if len(parts) > 3:
        summary += f" (+{len(parts) - 3} more)"

    return f"[auto] {summary} — {timestamp}"


# ═══════════════════════════════════════════
#  WATCHDOG HANDLER
# ═══════════════════════════════════════════


class BotChangeHandler(RegexMatchingEventHandler):
    """
    Watches for file changes with a sliding debounce window.

    Safety:
    - .git/, .db, .log etc. excluded via IGNORE_REGEXES
    - 30s sliding debounce handles LLM streaming
    - Git lock detection prevents concurrent git operations
    - Kill-switch (.pause_tracking) halts commits
    - Merge conflict markers are detected and rejected
    """

    def __init__(self, debounce_seconds: float = DEFAULT_DEBOUNCE, auto_push: bool = False):
        super().__init__(
            ignore_regexes=IGNORE_REGEXES,
            ignore_directories=True,
            case_sensitive=False,
        )
        self.debounce_seconds = debounce_seconds
        self.auto_push = auto_push
        self.commit_timer: Timer | None = None
        self.lock = Lock()

        # Track changes by action type
        self.pending: dict[str, set[str]] = {
            "modified": set(),
            "created": set(),
            "deleted": set(),
        }

        # Stats
        self.total_commits = 0
        self.total_files_tracked = 0

    def on_modified(self, event):
        self._register_change("modified", event.src_path)

    def on_created(self, event):
        self._register_change("created", event.src_path)

    def on_deleted(self, event):
        self._register_change("deleted", event.src_path)

    def on_moved(self, event):
        self._register_change("deleted", event.src_path)
        self._register_change("created", event.dest_path)

    def _register_change(self, action: str, path: str):
        """Register a change and reset the debounce timer."""
        with self.lock:
            self.pending[action].add(path)
            filename = os.path.basename(path)
            log.info(f"📝 {action.upper()}: {filename}")

            # Cancel existing timer and start a new one
            if self.commit_timer is not None:
                self.commit_timer.cancel()

            self.commit_timer = Timer(
                self.debounce_seconds,
                self._execute_commit,
            )
            self.commit_timer.daemon = True
            self.commit_timer.start()

    def _execute_commit(self):
        """Commit all pending changes after the debounce window."""
        with self.lock:
            # ── KILL-SWITCH CHECK ──
            if is_paused():
                log.warning("⏸️  PAUSED — .pause_tracking exists, skipping commit")
                return

            # ── MERGE CONFLICT CHECK (pre-stage) ──
            if has_merge_conflict():
                log.error("🚨 MERGE CONFLICT DETECTED — refusing to commit!")
                log.error("   Fix the conflict, then run: python3 change_tracker.py --resume")
                return

            # Check if there's actually anything to commit
            total_pending = sum(len(v) for v in self.pending.values())
            if total_pending == 0:
                return

            # Wait for git lock to clear
            retries = 0
            while is_git_locked() and retries < 10:
                log.info("⏳ Waiting for git lock to clear...")
                time.sleep(2)
                retries += 1

            if is_git_locked():
                log.warning("⚠️ Git lock persisted, skipping commit")
                return

            # Build commit message before clearing pending
            commit_msg = build_commit_message(self.pending)
            file_count = total_pending

            # Stage and commit
            rc, out = git("add", "-A")
            if rc != 0:
                log.error(f"git add failed: {out}")
                return

            # ── POST-STAGE CONFLICT CHECK ──
            if has_merge_conflict():
                log.error("🚨 CONFLICT MARKERS detected after staging — aborting!")
                git("reset", "HEAD")  # Unstage everything
                return

            # Check if there are actually staged changes
            rc, diff_out = git("diff", "--cached", "--stat")
            if rc != 0 or not diff_out.strip():
                log.info("No actual changes to commit (gitignored or unchanged)")
                self.pending = {"modified": set(), "created": set(), "deleted": set()}
                return

            rc, out = git("commit", "-m", commit_msg)
            if rc != 0:
                if "nothing to commit" in out:
                    log.info("Nothing to commit")
                else:
                    log.error(f"git commit failed: {out}")
                self.pending = {"modified": set(), "created": set(), "deleted": set()}
                return

            self.total_commits += 1
            self.total_files_tracked += file_count
            log.info(f"✅ COMMITTED #{self.total_commits}: {commit_msg}")
            log.info(f"   Files: {file_count} | Total tracked: {self.total_files_tracked}")

            # Optional: push to GitHub
            if self.auto_push:
                rc, out = git("push", "origin", BRANCH)
                if rc == 0:
                    log.info(f"🚀 Pushed to origin/{BRANCH}")
                else:
                    log.warning(f"Push failed: {out}")

            # Clear pending
            self.pending = {"modified": set(), "created": set(), "deleted": set()}


# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════


def ensure_branch():
    """Ensure we're on the synapse-auto-updates branch."""
    # Check current branch
    rc, current = git("branch", "--show-current")
    if current.strip() == BRANCH:
        log.info(f"Already on branch: {BRANCH}")
        return True

    # Stash any dirty files that might block checkout
    rc, stash_out = git("stash", "--include-untracked")
    stashed = rc == 0 and "No local changes" not in stash_out
    if stashed:
        log.info(f"Stashed dirty files before branch switch")

    # Check if branch exists
    rc, branches = git("branch", "--list", BRANCH)
    if BRANCH in branches:
        rc, out = git("checkout", BRANCH)
    else:
        rc, out = git("checkout", "-b", BRANCH)

    if rc != 0:
        log.error(f"Failed to switch to {BRANCH}: {out}")
        # Pop stash back if checkout failed
        if stashed:
            git("stash", "pop")
        return False

    # Pop stash on the new branch
    if stashed:
        git("stash", "pop")
        log.info("Restored stashed files")

    log.info(f"Switched to branch: {BRANCH}")
    return True


def cmd_pause():
    """Create the .pause_tracking kill-switch file."""
    with open(PAUSE_FILE, "w") as f:
        f.write(f"Paused at {datetime.now().isoformat()} by user\n")
    print(f"  ⏸️  Kill-switch ON — created {PAUSE_FILE}")
    print("  Tracker will skip all commits until you run --resume")


def cmd_resume():
    """Remove the .pause_tracking kill-switch file."""
    if os.path.exists(PAUSE_FILE):
        os.remove(PAUSE_FILE)
        print(f"  ▶️  Kill-switch OFF — removed {PAUSE_FILE}")
        print("  Tracker will resume committing changes")
    else:
        print("  ℹ️  Tracker is not paused (no .pause_tracking file)")


def main():
    parser = argparse.ArgumentParser(description="Hardened Git Auto-Commit Daemon v2.0")
    parser.add_argument("--push", action="store_true", help="Auto-push after each commit")
    parser.add_argument(
        "--debounce",
        type=float,
        default=DEFAULT_DEBOUNCE,
        help=f"Debounce seconds (default: {DEFAULT_DEBOUNCE})",
    )
    parser.add_argument(
        "--pause", action="store_true", help="Create .pause_tracking kill-switch and exit"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Remove .pause_tracking kill-switch and exit"
    )
    args = parser.parse_args()

    # Handle pause/resume subcommands
    if args.pause:
        cmd_pause()
        return
    if args.resume:
        cmd_resume()
        return

    paused = is_paused()

    log.info("═" * 56)
    log.info("🔍 CHANGE TRACKER v2.0 — Hardened Git Auto-Commit")
    log.info("═" * 56)
    log.info(f"📂 Watching: {WORKSPACE}")
    log.info(f"🌿 Branch:   {BRANCH}")
    log.info(f"⏱️  Debounce: {args.debounce}s")
    log.info(f"🚀 Auto-push: {'ON' if args.push else 'OFF'}")
    log.info(f"⏸️  Paused:    {'YES ⚠️' if paused else 'NO'}")
    log.info(f"📝 Log file: {LOG_FILE}")
    log.info(f"🛡️  Excluded:  .git/, .db, .log, __pycache__, qdrant/")
    log.info("═" * 56)

    if paused:
        log.warning("Tracker is PAUSED. Commits will be skipped until --resume.")

    # Switch to tracking branch
    if not ensure_branch():
        log.error("Cannot start: branch switch failed")
        sys.exit(1)

    # Create handler and observer
    handler = BotChangeHandler(
        debounce_seconds=args.debounce,
        auto_push=args.push,
    )
    observer = Observer()
    observer.schedule(handler, WORKSPACE, recursive=True)

    # Graceful shutdown
    def shutdown(signum, frame):
        log.info("")
        log.info("🛑 Shutting down tracker...")
        log.info(f"   Total commits: {handler.total_commits}")
        log.info(f"   Total files tracked: {handler.total_files_tracked}")

        # Cancel any pending timer
        if handler.commit_timer:
            handler.commit_timer.cancel()

        # Commit anything left (if not paused)
        if not is_paused():
            total_left = sum(len(v) for v in handler.pending.values())
            if total_left > 0:
                log.info(f"   Committing {total_left} remaining changes...")
                handler._execute_commit()

        observer.stop()
        observer.join()

        # NOTE: Do NOT switch back to main here.
        # Under launchd, the daemon auto-restarts — switching branches
        # would cause the next start to be on 'main', and auto-commits
        # would go to the wrong branch. Stay on synapse-auto-updates.
    log.info("👋 Tracker stopped (staying on synapse-auto-updates).")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start watching
    observer.start()
    log.info("")
    log.info("👁️  Watching for changes... (Ctrl+C or SIGTERM to stop)")
    log.info("")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
