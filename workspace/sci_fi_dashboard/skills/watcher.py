"""
skills/watcher.py — SkillWatcher: watchdog-based filesystem watcher for skill hot-reload.

Watches ~/.synapse/skills/ for SKILL.md create/modify/delete events and calls
registry.reload() to pick up changes without server restart.

Security mitigations (T-01-04):
  - Debounce of `debounce_seconds` (default 2.0s) prevents rapid-fire reload loops
  - reload() is called in try/except — watcher never crashes on a bad SKILL.md
  - Polling fallback when watchdog is unavailable (logs a warning)
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Detect watchdog availability at import time.
try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WATCHDOG_AVAILABLE = False
    logger.warning(
        "watchdog not installed — skill hot-reload will use polling mode. "
        "Install with: pip install watchdog>=4.0.0"
    )


# ---------------------------------------------------------------------------
# watchdog event handler (used when watchdog is available)
# ---------------------------------------------------------------------------

if _WATCHDOG_AVAILABLE:

    class _SkillEventHandler(FileSystemEventHandler):
        """Handles filesystem events and triggers registry.reload() with debounce."""

        def __init__(self, registry: "SkillRegistry", debounce_seconds: float) -> None:
            super().__init__()
            self._registry = registry
            self._debounce = debounce_seconds
            self._last_reload: float = 0.0

        def _should_trigger(self, event: "FileSystemEvent") -> bool:
            """Return True if this event should trigger a reload."""
            src = str(event.src_path)
            # Trigger on SKILL.md changes or directory-level events
            return src.endswith("SKILL.md") or event.is_directory  # type: ignore[union-attr]

        def _maybe_reload(self, event: "FileSystemEvent") -> None:
            if not self._should_trigger(event):
                return
            now = time.monotonic()
            if now - self._last_reload < self._debounce:
                return
            self._last_reload = now
            try:
                self._registry.reload()
            except Exception as exc:
                logger.warning("[SkillWatcher] reload() raised: %s", exc)

        def on_created(self, event: "FileSystemEvent") -> None:
            self._maybe_reload(event)

        def on_deleted(self, event: "FileSystemEvent") -> None:
            self._maybe_reload(event)

        def on_modified(self, event: "FileSystemEvent") -> None:
            self._maybe_reload(event)

        def on_moved(self, event: "FileSystemEvent") -> None:
            self._maybe_reload(event)


# ---------------------------------------------------------------------------
# SkillWatcher
# ---------------------------------------------------------------------------


class SkillWatcher:
    """Watches a skills directory for changes and triggers registry.reload().

    Uses `watchdog` when available; falls back to polling every
    ``debounce_seconds * 5`` seconds with a logged warning.

    Usage::

        watcher = SkillWatcher(skills_dir, registry, debounce_seconds=2.0)
        watcher.start()  # non-blocking — spawns background thread
        # ... server runs ...
        watcher.stop()   # clean shutdown
    """

    def __init__(
        self,
        skills_dir: Path,
        registry: "SkillRegistry",
        debounce_seconds: float = 2.0,
    ) -> None:
        self._skills_dir = skills_dir
        self._registry = registry
        self._debounce = debounce_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Watchdog-specific state
        self._observer: "Observer | None" = None  # type: ignore[name-defined]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching the skills directory in a background thread."""
        if _WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            self._start_polling()

    def stop(self) -> None:
        """Stop watching and join the background thread."""
        self._stop_event.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5.0)
            except Exception as exc:
                logger.warning("[SkillWatcher] Error stopping observer: %s", exc)
            self._observer = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Private — watchdog mode
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        handler = _SkillEventHandler(self._registry, self._debounce)
        observer = Observer()
        observer.schedule(handler, str(self._skills_dir), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("[SkillWatcher] Watching %s via watchdog", self._skills_dir)

    # ------------------------------------------------------------------
    # Private — polling fallback
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        interval = self._debounce * 5
        logger.warning(
            "[SkillWatcher] Polling mode (watchdog not installed). "
            "Checking for skill changes every %.1fs.",
            interval,
        )
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(interval,),
            daemon=True,
            name="SkillWatcher-poll",
        )
        self._thread.start()

    def _poll_loop(self, interval: float) -> None:
        while not self._stop_event.wait(timeout=interval):
            try:
                self._registry.reload()
            except Exception as exc:
                logger.warning("[SkillWatcher] Poll reload() raised: %s", exc)
