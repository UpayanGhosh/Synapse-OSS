"""Phase 14 Wave 0 -- failing stubs for SUPV-01..04.

Every test imports from sci_fi_dashboard.channels.supervisor which does NOT
YET EXIST. pytest.importorskip makes these tests SKIP (green suite) until
Wave 1 (Plan 02) lands the module; once it does, the tests turn RED and
Wave 1 implementation work flips them GREEN.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip(
    "sci_fi_dashboard.channels.supervisor",
    reason="Phase 14 supervisor module not yet installed (Wave 1)",
)

from sci_fi_dashboard.channels.supervisor import (  # noqa: E402
    NONRETRYABLE_CODES,
    STATE_MAP,
    WA_SILENCE_THRESHOLD_S,
    ReconnectPolicy,
    WhatsAppSupervisor,
)


# ===========================================================================
# SUPV-01: Watchdog stall detection
# ===========================================================================


class TestWatchdog:
    """SUPV-01: Silence watchdog fires restart_callback after stall threshold."""

    @pytest.mark.asyncio
    async def test_watchdog_fires_after_silence(self):
        """After WA_SILENCE_THRESHOLD_S + 60s without activity, restart_callback is awaited."""
        restart_cb = AsyncMock()
        policy = ReconnectPolicy()
        sup = WhatsAppSupervisor(restart_callback=restart_cb, policy=policy)

        fake_time = [0.0]
        with patch(
            "sci_fi_dashboard.channels.polling_watchdog.time.monotonic",
            lambda: fake_time[0],
        ):
            await sup.start()
            fake_time[0] = WA_SILENCE_THRESHOLD_S + 60
            await sup._trigger_stall_check_for_test()
            await sup.stop()

        assert restart_cb.await_count == 1, (
            f"Expected restart_callback to be awaited once, got {restart_cb.await_count}"
        )

    @pytest.mark.asyncio
    async def test_activity_resets_timer(self):
        """record_activity() at t=1700 prevents a stall at t=2000 (gap only 300s < threshold)."""
        restart_cb = AsyncMock()
        policy = ReconnectPolicy()
        sup = WhatsAppSupervisor(restart_callback=restart_cb, policy=policy)

        fake_time = [0.0]
        with patch(
            "sci_fi_dashboard.channels.polling_watchdog.time.monotonic",
            lambda: fake_time[0],
        ):
            await sup.start()
            # Advance to t=1700 and record activity — timer resets
            fake_time[0] = 1700.0
            sup.record_activity()
            # Advance to t=2000 — gap is only 300s, below the threshold of 1800s
            fake_time[0] = 2000.0
            await sup._trigger_stall_check_for_test()
            await sup.stop()

        assert restart_cb.await_count == 0, (
            f"Expected no restart (gap < threshold), got {restart_cb.await_count} calls"
        )


# ===========================================================================
# SUPV-02: Reconnect policy backoff
# ===========================================================================


class TestReconnectPolicy:
    """SUPV-02: ReconnectPolicy dataclass defaults and backoff curve."""

    def test_reconnect_policy_defaults(self):
        """ReconnectPolicy() has correct default values."""
        p = ReconnectPolicy()
        assert p.initial_ms == 1000
        assert p.max_ms == 60000
        assert p.factor == 2.0
        assert p.jitter == 0.2
        assert p.max_attempts == 5

    def test_reconnect_policy_backoff_curve(self):
        """With no jitter, backoff doubles per attempt and clamps at max_ms."""
        p = ReconnectPolicy(initial_ms=100, max_ms=1000, factor=2.0, jitter=0.0)
        # attempt 0 → 0.1s, 1 → 0.2s, 2 → 0.4s, 3 → 0.8s, 4 → 1.0s (clamped)
        expected = [0.1, 0.2, 0.4, 0.8, 1.0]
        for attempt, exp in enumerate(expected):
            result = p.compute_backoff_s(attempt)
            assert abs(result - exp) < 1e-9, (
                f"attempt={attempt}: expected {exp}, got {result}"
            )

    def test_reconnect_policy_jitter_envelope(self):
        """With jitter=0.5, 100 samples of compute_backoff_s(3) all fall in [4.0, 12.0]."""
        p = ReconnectPolicy(
            initial_ms=1000, max_ms=60000, factor=2.0, jitter=0.5, max_attempts=10
        )
        # base at attempt 3: 1000 * 2^3 = 8000ms = 8.0s; ±50% → [4.0, 12.0]
        for i in range(100):
            val = p.compute_backoff_s(3)
            assert 4.0 <= val <= 12.0, (
                f"Sample {i}: compute_backoff_s(3)={val} outside [4.0, 12.0]"
            )

    def test_reconnect_policy_config_override(self, tmp_path, monkeypatch):
        """synapse.json reconnect block overrides ReconnectPolicy defaults when loaded."""
        config_data = {
            "reconnect": {
                "initialMs": 2000,
                "maxAttempts": 3,
            }
        }
        config_file = tmp_path / "synapse.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        # Monkeypatch SYNAPSE_HOME so SynapseConfig reads from tmp_path
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

        # Lazy import to pick up the monkeypatched env
        from sci_fi_dashboard.channels.supervisor import load_reconnect_policy_from_config

        loaded = load_reconnect_policy_from_config(config_file)

        assert loaded.initial_ms == 2000, f"Expected 2000, got {loaded.initial_ms}"
        assert loaded.max_attempts == 3, f"Expected 3, got {loaded.max_attempts}"
        # max_ms not overridden — should retain default
        assert loaded.max_ms == 60000, f"Expected default 60000, got {loaded.max_ms}"


# ===========================================================================
# SUPV-03: Health state transitions
# ===========================================================================


class TestHealthState:
    """SUPV-03: WhatsAppSupervisor.health_state transitions through lifecycle events."""

    def test_health_state_field(self):
        """Fresh instance is 'stopped'; after note_connected() it is 'connected'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        assert sup.health_state == "stopped"
        sup.note_connected()
        assert sup.health_state == "connected"

    def test_health_state_transitions(self):
        """Full transition path: connected → reconnecting → connected."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_connected()
        assert sup.health_state == "connected"

        sup.note_disconnect("428")  # retryable
        assert sup.health_state == "reconnecting"

        sup.note_connected()
        assert sup.health_state == "connected"

    def test_health_state_uses_hyphen_not_underscore(self):
        """note_disconnect('401') yields 'logged-out' (hyphen), never 'logged_out'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("401")
        state = sup.health_state
        assert state == "logged-out", f"Expected 'logged-out', got '{state}'"
        assert state != "logged_out", "State must use hyphen, not underscore"

    def test_health_state_unknown_maps_to_stopped(self):
        """An unknown disconnect code maps to a valid STATE_MAP value or 'stopped'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("9999")
        valid_states = set(STATE_MAP.values()) | {"stopped"}
        assert sup.health_state in valid_states, (
            f"health_state '{sup.health_state}' is not in {valid_states}"
        )
        assert sup.health_state != "9999", "Unknown code must not leak into health_state"


# ===========================================================================
# SUPV-04: Non-retryable code handling
# ===========================================================================


class TestNonRetryable:
    """SUPV-04: NONRETRYABLE_CODES set stop_reconnect=True and correct health_state."""

    def test_nonretryable_440_stops_loop(self):
        """Disconnect code '440' (conflict) sets stop_reconnect=True, health_state='conflict'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_connected()
        sup.note_disconnect("440")
        assert sup.stop_reconnect is True, "440 must set stop_reconnect=True"
        assert sup.health_state == "conflict", (
            f"Expected 'conflict', got '{sup.health_state}'"
        )

    def test_nonretryable_401_stops_loop(self):
        """Disconnect code '401' sets stop_reconnect=True, health_state='logged-out'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("401")
        assert sup.stop_reconnect is True, "401 must set stop_reconnect=True"
        assert sup.health_state == "logged-out", (
            f"Expected 'logged-out', got '{sup.health_state}'"
        )

    def test_nonretryable_403_stops_loop(self):
        """Disconnect code '403' sets stop_reconnect=True, health_state='logged-out'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("403")
        assert sup.stop_reconnect is True, "403 must set stop_reconnect=True"
        assert sup.health_state == "logged-out", (
            f"Expected 'logged-out', got '{sup.health_state}'"
        )

    def test_retryable_code_continues(self):
        """Retryable code '428' sets stop_reconnect=False, health_state='reconnecting'."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("428")
        assert sup.stop_reconnect is False, "428 must NOT set stop_reconnect"
        assert sup.health_state == "reconnecting", (
            f"Expected 'reconnecting', got '{sup.health_state}'"
        )

    def test_relink_clears_stop_flag(self):
        """reset_stop_reconnect() clears the stop flag after a non-retryable disconnect."""
        sup = WhatsAppSupervisor(
            restart_callback=AsyncMock(),
            policy=ReconnectPolicy(),
        )
        sup.note_disconnect("401")
        assert sup.stop_reconnect is True  # precondition

        sup.reset_stop_reconnect()
        assert sup.stop_reconnect is False, (
            "reset_stop_reconnect() must clear stop_reconnect flag"
        )
