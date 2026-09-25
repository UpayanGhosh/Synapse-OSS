from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.gateway.retry_queue import RetryQueue

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "outbox-tests"


@pytest.fixture
def data_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeChannel:
    def __init__(self, results: list[bool | Exception]):
        self.results = list(results)
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        result = self.results.pop(0) if self.results else True
        if isinstance(result, Exception):
            raise result
        return result


class FakeRegistry:
    def __init__(self, channel: FakeChannel | None):
        self.channel = channel

    def get(self, _channel_id: str) -> FakeChannel | None:
        return self.channel


def enqueue(queue: RetryQueue, *, owner: str, recipient: str, key: str, job: str) -> int:
    return asyncio.run(
        queue.enqueue_outbound(
            channel_id="whatsapp",
            chat_id=recipient,
            text=f"Reminder for {owner}",
            message_key=key,
            owner_id=owner,
            source_job_id=job,
            source_revision=1,
        )
    )


def test_failed_send_recovers_after_restart_with_one_accepted_delivery(data_root: Path) -> None:
    channel = FakeChannel([False, True])
    queue = RetryQueue(data_root)
    queue.set_source_validator(lambda _job_id, _revision: True)
    entry_id = enqueue(queue, owner="person-a", recipient="+91-a", key="task-a:1", job="task-a")

    async def scenario() -> None:
        await queue.start(FakeRegistry(channel))
        assert await queue.attempt_now(entry_id) == "pending"
        [persisted] = await queue.list_pending()
        assert persisted["owner_id"] == "person-a"
        assert persisted["source_job_id"] == "task-a"
        assert persisted["message_key"] == "task-a:1"
        await queue.stop()

        restarted = RetryQueue(data_root)
        restarted.set_source_validator(lambda _job_id, _revision: True)
        await restarted.start(FakeRegistry(channel))
        try:
            assert await restarted.flush() == 1
            entry = await restarted.get_entry(entry_id)
            assert entry["status"] == "accepted"
            assert channel.sent == [
                ("+91-a", "Reminder for person-a"),
                ("+91-a", "Reminder for person-a"),
            ]
            assert await restarted.flush() == 0, "accepted delivery must not be replayed"
            assert len(channel.sent) == 2
        finally:
            await restarted.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [False, RuntimeError("synthetic channel failure")])
def test_send_failure_forms_stay_retryable(data_root: Path, failure: bool | Exception) -> None:
    channel = FakeChannel([failure, True])
    queue = RetryQueue(data_root)
    queue.set_source_validator(lambda _job_id, _revision: True)
    entry_id = enqueue(queue, owner="person-a", recipient="+91-a", key="task-a:2", job="task-a")

    async def scenario() -> None:
        await queue.start(FakeRegistry(channel))
        try:
            assert await queue.attempt_now(entry_id) == "pending"
            assert await queue.flush() == 1
            assert (await queue.get_entry(entry_id))["status"] == "accepted"
            assert len(channel.sent) == 2
        finally:
            await queue.stop()

    asyncio.run(scenario())


def test_unavailable_channel_remains_pending_then_recovers(data_root: Path) -> None:
    channel = FakeChannel([True])
    queue = RetryQueue(data_root)
    queue.set_source_validator(lambda _job_id, _revision: True)
    entry_id = enqueue(queue, owner="person-a", recipient="+91-a", key="task-a:3", job="task-a")

    async def scenario() -> None:
        await queue.start(FakeRegistry(None))
        assert await queue.attempt_now(entry_id) == "pending"
        assert (await queue.get_entry(entry_id))["attempt_count"] == 1
        await queue.stop()
        await queue.start(FakeRegistry(channel))
        try:
            assert await queue.flush() == 1
            assert (await queue.get_entry(entry_id))["status"] == "accepted"
            assert channel.sent == [("+91-a", "Reminder for person-a")]
        finally:
            await queue.stop()

    asyncio.run(scenario())


def test_cancel_or_revision_change_invalidates_pending_delivery(data_root: Path) -> None:
    channel = FakeChannel([True, True])
    queue = RetryQueue(data_root)
    cancelled_id = enqueue(
        queue, owner="person-a", recipient="+91-a", key="cancelled:1", job="cancelled"
    )
    changed_id = enqueue(queue, owner="person-a", recipient="+91-a", key="changed:1", job="changed")
    queue.set_source_validator(lambda job_id, revision: job_id == "changed" and revision == 2)

    async def scenario() -> None:
        assert queue.cancel_source("cancelled") == 1
        await queue.start(FakeRegistry(channel))
        try:
            assert await queue.flush() == 1
            assert (await queue.get_entry(cancelled_id))["status"] == "cancelled"
            assert (await queue.get_entry(changed_id))["status"] == "cancelled"
            assert channel.sent == []
        finally:
            await queue.stop()

    asyncio.run(scenario())


def test_stable_key_deduplicates_replay_and_is_scoped_to_owner(data_root: Path) -> None:
    queue = RetryQueue(data_root)
    first = enqueue(queue, owner="person-a", recipient="+91-a", key="reminder:1", job="job-a")
    replay = enqueue(queue, owner="person-a", recipient="+91-a", key="reminder:1", job="job-a")
    other_owner = enqueue(
        queue, owner="person-b", recipient="+91-b", key="reminder:1", job="job-b"
    )

    assert replay == first
    assert other_owner != first, "one person's idempotency key must not alias another person's task"
