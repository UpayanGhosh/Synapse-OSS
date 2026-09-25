from __future__ import annotations

import asyncio
import contextlib
import inspect
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.gateway.durable_io import InboxStore
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
from sci_fi_dashboard.gateway.retry_queue import RetryQueue
from sci_fi_dashboard.gateway.worker import MessageWorker

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "live-worker-retry"


@pytest.fixture
def data_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeChannel:
    channel_id = "whatsapp"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        return True

    async def mark_read(self, _recipient: str, _message_id: str) -> None:
        return None

    async def send_typing(self, _recipient: str) -> None:
        return None


class FakeRegistry:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get(self, channel_id: str) -> FakeChannel | None:
        return self.channel if channel_id == "whatsapp" else None


def _status(store: InboxStore, entry_id: int) -> tuple[str, int]:
    with sqlite3.connect(store.path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(inbound_messages)")}
        attempt_expr = "attempts" if "attempts" in columns else "0"
        row = conn.execute(
            f"SELECT status, {attempt_expr} FROM inbound_messages WHERE id = ?", (entry_id,)
        ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


def _entry_id(store: InboxStore, message_id: str) -> int:
    with sqlite3.connect(store.path) as conn:
        row = conn.execute(
            "SELECT id FROM inbound_messages WHERE channel_id = 'whatsapp' AND message_id = ?",
            (message_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


async def _wait_for_status(store: InboxStore, entry_id: int, expected: str) -> tuple[str, int]:
    deadline = asyncio.get_running_loop().time() + 0.4
    while asyncio.get_running_loop().time() < deadline:
        state = _status(store, entry_id)
        if state[0] == expected:
            return state
        await asyncio.sleep(0.01)
    return _status(store, entry_id)


async def _wait_for_send(channel: FakeChannel, expected: tuple[str, str]) -> None:
    deadline = asyncio.get_running_loop().time() + 0.4
    while asyncio.get_running_loop().time() < deadline:
        if expected in channel.sent:
            return
        await asyncio.sleep(0.01)


async def _wait_for_outbox_status(
    retry_queue: RetryQueue, message_key: str, expected: str
) -> tuple[str, str] | None:
    deadline = asyncio.get_running_loop().time() + 0.5
    row = None
    while asyncio.get_running_loop().time() < deadline:
        with sqlite3.connect(retry_queue._db_path) as conn:
            row = conn.execute(
                "SELECT status,text FROM retry_queue WHERE message_key=?", (message_key,)
            ).fetchone()
        if row and row[0] == expected:
            return str(row[0]), str(row[1])
        await asyncio.sleep(0.01)
    return None if row is None else (str(row[0]), str(row[1]))


class OrderedInboxStore(InboxStore):
    def __init__(self, data_root: Path) -> None:
        super().__init__(data_root)
        self.outbox_path = Path(data_root) / "state" / "retry_queue.db"
        self.completed_after_outbox_commit = False

    def mark_completed(self, ids: list[int]) -> None:
        with sqlite3.connect(self.outbox_path) as conn:
            [count] = conn.execute("SELECT COUNT(*) FROM retry_queue").fetchone()
        self.completed_after_outbox_commit = count > 0
        super().mark_completed(ids)


def _task_for_entry(entry_id: int, message_id: str, chat_id: str):
    kwargs = {
        "task_id": message_id,
        "chat_id": chat_id,
        "user_message": "captured inbound text",
        "message_id": message_id,
        "channel_id": "whatsapp",
        "inbox_ids": [entry_id],
    }
    if "inbox_claimed" in inspect.signature(MessageTask).parameters:
        kwargs["inbox_claimed"] = False
    return MessageTask(**kwargs)


def _start_live_stack(data_root: Path, processor, channel: FakeChannel, num_workers: int = 1):
    inbox = OrderedInboxStore(data_root)
    flood = FloodGate(batch_window_seconds=0.001)
    flood.set_inbox_store(inbox)
    queue = TaskQueue()
    retry_queue = RetryQueue(data_root)
    registry = FakeRegistry(channel)

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        kwargs = {
            "task_id": metadata["message_id"],
            "chat_id": chat_id,
            "user_message": text,
            "message_id": metadata["message_id"],
            "channel_id": metadata["channel_id"],
            "inbox_ids": metadata["inbox_ids"],
        }
        if "inbox_claimed" in inspect.signature(MessageTask).parameters:
            kwargs["inbox_claimed"] = bool(metadata.get("inbox_claimed", False))
        await queue.enqueue(MessageTask(**kwargs))

    flood.set_callback(on_batch)
    worker_kwargs = {
        "num_workers": num_workers,
        "channel_registry": registry,
        "retry_queue": retry_queue,
        "inbox_store": inbox,
    }
    supported = inspect.signature(MessageWorker.__init__).parameters
    if "inbox_replay" in supported:
        worker_kwargs.update(
            inbox_replay=flood.replay,
            max_processing_attempts=2,
            processing_retry_delay_seconds=0.01,
            inbox_poll_seconds=0.01,
        )
    worker = MessageWorker(
        queue,
        processor,
        **worker_kwargs,
    )
    return inbox, flood, queue, retry_queue, registry, worker


def test_transient_processing_failure_retries_while_gateway_stays_running(data_root: Path) -> None:
    attempts = 0

    async def processor(_message: str, _chat_id: str, **_kwargs) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic temporary model failure")
        return "Done — I saved that reminder."

    channel = FakeChannel()
    inbox, flood, _queue, retry_queue, registry, worker = _start_live_stack(
        data_root, processor, channel
    )
    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            assert await flood.incoming(
                "+15550000001",
                "captured inbound text",
                {"message_id": "transient-message", "channel_id": "whatsapp"},
            )
            entry_id = _entry_id(inbox, "transient-message")
            state = await _wait_for_status(inbox, entry_id, "completed")
            assert state == ("completed", 2)
            assert attempts == 2
            assert inbox.completed_after_outbox_commit
            outbox_state = await _wait_for_outbox_status(
                retry_queue, "reply:transient-message:0", "accepted"
            )
            assert outbox_state is not None and outbox_state[0] == "accepted"
            await _wait_for_send(channel, ("+15550000001", "Done — I saved that reminder."))
            with sqlite3.connect(retry_queue._db_path) as conn:
                [row] = conn.execute(
                    "SELECT status, text FROM retry_queue WHERE owner_id = ?",
                    ("whatsapp:+15550000001",),
                ).fetchall()
            assert row == ("accepted", "Done — I saved that reminder.")
            assert channel.sent == [("+15550000001", "Done — I saved that reminder.")]
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())


def test_permanent_processing_failure_dead_letters_and_notifies_once(data_root: Path) -> None:
    attempts = 0

    async def processor(_message: str, _chat_id: str, **_kwargs) -> str:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("synthetic permanent processor failure")

    channel = FakeChannel()
    inbox, flood, queue, retry_queue, registry, worker = _start_live_stack(
        data_root, processor, channel
    )
    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            assert await flood.incoming(
                "+15550000002",
                "captured inbound text",
                {"message_id": "permanent-message", "channel_id": "whatsapp"},
            )
            entry_id = _entry_id(inbox, "permanent-message")
            state = await _wait_for_status(inbox, entry_id, "dead_letter")
            assert state == ("dead_letter", 2)
            await asyncio.sleep(0.05)
            assert attempts == 2, "dead-lettered inbox work must not retry forever"
            with sqlite3.connect(retry_queue._db_path) as conn:
                [notice_count] = conn.execute(
                    "SELECT COUNT(*) FROM retry_queue WHERE owner_id = ?",
                    ("whatsapp:+15550000002",),
                ).fetchone()
            assert notice_count == 1, "terminal user notice must be durably enqueued once"
            assert len(channel.sent) == 1
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())


def test_duplicate_claim_cannot_run_pipeline_concurrently(data_root: Path) -> None:
    attempts = 0
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    duplicate_started = asyncio.Event()

    async def processor(_message: str, _chat_id: str, **_kwargs) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_started.set()
            await release_first.wait()
        else:
            duplicate_started.set()
        return "Handled once."

    channel = FakeChannel()
    inbox, _flood, queue, retry_queue, registry, worker = _start_live_stack(
        data_root, processor, channel, num_workers=2
    )
    entry_id, _ = inbox.capture(
        "whatsapp", "same-provider-message", "+15550000003", "captured inbound text", {}
    )

    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            await queue.enqueue(_task_for_entry(entry_id, "same-provider-message", "+15550000003"))
            await asyncio.wait_for(first_started.wait(), timeout=1)
            await queue.enqueue(_task_for_entry(entry_id, "same-provider-message", "+15550000003"))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(duplicate_started.wait(), timeout=0.1)
            assert not duplicate_started.is_set()
            assert attempts == 1
            release_first.set()
            assert await _wait_for_status(inbox, entry_id, "completed") == ("completed", 1)
            assert channel.sent == [("+15550000003", "Handled once.")]
        finally:
            release_first.set()
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())


def test_replay_callback_failure_releases_claim_for_live_retry(data_root: Path) -> None:
    callback_attempts = 0
    processor_attempts = 0
    channel = FakeChannel()
    inbox = OrderedInboxStore(data_root)
    flood = FloodGate(batch_window_seconds=0.001)
    flood.set_inbox_store(inbox)
    queue = TaskQueue()
    retry_queue = RetryQueue(data_root)
    registry = FakeRegistry(channel)

    async def processor(_message: str, _chat_id: str, **_kwargs) -> str:
        nonlocal processor_attempts
        processor_attempts += 1
        return "Processed after replay recovery."

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        nonlocal callback_attempts
        callback_attempts += 1
        if callback_attempts == 1:
            raise RuntimeError("synthetic transient on_batch_ready failure")
        task_kwargs = {
            "task_id": metadata["message_id"],
            "chat_id": chat_id,
            "user_message": text,
            "message_id": metadata["message_id"],
            "channel_id": metadata["channel_id"],
            "inbox_ids": metadata["inbox_ids"],
        }
        if "inbox_claimed" in inspect.signature(MessageTask).parameters:
            task_kwargs["inbox_claimed"] = bool(metadata.get("inbox_claimed", False))
        await queue.enqueue(MessageTask(**task_kwargs))

    flood.set_callback(on_batch)
    worker = MessageWorker(
        queue,
        processor,
        num_workers=1,
        channel_registry=registry,
        retry_queue=retry_queue,
        inbox_store=inbox,
        inbox_replay=flood.replay,
        max_processing_attempts=2,
        processing_retry_delay_seconds=0.01,
        inbox_poll_seconds=0.01,
    )
    entry_id, _ = inbox.capture(
        "whatsapp", "callback-failure-message", "+15550000004", "captured inbound text", {}
    )
    with sqlite3.connect(inbox.path) as conn:
        old = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE inbound_messages SET received_at = ? WHERE id = ?", (old, entry_id))

    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            state = await _wait_for_status(inbox, entry_id, "completed")
            assert state == ("completed", 2)
            assert callback_attempts == 2
            assert processor_attempts == 1
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())


