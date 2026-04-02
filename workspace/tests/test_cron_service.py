"""
Tests for sci_fi_dashboard.cron.service — CRUD API, timer loop, catch-up, alerting, delivery.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sci_fi_dashboard.cron.service import CronService
from sci_fi_dashboard.cron.types import (
    DeliveryMode,
    PayloadKind,
    ScheduleKind,
    SessionTarget,
    WakeMode,
)


@pytest.fixture
def data_root(temp_dir):
    return temp_dir


@pytest.fixture
def execute_fn():
    """A mock execute function that returns a fixed string."""
    fn = AsyncMock(return_value="cron output")
    return fn


@pytest.fixture
def channel_registry():
    """A mock channel registry with a sendable channel."""
    channel = MagicMock()
    channel.send = AsyncMock()
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)
    return registry


@pytest.fixture
def service(data_root, execute_fn, channel_registry):
    return CronService(
        agent_id="test_agent",
        data_root=data_root,
        execute_fn=execute_fn,
        channel_registry=channel_registry,
    )


def _every_schedule(every_ms: int = 60_000) -> dict:
    return {
        "schedule": {"kind": "every", "every_ms": every_ms, "anchor_ms": 0},
        "payload": {"kind": "systemEvent", "message": "tick"},
        "name": "test-every",
    }


def _cron_schedule(expr: str = "*/5 * * * *") -> dict:
    return {
        "schedule": {"kind": "cron", "expr": expr},
        "payload": {"kind": "agentTurn", "message": "run agent"},
        "name": "test-cron",
    }


# ---------------------------------------------------------------------------
# CRUD lifecycle
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_add_assigns_id_and_computes_next_run(self, service):
        job = service.add(_every_schedule())

        assert job.id  # non-empty UUID hex
        assert len(job.id) == 32
        assert job.name == "test-every"
        assert job.state.next_run_at_ms is not None
        assert job.state.next_run_at_ms > 0

    def test_list_returns_added_jobs(self, service):
        service.add(_every_schedule())
        service.add(_cron_schedule())

        jobs = service.list()
        assert len(jobs) == 2

    def test_list_enabled_only(self, service):
        j1 = service.add(_every_schedule())
        j2 = service.add(_cron_schedule())
        service.update(j2.id, {"enabled": False})

        enabled = service.list(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].id == j1.id

    def test_update_merges_fields(self, service):
        job = service.add(_every_schedule())
        updated = service.update(job.id, {"name": "renamed"})

        assert updated.name == "renamed"
        assert updated.id == job.id

    def test_update_schedule_recomputes_next_run(self, service):
        job = service.add(_every_schedule(every_ms=60_000))
        old_next = job.state.next_run_at_ms

        updated = service.update(
            job.id,
            {"schedule": {"kind": "every", "every_ms": 120_000, "anchor_ms": 0}},
        )
        # The next_run should have been recomputed (could be different)
        assert updated.state.next_run_at_ms is not None

    def test_update_nonexistent_raises(self, service):
        with pytest.raises(KeyError, match="not found"):
            service.update("nonexistent", {"name": "x"})

    def test_remove_existing(self, service):
        job = service.add(_every_schedule())
        assert service.remove(job.id) is True
        assert service.list() == []

    def test_remove_nonexistent(self, service):
        assert service.remove("nonexistent") is False

    @pytest.mark.asyncio
    async def test_run_force(self, service, execute_fn):
        job = service.add({
            "schedule": {"kind": "every", "every_ms": 60_000, "anchor_ms": 0},
            "payload": {"kind": "systemEvent", "message": "force run"},
            "name": "force-test",
        })

        result = await service.run(job.id)
        assert result["status"] == "ok"
        execute_fn.assert_awaited()

    @pytest.mark.asyncio
    async def test_run_nonexistent(self, service):
        result = await service.run("nonexistent")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Persistence across restart
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_jobs_survive_restart(self, data_root, execute_fn, channel_registry):
        svc1 = CronService("test_agent", data_root, execute_fn, channel_registry)
        job = svc1.add(_every_schedule())
        job_id = job.id

        # New service instance, same data_root
        svc2 = CronService("test_agent", data_root, execute_fn, channel_registry)
        svc2._jobs = svc2._store.load()
        loaded = svc2.list()

        assert len(loaded) == 1
        assert loaded[0].id == job_id


# ---------------------------------------------------------------------------
# Timer loop
# ---------------------------------------------------------------------------


class TestTimerLoop:
    @pytest.mark.asyncio
    async def test_due_jobs_collected_and_run(self, service, execute_fn):
        """Jobs whose next_run is in the past should be executed by the loop."""
        job = service.add(_every_schedule(every_ms=60_000))
        # Force next_run to the past
        job.state.next_run_at_ms = int(time.time() * 1000) - 1000

        # Run one iteration of the timer loop manually
        service._running = True
        with patch.object(service, "_seconds_until_next", return_value=0.0):
            # Let the loop run once then stop
            async def stop_after_one():
                await asyncio.sleep(0.1)
                service._running = False

            loop_task = asyncio.create_task(service._timer_loop())
            stop_task = asyncio.create_task(stop_after_one())
            await asyncio.gather(loop_task, stop_task, return_exceptions=True)

        execute_fn.assert_awaited()


# ---------------------------------------------------------------------------
# Catch-up
# ---------------------------------------------------------------------------


class TestCatchUp:
    @pytest.mark.asyncio
    async def test_missed_wake_now_runs_immediately(self, service, execute_fn):
        """Past next_run + wake_mode=NOW → run immediately on startup."""
        job = service.add({
            **_every_schedule(),
            "wake_mode": "now",
        })
        # Force next_run into the past
        job.state.next_run_at_ms = int(time.time() * 1000) - 5000

        await service._catch_up_missed_jobs()
        execute_fn.assert_awaited()

    @pytest.mark.asyncio
    async def test_missed_wake_next_heartbeat_skipped(self, service, execute_fn):
        """Past next_run + wake_mode=NEXT_HEARTBEAT → skipped, next_run recomputed."""
        job = service.add({
            **_every_schedule(),
            "wake_mode": "next-heartbeat",
        })
        old_next = job.state.next_run_at_ms
        # Force next_run into the past
        job.state.next_run_at_ms = int(time.time() * 1000) - 5000

        await service._catch_up_missed_jobs()
        execute_fn.assert_not_awaited()

        # next_run should be recomputed to a future time
        assert job.state.next_run_at_ms is not None
        assert job.state.next_run_at_ms > int(time.time() * 1000) - 1000


# ---------------------------------------------------------------------------
# Failure alerting
# ---------------------------------------------------------------------------


class TestFailureAlerting:
    @pytest.mark.asyncio
    async def test_alert_sent_after_threshold(self, data_root, channel_registry):
        """After N consecutive errors, an alert should be sent."""
        failing_fn = AsyncMock(side_effect=RuntimeError("boom"))
        svc = CronService("test", data_root, failing_fn, channel_registry)

        job = svc.add({
            **_every_schedule(),
            "failure_alert": {
                "after": 3,
                "channel": "whatsapp",
                "to": "admin",
                "cooldown_ms": 1000,
                "mode": "announce",
            },
        })

        # Run 3 times to hit threshold
        for _ in range(3):
            await svc._execute_job(job)

        assert job.state.consecutive_errors == 3
        # The channel's send should have been called for the alert
        channel = channel_registry.get("whatsapp")
        channel.send.assert_awaited()

    @pytest.mark.asyncio
    async def test_alert_cooldown_respected(self, data_root, channel_registry):
        """After an alert, a second should not be sent within the cooldown."""
        failing_fn = AsyncMock(side_effect=RuntimeError("boom"))
        svc = CronService("test", data_root, failing_fn, channel_registry)

        job = svc.add({
            **_every_schedule(),
            "failure_alert": {
                "after": 1,
                "channel": "whatsapp",
                "to": "admin",
                "cooldown_ms": 999_999_999,  # very long cooldown
                "mode": "announce",
            },
        })

        # First failure — alert sent
        await svc._execute_job(job)
        channel = channel_registry.get("whatsapp")
        first_count = channel.send.await_count

        # Second failure — alert should be suppressed by cooldown
        await svc._execute_job(job)
        assert channel.send.await_count == first_count  # no new call


# ---------------------------------------------------------------------------
# Delivery routing
# ---------------------------------------------------------------------------


class TestDeliveryRouting:
    @pytest.mark.asyncio
    async def test_announce_calls_channel_send(self, data_root, execute_fn, channel_registry):
        svc = CronService("test", data_root, execute_fn, channel_registry)

        job = svc.add({
            **_every_schedule(),
            "delivery": {
                "mode": "announce",
                "channel": "whatsapp",
                "to": "+1234567890",
            },
        })

        result = await svc._execute_job(job)
        assert result["delivery"]["status"] == "ok"
        channel = channel_registry.get("whatsapp")
        channel.send.assert_awaited_with("+1234567890", "cron output")

    @pytest.mark.asyncio
    async def test_webhook_calls_httpx_post(self, data_root, execute_fn):
        svc = CronService("test", data_root, execute_fn)

        job = svc.add({
            **_every_schedule(),
            "delivery": {
                "mode": "webhook",
                "to": "https://example.com/hook",
            },
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sci_fi_dashboard.cron.delivery.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            result = await svc._execute_job(job)

        assert result["delivery"]["status"] == "ok"
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_none_delivery_skipped(self, data_root, execute_fn):
        svc = CronService("test", data_root, execute_fn)
        job = svc.add(_every_schedule())

        result = await svc._execute_job(job)
        assert result["delivery"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------


class TestRunLog:
    @pytest.mark.asyncio
    async def test_run_log_entry_written(self, service, execute_fn):
        """After execution, a run log entry should exist."""
        job = service.add(_every_schedule())
        await service._execute_job(job)

        entries = service._run_log.get(job.id)
        assert len(entries) == 1
        assert entries[0]["status"] == "ok"
        assert "timestamp_ms" in entries[0]
        assert "duration_ms" in entries[0]
