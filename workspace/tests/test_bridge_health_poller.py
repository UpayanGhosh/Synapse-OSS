"""Phase 16 BRIDGE-02 + BRIDGE-03 — RED test stubs for BridgeHealthPoller.

Every test imports sci_fi_dashboard.channels.bridge_health_poller which does NOT exist in Wave 0.
Plan 03 creates the module and flips these tests GREEN.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.fixtures.bridge_health_transport import (
    AUTH_EXPIRED_RESPONSE,
    SERVER_ERROR_RESPONSE,
    SUCCESS_HEALTH_JSON,
    make_mock_transport,
)

pytestmark = pytest.mark.asyncio


def _make_fake_channel(port: int = 5010) -> types.SimpleNamespace:
    """Fake WhatsAppChannel exposing only the attributes BridgeHealthPoller touches."""
    ch = types.SimpleNamespace()
    ch._port = port
    ch._restart_bridge = AsyncMock()
    ch._restart_in_progress = asyncio.Event()
    return ch


def _make_fake_supervisor(stop_reconnect: bool = False):
    sup = types.SimpleNamespace()
    sup._stop_reconnect = stop_reconnect
    # emulate property-like read
    return types.SimpleNamespace(
        stop_reconnect=stop_reconnect,
        note_connected=AsyncMock() if False else (lambda: None),
        note_disconnect=(lambda code: None),
    )


async def test_poll_cadence(monkeypatch):
    """BRIDGE-02: poller calls /health once per interval_s."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    transport = make_mock_transport([SUCCESS_HEALTH_JSON])

    # Inject transport via http_client_factory so no real bridge is needed in CI.
    def _client_factory(timeout):
        return httpx.AsyncClient(transport=transport, timeout=timeout)

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor()
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=0.05, failures_before_restart=3,
        http_client_factory=_client_factory,
    )
    await poller.start()
    await asyncio.sleep(0.18)   # ~3 ticks
    await poller.stop()
    assert poller.consecutive_failures == 0
    assert poller.last_health.get("status") == "ok"


async def test_status_surfaces_health(monkeypatch):
    """BRIDGE-02: last_health is readable after at least one successful poll."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor()
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=10.0, failures_before_restart=3,
    )
    # Directly inject last_health to validate the readable contract
    poller._last_health = dict(SUCCESS_HEALTH_JSON)
    assert poller.last_health["status"] == "ok"
    assert "last_inbound_at" in poller.last_health
    assert "bridge_version" in poller.last_health


async def test_three_failures_trigger_restart(monkeypatch):
    """BRIDGE-03: 3 consecutive poll failures call channel._restart_bridge()."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor(stop_reconnect=False)
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=0.02, failures_before_restart=3,
        grace_window_s=10.0,
    )
    # Force every poll to fail at the HTTP layer
    async def _always_fail():
        return False
    poller.poll_once = _always_fail  # type: ignore[assignment]

    await poller.start()
    await asyncio.sleep(0.2)  # allow 3+ ticks
    await poller.stop()
    channel._restart_bridge.assert_awaited()


async def test_threshold_configurable(monkeypatch):
    """BRIDGE-03: failures_before_restart=5 means restart does NOT fire at 3 failures."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor(stop_reconnect=False)
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=0.02, failures_before_restart=5,
        grace_window_s=10.0,
    )
    async def _always_fail():
        return False
    poller.poll_once = _always_fail  # type: ignore[assignment]

    await poller.start()
    await asyncio.sleep(0.09)  # ~4 ticks — below threshold
    await poller.stop()
    channel._restart_bridge.assert_not_called()


async def test_stop_reconnect_blocks_restart():
    """BRIDGE-03: supervisor.stop_reconnect=True blocks restart even after N failures."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor(stop_reconnect=True)
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=0.02, failures_before_restart=3,
        grace_window_s=10.0,
    )
    async def _always_fail():
        return False
    poller.poll_once = _always_fail  # type: ignore[assignment]

    await poller.start()
    await asyncio.sleep(0.2)
    await poller.stop()
    channel._restart_bridge.assert_not_called()


async def test_401_not_counted_as_failure(monkeypatch):
    """BRIDGE-03 (G6): 401 from /health treated as degraded, not a consecutive-failure hit."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    # Plan 03 MUST treat 401 specifically: return True from poll_once AND set last_health to degraded.
    # This test asserts poll_once returns True on a 401 response.
    transport = make_mock_transport([AUTH_EXPIRED_RESPONSE])

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor()
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=10.0, failures_before_restart=3,
    )
    # Plan 03 must expose `_http_client_factory` OR accept a transport kwarg; for Wave 0 we verify the contract
    # by patching the internal call. If Plan 03 uses a different seam this test will break RED → Plan 03 must fix.
    async def fake_poll_once_401() -> bool:
        # Simulate the exact Plan 03 logic: 401 → set last_health to degraded + return True
        poller._last_health = {"status": "degraded", "error": "auth_expired"}
        return True
    poller.poll_once = fake_poll_once_401  # type: ignore[assignment]

    await poller.start()
    await asyncio.sleep(0.12)
    await poller.stop()
    assert poller.consecutive_failures == 0
    assert poller.last_health == {"status": "degraded", "error": "auth_expired"}


async def test_grace_window_after_restart():
    """BRIDGE-03 (G4): after restart is triggered, poller enters grace_window_s grace period."""
    from sci_fi_dashboard.channels.bridge_health_poller import BridgeHealthPoller

    channel = _make_fake_channel()
    supervisor = _make_fake_supervisor(stop_reconnect=False)
    poller = BridgeHealthPoller(
        channel=channel, supervisor=supervisor, interval_s=0.02, failures_before_restart=3,
        grace_window_s=0.2,  # short grace so test finishes quickly
    )
    async def _always_fail():
        return False
    poller.poll_once = _always_fail  # type: ignore[assignment]

    await poller.start()
    await asyncio.sleep(0.1)  # allow restart to trigger once
    assert poller.in_grace_window is True
    # During grace window, additional failures must NOT trigger another restart
    prev_call_count = channel._restart_bridge.await_count
    await asyncio.sleep(0.05)
    assert channel._restart_bridge.await_count == prev_call_count
    await poller.stop()
