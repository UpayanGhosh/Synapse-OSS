"""
SkillWatcher — filesystem watcher for hot-reload of skill directories.

Watches ~/.synapse/skills/ for SKILL.md changes and triggers registry.reload().
Uses watchdog when available; falls back to polling if not installed.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillWatcher:
    """Watches skills_dir for filesystem changes and triggers registry.reload().

    Uses watchdog (pip install watchdog) for efficient event-driven watching.
    Falls back to a simple polling loop if watchdog is not installed.

    Debounce prevents rapid-fire reload loops (default: 2.0 seconds).
    """

    def __init__(
        self,
        skills_dir: Path,
        registry,
        debounce_seconds: float = 2.0,
    ) -> None:
        self._skills_dir = skills_dir
        self._registry = registry
        self._debounce = debounce_seconds
        self._observer = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_reload: float = 0.0
        self._last_snapshot: tuple[tuple[str, int, int], ...] = self._snapshot()

    def _try_reload(self) -> None:
        """Attempt registry reload with debounce protection. Never crashes."""
        now = time.monotonic()
        if now - self._last_reload < self._debounce:
            return
        self._last_reload = now
        try:
            self._registry.reload()
            self._last_snapshot = self._snapshot()
        except Exception as exc:
            logger.warning("[Skills] Watcher: reload failed: %s", exc)

    def _snapshot(self) -> tuple[tuple[str, int, int], ...]:
        """Return a cheap fingerprint of all skill manifests."""
        if not self._skills_dir.exists():
            return ()
        rows: list[tuple[str, int, int]] = []
        for path in self._skills_dir.rglob("SKILL.md"):
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = str(path.relative_to(self._skills_dir)).replace("\\", "/")
            rows.append((rel, int(stat.st_mtime_ns), int(stat.st_size)))
        return tuple(sorted(rows))

    def _poll_changed(self) -> bool:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return False
        self._last_snapshot = snapshot
        return True

    def start(self) -> None:
        """Start watching for filesystem changes."""
        try:
            self._start_watchdog()
        except ImportError:
            logger.warning(
                "[Skills] watchdog not installed — falling back to polling every %.0fs",
                self._debounce * 5,
            )
            self._start_polling()

    def stop(self) -> None:
        """Stop the watcher and clean up resources."""
        self._stop_event.set()

        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5.0)
            except Exception as exc:
                logger.debug("[Skills] Watcher stop error: %s", exc)
            self._observer = None

        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None

    # ------------------------------------------------------------------
    # Watchdog implementation
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        """Start watchdog-based observer. Raises ImportError if not installed."""
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                # Only react to SKILL.md changes or directory events
                src = getattr(event, "src_path", "")
                dest = getattr(event, "dest_path", "")
                if "SKILL.md" in src or "SKILL.md" in dest or event.is_directory:
                    watcher._try_reload()

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self._skills_dir), recursive=True)
        self._observer.start()
        logger.info("[Skills] Watchdog started on %s", self._skills_dir)

    # ------------------------------------------------------------------
    # Polling fallback
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        """Start a polling thread as fallback when watchdog is unavailable."""
        interval = self._debounce * 5

        def _poll_loop():
            logger.info("[Skills] Polling fallback: checking for changes every %.0fs", interval)
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=interval)
                if not self._stop_event.is_set():
                    if self._poll_changed():
                        try:
                            self._registry.reload()
                        except Exception as exc:
                            logger.warning("[Skills] Poll reload failed: %s", exc)

        self._poll_thread = threading.Thread(
            target=_poll_loop,
            daemon=True,
            name="skill-watcher-poll",
        )
        self._poll_thread.start()
