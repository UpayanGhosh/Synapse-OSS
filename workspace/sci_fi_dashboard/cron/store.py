"""
Cron Scheduler — JSON persistence.

Stores the job list in a single JSON file per agent with atomic writes
(write to tempfile then os.replace) so a crash never corrupts the store.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .types import (
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

logger = logging.getLogger(__name__)

_CURRENT_VERSION = 1


class CronStore:
    """Persist cron jobs as JSON at ``data_root/state/agents/{agent_id}/cron.json``."""

    def __init__(self, agent_id: str, data_root: str | Path):
        self._agent_id = agent_id
        self._path = Path(data_root) / "state" / "agents" / agent_id / "cron.json"

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> list[CronJob]:
        """Load jobs from disk.  Returns an empty list on missing / corrupt file."""
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt or unreadable cron store at %s: %s", self._path, exc)
            return []

        raw = self.migrate(raw)
        return [self._dict_to_job(j) for j in raw.get("jobs", [])]

    def save(self, jobs: list[CronJob]) -> None:
        """Atomically write jobs to disk."""
        payload: dict[str, Any] = {
            "version": _CURRENT_VERSION,
            "jobs": [asdict(j) for j in jobs],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: tempfile in the same directory → os.replace
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp", prefix="cron_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            os.replace(tmp_path, str(self._path))
        except BaseException:
            # Clean up the temp file on any error
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    @staticmethod
    def migrate(raw: dict) -> dict:
        """Apply version migrations.  Currently a no-op for version 1."""
        version = raw.get("version", 0)
        if version < 1:
            # Future: migration logic goes here
            raw["version"] = _CURRENT_VERSION
        return raw

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_job(d: dict) -> CronJob:
        """Reconstruct a CronJob from a plain dict."""
        schedule_raw = d.get("schedule", {})
        schedule = CronSchedule(
            kind=ScheduleKind(schedule_raw.get("kind", "cron")),
            at=schedule_raw.get("at"),
            every_ms=schedule_raw.get("every_ms"),
            anchor_ms=schedule_raw.get("anchor_ms"),
            expr=schedule_raw.get("expr"),
            tz=schedule_raw.get("tz", "UTC"),
            stagger_ms=schedule_raw.get("stagger_ms", 0),
        )

        payload_raw = d.get("payload", {})
        deliver_raw = payload_raw.get("deliver")
        deliver = (
            CronDelivery(
                mode=DeliveryMode(deliver_raw.get("mode", "none")),
                channel=deliver_raw.get("channel"),
                to=deliver_raw.get("to"),
                account_id=deliver_raw.get("account_id"),
                best_effort=deliver_raw.get("best_effort", True),
                failure_destination=deliver_raw.get("failure_destination"),
            )
            if deliver_raw
            else None
        )
        payload = CronPayload(
            kind=PayloadKind(payload_raw.get("kind", "systemEvent")),
            message=payload_raw.get("message"),
            model_override=payload_raw.get("model_override"),
            fallbacks=payload_raw.get("fallbacks"),
            thinking=payload_raw.get("thinking", False),
            timeout_seconds=payload_raw.get("timeout_seconds", 300),
            tools_allow=payload_raw.get("tools_allow"),
            deliver=deliver,
            light_context=payload_raw.get("light_context", False),
        )

        delivery_raw = d.get("delivery", {})
        delivery = CronDelivery(
            mode=DeliveryMode(delivery_raw.get("mode", "none")),
            channel=delivery_raw.get("channel"),
            to=delivery_raw.get("to"),
            account_id=delivery_raw.get("account_id"),
            best_effort=delivery_raw.get("best_effort", True),
            failure_destination=delivery_raw.get("failure_destination"),
        )

        alert_raw = d.get("failure_alert")
        failure_alert = (
            CronFailureAlert(
                after=alert_raw.get("after", 3),
                channel=alert_raw.get("channel"),
                to=alert_raw.get("to"),
                cooldown_ms=alert_raw.get("cooldown_ms", 300_000),
                mode=DeliveryMode(alert_raw.get("mode", "none")),
                account_id=alert_raw.get("account_id"),
            )
            if alert_raw
            else None
        )

        state_raw = d.get("state", {})
        state = CronJobState(
            next_run_at_ms=state_raw.get("next_run_at_ms"),
            last_run_at_ms=state_raw.get("last_run_at_ms"),
            last_run_status=state_raw.get("last_run_status", "pending"),
            last_error=state_raw.get("last_error"),
            last_duration_ms=state_raw.get("last_duration_ms"),
            consecutive_errors=state_raw.get("consecutive_errors", 0),
            last_failure_alert_at_ms=state_raw.get("last_failure_alert_at_ms", 0),
            schedule_error_count=state_raw.get("schedule_error_count", 0),
            last_delivery_status=state_raw.get("last_delivery_status"),
        )

        return CronJob(
            id=d["id"],
            name=d.get("name", ""),
            schedule=schedule,
            payload=payload,
            delivery=delivery,
            failure_alert=failure_alert,
            session_target=SessionTarget(d.get("session_target", "main")),
            wake_mode=WakeMode(d.get("wake_mode", "now")),
            enabled=d.get("enabled", True),
            state=state,
            created_at_ms=d.get("created_at_ms", 0),
        )
