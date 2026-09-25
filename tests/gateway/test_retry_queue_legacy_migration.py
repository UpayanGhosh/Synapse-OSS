from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

from sci_fi_dashboard.gateway.retry_queue import RetryQueue

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "legacy-queue-tests"


class FakeChannel:
    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        return True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []


class FakeRegistry:
    def __init__(self, channel: FakeChannel):
        self.channel = channel

    def get(self, _channel_id: str) -> FakeChannel:
        return self.channel


def test_legacy_retry_queue_schema_migrates_and_preserves_pending_row() -> None:
    data_root = TEST_DATA_ROOT / uuid4().hex
    db_path = data_root / "state" / "retry_queue.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE retry_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL,
            chat_id TEXT NOT NULL, text TEXT, media_url TEXT, media_type TEXT,
            caption TEXT, created_at TEXT NOT NULL, next_retry_at TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 6,
            last_error TEXT, status TEXT NOT NULL DEFAULT 'pending'
        )""")
        conn.execute(
            "INSERT INTO retry_queue (channel_id, chat_id, text, created_at, next_retry_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("whatsapp", "+15550000001", "legacy reminder", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )

    queue = RetryQueue(data_root)
    channel = FakeChannel()

    async def scenario() -> None:
        await queue.start(FakeRegistry(channel))
        try:
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(retry_queue)")}
                row = conn.execute("SELECT status FROM retry_queue WHERE id = 1").fetchone()
            assert {"message_key", "owner_id", "source_job_id", "source_revision", "lease_until"} <= columns
            assert row == ("pending",), "schema migration must retain pending legacy sends"
            assert await queue.flush() == 1
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT status FROM retry_queue WHERE id = 1").fetchone()
            assert row == ("accepted",)
            assert channel.sent == [("+15550000001", "legacy reminder")]
        finally:
            await queue.stop()

    asyncio.run(scenario())
