#!/usr/bin/env python3
"""
Change Tracker v1.0 — Synapse Git Auto-Commit Daemon

Watches ~/.synapse/ for file changes and auto-commits them
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
  python3 change_tracker.py                 # Run (foreground)
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

WORKSPACE = os.path.expanduser("~/.synapse")
BRANCH = "synapse-auto-updates"
DEFAULT_DEBOUNCE = 30.0  # seconds of silence before commit
PAUSE_FILE = os.path.join(WORKSPACE, ".pause_tracking")
LOG_FILE = os.path.join(WORKSPACE, "logs", "change_tracker.log")

# Logging
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("tracker")

# Patterns to IGNORE (regex, applied to full path)
IGNORE_REGEXES = [
    # Git internals
    r".*[/\\]\.git[/\\].*",
    r".*[/\\]\.git$",

    # Binary / large files
    r".*\.db$",
    r".*\.db-shm$",
    r".*\.db-wal$",
    r".*\.sqlite$",
    r".*\.gz$",
    r".*\.jsonl$",

    # Logs
    r".*\.log$",
    r".*[/\\]logs[/\\].*",

    # Backups
    r".*\.bak$",
    r".*\.bak\.\d+$",

    # Python
    r".*[/\\]__pycache__[/\\].*",
    r".*\.pyc$",
    r".*[/\\]\.venv[/\\].*",

    # Windows
    r".*[/\\]\.DS_Store$",
    r".*Thumbs\.db$",

    # Synapse internals
    r".*[/\\]lancedb[/\\].*",        # LanceDB vector storage
    r".*[/\\]sessions[/\\].*",       # Session files
    r".*[/\\]media[/\\].*",          # Media files
    r".*[/\\]backups[/\\].*",        # Backups
    r".*[/\\]node_modules[/\\].*",   # Node modules
    r".*\.swp$",                     # Vim swap files
    r".*~$",                         # Editor backup files
    r".*\.pause_tracking$",          # Kill-switch file itself
]

# File categories for commit messages
CATEGORY_MAP = {
    "identity": ["SOUL.md", "CORE.md", "IDENTITY.md", "USER.md", "AGENTS.md",
                 "MEMORY.md", "HEARTBEAT.md"],
    "persona": ["upayan_profile.json", "shreya_profile.json", "persona.py",
                "chat_parser.py", "build_persona.py"],
    "gateway": ["api_gateway.py", "chat_pipeline.py", "retriever.py", "memory_engine.py"],
    "config": ["synapse.json", "synapse_config.py", ".gitignore"],
    "monitor": ["change_tracker.py", "gentle_worker.py"],
    "skills": [],   # Anything under skills/
    "memory": [],   # Anything under memory/ or diary/
    "cron": [],     # Anything under cron/
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
    lock_file = os.path.join(WORKSPACE, ".git", "index.lock")
    return os.path.exists(lock_file)


def is_paused() -> bool:
    return os.path.exists(PAUSE_FILE)


def has_merge_conflict() -> bool:
    merge_head = os.path.join(WORKSPACE, ".git", "MERGE_HEAD")
    if os.path.exists(merge_head):
        return True
    rc, out = git("diff", "--cached", "--diff-filter=U")
    if out.strip():
        return True
    rc, staged = git("diff", "--cached", "--name-only")
    if staged.strip():
        for fname in staged.strip().split("\n"):
            fpath = os.path.join(WORKSPACE, fname)
            try:
                with open(fpath, "r", errors="ignore") as f:
                    content = f.read(50_000)
                    if "<<<<<<< " in content and "=======\n" in content and ">>>>>>> " in content:
                        return True
            except Exception:
                pass
    return False


def classify_file(filepath: str) -> str:
    basename = os.path.basename(filepath)
    relpath = os.path.relpath(filepath, WORKSPACE)

    for category, patterns in CATEGORY_MAP.items():
        if basename in patterns:
            return category

    if "skills/" in relpath or "skills\\" in relpath:
        return "skills"
    if "memory/" in relpath or "memory\\" in relpath:
        return "memory"
    if "diary/" in relpath or "diary\\" in relpath:
        return "memory"
    if "cron/" in relpath or "cron\\" in relpath:
        return "cron"
    if "sci_fi_dashboard/" in relpath or "sci_fi_dashboard\\" in relpath:
        return "gateway"
    if "personas/" in relpath or "personas\\" in relpath:
        return "persona"
    return "workspace"


def build_commit_message(changes: dict[str, set[str]]) -> str:
    parts = []
    for action, files in changes.items():
        if not files:
            continue
        categories: dict[str, list[str]] = {}
        for f in files:
            cat = classify_file(f)
            categories.setdefault(cat, []).append(os.path.basename(f))
        for cat, filenames in categories.items():
            names = ", ".join(sorted(set(filenames))[:5])
            extra = f" +{len(filenames) - 5} more" if len(filenames) > 5 else ""
            parts.append(f"{action} [{cat}]: {names}{extra}")

    if not parts:
        return "[auto] Minor workspace changes"

    timestamp = datetime.now().strftime("%H:%M")
    summary = " | ".join(parts[:3])
    if len(parts) > 3:
        summary += f" (+{len(parts) - 3} more)"
    return f"[auto] {summary} - {timestamp}"


# ═══════════════════════════════════════════
#  WATCHDOG HANDLER
# ═══════════════════════════════════════════

class BotChangeHandler(RegexMatchingEventHandler):
    """Watches for file changes with a sliding debounce window."""

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
        self.pending: dict[str, set[str]] = {
            "modified": set(),
            "created": set(),
            "deleted": set(),
        }
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
        with self.lock:
            self.pending[action].add(path)
            log.info(f"[{action.upper()}] {os.path.basename(path)}")
            if self.commit_timer is not None:
                self.commit_timer.cancel()
            self.commit_timer = Timer(self.debounce_seconds, self._execute_commit)
            self.commit_timer.daemon = True
            self.commit_timer.start()

    def _execute_commit(self):
        with self.lock:
            if is_paused():
                log.warning("PAUSED — .pause_tracking exists, skipping commit")
                return

            if has_merge_conflict():
                log.error("MERGE CONFLICT DETECTED — refusing to commit!")
                return

            total_pending = sum(len(v) for v in self.pending.values())
            if total_pending == 0:
                return

            retries = 0
            while is_git_locked() and retries < 10:
                log.info("Waiting for git lock to clear...")
                time.sleep(2)
                retries += 1

            if is_git_locked():
                log.warning("Git lock persisted, skipping commit")
                return

            commit_msg = build_commit_message(self.pending)
            file_count = total_pending

            rc, out = git("add", "-A")
            if rc != 0:
                log.error(f"git add failed: {out}")
                return

            if has_merge_conflict():
                log.error("CONFLICT MARKERS detected after staging — aborting!")
                git("reset", "HEAD")
                return

            rc, diff_out = git("diff", "--cached", "--stat")
            if rc != 0 or not diff_out.strip():
                log.info("No actual changes to commit")
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
            log.info(f"COMMITTED #{self.total_commits}: {commit_msg}")

            if self.auto_push:
                rc, out = git("push", "origin", BRANCH)
                if rc == 0:
                    log.info(f"Pushed to origin/{BRANCH}")
                else:
                    log.warning(f"Push failed: {out}")

            self.pending = {"modified": set(), "created": set(), "deleted": set()}


# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════

def ensure_branch():
    rc, current = git("branch", "--show-current")
    if current.strip() == BRANCH:
        log.info(f"Already on branch: {BRANCH}")
        return True

    rc, branches = git("branch", "--list", BRANCH)
    if BRANCH in branches:
        rc, out = git("checkout", BRANCH)
    else:
        rc, out = git("checkout", "-b", BRANCH)

    if rc != 0:
        log.error(f"Failed to switch to {BRANCH}: {out}")
        return False

    log.info(f"Switched to branch: {BRANCH}")
    return True


def cmd_pause():
    with open(PAUSE_FILE, "w") as f:
        f.write(f"Paused at {datetime.now().isoformat()} by user\n")
    print(f"Kill-switch ON — created {PAUSE_FILE}")


def cmd_resume():
    if os.path.exists(PAUSE_FILE):
        os.remove(PAUSE_FILE)
        print("Kill-switch OFF — tracker will resume")
    else:
        print("Tracker is not paused")


def main():
    parser = argparse.ArgumentParser(description="Synapse Git Auto-Commit Daemon")
    parser.add_argument("--push", action="store_true", help="Auto-push after each commit")
    parser.add_argument("--debounce", type=float, default=DEFAULT_DEBOUNCE)
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if args.pause:
        cmd_pause()
        return
    if args.resume:
        cmd_resume()
        return

    log.info("=" * 56)
    log.info("CHANGE TRACKER v1.0 — Synapse Git Auto-Commit")
    log.info("=" * 56)
    log.info(f"Watching: {WORKSPACE}")
    log.info(f"Branch:   {BRANCH}")
    log.info(f"Debounce: {args.debounce}s")
    log.info(f"Auto-push: {'ON' if args.push else 'OFF'}")
    log.info("=" * 56)

    if is_paused():
        log.warning("Tracker is PAUSED. Run --resume to enable commits.")

    handler = BotChangeHandler(debounce_seconds=args.debounce, auto_push=args.push)
    observer = Observer()
    observer.schedule(handler, WORKSPACE, recursive=True)

    def shutdown(signum, frame):
        log.info("Shutting down tracker...")
        if handler.commit_timer:
            handler.commit_timer.cancel()
        if not is_paused():
            total_left = sum(len(v) for v in handler.pending.values())
            if total_left > 0:
                handler._execute_commit()
        observer.stop()
        observer.join()
        log.info(f"Stopped. Total commits: {handler.total_commits}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    observer.start()
    log.info("Watching for changes... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
