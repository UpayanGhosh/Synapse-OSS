from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.cron.service import CronService
from sci_fi_dashboard.gateway.durable_io import InboxStore
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
from sci_fi_dashboard.gateway.retry_queue import RetryQueue
from sci_fi_dashboard.gateway.worker import MessageWorker

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "integration-tests"


@pytest.fixture
def data_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeChannel:
    channel_id = "whatsapp"

    def __init__(self, results: list[bool]):
        self.results = list(results)
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        return self.results.pop(0) if self.results else True

    async def mark_read(self, _recipient: str, _message_id: str) -> None:
        return None

    async def send_typing(self, _recipient: str) -> None:
        return None


class FakeRegistry:
    def __init__(self, channel: FakeChannel):
        self.channel = channel

    def get(self, channel_id: str):
        return self.channel if channel_id == "whatsapp" else None


def test_inbound_reply_and_scheduled_reminder_share_restart_safe_outbox(data_root: Path) -> None:
    channel = FakeChannel([False, False, True, True])
    registry = FakeRegistry(channel)
    inbox = InboxStore(data_root)
    flood = FloodGate(batch_window_seconds=0.001)
    flood.set_inbox_store(inbox)
    messages = TaskQueue()
    delivery = RetryQueue(data_root)
    cron = CronService(
        "assistant", str(data_root), channel_registry=registry, retry_queue=delivery
    )
    reminder = cron.add(
        {
            "name": "Saturday reminder",
            "schedule": {"kind": "at", "at": "2026-09-26T09:00:00+05:30"},
            "payload": {"kind": "systemEvent", "message": "Get movie tickets"},
            "delivery": {"mode": "announce", "channel": "whatsapp", "to": "+91-person-a"},
            "owner_id": "person-a",
        }
    )

    async def pipeline(_message: str, _chat_id: str, **_kwargs) -> str:
        return "Sure, I’ll remind you Saturday."

    worker = MessageWorker(
        messages,
        pipeline,
        num_workers=1,
        channel_registry=registry,
        retry_queue=delivery,
        inbox_store=inbox,
    )

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        await messages.enqueue(
            MessageTask(
                task_id=metadata["message_id"],
                chat_id=chat_id,
                user_message=text,
                message_id=metadata["message_id"],
                channel_id=metadata["channel_id"],
                inbox_ids=metadata["inbox_ids"],
            )
        )

    flood.set_callback(on_batch)

    async def scenario() -> None:
        await cron.start()  # restores the schedule and installs its outbox validator
        await delivery.start(registry)
        try:
            assert await flood.incoming(
                "+91-person-a",
                "Remind me Saturday at 9 to get movie tickets",
                {"message_id": "wa-inbound-1", "channel_id": "whatsapp"},
            )
            await asyncio.sleep(0.01)
            inbound = await messages.dequeue()
            await worker._handle_task(inbound, 0)
            assert inbound.status.value == "completed"
            assert inbox.unfinished() == [], "outbox commit closes inbox before model work replays"

            reminder_result = await cron.run(reminder.id)
            assert reminder_result["delivery"]["status"] == "pending"
            rows = await delivery.list_pending()
            assert len(rows) == 2
            assert {row["status"] for row in rows} == {"pending"}
            assert len(channel.sent) == 2  # both initial sends failed
        finally:
            await delivery.stop()
            await cron.stop()

        # Simulate process restart: re-open inbox, cron store, and retry DB.
        recovered_inbox = InboxStore(data_root)
        assert recovered_inbox.unfinished() == []
        recovered_delivery = RetryQueue(data_root)
        recovered_cron = CronService(
            "assistant", str(data_root), channel_registry=registry, retry_queue=recovered_delivery
        )
        await recovered_cron.start()
        await recovered_delivery.start(registry)
        try:
            assert await recovered_delivery.flush() == 2
            with sqlite3.connect(recovered_delivery._db_path) as conn:
                rows_after = conn.execute(
                    "SELECT status FROM retry_queue ORDER BY id"
                ).fetchall()
            assert len(rows_after) == 2
            assert {row[0] for row in rows_after} == {"accepted"}
            assert len(channel.sent) == 4
            assert await recovered_delivery.flush() == 0
            assert len(channel.sent) == 4, "accepted results must not be resent after restart"
        finally:
            await recovered_delivery.stop()
            await recovered_cron.stop()

    asyncio.run(scenario())
