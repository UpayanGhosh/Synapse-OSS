"""
retry_queue.py — SQLite-backed persistent retry queue for failed channel messages.

When a channel.send() returns False, the message is enqueued here instead of being
lost. A background asyncio task polls every POLL_INTERVAL seconds and retries pending
messages with exponential backoff. On bridge reconnect (connection-state webhook),
flush() is called immediately to drain the queue.

Storage: ~/.synapse/state/retry_queue.db
"""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Retry schedule: attempt_count → delay before next retry
RETRY_DELAYS = [30, 60, 120, 300, 600]  # seconds: 30s, 1m, 2m, 5m, 10m
POLL_INTERVAL = 10  # seconds between queue checks
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1  # 6 total attempts (1 original + 5 retries)


class RetryQueue:
    """
    Persistent retry queue for outbound channel messages.

    Usage:
        queue = RetryQueue(data_root)
        await queue.start(channel)   # starts background polling task
        await queue.stop()           # cancels polling task
        await queue.enqueue(channel_id, chat_id, text)
        await queue.flush()          # force immediate retry of all pending
    """

    def __init__(self, data_root: Path | str) -> None:
        self._db_path = Path(data_root) / "state" / "retry_queue.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._channel = None  # injected via start()
        self._task: asyncio.Task | None = None
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    text TEXT,
                    media_url TEXT,
                    media_type TEXT,
                    caption TEXT,
                    created_at TEXT NOT NULL,
                    next_retry_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 6,
                    last_error TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retry_status ON retry_queue(status, next_retry_at)"
            )
            conn.commit()

    async def start(self, channel) -> None:
        """Start background polling task. Call from api_gateway lifespan."""
        self._channel = channel
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[RetryQueue] Started — polling every %ds", POLL_INTERVAL)

    async def stop(self) -> None:
        """Cancel background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[RetryQueue] Stopped")

    async def enqueue(
        self,
        channel_id: str,
        chat_id: str,
        text: str = "",
        media_url: str = "",
        media_type: str = "",
        caption: str = "",
        error: str = "",
    ) -> int:
        """Add a failed message to the retry queue. Returns the new entry id."""
        now = datetime.utcnow()
        next_retry = now + timedelta(seconds=RETRY_DELAYS[0])

        def _insert():
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    """INSERT INTO retry_queue
                       (channel_id, chat_id, text, media_url, media_type, caption,
                        created_at, next_retry_at, attempt_count, max_attempts, last_error, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'pending')""",
                    (
                        channel_id, chat_id, text, media_url, media_type, caption,
                        now.isoformat(), next_retry.isoformat(),
                        MAX_ATTEMPTS, error or None,
                    ),
                )
                conn.commit()
                return cur.lastrowid

        entry_id = await asyncio.get_event_loop().run_in_executor(None, _insert)
        logger.info("[RetryQueue] Enqueued entry %d for %s → %s", entry_id, channel_id, chat_id)
        return entry_id

    async def flush(self) -> int:
        """Force immediate retry of all pending entries. Returns count attempted."""
        def _mark_due():
            now = datetime.utcnow().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE retry_queue SET next_retry_at = ? WHERE status = 'pending'",
                    (now,),
                )
                conn.commit()

        await asyncio.get_event_loop().run_in_executor(None, _mark_due)
        return await self._retry_due()

    async def list_pending(self) -> list[dict]:
        """Return all non-dead-letter entries as dicts."""
        def _query():
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM retry_queue WHERE status != 'dead_letter' ORDER BY id"
                ).fetchall()
            return [dict(r) for r in rows]

        return await asyncio.get_event_loop().run_in_executor(None, _query)

    async def delete(self, entry_id: int) -> bool:
        """Delete a specific queue entry. Returns True if found and deleted."""
        def _delete():
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    "DELETE FROM retry_queue WHERE id = ?", (entry_id,)
                )
                conn.commit()
                return cur.rowcount > 0

        return await asyncio.get_event_loop().run_in_executor(None, _delete)

    async def _poll_loop(self) -> None:
        """Background task: retry due messages every POLL_INTERVAL seconds."""
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                await self._retry_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[RetryQueue] Poll error: %s", exc)

    async def _retry_due(self) -> int:
        """Retry all entries whose next_retry_at is past. Returns count attempted."""
        if self._channel is None:
            return 0

        def _fetch_due():
            now = datetime.utcnow().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    "SELECT * FROM retry_queue WHERE status = 'pending' AND next_retry_at <= ? "
                    "ORDER BY id LIMIT 20",
                    (now,),
                ).fetchall()

        rows = await asyncio.get_event_loop().run_in_executor(None, _fetch_due)
        attempted = 0

        for row in rows:
            entry = dict(row)
            attempted += 1
            await self._attempt_send(entry)

        return attempted

    async def _attempt_send(self, entry: dict) -> None:
        """Attempt to send one entry. Updates DB based on result."""
        channel = self._channel
        attempt = entry["attempt_count"] + 1
        success = False
        error = ""

        try:
            if entry.get("media_url"):
                success = await channel.send_media(
                    entry["chat_id"],
                    entry["media_url"],
                    entry.get("media_type", "image"),
                    entry.get("caption", ""),
                )
            else:
                success = await channel.send(entry["chat_id"], entry["text"] or "")
        except Exception as exc:
            error = str(exc)

        def _update(success, attempt, error):
            with sqlite3.connect(self._db_path) as conn:
                if success:
                    conn.execute(
                        "UPDATE retry_queue SET status = 'delivered', attempt_count = ? WHERE id = ?",
                        (attempt, entry["id"]),
                    )
                    logger.info("[RetryQueue] Entry %d delivered on attempt %d", entry["id"], attempt)
                elif attempt >= entry["max_attempts"]:
                    conn.execute(
                        "UPDATE retry_queue SET status = 'dead_letter', attempt_count = ?, "
                        "last_error = ? WHERE id = ?",
                        (attempt, error or "max attempts reached", entry["id"]),
                    )
                    logger.warning(
                        "[RetryQueue] Entry %d dead-lettered after %d attempts", entry["id"], attempt
                    )
                else:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    next_retry = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
                    conn.execute(
                        "UPDATE retry_queue SET status = 'pending', attempt_count = ?, "
                        "next_retry_at = ?, last_error = ? WHERE id = ?",
                        (attempt, next_retry, error or None, entry["id"]),
                    )
                conn.commit()

        await asyncio.get_event_loop().run_in_executor(None, _update, success, attempt, error)
