"""
Tests for sci_fi_dashboard.cron.store — JSON persistence.
"""
from __future__ import annotations

import json
import os

import pytest

from sci_fi_dashboard.cron.store import CronStore
from sci_fi_dashboard.cron.types import (
    CronDelivery,
    CronFailureAlert,
    CronJob,
    CronJobState,
    CronPayload,
    CronSchedule,
    DeliveryMode,
    PayloadKind,
    ScheduleKind,
    SessionTarget,
    WakeMode,
)


@pytest.fixture
def store(temp_dir):
    """Create a CronStore pointing at a temp directory."""
    return CronStore(agent_id="test_agent", data_root=temp_dir)


def _sample_job(job_id: str = "abc123", name: str = "test-job") -> CronJob:
    """Build a fully populated CronJob for round-trip testing."""
    return CronJob(
        id=job_id,
        name=name,
        schedule=CronSchedule(
            kind=ScheduleKind.CRON,
            expr="*/5 * * * *",
            tz="America/New_York",
            stagger_ms=1500,
        ),
        payload=CronPayload(
            kind=PayloadKind.AGENT_TURN,
            message="Hello from cron",
            model_override="gemini/gemini-2.0-flash-exp",
            fallbacks=["anthropic/claude-3-5-sonnet-20241022"],
            thinking=True,
            timeout_seconds=120,
            tools_allow=["web_search"],
            light_context=True,
        ),
        delivery=CronDelivery(
            mode=DeliveryMode.ANNOUNCE,
            channel="whatsapp",
            to="+1234567890",
            account_id="acct_1",
            best_effort=False,
            failure_destination="fallback_channel",
        ),
        failure_alert=CronFailureAlert(
            after=5,
            channel="telegram",
            to="admin_chat",
            cooldown_ms=600_000,
            mode=DeliveryMode.ANNOUNCE,
            account_id="acct_alert",
        ),
        session_target=SessionTarget.ISOLATED,
        wake_mode=WakeMode.NEXT_HEARTBEAT,
        enabled=True,
        state=CronJobState(
            next_run_at_ms=9999999999999,
            last_run_at_ms=1000000000000,
            last_run_status="ok",
            last_error=None,
            last_duration_ms=450,
            consecutive_errors=0,
            last_failure_alert_at_ms=0,
            schedule_error_count=0,
            last_delivery_status="ok",
        ),
        created_at_ms=1700000000000,
    )


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    def test_full_round_trip_preserves_all_fields(self, store):
        """Save then load should give back identical data."""
        original = _sample_job()
        store.save([original])
        loaded = store.load()

        assert len(loaded) == 1
        job = loaded[0]

        # Top-level fields
        assert job.id == original.id
        assert job.name == original.name
        assert job.session_target == original.session_target
        assert job.wake_mode == original.wake_mode
        assert job.enabled == original.enabled
        assert job.created_at_ms == original.created_at_ms

        # Schedule
        assert job.schedule.kind == original.schedule.kind
        assert job.schedule.expr == original.schedule.expr
        assert job.schedule.tz == original.schedule.tz
        assert job.schedule.stagger_ms == original.schedule.stagger_ms

        # Payload
        assert job.payload.kind == original.payload.kind
        assert job.payload.message == original.payload.message
        assert job.payload.model_override == original.payload.model_override
        assert job.payload.fallbacks == original.payload.fallbacks
        assert job.payload.thinking == original.payload.thinking
        assert job.payload.timeout_seconds == original.payload.timeout_seconds
        assert job.payload.tools_allow == original.payload.tools_allow
        assert job.payload.light_context == original.payload.light_context

        # Delivery
        assert job.delivery.mode == original.delivery.mode
        assert job.delivery.channel == original.delivery.channel
        assert job.delivery.to == original.delivery.to
        assert job.delivery.account_id == original.delivery.account_id
        assert job.delivery.best_effort == original.delivery.best_effort
        assert job.delivery.failure_destination == original.delivery.failure_destination

        # Failure alert
        assert job.failure_alert is not None
        assert job.failure_alert.after == original.failure_alert.after
        assert job.failure_alert.channel == original.failure_alert.channel
        assert job.failure_alert.to == original.failure_alert.to
        assert job.failure_alert.cooldown_ms == original.failure_alert.cooldown_ms
        assert job.failure_alert.mode == original.failure_alert.mode

        # State
        assert job.state.next_run_at_ms == original.state.next_run_at_ms
        assert job.state.last_run_at_ms == original.state.last_run_at_ms
        assert job.state.last_run_status == original.state.last_run_status
        assert job.state.consecutive_errors == original.state.consecutive_errors
        assert job.state.last_duration_ms == original.state.last_duration_ms

    def test_multiple_jobs_round_trip(self, store):
        """Multiple jobs should all survive serialization."""
        jobs = [_sample_job(f"job_{i}", f"test-{i}") for i in range(5)]
        store.save(jobs)
        loaded = store.load()

        assert len(loaded) == 5
        loaded_ids = {j.id for j in loaded}
        assert loaded_ids == {f"job_{i}" for i in range(5)}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_missing_file_returns_empty_list(self, store):
        """Loading when no file exists should return an empty list."""
        result = store.load()
        assert result == []

    def test_corrupt_json_returns_empty_list(self, store):
        """Corrupt JSON should return an empty list and not crash."""
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{{not valid json!!", encoding="utf-8")

        result = store.load()
        assert result == []

    def test_empty_file_returns_empty_list(self, store):
        """An empty file should return an empty list."""
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("", encoding="utf-8")

        result = store.load()
        assert result == []


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_no_partial_writes_on_success(self, store):
        """After a successful save, the file should contain valid JSON."""
        store.save([_sample_job()])

        raw = json.loads(store.path.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert len(raw["jobs"]) == 1

    def test_original_preserved_if_save_interrupted(self, store, monkeypatch):
        """If os.replace fails, the original file should remain intact."""
        original = _sample_job("original")
        store.save([original])

        # Now make os.replace raise
        def bad_replace(src, dst):
            os.unlink(src)  # clean up temp file
            raise OSError("simulated disk failure")

        monkeypatch.setattr(os, "replace", bad_replace)

        with pytest.raises(OSError, match="simulated disk failure"):
            store.save([_sample_job("new_job")])

        # Original should still be loadable
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].id == "original"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_version_0_migrated_to_1(self):
        raw = {"jobs": []}  # no version key
        result = CronStore.migrate(raw)
        assert result["version"] == 1

    def test_version_1_untouched(self):
        raw = {"version": 1, "jobs": []}
        result = CronStore.migrate(raw)
        assert result["version"] == 1
