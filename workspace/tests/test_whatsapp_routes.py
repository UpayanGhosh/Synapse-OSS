"""Phase 12 — route-level tests for WA-FIX-01, WA-FIX-02, WA-FIX-03.

Wave 0: these tests are FAILING stubs. Wave 2 flips them green by:
- adding `await` at routes/whatsapp.py:147 (WA-FIX-01) — also unblocks WA-FIX-02
- adding `base["isLoggedOut"] = self._connection_state == "logged_out"` in
  channels/whatsapp.py:get_status (WA-FIX-03)
"""

from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WA_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.whatsapp") is not None
pytestmark = pytest.mark.skipif(not WA_AVAILABLE, reason="WhatsAppChannel not available")

if WA_AVAILABLE:
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel


# ===========================================================================
# WA-FIX-01 + WA-FIX-02 — route handler awaits update_connection_state
# ===========================================================================


class TestConnectionStateRoute:
    """Route-level coverage for POST /channels/whatsapp/connection-state."""

    def _build_app(self, monkeypatch, wa_channel):
        """Mount the connection-state route with channel_registry patched via monkeypatch."""
        from sci_fi_dashboard import _deps
        from sci_fi_dashboard.routes.whatsapp import router as whatsapp_router

        monkeypatch.setattr(
            _deps.channel_registry,
            "get",
            lambda ch_id: wa_channel if ch_id == "whatsapp" else None,
        )
        app = FastAPI()
        app.include_router(whatsapp_router)
        return app

    @pytest.mark.unit
    def test_route_awaits_update(self, monkeypatch):
        """WA-FIX-01: routes/whatsapp.py:147 MUST await update_connection_state."""
        mock_ch = MagicMock(spec=WhatsAppChannel)
        mock_ch.__class__ = WhatsAppChannel  # passes isinstance guard in route
        mock_ch.update_connection_state = AsyncMock(return_value=None)

        app = self._build_app(monkeypatch, mock_ch)
        client = TestClient(app)
        resp = client.post(
            "/channels/whatsapp/connection-state",
            json={"connectionState": "connected"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}  # confirms route reached happy path
        # Load-bearing assertion — FAILS TODAY because the coroutine is created
        # but never awaited (line 147 is synchronous).
        mock_ch.update_connection_state.assert_awaited_once()

    @pytest.mark.unit
    def test_515_routes_to_restart(self, monkeypatch):
        """WA-FIX-02: code 515 payload must reach _restart_bridge.

        Uses a REAL WhatsAppChannel instance so the test exercises actual
        update_connection_state logic, not a hand-rolled re-implementation.
        Only _restart_bridge is mocked to avoid subprocess side-effects.

        Fails today because WA-FIX-01 never awaits the coroutine, so the
        515 branch inside update_connection_state never runs.
        """
        ch = WhatsAppChannel(bridge_port=5010)  # real instance — real 515 logic
        ch._proc = None  # no subprocess running

        restart_mock = AsyncMock(return_value=None)
        monkeypatch.setattr(ch, "_restart_bridge", restart_mock)
        # Skip the 2-second sleep inside update_connection_state so the test is fast
        monkeypatch.setattr("asyncio.sleep", AsyncMock(return_value=None))

        app = self._build_app(monkeypatch, ch)
        client = TestClient(app)
        resp = client.post(
            "/channels/whatsapp/connection-state",
            json={"connectionState": "close", "lastDisconnectReason": 515},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        restart_mock.assert_awaited_once()


# ===========================================================================
# WA-FIX-03 — isLoggedOut field appears in get_status()
# ===========================================================================


class TestGetStatusIsLoggedOut:
    """Derived boolean `isLoggedOut` MUST appear in status payload."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_is_logged_out_true_when_connection_state_logged_out(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=5010)
        ch._connection_state = "logged_out"

        async def _fake_health_check():
            return {"status": "down", "channel": "whatsapp"}

        monkeypatch.setattr(ch, "health_check", _fake_health_check)
        status = await ch.get_status()
        # FAILS TODAY — field does not exist yet (WA-FIX-03 not applied)
        assert "isLoggedOut" in status
        assert status["isLoggedOut"] is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_is_logged_out_false_when_connected(self, monkeypatch):
        ch = WhatsAppChannel(bridge_port=5010)
        ch._connection_state = "connected"

        async def _fake_health_check():
            return {"status": "down", "channel": "whatsapp"}

        monkeypatch.setattr(ch, "health_check", _fake_health_check)
        status = await ch.get_status()
        assert "isLoggedOut" in status
        assert status["isLoggedOut"] is False
