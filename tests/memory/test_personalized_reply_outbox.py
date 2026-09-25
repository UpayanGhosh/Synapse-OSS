from __future__ import annotations

import asyncio
import inspect
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
from sci_fi_dashboard.gateway.retry_queue import RetryQueue
from sci_fi_dashboard.gateway.worker import MessageWorker
from sci_fi_dashboard.personal_memory import (
    PersonalizedReply,
    PersonalMemoryStore,
    PersonMemoryContext,
)
from sci_fi_dashboard.personal_memory_service import PersonalMemoryService

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "personalized-outbox"


@pytest.fixture
def data_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeChannel:
    channel_id = "whatsapp"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.accepted = True
        self.sent_event = asyncio.Event()

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        self.sent_event.set()
        return self.accepted

    async def mark_read(self, _recipient: str, _message_id: str) -> None:
        return None

    async def send_typing(self, _recipient: str) -> None:
        return None


class FakeRegistry:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get(self, channel_id: str) -> FakeChannel | None:
        return self.channel if channel_id == "whatsapp" else None


async def _wait_for_outbox_status(retry_queue: RetryQueue, message_key: str, expected: str) -> None:
    deadline = asyncio.get_running_loop().time() + 0.5
    while asyncio.get_running_loop().time() < deadline:
        with sqlite3.connect(retry_queue._db_path) as conn:
            row = conn.execute(
                "SELECT status FROM retry_queue WHERE message_key = ?", (message_key,)
            ).fetchone()
        if row and row[0] == expected:
            return
        await asyncio.sleep(0.01)
    assert row == (expected,), f"outbox {message_key} did not reach {expected}: {row}"


