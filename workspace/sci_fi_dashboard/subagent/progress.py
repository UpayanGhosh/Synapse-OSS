"""
ProgressReporter — periodic progress callback for long-running sub-agents.

Fires an async callback at a configurable interval so the parent conversation
can see that the agent is still alive and working.  Intentionally lightweight:
no heavy imports, no references to MemoryEngine or the LLM router.

Usage::

    async def _on_progress(agent_id: str, message: str) -> None:
        ...

    reporter = ProgressReporter(
        agent_id="abc-123",
        interval_seconds=15.0,
        callback=_on_progress,
    )
    reporter.start()
    ...
    reporter.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# GC anchor — prevents the background task from being garbage-collected before
# the reporter is stopped (same pattern used in pipeline_helpers.py).
_reporter_tasks: set[asyncio.Task] = set()


class ProgressReporter:
    """Periodically fires a callback to signal that an agent is still working.

    Parameters
    ----------
    agent_id:
        Identifier of the owning sub-agent.
    interval_seconds:
        How often to fire the callback (default 15 s).
    callback:
        Optional async callable with signature
        ``async def callback(agent_id: str, message: str) -> None``.
        If *None*, start() is a no-op (no background loop is created).
    """

    def __init__(
        self,
        agent_id: str,
        interval_seconds: float = 15.0,
        callback: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.interval_seconds = interval_seconds
        self.callback = callback

        # Latest human-readable status set by update().
        self._latest_message: str = "working…"

        # Background asyncio.Task handle.
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background progress loop.

        Creates an asyncio.Task that sleeps for *interval_seconds*, then calls
        the callback with the latest progress message, and repeats until
        cancelled.  A strong reference is kept in the module-level
        ``_reporter_tasks`` set so the task is not garbage-collected.

        If no callback was provided this method is a no-op.
        """
        if self.callback is None:
            return
        if self._task is not None and not self._task.done():
            logger.debug("ProgressReporter for %s already running", self.agent_id)
            return

        self._task = asyncio.create_task(
            self._loop(),
            name=f"progress-{self.agent_id}",
        )
        _reporter_tasks.add(self._task)
        self._task.add_done_callback(_reporter_tasks.discard)
        logger.debug(
            "ProgressReporter started for agent %s (interval=%.1fs)",
            self.agent_id,
            self.interval_seconds,
        )

    def stop(self) -> None:
        """Cancel the background loop and suppress the resulting CancelledError."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            # The task will be cancelled on the next event-loop iteration; we
            # don't await here because stop() is called from sync and async
            # contexts alike.  The suppress just silences any synchronous
            # propagation.
            pass
        logger.debug("ProgressReporter stopped for agent %s", self.agent_id)

    def update(self, message: str) -> None:
        """Update the latest progress message and fire the callback immediately.

        This does not reset the periodic timer — it only sends an out-of-band
        update so the caller can surface important milestones right away.

        Parameters
        ----------
        message:
            Human-readable status to send (e.g. "Querying knowledge base…").
        """
        self._latest_message = message
        if self.callback is not None:
            # Fire-and-forget: schedule on the running loop without awaiting.
            task = asyncio.create_task(
                self._fire(message),
                name=f"progress-update-{self.agent_id}",
            )
            _reporter_tasks.add(task)
            task.add_done_callback(_reporter_tasks.discard)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Background loop: sleep then call the callback, repeat indefinitely."""
        while True:
            await asyncio.sleep(self.interval_seconds)
            await self._fire(self._latest_message)

    async def _fire(self, message: str) -> None:
        """Invoke the callback, swallowing any exception so it never crashes."""
        if self.callback is None:
            return
        try:
            await self.callback(self.agent_id, message)
        except Exception:
            logger.exception(
                "ProgressReporter callback raised for agent %s", self.agent_id
            )
