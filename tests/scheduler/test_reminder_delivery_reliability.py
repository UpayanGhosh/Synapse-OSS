from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sci_fi_dashboard.cron.service import CronService
from sci_fi_dashboard.gateway.retry_queue import RetryQueue

REMINDER_AT = "2026-09-26T09:00:00+05:30"
TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "cron-tests"


@pytest.fixture
def data_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


class FakeChannel:
    def __init__(self, results: list[bool]):
        self.results = list(results)
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, message: str) -> bool:
        self.sent.append((recipient, message))
        return self.results.pop(0) if self.results else True


class FakeRegistry:
    def __init__(self, channel: FakeChannel):
        self.channel = channel

    def get(self, channel_id: str) -> FakeChannel | None:
        return self.channel if channel_id == "whatsapp" else None


def add_reminder(service: CronService, recipient: str, message: str = "Get movie tickets"):
    return service.add(
        {
            "name": "Saturday reminder",
            "schedule": {"kind": "at", "at": REMINDER_AT},
            "payload": {"kind": "systemEvent", "message": message},
            "delivery": {"mode": "announce", "channel": "whatsapp", "to": recipient},
        }
    )


def test_tuesday_to_saturday_reminder_fires_after_due_time_and_restart(
    data_root: Path, monkeypatch
) -> None:
    due = datetime.fromisoformat(REMINDER_AT)
    assert due == datetime(2026, 9, 26, 9, tzinfo=ZoneInfo("Asia/Kolkata"))
    channel = FakeChannel([False, True])
    registry = FakeRegistry(channel)
    queue = RetryQueue(data_root)

    async def scenario() -> None:
        first = CronService(
            "assistant", str(data_root), channel_registry=registry, retry_queue=queue
        )
        original = add_reminder(first, "+91-user-a")
        await first.start()
        await queue.start(registry)
        assert channel.sent == [], "Saturday reminder must remain pending before its local due time"
        await queue.stop()
        await first.stop()

        # Simulate the host being stopped through Saturday morning. Startup must
        # catch up the explicit one-shot and preserve a failed delivery for retry.
        monkeypatch.setattr(
            "sci_fi_dashboard.cron.service.time.time",
            lambda: due.timestamp() + 5,
        )
        recovered_queue = RetryQueue(data_root)
        restarted = CronService(
            "assistant",
            str(data_root),
            channel_registry=registry,
            retry_queue=recovered_queue,
        )
        await restarted.start()
        try:
            [loaded] = restarted.list()
            assert loaded.id == original.id
            assert loaded.schedule.at == REMINDER_AT
            assert loaded.payload.message == "Get movie tickets"
            assert loaded.delivery.to == "+91-user-a"
            assert loaded.state.next_run_at_ms is None
            assert channel.sent == [("+91-user-a", "Get movie tickets")]
            assert restarted.has_pending_delivery(loaded.id)
            assert restarted.list_for_owner("whatsapp:+91-user-a") == [loaded]
        finally:
            await recovered_queue.stop()
            await restarted.stop()

        # A second restart must not regenerate the same one-shot; it should
        # recover the existing outbox entry and accept it once.
        final_queue = RetryQueue(data_root)
        final_service = CronService(
            "assistant",
            str(data_root),
            channel_registry=registry,
            retry_queue=final_queue,
        )
        await final_service.start()
        await final_queue.start(registry)
        try:
            [loaded] = final_service.list()
            assert loaded.state.next_run_at_ms is None
            assert final_service.has_pending_delivery(loaded.id)
            assert await final_queue.flush() == 1
            assert not final_service.has_pending_delivery(loaded.id)
            assert channel.sent == [
                ("+91-user-a", "Get movie tickets"),
                ("+91-user-a", "Get movie tickets"),
            ]
            with sqlite3.connect(data_root / "state" / "retry_queue.db") as conn:
                [row_count] = conn.execute(
                    "SELECT COUNT(*) FROM retry_queue WHERE source_job_id = ? AND status = 'accepted'",
                    (loaded.id,),
                ).fetchone()
            assert row_count == 1
            assert await final_queue.flush() == 0
            assert len(channel.sent) == 2
        finally:
            await final_queue.stop()
            await final_service.stop()

    asyncio.run(scenario())


def test_failed_one_shot_delivery_remains_durable_and_retryable(data_root: Path) -> None:
    channel = FakeChannel([False, True])
    registry = FakeRegistry(channel)
    queue = RetryQueue(data_root)
    service = CronService(
        "assistant", str(data_root), channel_registry=registry, retry_queue=queue
    )
    job = add_reminder(service, "+91-user-a")

    async def scenario() -> None:
        await service.start()
        await queue.start(registry)
        result = await service.run(job.id)
        assert result["delivery"]["status"] in {"queued", "pending"}, (
            "a failed WhatsApp send must be committed to the shared retry path, "
            "not treated as a completed one-shot reminder"
        )
        entry_id = result["delivery"]["outbox_id"]
        first_attempt = await queue.get_entry(entry_id)
        assert first_attempt["owner_id"] == "whatsapp:+91-user-a"
        assert first_attempt["source_job_id"] == job.id
        assert first_attempt["source_revision"] == job.revision
        assert first_attempt["status"] == "pending"
        assert len(channel.sent) == 1
        await queue.stop()
        await service.stop()
        # On restart, restore the scheduled task and its source validator before
        # the shared outbox is allowed to retry pending sends.
        restarted_queue = RetryQueue(data_root)
        restarted = CronService(
            "assistant", str(data_root), channel_registry=registry, retry_queue=restarted_queue
        )
        await restarted.start()
        await restarted_queue.start(registry)
        try:
            assert await restarted_queue.flush() == 1
            entry = await restarted_queue.get_entry(entry_id)
            assert entry["status"] == "accepted"
            assert await restarted_queue.flush() == 0
            assert len(channel.sent) == 2
        finally:
            await restarted_queue.stop()
            await restarted.stop()

    asyncio.run(scenario())


