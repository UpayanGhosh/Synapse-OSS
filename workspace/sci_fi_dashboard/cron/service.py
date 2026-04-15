"""
Cron Scheduler — CRUD API and async timer loop.

``CronService`` is the main entry point: it owns the store, manages the
timer that fires due jobs, handles catch-up after restart, and exposes
a simple add / update / remove / list / run API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from .alerting import check_and_send_failure_alert
from .delivery import deliver_output
from .isolated_agent import run_isolated_agent
from .run_log import RunLog
from .schedule import compute_next_run_at_ms
from .store import CronStore
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


class CronService:
    """Full lifecycle manager for cron jobs."""

    def __init__(
        self,
        agent_id: str,
        data_root: str,
        execute_fn: Callable[..., Coroutine[Any, Any, str]] | None = None,
        channel_registry: Any | None = None,
    ):
        self._agent_id = agent_id
        self._data_root = data_root
        self._execute_fn = execute_fn
        self._channel_registry = channel_registry

        self._store = CronStore(agent_id, data_root)
        self._run_log = RunLog(data_root)
        self._jobs: list[CronJob] = []
        self._timer_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load the store, catch up missed jobs, and start the timer loop."""
        self._jobs = self._store.load()
        logger.info("Loaded %d cron jobs for agent %s", len(self._jobs), self._agent_id)
        await self._catch_up_missed_jobs()
        self._running = True
        self._timer_task = asyncio.create_task(self._timer_loop())

    async def stop(self) -> None:
        """Cancel the timer and persist the current state."""
        self._running = False
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timer_task
        self._store.save(self._jobs)
        logger.info("Cron service stopped for agent %s", self._agent_id)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, job_input: dict[str, Any]) -> CronJob:
        """Create a new job from a dict specification, assign a UUID, and persist."""
        job_id = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)

        schedule = self._build_schedule(job_input.get("schedule", {}))
        payload = self._build_payload(job_input.get("payload", {}))
        delivery = self._build_delivery(job_input.get("delivery", {}))
        failure_alert = self._build_failure_alert(job_input.get("failure_alert"))

        state = CronJobState()
        state.next_run_at_ms = compute_next_run_at_ms(schedule, now_ms)

        job = CronJob(
            id=job_id,
            name=job_input.get("name", ""),
            schedule=schedule,
            payload=payload,
            delivery=delivery,
            failure_alert=failure_alert,
            session_target=SessionTarget(job_input.get("session_target", "main")),
            wake_mode=WakeMode(job_input.get("wake_mode", "now")),
            enabled=job_input.get("enabled", True),
            state=state,
            created_at_ms=now_ms,
        )

        self._jobs.append(job)
        self._store.save(self._jobs)
        logger.info("Added cron job %s (%s)", job.id, job.name)
        return job

    def update(self, job_id: str, patch: dict[str, Any]) -> CronJob:
        """Merge-patch an existing job.  Recomputes next_run if schedule changed."""
        job = self._find_job(job_id)
        if job is None:
            raise KeyError(f"Job {job_id!r} not found")

        now_ms = int(time.time() * 1000)
        schedule_changed = False

        if "name" in patch:
            job.name = patch["name"]
        if "enabled" in patch:
            job.enabled = patch["enabled"]
        if "session_target" in patch:
            job.session_target = SessionTarget(patch["session_target"])
        if "wake_mode" in patch:
            job.wake_mode = WakeMode(patch["wake_mode"])

        if "schedule" in patch:
            job.schedule = self._build_schedule(patch["schedule"])
            schedule_changed = True

        if "payload" in patch:
            job.payload = self._build_payload(patch["payload"])

        if "delivery" in patch:
            job.delivery = self._build_delivery(patch["delivery"])

        if "failure_alert" in patch:
            job.failure_alert = self._build_failure_alert(patch["failure_alert"])

        if schedule_changed:
            job.state.next_run_at_ms = compute_next_run_at_ms(job.schedule, now_ms)

        self._store.save(self._jobs)
        logger.info("Updated cron job %s", job_id)
        return job

    def remove(self, job_id: str) -> bool:
        """Remove a job by ID.  Returns True if found and removed."""
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        removed = len(self._jobs) < before
        if removed:
            self._store.save(self._jobs)
            logger.info("Removed cron job %s", job_id)
        return removed

    def list(self, enabled_only: bool = False) -> list[CronJob]:
        """Return all jobs, optionally filtered to enabled-only."""
        if enabled_only:
            return [j for j in self._jobs if j.enabled]
        return list(self._jobs)

    async def run(self, job_id: str, mode: str = "due") -> dict[str, Any]:
        """Force-run a job regardless of schedule.

        Parameters
        ----------
        mode:
            ``"due"`` — normal execution as if the timer fired.
            ``"force"`` — same, but doesn't check enabled/next_run.
        """
        job = self._find_job(job_id)
        if job is None:
            return {"status": "error", "reason": f"job {job_id!r} not found"}
        return await self._execute_job(job)

    # ------------------------------------------------------------------
    # Timer loop
    # ------------------------------------------------------------------

    async def _timer_loop(self) -> None:
        """Sleep until the next due job, execute all due jobs, rearm."""
        while self._running:
            try:
                sleep_seconds = self._seconds_until_next()
                if sleep_seconds is None:
                    # No jobs with a next_run — sleep a bit and re-check
                    await asyncio.sleep(10)
                    continue

                if sleep_seconds > 0:
                    await asyncio.sleep(sleep_seconds)

                if not self._running:
                    break

                # Collect all due jobs
                now_ms = int(time.time() * 1000)
                due = [
                    j
                    for j in self._jobs
                    if j.enabled
                    and j.state.next_run_at_ms is not None
                    and j.state.next_run_at_ms <= now_ms
                ]

                if due:
                    results = await asyncio.gather(
                        *(self._execute_job(j) for j in due),
                        return_exceptions=True,
                    )
                    for job, result in zip(due, results, strict=False):
                        if isinstance(result, BaseException):
                            logger.error("Unhandled error executing job %s: %s", job.id, result)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in cron timer loop")
                await asyncio.sleep(5)

    def _seconds_until_next(self) -> float | None:
        """Return seconds until the earliest due job, or None if no jobs scheduled."""
        now_ms = int(time.time() * 1000)
        candidates = [
            j.state.next_run_at_ms
            for j in self._jobs
            if j.enabled and j.state.next_run_at_ms is not None
        ]
        if not candidates:
            return None
        earliest = min(candidates)
        delta_ms = earliest - now_ms
        return max(delta_ms / 1000.0, 0.0)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------

    async def _execute_job(self, job: CronJob) -> dict[str, Any]:
        """Run a single job's payload, update state, handle alerting + logging."""
        now_ms = int(time.time() * 1000)
        start_mono = time.monotonic()
        result: dict[str, Any] = {"job_id": job.id, "status": "ok"}

        try:
            from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

            _get_emitter().emit(
                "cron.job_start",
                {
                    "job_id": job.id,
                    "job_name": job.name,
                    "session_target": str(job.session_target),
                },
            )
        except Exception:
            pass  # emitter is optional — never block cron

        try:
            output = await self._run_payload(job)
            duration_ms = int((time.monotonic() - start_mono) * 1000)

            job.state.last_run_at_ms = now_ms
            job.state.last_run_status = "ok"
            job.state.last_error = None
            job.state.last_duration_ms = duration_ms
            job.state.consecutive_errors = 0

            # Delivery
            delivery_result = await deliver_output(output, job.delivery, self._channel_registry)
            job.state.last_delivery_status = delivery_result.get("status")
            result["delivery"] = delivery_result
            result["output"] = output

            try:
                from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

                _get_emitter().emit(
                    "cron.job_done",
                    {
                        "job_id": job.id,
                        "job_name": job.name,
                        "status": result.get("status", "unknown"),
                        "duration_ms": job.state.last_duration_ms,
                    },
                )
            except Exception:
                pass  # emitter is optional — never block cron

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            job.state.last_run_at_ms = now_ms
            job.state.last_run_status = "error"
            job.state.last_error = str(exc)
            job.state.last_duration_ms = duration_ms
            job.state.consecutive_errors += 1
            result["status"] = "error"
            result["error"] = str(exc)
            logger.error("Job %s failed: %s", job.id, exc)

            try:
                from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

                _get_emitter().emit(
                    "cron.job_error",
                    {
                        "job_id": job.id,
                        "job_name": job.name,
                        "error": str(exc)[:200],
                    },
                )
            except Exception:
                pass  # emitter is optional — never block cron

            # Failure alerting
            if job.failure_alert:
                try:
                    await check_and_send_failure_alert(
                        job, job.failure_alert, self._channel_registry
                    )
                except Exception:
                    logger.exception("Failed to send failure alert for job %s", job.id)

        # Recompute next_run
        now_ms = int(time.time() * 1000)
        job.state.next_run_at_ms = compute_next_run_at_ms(job.schedule, now_ms)

        # Write run log
        log_entry = {
            "timestamp_ms": now_ms,
            "status": job.state.last_run_status,
            "duration_ms": job.state.last_duration_ms,
            "error": job.state.last_error,
            "delivery_status": job.state.last_delivery_status,
        }
        self._run_log.append(job.id, log_entry)

        # Persist
        self._store.save(self._jobs)
        return result

    async def _run_payload(self, job: CronJob) -> str:
        """Dispatch the payload to the appropriate executor."""
        payload = job.payload

        if payload.kind == PayloadKind.AGENT_TURN:
            session_key = f"cron-{job.id}-{uuid.uuid4().hex[:8]}"
            if job.session_target == SessionTarget.ISOLATED:
                return await run_isolated_agent(payload, session_key, self._execute_fn)
            # MAIN or CURRENT — use execute_fn directly
            if self._execute_fn:
                return await self._execute_fn(payload.message or "", session_key)
            return ""

        if payload.kind == PayloadKind.SYSTEM_EVENT:
            # System events are just passed through execute_fn if available
            if self._execute_fn:
                return await self._execute_fn(payload.message or "", f"cron-sys-{job.id}")
            return payload.message or ""

        return ""

    # ------------------------------------------------------------------
    # Catch-up
    # ------------------------------------------------------------------

    async def _catch_up_missed_jobs(self) -> None:
        """On startup, run any jobs whose next_run is in the past and wake_mode is NOW."""
        now_ms = int(time.time() * 1000)
        missed = [
            j
            for j in self._jobs
            if j.enabled
            and j.state.next_run_at_ms is not None
            and j.state.next_run_at_ms < now_ms
            and j.wake_mode == WakeMode.NOW
        ]

        if missed:
            logger.info("Catching up %d missed jobs", len(missed))
            await asyncio.gather(
                *(self._execute_job(j) for j in missed),
                return_exceptions=True,
            )

        # For NEXT_HEARTBEAT jobs, just recompute next_run without executing
        for j in self._jobs:
            if (
                j.enabled
                and j.state.next_run_at_ms is not None
                and j.state.next_run_at_ms < now_ms
                and j.wake_mode == WakeMode.NEXT_HEARTBEAT
            ):
                j.state.next_run_at_ms = compute_next_run_at_ms(j.schedule, now_ms)

        self._store.save(self._jobs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_job(self, job_id: str) -> CronJob | None:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    @staticmethod
    def _build_schedule(raw: dict[str, Any]) -> CronSchedule:
        return CronSchedule(
            kind=ScheduleKind(raw.get("kind", "cron")),
            at=raw.get("at"),
            every_ms=raw.get("every_ms"),
            anchor_ms=raw.get("anchor_ms"),
            expr=raw.get("expr"),
            tz=raw.get("tz", "UTC"),
            stagger_ms=raw.get("stagger_ms", 0),
        )

    @staticmethod
    def _build_payload(raw: dict[str, Any]) -> CronPayload:
        deliver_raw = raw.get("deliver")
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
        return CronPayload(
            kind=PayloadKind(raw.get("kind", "systemEvent")),
            message=raw.get("message"),
            model_override=raw.get("model_override"),
            fallbacks=raw.get("fallbacks"),
            thinking=raw.get("thinking", False),
            timeout_seconds=raw.get("timeout_seconds", 300),
            tools_allow=raw.get("tools_allow"),
            deliver=deliver,
            light_context=raw.get("light_context", False),
        )

    @staticmethod
    def _build_delivery(raw: dict[str, Any]) -> CronDelivery:
        return CronDelivery(
            mode=DeliveryMode(raw.get("mode", "none")),
            channel=raw.get("channel"),
            to=raw.get("to"),
            account_id=raw.get("account_id"),
            best_effort=raw.get("best_effort", True),
            failure_destination=raw.get("failure_destination"),
        )

    @staticmethod
    def _build_failure_alert(raw: dict[str, Any] | None) -> CronFailureAlert | None:
        if raw is None:
            return None
        return CronFailureAlert(
            after=raw.get("after", 3),
            channel=raw.get("channel"),
            to=raw.get("to"),
            cooldown_ms=raw.get("cooldown_ms", 300_000),
            mode=DeliveryMode(raw.get("mode", "none")),
            account_id=raw.get("account_id"),
        )
