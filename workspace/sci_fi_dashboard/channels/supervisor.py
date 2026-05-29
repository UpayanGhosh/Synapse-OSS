"""
WhatsApp supervisor — watchdog wrapper + reconnect policy + health state.

Wraps :class:`PollingWatchdog` with WhatsApp-specific reconnect semantics:
- 1800-second silence threshold (WA long-polling sessions go quiet before dying)
- Exponential backoff with jitter via :class:`ReconnectPolicy`
- Non-retryable disconnect codes that halt the reconnect loop
- A ``health_state`` property exposing the current lifecycle state

Phase 14 SUPV-01..04.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sci_fi_dashboard.channels.polling_watchdog import PollingWatchdog
from sci_fi_dashboard.observability import get_child_logger

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------

_log = get_child_logger("channel.whatsapp.supv")

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Seconds of WhatsApp silence before the watchdog fires a restart.
WA_SILENCE_THRESHOLD_S: float = 1800.0

#: Disconnect codes that are permanent — must not trigger automatic reconnect.
NONRETRYABLE_CODES: frozenset[str] = frozenset({"401", "403", "440"})

#: Normalised health-state vocabulary (canonical name → display string).
STATE_MAP: dict[str, str] = {
    "connected": "connected",
    "logged_out": "logged-out",
    "reconnecting": "reconnecting",
    "conflict": "conflict",
    "stopped": "stopped",
}

#: Map from a non-retryable disconnect code to the resulting health state.
_CODE_TO_STATE: dict[str, str] = {
    "401": "logged-out",
    "403": "logged-out",
    "440": "conflict",
}

# ---------------------------------------------------------------------------
# ReconnectPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconnectPolicy:
    """Immutable policy for WhatsApp reconnect back-off.

    All ``_ms`` values are in **milliseconds** to match browser/Baileys
    conventions; ``compute_backoff_s`` returns **seconds** for asyncio.sleep.

    Attributes:
        initial_ms: Initial back-off window in ms (default 1 000 ms = 1 s).
        max_ms: Upper cap for the clamped back-off in ms (default 60 000 ms).
        factor: Multiplicative growth factor per attempt (default 2.0).
        jitter: Relative jitter fraction applied to the clamped value.
                0.0 → deterministic; 0.2 → ±20 % of the clamped value.
        max_attempts: Maximum reconnect attempts before giving up.
    """

    initial_ms: int = 1000
    max_ms: int = 60000
    factor: float = 2.0
    jitter: float = 0.2
    max_attempts: int = 5

    def compute_backoff_s(self, attempt: int) -> float:
        """Return back-off duration in seconds for the given (0-indexed) attempt.

        Formula::

            base_s  = (initial_ms / 1000) * factor ** attempt
            clamped = min(base_s, max_ms / 1000)
            result  = clamped * uniform(1 - jitter, 1 + jitter)   # when jitter > 0
            result  = clamped                                        # when jitter == 0

        Returns:
            Non-negative float — seconds to sleep before the next reconnect.
        """
        import random  # imported lazily so tests can patch random.uniform

        initial_s: float = self.initial_ms / 1000.0
        max_s: float = self.max_ms / 1000.0
        base_s: float = initial_s * (self.factor ** attempt)
        clamped_s: float = min(base_s, max_s)
        if self.jitter > 0:
            clamped_s = clamped_s * (1.0 + random.uniform(-self.jitter, self.jitter))
        return max(0.0, clamped_s)


# ---------------------------------------------------------------------------
# load_reconnect_policy_from_config (Task 2 — stub present to avoid ImportError)
# ---------------------------------------------------------------------------


def load_reconnect_policy_from_config(config_path: Path | None = None) -> ReconnectPolicy:
    """Load :class:`ReconnectPolicy` from ``synapse.json`` reconnect block.

    Reads the optional ``reconnect`` key from the resolved config file and
    merges any provided values with :class:`ReconnectPolicy` defaults.  Keys
    not present in the config file retain their dataclass defaults.

    The ``config_path`` argument is used by tests to point at a temporary
    ``synapse.json`` file.  When omitted the standard config location is
    resolved via ``SYNAPSE_HOME`` (falls back to ``~/.synapse/synapse.json``).

    Supported JSON keys inside ``reconnect``::

        {
            "reconnect": {
                "initialMs":   <int>,
                "maxMs":       <int>,
                "factor":      <float>,
                "jitter":      <float>,
                "maxAttempts": <int>
            }
        }
    """
    import json
    import os

    if config_path is None:
        synapse_home = os.environ.get("SYNAPSE_HOME", str(Path.home() / ".synapse"))
        config_path = Path(synapse_home) / "synapse.json"

    reconnect_block: dict[str, Any] = {}
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            reconnect_block = raw.get("reconnect", {})
    except Exception as exc:  # noqa: BLE001
        _log.warning("Failed to parse reconnect config from %s: %s", config_path, exc)

    defaults = ReconnectPolicy()
    return ReconnectPolicy(
        initial_ms=int(reconnect_block.get("initialMs", defaults.initial_ms)),
        max_ms=int(reconnect_block.get("maxMs", defaults.max_ms)),
        factor=float(reconnect_block.get("factor", defaults.factor)),
        jitter=float(reconnect_block.get("jitter", defaults.jitter)),
        max_attempts=int(reconnect_block.get("maxAttempts", defaults.max_attempts)),
    )


# ---------------------------------------------------------------------------
# WhatsAppSupervisor
# ---------------------------------------------------------------------------


class WhatsAppSupervisor:
    """High-level supervisor for the WhatsApp channel lifecycle.

    Wraps :class:`PollingWatchdog` and adds:

    * **Silence detection** — fires ``restart_callback`` after
      ``stall_threshold_s`` seconds without a recorded activity event.
    * **Health state tracking** — ``health_state`` is a string drawn from
      ``STATE_MAP`` values (or ``"stopped"`` for the initial state).
    * **Non-retryable code handling** — disconnect codes in
      ``NONRETRYABLE_CODES`` set ``stop_reconnect = True`` so the caller knows
      not to schedule another reconnect attempt.
    * **Attempt counter** — reset to 0 on ``note_connected()``.

    Args:
        restart_callback: Async callable invoked by the watchdog when a stall
                          is detected.  Must accept no positional arguments.
        policy: :class:`ReconnectPolicy` controlling back-off timing.
        stall_threshold_s: Seconds of inactivity before a stall is declared.
                           Defaults to :data:`WA_SILENCE_THRESHOLD_S`.
    """

    def __init__(
        self,
        restart_callback: Callable[[], Awaitable[None]],
        policy: ReconnectPolicy,
        stall_threshold_s: float = WA_SILENCE_THRESHOLD_S,
    ) -> None:
        self.policy: ReconnectPolicy = policy
        self._stall_threshold_s: float = stall_threshold_s
        self._raw_restart_callback: Callable[[], Awaitable[None]] = restart_callback
        self._health_state: str = "stopped"
        self._stop_reconnect: bool = False
        self._last_code: str | None = None
        self._attempts: int = 0

        # PollingWatchdog is initialised last because it takes _on_stall which
        # requires self to be partially constructed.
        self._watchdog: PollingWatchdog = PollingWatchdog(
            restart_callback=self._on_stall,
            stall_threshold_s=stall_threshold_s,
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def health_state(self) -> str:
        """Current lifecycle state string (never raw disconnect codes)."""
        return self._health_state

    @property
    def stop_reconnect(self) -> bool:
        """``True`` when a non-retryable code has permanently halted reconnects."""
        return self._stop_reconnect

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the underlying :class:`PollingWatchdog` background task."""
        _log.info("WhatsAppSupervisor starting (threshold=%.0fs)", self._stall_threshold_s)
        await self._watchdog.start()

    async def stop(self) -> None:
        """Stop the underlying watchdog and clean up."""
        _log.info("WhatsAppSupervisor stopping")
        await self._watchdog.stop()

    # ------------------------------------------------------------------
    # Activity tracking
    # ------------------------------------------------------------------

    def record_activity(self) -> None:
        """Delegate to the watchdog to reset the stall timer.

        Call this on every received WhatsApp event / message.
        """
        self._watchdog.record_activity()

    # ------------------------------------------------------------------
    # State-transition helpers
    # ------------------------------------------------------------------

    def note_connected(self) -> None:
        """Record a successful (re)connection.

        Resets the attempt counter and sets ``health_state`` to ``"connected"``.
        """
        prev = self._health_state
        self._health_state = "connected"
        self._attempts = 0
        _log.info(
            "WhatsApp connected",
            extra={"prev_state": prev, "health_state": self._health_state},
        )

    def note_disconnect(self, code: int | str | None) -> None:
        """Record a disconnection event with the given Baileys close code.

        Non-retryable codes (``401``, ``403``, ``440``) set
        ``stop_reconnect = True`` and map to a specific health state.
        All other codes map to ``"reconnecting"``.

        Args:
            code: The numeric or string disconnect code reported by Baileys.
                  ``None`` is treated as a generic retryable disconnect.
        """
        code_str: str | None = str(code) if code is not None else None
        self._last_code = code_str
        self._attempts += 1

        if code_str and code_str in NONRETRYABLE_CODES:
            new_state = _CODE_TO_STATE.get(code_str, "stopped")
            prev = self._health_state
            self._health_state = new_state
            self._stop_reconnect = True
            _log.warning(
                "WhatsApp non-retryable disconnect",
                extra={
                    "code": code_str,
                    "prev_state": prev,
                    "health_state": new_state,
                    "stop_reconnect": True,
                },
            )
        else:
            prev = self._health_state
            self._health_state = "reconnecting"
            _log.info(
                "WhatsApp retryable disconnect",
                extra={
                    "code": code_str,
                    "prev_state": prev,
                    "health_state": "reconnecting",
                    "attempt": self._attempts,
                },
            )

    def reset_stop_reconnect(self) -> None:
        """Clear the non-retryable stop flag so reconnect may resume.

        Only has an effect when ``stop_reconnect`` is currently ``True``.
        After clearing, ``health_state`` is set to ``"reconnecting"`` and the
        attempt counter is reset.
        """
        if self._stop_reconnect:
            _log.info(
                "Clearing stop_reconnect flag — supervisor resuming reconnect loop",
                extra={"prev_state": self._health_state},
            )
            self._stop_reconnect = False
            self._health_state = "reconnecting"
            self._attempts = 0

    # ------------------------------------------------------------------
    # Internal watchdog stall handler
    # ------------------------------------------------------------------

    async def _on_stall(self) -> None:
        """Invoked by :class:`PollingWatchdog` when a stall is detected.

        Silently no-ops when ``stop_reconnect`` is ``True``.  Exceptions from
        the user-supplied restart callback are swallowed so the watchdog loop
        continues.
        """
        if self._stop_reconnect:
            _log.debug("_on_stall: stop_reconnect=True, skipping restart callback")
            return
        _log.warning(
            "WhatsApp stall detected — invoking restart callback",
            extra={"health_state": self._health_state, "attempt": self._attempts},
        )
        try:
            await self._raw_restart_callback()
        except Exception:  # noqa: BLE001
            _log.exception("restart_callback raised an exception (suppressed)")

    # ------------------------------------------------------------------
    # Test helper
    # ------------------------------------------------------------------

    async def _trigger_stall_check_for_test(self) -> None:
        """Synchronously execute one iteration of the stall check logic.

        This is a **test-only** helper that bypasses the ``asyncio.sleep``
        inside ``PollingWatchdog._watch_loop`` so unit tests can drive time
        forward with a fake ``time.monotonic`` without waiting for real
        elapsed time.

        It reads ``_watchdog._last_activity`` directly (the same attribute
        :class:`PollingWatchdog` maintains) and calls :meth:`_on_stall` when
        the elapsed time exceeds the stall threshold.  After firing it resets
        ``_last_activity`` to prevent immediate re-triggering — mirroring the
        behaviour of the real watch loop.
        """
        elapsed: float = time.monotonic() - self._watchdog._last_activity
        if elapsed >= self._stall_threshold_s:
            await self._on_stall()
            # Reset so a second call in the same test doesn't immediately re-fire.
            self._watchdog._last_activity = time.monotonic()