def test_two_recipients_keep_independent_reminder_destinations(data_root: Path) -> None:
    channel = FakeChannel([True, True])
    service_a = CronService("assistant-a", str(data_root), channel_registry=FakeRegistry(channel))
    service_b = CronService("assistant-b", str(data_root), channel_registry=FakeRegistry(channel))
    job_a = add_reminder(service_a, "+91-user-a", "A's reminder")
    job_b = add_reminder(service_b, "+91-user-b", "B's reminder")

    async def scenario() -> None:
        await service_a.run(job_a.id)
        await service_b.run(job_b.id)
        assert channel.sent == [
            ("+91-user-a", "A's reminder"),
            ("+91-user-b", "B's reminder"),
        ]
        await service_a.stop()
        await service_b.stop()

    asyncio.run(scenario())


def test_cancelled_reminder_cannot_be_force_run(data_root: Path) -> None:
    channel = FakeChannel([True])
    service = CronService("assistant", str(data_root), channel_registry=FakeRegistry(channel))
    job = add_reminder(service, "+91-user-a")
    assert service.remove(job.id)

    async def scenario() -> None:
        result = await service.run(job.id)
        assert result["status"] == "error"
        assert channel.sent == []
        await service.stop()

    asyncio.run(scenario())


def test_non_owner_cannot_cancel_or_change_another_users_job(data_root: Path) -> None:
    service = CronService("assistant", str(data_root))
    job_a = service.add({**{
        "schedule": {"kind": "at", "at": REMINDER_AT},
        "payload": {"kind": "systemEvent", "message": "A"},
        "delivery": {"mode": "announce", "channel": "whatsapp", "to": "+91-a"},
    }, "owner_id": "person-a"})
    job_b = service.add({
        "schedule": {"kind": "at", "at": REMINDER_AT},
        "payload": {"kind": "systemEvent", "message": "B"},
        "delivery": {"mode": "announce", "channel": "whatsapp", "to": "+91-b"},
        "owner_id": "person-b",
    })
    original_revision = job_b.revision

    assert service.list_for_owner("person-a") == [job_a]
    assert service.list_for_owner("person-b") == [job_b]
    assert service.remove_for_owner(job_b.id, "person-a") is False
    with pytest.raises(KeyError):
        service.update_for_owner(job_b.id, "person-a", {"schedule": {"kind": "at", "at": "2026-09-27T09:00:00+05:30"}})
    assert job_b.revision == original_revision
    assert job_b.schedule.at == REMINDER_AT


def test_owner_cancel_and_reschedule_invalidate_old_pending_occurrence(data_root: Path) -> None:
    channel = FakeChannel([False, True])
    registry = FakeRegistry(channel)
    queue = RetryQueue(data_root)
    service = CronService("assistant", str(data_root), channel_registry=registry, retry_queue=queue)
    job = service.add({
        "name": "Saturday reminder",
        "schedule": {"kind": "at", "at": REMINDER_AT},
        "payload": {"kind": "systemEvent", "message": "Get tickets"},
        "delivery": {"mode": "announce", "channel": "whatsapp", "to": "+91-b"},
        "owner_id": "person-b",
    })

    async def scenario() -> None:
        await service.start()
        await queue.start(registry)

        first = await service.run(job.id)
        old_entry_id = first["delivery"]["outbox_id"]
        assert (await queue.get_entry(old_entry_id))["status"] == "pending"

        assert service.remove_for_owner(job.id, "person-a") is False
        with pytest.raises(KeyError):
            service.update_for_owner(
                job.id,
                "person-a",
                {"schedule": {"kind": "at", "at": "2026-09-27T09:00:00+05:30"}},
            )

        # A's attempted mutation must leave B's pending occurrence eligible only
        # for B's current schedule; do not dispatch it as a second reminder.
        assert service.update_for_owner(
            job.id,
            "person-b",
            {"schedule": {"kind": "at", "at": "2026-09-27T09:00:00+05:30"}},
        ).revision == 2
        assert (await queue.get_entry(old_entry_id))["status"] == "cancelled"

        updated = await service.run(job.id)
        new_entry_id = updated["delivery"]["outbox_id"]
        assert new_entry_id != old_entry_id
        assert (await queue.get_entry(new_entry_id))["status"] == "accepted"
        assert await queue.flush() == 0
        assert channel.sent == [
            ("+91-b", "Get tickets"),
            ("+91-b", "Get tickets"),
        ]
        await queue.stop()
        await service.stop()

    asyncio.run(scenario())


def test_legacy_cron_row_without_owner_loads_destination_scoped_default(data_root: Path) -> None:
    store_dir = data_root / "state" / "agents" / "assistant"
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / "cron.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "legacy-job",
                        "name": "old reminder",
                        "schedule": {"kind": "at", "at": REMINDER_AT},
                        "payload": {"kind": "systemEvent", "message": "Legacy"},
                        "delivery": {"mode": "announce", "channel": "whatsapp", "to": "+91-legacy"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = CronService("assistant", str(data_root))

    async def scenario() -> None:
        await service.start()
        try:
            [job] = service.list_for_owner("whatsapp:+91-legacy")
            assert job.id == "legacy-job"
            assert job.revision == 1
        finally:
            await service.stop()

    asyncio.run(scenario())