def test_accepted_personalized_reply_is_recallable_once_from_shared_outbox(data_root: Path) -> None:
    store = PersonalMemoryStore(data_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    parent_id = store.capture_episode(
        context,
        source_message_id="user-episode",
        content="The haunted toaster is our new office mascot.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    service = PersonalMemoryService(store)
    reply_text = "Ha, the haunted toaster gets a tiny desk now."
    reply = PersonalizedReply(reply_text, context, parent_id)
    channel = FakeChannel()
    registry = FakeRegistry(channel)
    retry_queue = RetryQueue(data_root)

    async def processor(_message: str, _chat_id: str, **_kwargs):
        return reply

    worker_kwargs = {
        "num_workers": 1,
        "channel_registry": registry,
        "retry_queue": retry_queue,
    }
    if "personal_memory_service" in inspect.signature(MessageWorker.__init__).parameters:
        worker_kwargs["personal_memory_service"] = service
    queue = TaskQueue()
    worker = MessageWorker(queue, processor, **worker_kwargs)

    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            await queue.enqueue(
                MessageTask(
                    task_id="reply-task-1",
                    chat_id="+15550000007",
                    user_message="Continue our joke.",
                    channel_id="whatsapp",
                )
            )
            await asyncio.wait_for(channel.sent_event.wait(), timeout=0.5)
            await _wait_for_outbox_status(retry_queue, "reply:reply-task-1:0", "accepted")
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())

    recalled = store.recall(context, "haunted toaster tiny desk", limit=5)
    assistant = [episode for episode in recalled if episode.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == reply_text
    assert assistant[0].parent_episode_id == parent_id
    assert assistant[0].delivery_state == "accepted"
    assert channel.sent == [("+15550000007", reply_text)]
    with sqlite3.connect(retry_queue._db_path) as conn:
        [row_count] = conn.execute(
            "SELECT COUNT(*) FROM retry_queue WHERE message_key LIKE 'reply:reply-task-1:%'"
        ).fetchone()
    assert row_count == 1


def test_accepted_outbox_delivery_repairs_memory_projection_after_restart(
    data_root: Path,
) -> None:
    store = PersonalMemoryStore(data_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    parent_id = store.capture_episode(
        context,
        source_message_id="user-joke-parent",
        content="The haunted toaster is still our office mascot.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    service = PersonalMemoryService(store)
    reply_text = "The haunted toaster now has a tiny name badge."
    reply = PersonalizedReply(reply_text, context, parent_id)
    channel = FakeChannel()
    registry = FakeRegistry(channel)
    retry_queue = RetryQueue(data_root)

    def lose_projection_callback(*_args, **_kwargs) -> None:
        raise RuntimeError("synthetic crash after channel acceptance")

    # Simulate a process interruption at the accepted-outbox -> memory projection
    # boundary. RetryQueue's durable accepted state must be enough to reconcile.
    if hasattr(service, "mark_assistant_delivery"):
        service.mark_assistant_delivery = lose_projection_callback

    async def processor(_message: str, _chat_id: str, **_kwargs):
        return reply

    worker_kwargs = {
        "num_workers": 1,
        "channel_registry": registry,
        "retry_queue": retry_queue,
    }
    if "personal_memory_service" in inspect.signature(MessageWorker.__init__).parameters:
        worker_kwargs["personal_memory_service"] = service
    queue = TaskQueue()
    worker = MessageWorker(queue, processor, **worker_kwargs)

    async def deliver_once() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            await queue.enqueue(
                MessageTask(
                    task_id="reply-task-crash-window",
                    chat_id="+15550000008",
                    user_message="Continue our joke.",
                    channel_id="whatsapp",
                )
            )
            await asyncio.wait_for(channel.sent_event.wait(), timeout=0.5)
            await _wait_for_outbox_status(
                retry_queue,
                "reply:reply-task-crash-window:0",
                "accepted",
            )
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(deliver_once())

    restarted = PersonalMemoryService(store, retry_queue=retry_queue)
    asyncio.run(restarted.process_pending_once(limit=8))

    recalled = store.recall(context, "haunted toaster tiny name badge", limit=5)
    assistant = [episode for episode in recalled if episode.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == reply_text
    assert assistant[0].parent_episode_id == parent_id
    assert assistant[0].delivery_state == "accepted"
    assert channel.sent == [("+15550000008", reply_text)]
    with sqlite3.connect(retry_queue._db_path) as conn:
        [row_count] = conn.execute(
            "SELECT COUNT(*) FROM retry_queue WHERE message_key LIKE 'reply:reply-task-crash-window:%'"
        ).fetchone()
        [status] = conn.execute(
            "SELECT status FROM retry_queue WHERE message_key LIKE 'reply:reply-task-crash-window:%'"
        ).fetchone()
    assert (row_count, status) == (1, "accepted")


def test_pending_reply_stays_out_of_memory_until_retry_is_accepted(data_root: Path) -> None:
    store = PersonalMemoryStore(data_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    parent_id = store.capture_episode(
        context,
        source_message_id="user-pending-joke",
        content="The haunted toaster is our office mascot again.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    service = PersonalMemoryService(store)
    reply_text = "The haunted toaster deserves a tiny crown."
    reply = PersonalizedReply(reply_text, context, parent_id)
    channel = FakeChannel()
    channel.accepted = False
    registry = FakeRegistry(channel)
    retry_queue = RetryQueue(data_root)

    async def processor(_message: str, _chat_id: str, **_kwargs):
        return reply

    worker_kwargs = {
        "num_workers": 1,
        "channel_registry": registry,
        "retry_queue": retry_queue,
        "personal_memory_service": service,
    }
    if "personal_memory_service" not in inspect.signature(MessageWorker.__init__).parameters:
        worker_kwargs.pop("personal_memory_service")
    queue = TaskQueue()
    worker = MessageWorker(queue, processor, **worker_kwargs)

    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            await queue.enqueue(
                MessageTask(
                    task_id="reply-task-pending",
                    chat_id="+15550000009",
                    user_message="Continue the joke.",
                    channel_id="whatsapp",
                )
            )
            await asyncio.wait_for(channel.sent_event.wait(), timeout=0.5)
            await _wait_for_outbox_status(retry_queue, "reply:reply-task-pending:0", "pending")
            assert not [
                item for item in store.recall(context, "haunted toaster tiny crown", limit=5)
                if item.role == "assistant"
            ]

            channel.accepted = True
            await retry_queue.flush()
            await _wait_for_outbox_status(retry_queue, "reply:reply-task-pending:0", "accepted")
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())

    assistant = [
        item for item in store.recall(context, "haunted toaster tiny crown", limit=5)
        if item.role == "assistant"
    ]
    assert len(assistant) == 1
    assert assistant[0].content == reply_text
    assert assistant[0].parent_episode_id == parent_id
    assert assistant[0].delivery_state == "accepted"
    assert channel.sent == [
        ("+15550000009", reply_text),
        ("+15550000009", reply_text),
    ]
