"""Durable inbound envelopes for channel webhooks and adapter callbacks."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


class InboxStore:
    """Capture each provider message before acknowledging it or batching it."""

    def __init__(self, data_root: Path | str) -> None:
        self.path = Path(data_root) / "state" / "inbox.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS inbound_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    completed_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    terminal_message_key TEXT,
                    UNIQUE(channel_id, message_id)
                )"""
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(inbound_messages)")
            }
            for name, definition in (
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("next_attempt_at", "TEXT"),
                ("last_error", "TEXT"),
                ("terminal_message_key", "TEXT"),
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE inbound_messages ADD COLUMN {name} {definition}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_inbound_pending "
                "ON inbound_messages(status, next_attempt_at, id)"
            )

    def capture(
        self,
        channel_id: str,
        message_id: str,
        chat_id: str,
        text: str,
        metadata: dict,
    ) -> tuple[int, bool]:
        if not channel_id or not message_id or not chat_id:
            raise ValueError("channel, message, and chat IDs are required")
        encoded = json.dumps(metadata, ensure_ascii=False, default=str)
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO inbound_messages
                   (channel_id, message_id, chat_id, text, metadata_json, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    channel_id,
                    message_id,
                    chat_id,
                    text,
                    encoded,
                    datetime.now(UTC).isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT id, chat_id, text FROM inbound_messages "
                "WHERE channel_id = ? AND message_id = ?",
                (channel_id, message_id),
            ).fetchone()
            assert row is not None
            if (row[1], row[2]) != (chat_id, text):
                raise ValueError("inbound message ID reused with different sender or content")
            return int(row[0]), cur.rowcount == 1

    def received_at(self, ids: list[int]) -> str | None:
        """Earliest durable receipt for one batched turn, including after replay."""
        if not ids:
            return None
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                f"SELECT MIN(received_at) FROM inbound_messages WHERE id IN ({placeholders})",
                ids,
            ).fetchone()
            return str(row[0]) if row and row[0] else None

    def unfinished(self) -> list[dict]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM inbound_messages WHERE status = 'pending' ORDER BY id"
            ).fetchall()
        return [
            {**dict(row), "metadata": json.loads(row["metadata_json"])}
            for row in rows
        ]

    def recover_processing(self) -> None:
        """Restore claims left by a stopped single-gateway process."""
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE inbound_messages SET status = 'pending', next_attempt_at = NULL "
                "WHERE status = 'processing'"
            )
            conn.execute(
                "UPDATE inbound_messages SET status = 'terminal_notice_pending' "
                "WHERE status = 'notifying'"
            )

    def claim(self, ids: list[int]) -> bool:
        """Atomically claim one batched turn before invoking its handler."""
        if not ids:
            return True
        unique_ids = list(dict.fromkeys(ids))
        placeholders = ",".join("?" for _ in unique_ids)
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT status, next_attempt_at FROM inbound_messages "
                f"WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
            if len(rows) != len(unique_ids) or any(
                status != "pending" or (next_at is not None and next_at > now)
                for status, next_at in rows
            ):
                return False
            conn.execute(
                f"UPDATE inbound_messages SET status = 'processing', attempts = attempts + 1, "
                f"next_attempt_at = NULL WHERE id IN ({placeholders})",
                unique_ids,
            )
            return True

    def claim_due(self, limit: int = 20, new_message_grace_seconds: float = 5.0) -> list[dict]:
        """Claim due retries before putting them back in the volatile queue."""
        now = datetime.now(UTC).isoformat()
        grace_cutoff = (
            datetime.now(UTC) - timedelta(seconds=new_message_grace_seconds)
        ).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM inbound_messages WHERE status = 'pending' "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
                "AND (attempts > 0 OR received_at <= ?) "
                "ORDER BY id LIMIT ?",
                (now, grace_cutoff, limit),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE inbound_messages SET status = 'processing', "
                    "attempts = attempts + 1, next_attempt_at = NULL WHERE id = ?",
                    (row["id"],),
                )
        return [
            {**dict(row), "metadata": json.loads(row["metadata_json"]), "inbox_claimed": True}
            for row in rows
        ]

    def will_exhaust(self, ids: list[int], max_attempts: int) -> bool:
        if not ids:
            return False
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT attempts FROM inbound_messages WHERE id IN ({placeholders}) "
                "AND status = 'processing'",
                ids,
            ).fetchall()
        return len(rows) == len(ids) and all(row[0] >= max_attempts for row in rows)

    def mark_failed(
        self,
        ids: list[int],
        *,
        max_attempts: int,
        retry_delay_seconds: float,
        error: str,
        terminal_message_key: str,
    ) -> None:
        if not ids:
            return
        now = datetime.now(UTC)
        with sqlite3.connect(self.path) as conn:
            for entry_id in dict.fromkeys(ids):
                row = conn.execute(
                    "SELECT attempts FROM inbound_messages WHERE id = ? AND status = 'processing'",
                    (entry_id,),
                ).fetchone()
                if row is None:
                    continue
                exhausted = row[0] >= max_attempts
                next_at = None if exhausted else (
                    now + timedelta(seconds=retry_delay_seconds * 2 ** (row[0] - 1))
                ).isoformat()
                conn.execute(
                    "UPDATE inbound_messages SET status = ?, next_attempt_at = ?, "
                    "last_error = ?, terminal_message_key = ? "
                    "WHERE id = ? AND status = 'processing'",
                    (
                        "terminal_notice_pending" if exhausted else "pending",
                        next_at,
                        error,
                        terminal_message_key if exhausted else None,
                        entry_id,
                    ),
                )

    def claim_terminal_notices(self, limit: int = 20) -> list[dict]:
        """Claim each failed turn's fixed notification once across pollers."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM inbound_messages WHERE status = 'terminal_notice_pending' "
                "ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            keys = list(dict.fromkeys(row["terminal_message_key"] for row in rows))
            representatives = []
            for key in keys:
                group = conn.execute(
                    "SELECT * FROM inbound_messages WHERE status = 'terminal_notice_pending' "
                    "AND terminal_message_key = ? ORDER BY id",
                    (key,),
                ).fetchall()
                if not group:
                    continue
                conn.execute(
                    "UPDATE inbound_messages SET status = 'notifying' "
                    "WHERE status = 'terminal_notice_pending' AND terminal_message_key = ?",
                    (key,),
                )
                representatives.append({**dict(group[0]), "inbox_ids": [row["id"] for row in group]})
        return representatives

    def mark_dead_letter(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"UPDATE inbound_messages SET status = 'dead_letter' "
                f"WHERE id IN ({placeholders}) AND status = 'notifying'",
                ids,
            )

    def release_terminal_notice(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"UPDATE inbound_messages SET status = 'terminal_notice_pending' "
                f"WHERE id IN ({placeholders}) AND status = 'notifying'",
                ids,
            )

    def mark_completed(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"UPDATE inbound_messages SET status = 'completed', completed_at = ? "
                f"WHERE id IN ({placeholders}) AND status IN ('pending', 'processing')",
                (datetime.now(UTC).isoformat(), *ids),
            )
