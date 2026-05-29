"""Phase 16 BRIDGE-02 + BRIDGE-03 — Node bridge /health poller with gated restart.

Polls GET http://127.0.0.1:{channel._port}/health every `interval_s` seconds.
On N consecutive failures, triggers `channel._restart_bridge()` — but ONLY
when `supervisor.stop_reconnect is False` (no restart for 440/401/logged-out).

Design anchors (from 16-RESEARCH.md):
  - G2 (restart race): use channel._restart_in_progress asyncio.Event so Phase 14
    watchdog + Phase 16 poller can't double-restart.
  - G4 (consecutive-failures reset): 60s grace window after a trigger — polls during
    grace don't count as failures.
  - G6 (401 not a failure): 401 from /health means auth-expired, not "bridge
    unreachable". Mark as degraded, return True from poll_once.

Reuses:
  - Phase 13 observability (get_child_logger, mint_run_id, redact_identifier where applicable)
  - Phase 14 WhatsAppSupervisor (stop_reconnect gate)
  - Phase 16 WhatsAppChannel._restart_bridge (existing restart path from code-515 flow)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Protocol

import httpx

from sci_fi_dashboard.observability import get_child_logger, mint_run_id

_log = get_child_logger("channel.whatsapp.health")


# ---------------------------------------------------------------------------
# Protocols (duck-typed interfaces)
# ---------------------------------------------------------------------------


class _ChannelProto(Protocol):
    _port: int
    _restart_in_progress: asyncio.Event

    async def _restart_bridge(self) -> None: ...


class _SupervisorProto(Protocol):
    @property
    def stop_reconnect(self) -> bool: ...


class _EmitterProto(Protocol):
    def emit(self, event_type: str, data: dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# BridgeHealthPoller
# ---------------------------------------------------------------------------


class BridgeHealthPoller:
    """Asyncio-based HTTP health poller for the Node bridge subprocess.

    Lifecycle:
        poller = BridgeHealthPoller(channel, supervisor, interval_s=30.0)
        await poller.start()
        # ... running
        await poller.stop()

    Public read-only state:
        poller.last_health          -> dict of most recent /health JSON
        poller.consecutive_failures -> int counter (reset on success)
        poller.in_grace_window      -> bool (True during post-restart grace)
    """

    def __init__(
        self,
        channel: _ChannelProto,
        supervisor: _SupervisorProto,
        interval_s: float = 30.0,
        failures_before_restart: int = 3,
        timeout_s: float = 5.0,
        grace_window_s: float = 60.0,
        emitter: _EmitterProto | None = None,
        http_client_factory: Any = None,
    ) -> None:
        self._channel = channel
        self._supervisor = supervisor
        self._interval_s = float(interval_s)
        self._failures_threshold = int(failures_before_restart)
        self._timeout_s = float(timeout_s)
        self._grace_window_s = float(grace_window_s)
        self._emitter = emitter
        # Callable(timeout_s) → httpx.AsyncClient; injectable for tests.
        self._http_client_factory = http_client_factory or (
            lambda timeout: httpx.AsyncClient(timeout=timeout)
        )

        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._consecutive_failures: int = 0
        self._last_health: dict[str, Any] = {}
        self._last_ok_at: float | None = None
        self._grace_until: float = 0.0

    # -------- public properties --------

    @property
    def last_health(self) -> dict[str, Any]:
        return dict(self._last_health)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def in_grace_window(self) -> bool:
        return time.monotonic() < self._grace_until

    # -------- lifecycle --------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._loop())
        _log.info(
            "bridge_health_poller_started",
            extra={
                "interval_s": self._interval_s,
                "failures_threshold": self._failures_threshold,
                "grace_window_s": self._grace_window_s,
            },
        )

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        _log.info("bridge_health_poller_stopped")

    # -------- core polling logic --------

    async def poll_once(self) -> bool:
        """Single /health fetch.

        Returns True iff the bridge is reachable (200 OK or 401 auth-expired).
        Returns False on timeout, connection error, or 5xx.

        Side effects:
          - self._last_health updated
          - self._last_ok_at updated on True return (for debug)

        401 handling (G6): mark as degraded in last_health, return True —
        401 means auth-expired, NOT bridge-down.
        """
        port = self._channel._port
        url = f"http://127.0.0.1:{port}/health"
        try:
            async with self._http_client_factory(self._timeout_s) as client:
                r = await client.get(url)
                if r.status_code == 401:
                    self._last_health = {"status": "degraded", "error": "auth_expired"}
                    self._last_ok_at = time.monotonic()
                    return True
                if r.status_code != 200:
                    _log.warning(
                        "bridge_health_non_200",
                        extra={"status_code": r.status_code, "port": port},
                    )
                    return False
                try:
                    self._last_health = r.json()
                except ValueError as exc:
                    _log.warning("bridge_health_bad_json", extra={"error": str(exc)})
                    return False
                self._last_ok_at = time.monotonic()
                return True
        except httpx.RequestError as exc:
            _log.warning(
                "bridge_health_request_error",
                extra={"error": str(exc), "port": port},
            )
            return False

    # -------- scheduler loop --------

    async def _loop(self) -> None:
        """Poll every interval_s; count failures; trigger restart when threshold met.

        Guards (in priority order):
          1. grace_window: skip polling logic entirely during post-restart grace
          2. supervisor.stop_reconnect: never restart when non-retryable state (440/401/logged-out)
          3. channel._restart_in_progress: never double-restart (G2)

        Never-crash contract (mirrors HEART-05): any unexpected exception inside
        the iteration body is caught, logged, and the loop sleeps interval_s before
        retrying — the poller task never silently dies.
        """
        try:
            while not self._stopped.is_set():
                try:
                    # G4 grace window: during grace, skip counting failures so
                    # the bridge has time to come up cleanly.
                    if not self.in_grace_window:
                        mint_run_id()
                        ok = await self.poll_once()
                        if ok:
                            if self._consecutive_failures > 0:
                                _log.info(
                                    "bridge_health_recovered",
                                    extra={"prior_failures": self._consecutive_failures},
                                )
                            self._consecutive_failures = 0
                            self._emit(
                                "bridge.health.poll",
                                {
                                    "ok": True,
                                    "consecutive_failures": 0,
                                    "status": self._last_health.get("status"),
                                    "uptime_ms": self._last_health.get("uptime_ms"),
                                    "bridge_version": self._last_health.get("bridge_version"),
                                },
                            )
                        else:
                            # Failure branch
                            self._consecutive_failures += 1
                            _log.warning(
                                "bridge_health_failed",
                                extra={"consecutive_failures": self._consecutive_failures},
                            )
                            self._emit(
                                "bridge.health.failed",
                                {"consecutive_failures": self._consecutive_failures},
                            )

                            if self._consecutive_failures >= self._failures_threshold:
                                # Threshold hit — consider restart.
                                if self._supervisor.stop_reconnect:
                                    _log.info(
                                        "bridge_health_threshold_skipped",
                                        extra={
                                            "reason": "supervisor_stop_reconnect",
                                            "consecutive_failures": self._consecutive_failures,
                                        },
                                    )
                                elif self._channel._restart_in_progress.is_set():
                                    # G2 race guard: don't double-restart
                                    _log.info(
                                        "bridge_health_threshold_skipped",
                                        extra={"reason": "restart_already_in_progress"},
                                    )
                                else:
                                    await self._trigger_restart()

                    await asyncio.sleep(self._interval_s)
                except Exception as exc:  # noqa: BLE001 — never-crash contract
                    _log.exception(
                        "bridge_health_loop_iteration_failed",
                        extra={"error": str(exc)},
                    )
                    # Sleep the full interval so we don't hot-loop on a persistent bug.
                    try:
                        await asyncio.sleep(self._interval_s)
                    except asyncio.CancelledError:
                        raise
        except asyncio.CancelledError:
            pass

    async def _trigger_restart(self) -> None:
        """Fire restart — expect G4 grace window to activate."""
        prior = self._consecutive_failures
        self._consecutive_failures = 0
        self._grace_until = time.monotonic() + self._grace_window_s
        _log.warning(
            "bridge_health_restart_triggered",
            extra={
                "prior_failures": prior,
                "grace_window_s": self._grace_window_s,
            },
        )
        self._emit(
            "bridge.health.restart",
            {"reason": "consecutive_failures", "prior_failures": prior},
        )
        try:
            await self._channel._restart_bridge()
        except Exception as exc:  # noqa: BLE001 — restart failure must not kill poller
            _log.warning(
                "bridge_health_restart_failed",
                extra={"error": str(exc)},
            )
            self._emit(
                "bridge.health.restart_failed",
                {"error": str(exc), "prior_failures": prior},
            )

    # -------- emit helper --------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emitter is None:
            return
        try:
            self._emitter.emit(event_type, data)
        except Exception as exc:  # noqa: BLE001 — emitter failures never crash poller
            _log.warning(
                "bridge_health_emitter_failed",
                extra={"event": event_type, "error": str(exc)},
            )