def test_delayed_inbox_replay_preserves_original_receipt_time(data_root: Path) -> None:
    source_times: list[datetime | str | None] = []

    async def processor(
        _message: str,
        _chat_id: str,
        *,
        source_received_at: datetime | str | None = None,
        **_kwargs,
    ) -> str:
        source_times.append(source_received_at)
        return "I saved that for you."

    channel = FakeChannel()
    inbox, _flood, queue, retry_queue, registry, worker = _start_live_stack(
        data_root, processor, channel
    )
    entry_id, _ = inbox.capture(
        "whatsapp", "delayed-reminder", "+15550000005", "Remind me Saturday morning.", {}
    )
    original_receipt = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)
    with sqlite3.connect(inbox.path) as conn:
        conn.execute(
            "UPDATE inbound_messages SET received_at = ? WHERE id = ?",
            (original_receipt.isoformat(), entry_id),
        )
    # Exercise the same persisted row after downtime without starting the
    # background replay poller, which would claim it concurrently with this task.
    worker.inbox_replay = None

    async def scenario() -> None:
        await retry_queue.start(registry)
        await worker.start()
        try:
            await queue.enqueue(
                _task_for_entry(entry_id, "delayed-reminder", "+15550000005")
            )
            state = await _wait_for_status(inbox, entry_id, "completed")
            assert state == ("completed", 1)
            assert source_times, "replayed turn must reach the pipeline"
            seen = source_times[0]
            if isinstance(seen, str):
                seen = datetime.fromisoformat(seen)
            assert seen == original_receipt
        finally:
            await worker.stop()
            await retry_queue.stop()

    asyncio.run(scenario())
