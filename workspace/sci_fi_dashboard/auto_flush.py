"""auto_flush.py — Background scanner that auto-archives idle/long sessions.

When a session has been idle for ``idle_threshold`` seconds OR has accumulated
``count_threshold`` messages it is automatically archived and ingested into
memory.db — identical to the user running /new manually.

Design decisions (Phase 3):
- Trigger semantics: OR-combined (idle OR message-count). Most robust against
  pathological cases (very active sessions that never go idle, and long-dead
  sessions that never hit the count).
- Idle threshold: 1800 s (30 min). Brief pauses don't flush; genuinely dead
  sessions flush within ~1 scan cycle after the threshold.
- Message count: 50. Matches SBS batch_threshold so ingest and profiling stay
  in sync.
- Scanner host: FastAPI lifespan background task. Flush cadence must follow
  gateway uptime, not battery/CPU state (so NOT gentle_worker_loop).
- Dedup: reuses SessionEntry.memory_flush_at — already set by manual /new.
- Empty sessions: min_messages floor (default 5) prevents trivial exchanges
  from being ingested.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Coroutine, Any

from sci_fi_dashboard.multiuser.session_store import SessionEntry, SessionStore
from sci_fi_dashboard.multiuser.transcript import transcript_path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias for the handle_new_command callable
# ---------------------------------------------------------------------------
_HandleNewFn = Callable[..., Coroutine[Any, Any, str]]


class SessionAutoFlusher:
    """Background scanner that auto-flushes idle or oversized sessions.

    Runs as an asyncio Task inside the FastAPI lifespan (Option B from the
    Phase 3 design doc). Each scan cycle iterates every known agent's
    SessionStore, checks whether any session meets the flush criteria, and
    calls ``_handle_new_command`` for matching sessions.

    Per-session exceptions are swallowed so one broken session never kills
    the scanner loop.

    Args:
        data_root:        Synapse data root (``cfg.data_root``).
        agent_ids:        Iterable of agent IDs to scan (keys of ``sbs_registry``).
        handle_new_command: Async callable with the same signature as
                          ``pipeline_helpers._handle_new_command``.
        idle_threshold:   Seconds of inactivity before a session is flushed.
        count_threshold:  Message count ceiling before a session is flushed.
        min_messages:     Sessions below this count are never auto-flushed.
        check_interval:   Seconds between scan cycles.
    """

    def __init__(
        self,
        *,
        data_root: Path,
        agent_ids: list[str],
        handle_new_command: _HandleNewFn,
        idle_threshold: float,
        count_threshold: int,
        min_messages: int,
        check_interval: float,
    ) -> None:
        self._data_root = data_root
        self._agent_ids = list(agent_ids)
        self._handle_new = handle_new_command
        self._idle_threshold = idle_threshold
        self._count_threshold = count_threshold
        self._min_messages = min_messages
        self._check_interval = check_interval

        self._stop: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background scanner loop."""
        if self._task is not None and not self._task.done():
            return  # already running
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="auto-flush-scanner")
        log.info(
            "[AutoFlush] Scanner started (idle=%ss, count=%d, interval=%ss)",
            self._idle_threshold,
            self._count_threshold,
            self._check_interval,
        )

    async def stop(self) -> None:
        """Signal the scanner to stop and await its termination."""
        self._stop.set()
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        log.info("[AutoFlush] Scanner stopped")

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main scanner loop — runs until _stop is set."""
        while not self._stop.is_set():
            try:
                n = await self._scan_once()
                if n:
                    log.info("[AutoFlush] Scan complete — flushed %d session(s)", n)
            except Exception as exc:
                log.error("[AutoFlush] Unhandled exception in scan loop: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(
                    asyncio.shield(asyncio.Event().wait()),
                    timeout=self._check_interval,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass  # normal — sleep expired or stop was set
            if self._stop.is_set():
                break

    async def _scan_once(self) -> int:
        """Scan all agents and flush qualifying sessions.

        Returns:
            Number of sessions flushed in this cycle.
        """
        flushed = 0
        for agent_id in self._agent_ids:
            store = SessionStore(agent_id=agent_id, data_root=self._data_root)
            try:
                sessions = await store.load()
            except Exception as exc:
                log.warning("[AutoFlush] Could not load sessions for agent %s: %s", agent_id, exc)
                continue

            for key, entry in sessions.items():
                try:
                    # Always re-fetch the entry from disk to avoid acting on stale state.
                    # (The user may have sent messages after we loaded the full map.)
                    fresh_entry = await store.get(key)
                    if fresh_entry is None:
                        continue
                    if await self._should_flush(agent_id, key, fresh_entry):
                        await self._flush_one(agent_id, key, fresh_entry, store)
                        flushed += 1
                except Exception as exc:
                    log.error(
                        "[AutoFlush] Exception flushing session %s/%s — skipping: %s",
                        agent_id,
                        key,
                        exc,
                        exc_info=True,
                    )
        return flushed

    # ------------------------------------------------------------------
    # Decision helpers
    # ------------------------------------------------------------------

    async def _should_flush(
        self,
        agent_id: str,
        key: str,
        entry: "SessionEntry",
    ) -> bool:
        """Return True if this session should be auto-flushed now.

        Criteria (OR-combined):
        1. Idle for >= idle_threshold seconds.
        2. Message count >= count_threshold.

        Guards:
        - min_messages: sessions below the floor are never flushed.
        - memory_flush_at dedup: if a flush happened recently (within the idle
          threshold window) we skip — prevents double-flush when /new was called
          manually just before the scanner wakes up.
        """
        now = time.time()

        # Count messages in the JSONL transcript
        msg_count = await self._count_messages(agent_id, entry)

        # Floor guard — never flush trivial sessions
        if msg_count < self._min_messages:
            return False

        # Dedup: if we already flushed this session recently, skip.
        # "Recently" = within the idle threshold window (conservative).
        if entry.memory_flush_at is not None:
            time_since_last_flush = now - entry.memory_flush_at
            if time_since_last_flush < self._idle_threshold:
                log.debug(
                    "[AutoFlush] Skipping %s/%s — flushed %.0fs ago",
                    agent_id,
                    key,
                    time_since_last_flush,
                )
                return False

        idle_seconds = now - entry.updated_at
        is_idle = idle_seconds >= self._idle_threshold
        is_long = msg_count >= self._count_threshold

        if is_idle or is_long:
            log.debug(
                "[AutoFlush] Will flush %s/%s (idle=%.0fs, msgs=%d)",
                agent_id,
                key,
                idle_seconds,
                msg_count,
            )
            return True

        return False

    async def _count_messages(self, agent_id: str, entry: "SessionEntry") -> int:
        """Count JSONL lines in the transcript file for *entry*.

        Runs synchronously inside asyncio.to_thread to avoid blocking the event loop.
        Returns 0 if the file is absent or unreadable.
        """
        path = transcript_path(entry, self._data_root, agent_id)

        def _count() -> int:
            if not path.exists():
                return 0
            try:
                return sum(1 for _ in open(path, "r", encoding="utf-8"))  # noqa: WPS515
            except OSError:
                return 0

        return await asyncio.to_thread(_count)

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def _flush_one(
        self,
        agent_id: str,
        key: str,
        entry: "SessionEntry",
        store: "SessionStore",
    ) -> None:
        """Archive and ingest one session, then record telemetry.

        Always uses hemisphere="safe" — the scanner never infers hemisphere
        from session metadata (would risk routing spicy content to cloud).
        """
        log.info("[AutoFlush] Flushing session %s/%s", agent_id, key)
        await self._handle_new(
            key,
            agent_id,
            self._data_root,
            store,
            hemisphere="safe",
        )

        # Mark memory_flush_at on the (now-rotated) NEW session entry so future
        # scans see the dedup timestamp. The old entry was deleted by _handle_new_command;
        # we write to the same key which now holds the fresh session.
        try:
            await store.update(key, {"memory_flush_at": time.time()})
        except Exception as exc:
            log.warning("[AutoFlush] Could not update memory_flush_at for %s/%s: %s", agent_id, key, exc)

        # Telemetry: record to ingest_failures with phase='auto_flush_triggered'
        try:
            from sci_fi_dashboard.db import get_db_connection  # noqa: PLC0415

            conn = get_db_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO ingest_failures
                        (session_key, agent_id, phase,
                         exception_type, exception_msg, traceback)
                    VALUES (?, ?, 'auto_flush_triggered', NULL, NULL, NULL)
                    """,
                    (key, agent_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            log.warning("[AutoFlush] Telemetry write failed (non-fatal): %s", exc)
