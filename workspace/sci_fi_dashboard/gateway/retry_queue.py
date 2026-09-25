"""
retry_queue.py — SQLite-backed persistent retry queue for failed channel messages.

When a channel.send() returns False, the message is enqueued here instead of being
lost. A background asyncio task polls every POLL_INTERVAL seconds and retries pending
messages with exponential backoff. On bridge reconnect (connection-state webhook),
flush() is called immediately to drain the queue.

Storage: ~/.synapse/state/retry_queue.db
"""

import asyncio
import contextlib
import inspect
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Retry schedule: attempt_count → delay before next retry
RETRY_DELAYS = [30, 60, 120, 300, 600]  # seconds: 30s, 1m, 2m, 5m, 10m
POLL_INTERVAL = 10  # seconds between queue checks
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1  # 6 total attempts (1 original + 5 retries)


def _utc_now() -> datetime:
    """Naive UTC for the existing SQLite timestamp format."""
    return datetime.now(UTC).replace(tzinfo=None)


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
        self._source_validator: Callable[[str, int], bool] | None = None
        self._delivery_observer = None
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
            # Existing installs already have retry_queue.db. Add outbox metadata
            # in place so failed legacy replies remain retryable after upgrade.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(retry_queue)")}
            additions = {
                "message_key": "TEXT",
                "owner_id": "TEXT",
                "source_job_id": "TEXT",
                "source_revision": "INTEGER",
                "lease_until": "TEXT",
                "group_key": "TEXT",
                "sequence": "INTEGER",
                "personal_context_json": "TEXT",
                "parent_episode_id": "TEXT",
                "personal_projected_at": "TEXT",
            }
            for name, sql_type in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE retry_queue ADD COLUMN {name} {sql_type}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retry_status ON retry_queue(status, next_retry_at)"
            )
            conn.execute("DROP INDEX IF EXISTS idx_retry_message_key")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_retry_owner_message_key "
                "ON retry_queue(owner_id, message_key) WHERE message_key IS NOT NULL"
            )
            conn.commit()

    def set_source_validator(self, validator: Callable[[str, int], bool]) -> None:
        """Check a scheduled job's current revision immediately before sending."""
        self._source_validator = validator

    def set_delivery_observer(self, observer) -> None:
        """Notify a best-effort projection only after transport state commits."""
        self._delivery_observer = observer

    def attach(self, channel_or_registry) -> None:
        """Set the transport without starting the background poller."""
        self._channel = channel_or_registry

    async def enqueue_outbound(
        self,
        *,
        channel_id: str,
        chat_id: str,
        text: str,
        message_key: str,
        owner_id: str,
        source_job_id: str | None = None,
        source_revision: int | None = None,
        group_key: str | None = None,
        sequence: int | None = None,
        personal_context_json: str | None = None,
        parent_episode_id: str | None = None,
    ) -> int:
        """Persist an outbound message before its first transport attempt.

        The stable key makes an occurrence/replayed reply idempotent within this
        local outbox. It cannot guarantee exactly-once at an external provider.
        """
        if not message_key or not channel_id or not chat_id or not owner_id:
            raise ValueError("outbound requires key, channel, recipient, and owner")
        now = _utc_now().isoformat()

        def _insert() -> int:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO retry_queue
                       (channel_id, chat_id, text, created_at, next_retry_at,
                        attempt_count, max_attempts, status, message_key, owner_id,
                        source_job_id, source_revision, group_key, sequence,
                        personal_context_json, parent_episode_id)
                       VALUES (?, ?, ?, ?, ?, 0, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        channel_id,
                        chat_id,
                        text,
                        now,
                        now,
                        MAX_ATTEMPTS,
                        message_key,
                        owner_id,
                        source_job_id,
                        source_revision,
                        group_key,
                        sequence,
                        personal_context_json,
                        parent_episode_id,
                    ),
                )
                row = conn.execute(
                    "SELECT id, channel_id, chat_id, text, source_job_id, source_revision, "
                    "group_key, sequence, personal_context_json, parent_episode_id "
                    "FROM retry_queue WHERE owner_id = ? AND message_key = ?",
                    (owner_id, message_key),
                ).fetchone()
                assert row is not None
                if row[1:] != (
                    channel_id, chat_id, text, source_job_id, source_revision, group_key,
                    sequence, personal_context_json, parent_episode_id
                ):
                    raise ValueError("outbound message key reused with different destination or content")
                return int(row[0])

        return await asyncio.get_running_loop().run_in_executor(None, _insert)

    def cancel_source(self, source_job_id: str) -> int:
        """Invalidate pending sends when a task is cancelled or changed."""
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE retry_queue SET status = 'cancelled' "
                "WHERE source_job_id = ? AND status IN ('pending', 'sending')",
                (source_job_id,),
            )
            conn.commit()
            return cur.rowcount

    def pending_for_source(self, source_job_id: str) -> bool:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM retry_queue WHERE source_job_id = ? "
                "AND status IN ('pending', 'sending') LIMIT 1",
                (source_job_id,),
            ).fetchone()
            return row is not None

    def _cancel_entry(self, entry_id: int) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE retry_queue SET status = 'cancelled', lease_until = NULL "
                "WHERE id = ? AND status IN ('pending', 'sending')",
                (entry_id,),
            )

    async def get_entry(self, entry_id: int) -> dict | None:
        def _read():
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM retry_queue WHERE id = ?", (entry_id,)
                ).fetchone()
                return dict(row) if row else None

        return await asyncio.get_running_loop().run_in_executor(None, _read)

    async def start(self, channel) -> None:
        """Start background polling task. Call from api_gateway lifespan."""
        if self._task and not self._task.done():
            return
        self._channel = channel
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[RetryQueue] Started — polling every %ds", POLL_INTERVAL)

    async def stop(self) -> None:
        """Cancel background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
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
        now = _utc_now()
        next_retry = now + timedelta(seconds=RETRY_DELAYS[0])

        def _insert():
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    """INSERT INTO retry_queue
                       (channel_id, chat_id, text, media_url, media_type, caption,
                        created_at, next_retry_at, attempt_count, max_attempts, last_error, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'pending')""",
                    (
                        channel_id,
                        chat_id,
                        text,
                        media_url,
                        media_type,
                        caption,
                        now.isoformat(),
                        next_retry.isoformat(),
                        MAX_ATTEMPTS,
                        error or None,
                    ),
                )
                conn.commit()
                return cur.lastrowid

        entry_id = await asyncio.get_running_loop().run_in_executor(None, _insert)
        logger.info("[RetryQueue] Enqueued entry %d for %s → %s", entry_id, channel_id, chat_id)
        return entry_id

    async def flush(self) -> int:
        """Force immediate retry of all pending entries. Returns count attempted."""

        def _mark_due():
            now = _utc_now().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE retry_queue SET next_retry_at = ? WHERE status = 'pending'",
                    (now,),
                )
                conn.commit()

        await asyncio.get_running_loop().run_in_executor(None, _mark_due)
        return await self._retry_due()

    async def attempt_now(self, entry_id: int) -> str:
        """Attempt a committed message once and return its durable state."""
        entry = await self.get_entry(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        if entry["status"] == "pending":
            await self._attempt_send(entry)
        current = await self.get_entry(entry_id)
        assert current is not None
        return str(current["status"])

    async def list_pending(self) -> list[dict]:
        """Return messages still awaiting channel acceptance."""

        def _query():
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM retry_queue WHERE status IN ('pending', 'sending') ORDER BY id"
                ).fetchall()
            return [dict(r) for r in rows]

        return await asyncio.get_running_loop().run_in_executor(None, _query)

    async def delete(self, entry_id: int) -> bool:
        """Delete a specific queue entry. Returns True if found and deleted."""

        def _delete():
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute("DELETE FROM retry_queue WHERE id = ?", (entry_id,))
                conn.commit()
                return cur.rowcount > 0

        return await asyncio.get_running_loop().run_in_executor(None, _delete)

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
            now = _utc_now().isoformat()
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    "SELECT * FROM retry_queue WHERE "
                    "(status = 'pending' AND next_retry_at <= ?) OR "
                    "(status = 'sending' AND lease_until <= ?) "
                    "ORDER BY id LIMIT 20",
                    (now, now),
                ).fetchall()

        rows = await asyncio.get_running_loop().run_in_executor(None, _fetch_due)
        attempted = 0

        for row in rows:
            entry = dict(row)
            attempted += 1
            await self._attempt_send(entry)

        return attempted

    async def _attempt_send(self, entry: dict) -> None:
        """Attempt to send one entry. Updates DB based on result."""
        if self._channel is None:
            return
        source_id = entry.get("source_job_id")
        revision = int(entry.get("source_revision") or 0)
        if source_id:
            if self._source_validator is None:
                # CronService may not have loaded yet on gateway startup.
                return
            if not self._source_validator(source_id, revision):
                self._cancel_entry(entry["id"])
                return

        if entry.get("group_key") is not None and entry.get("sequence") is not None:
            def _predecessors_accepted() -> bool:
                with sqlite3.connect(self._db_path) as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM retry_queue WHERE group_key = ? "
                        "AND owner_id = ? AND sequence < ? AND status != 'accepted'",
                        (entry["group_key"], entry["owner_id"], entry["sequence"]),
                    ).fetchone()
                    return bool(row and row[0] == 0)

            if not await asyncio.get_running_loop().run_in_executor(None, _predecessors_accepted):
                return

        def _claim() -> bool:
            now = _utc_now().isoformat()
            lease = (_utc_now() + timedelta(minutes=2)).isoformat()
            with sqlite3.connect(self._db_path) as conn:
                cur = conn.execute(
                    "UPDATE retry_queue SET status = 'sending', lease_until = ? "
                    "WHERE id = ? AND ((status = 'pending' AND next_retry_at <= ?) "
                    "OR (status = 'sending' AND lease_until <= ?))",
                    (lease, entry["id"], now, now),
                )
                conn.commit()
                return cur.rowcount == 1

        if not await asyncio.get_running_loop().run_in_executor(None, _claim):
            return

        if source_id and not self._source_validator(source_id, revision):
            self._cancel_entry(entry["id"])
            return

        channel = self._channel.get(entry["channel_id"]) if hasattr(self._channel, "get") else self._channel
        attempt = entry["attempt_count"] + 1
        success = False
        error = "channel unavailable" if channel is None else ""

        try:
            if channel is None:
                success = False
            elif entry.get("media_url"):
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
                        "UPDATE retry_queue SET status = 'accepted', attempt_count = ?, "
                        "lease_until = NULL WHERE id = ? AND status = 'sending'",
                        (attempt, entry["id"]),
                    )
                    logger.info(
                        "[RetryQueue] Entry %d accepted by channel on attempt %d", entry["id"], attempt
                    )
                elif attempt >= entry["max_attempts"]:
                    conn.execute(
                        "UPDATE retry_queue SET status = 'dead_letter', attempt_count = ?, "
                        "last_error = ?, lease_until = NULL WHERE id = ? AND status = 'sending'",
                        (attempt, error or "max attempts reached", entry["id"]),
                    )
                    logger.warning(
                        "[RetryQueue] Entry %d dead-lettered after %d attempts",
                        entry["id"],
                        attempt,
                    )
                else:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    next_retry = (_utc_now() + timedelta(seconds=delay)).isoformat()
                    conn.execute(
                        "UPDATE retry_queue SET status = 'pending', attempt_count = ?, "
                        "next_retry_at = ?, last_error = ?, lease_until = NULL "
                        "WHERE id = ? AND status = 'sending'",
                        (attempt, next_retry, error or None, entry["id"]),
                    )
                conn.commit()

        await asyncio.get_running_loop().run_in_executor(None, _update, success, attempt, error)
        if self._delivery_observer is not None and entry.get("personal_context_json"):
            current = await self.get_entry(entry["id"])
            if current is not None and current["status"] == "accepted":
                try:
                    observed = self._delivery_observer(current)
                    if inspect.isawaitable(observed):
                        await observed
                except Exception:
                    logger.warning("Assistant memory projection deferred; accepted send is durable")
