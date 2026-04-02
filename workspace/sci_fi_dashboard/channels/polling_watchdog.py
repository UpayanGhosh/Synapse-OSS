"""
Polling session stall watchdog.

Monitors a long-polling channel adapter and triggers a restart if no update
activity has been recorded for ``POLL_STALL_THRESHOLD_S`` seconds.  Restarts
use exponential backoff with jitter to avoid thundering-herd effects when
multiple bots share infrastructure.

Usage (from TelegramChannel)::

    watchdog = PollingWatchdog(restart_callback=self._restart_polling)
    await watchdog.start()
    # ... on every incoming update:
    watchdog.record_activity()
    # ... on shutdown:
    await watchdog.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

POLL_STALL_THRESHOLD_S: float = 90.0
POLL_WATCHDOG_INTERVAL_S: float = 30.0
POLL_STOP_GRACE_S: float = 15.0
RESTART_POLICY: dict = {
    "initial_s": 2.0,
    "max_s": 30.0,
    "factor": 1.8,
    "jitter": 0.25,
}


class PollingWatchdog:
    """Background task that detects stalled polling and triggers a restart.

    Args:
        restart_callback: An async callable invoked when a stall is detected.
                          Should restart the polling subsystem.
        stall_threshold_s: Seconds of inactivity before a stall is declared.
    """

    def __init__(
        self,
        restart_callback: Callable,
        stall_threshold_s: float = POLL_STALL_THRESHOLD_S,
    ) -> None:
        self._restart_callback = restart_callback
        self._stall_threshold_s = stall_threshold_s
        self._last_activity: float = time.monotonic()
        self._task: asyncio.Task | None = None
        self._consecutive_restarts: int = 0

    def record_activity(self) -> None:
        """Reset the stall timer.  Call on every received update."""
        self._last_activity = time.monotonic()
        self._consecutive_restarts = 0

    async def start(self) -> None:
        """Start the background watch loop."""
        if self._task is not None and not self._task.done():
            return
        self._last_activity = time.monotonic()
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("[WATCHDOG] Started (stall threshold=%.0fs)", self._stall_threshold_s)

    async def stop(self) -> None:
        """Cancel the background watch loop and wait for clean exit."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("[WATCHDOG] Stopped")

    async def _watch_loop(self) -> None:
        """Periodically check for stalls and invoke the restart callback."""
        try:
            while True:
                await asyncio.sleep(POLL_WATCHDOG_INTERVAL_S)

                elapsed = time.monotonic() - self._last_activity
                if elapsed < self._stall_threshold_s:
                    continue

                # Stall detected
                self._consecutive_restarts += 1
                backoff = self._compute_backoff()
                logger.warning(
                    "[WATCHDOG] Stall detected — no activity for %.0fs "
                    "(threshold=%.0fs, restart #%d, backoff=%.1fs)",
                    elapsed,
                    self._stall_threshold_s,
                    self._consecutive_restarts,
                    backoff,
                )

                await asyncio.sleep(backoff)

                try:
                    await self._restart_callback()
                except Exception:
                    logger.exception("[WATCHDOG] restart_callback raised")

                # Reset the activity timer after restart attempt so we don't
                # immediately trigger again.
                self._last_activity = time.monotonic()

        except asyncio.CancelledError:
            logger.debug("[WATCHDOG] Watch loop cancelled")

    def _compute_backoff(self) -> float:
        """Compute exponential backoff with jitter for the current restart count.

        Formula::

            base = initial_s * (factor ** (consecutive_restarts - 1))
            clamped = min(base, max_s)
            jittered = clamped * (1 + random.uniform(-jitter, +jitter))

        Returns:
            Backoff duration in seconds.
        """
        policy = RESTART_POLICY
        base = policy["initial_s"] * (policy["factor"] ** (self._consecutive_restarts - 1))
        clamped = min(base, policy["max_s"])
        jitter_range = policy["jitter"]
        jittered = clamped * (1.0 + random.uniform(-jitter_range, jitter_range))
        return max(0.0, jittered)
