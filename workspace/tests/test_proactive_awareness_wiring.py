"""Phase 12 — PROA-01 (GentleWorker in lifespan), PROA-02 (send via registry),
PROA-03 (thermal guard preserved), PROA-04 (SSE event emit), PROA-02 cross-thread.

Wave 0: FAILING stubs (except PROA-03 regression guard which passes today).
Wave 2 Plan 12-03 flips them green.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gentle_worker import GentleWorker
from sci_fi_dashboard.pipeline_emitter import get_emitter


def _fake_config_with_identity_links():
    cfg = MagicMock()
    cfg.session = {
        "identityLinks": {
            "the_creator": ["919876543210@s.whatsapp.net"],
            "the_partner": ["919111111111@s.whatsapp.net"],
        }
    }
    return cfg


class TestProactiveWiring:
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_gentle_worker_present_on_app_state(self):
        from fastapi.testclient import TestClient
        from sci_fi_dashboard.api_gateway import app

        with TestClient(app) as _client:
            assert hasattr(
                app.state, "gentle_worker"
            ), "lifespan() must instantiate GentleWorker and attach to app.state.gentle_worker"
            assert isinstance(app.state.gentle_worker, GentleWorker)

    @pytest.mark.unit
    def test_thermal_guard_skips_when_on_battery(self, monkeypatch):
        import psutil

        battery_mock = MagicMock()
        battery_mock.power_plugged = False
        battery_mock.percent = 50
        monkeypatch.setattr(psutil, "sensors_battery", lambda: battery_mock)

        sched_mock = MagicMock()
        mock_graph = MagicMock()
        worker = GentleWorker(
            graph=mock_graph,
            proactive_engine=MagicMock(),
            channel_registry=MagicMock(),
        )
        monkeypatch.setattr(
            asyncio, "run_coroutine_threadsafe", lambda *a, **kw: sched_mock(*a, **kw)
        )

        worker.heavy_task_proactive_checkin()
        sched_mock.assert_not_called()

    @pytest.mark.unit
    def test_heavy_task_uses_run_coroutine_threadsafe(self, monkeypatch):
        import psutil

        battery_mock = MagicMock()
        battery_mock.power_plugged = True
        battery_mock.percent = 100
        monkeypatch.setattr(psutil, "sensors_battery", lambda: battery_mock)
        monkeypatch.setattr(psutil, "cpu_percent", lambda interval=1: 5.0)

        loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run_loop, daemon=True)
        t.start()
        try:
            rcts_mock = MagicMock()
            monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", rcts_mock)
            # Also patch asyncio.get_event_loop so heavy_task sees our running loop
            monkeypatch.setattr(asyncio, "get_event_loop", lambda: loop)

            mock_graph = MagicMock()
            worker = GentleWorker(
                graph=mock_graph,
                proactive_engine=AsyncMock(),
                channel_registry=MagicMock(),
            )
            worker._event_loop = loop

            invoked = threading.Event()

            def _call():
                worker.heavy_task_proactive_checkin()
                invoked.set()

            call_thread = threading.Thread(target=_call, daemon=True)
            call_thread.start()
            invoked.wait(timeout=5)

            assert invoked.is_set(), (
                "heavy_task_proactive_checkin did not complete within 5s — "
                "check_conditions may be returning False or raising"
            )
            assert (
                rcts_mock.called
            ), "heavy_task_proactive_checkin must call asyncio.run_coroutine_threadsafe"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            t.join(timeout=2)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_emits_proactive_sent_event(self, monkeypatch):
        monkeypatch.setattr(
            "synapse_config.SynapseConfig.load",
            classmethod(lambda cls: _fake_config_with_identity_links()),
        )

        engine = MagicMock()
        engine.maybe_reach_out = AsyncMock(return_value="hi there")

        fake_channel = MagicMock()
        fake_channel.send = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get = MagicMock(return_value=fake_channel)

        mock_graph = MagicMock()
        worker = GentleWorker(
            graph=mock_graph,
            proactive_engine=engine,
            channel_registry=registry,
        )

        emitter = get_emitter()
        queue = emitter.subscribe()
        try:
            await worker._async_proactive_checkin()
            received: list[str] = []
            for _ in range(5):
                try:
                    received.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            joined = "\n".join(received)
            assert (
                "event: proactive.sent" in joined
            ), f"Expected 'proactive.sent' SSE event, got: {joined!r}"
        finally:
            emitter.unsubscribe(queue)


class TestProactiveSendWiring:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_maybe_reach_out_dispatches_via_channel_registry(self, monkeypatch):
        monkeypatch.setattr(
            "synapse_config.SynapseConfig.load",
            classmethod(lambda cls: _fake_config_with_identity_links()),
        )

        engine = MagicMock()
        engine.maybe_reach_out = AsyncMock(return_value="proactive hi")

        fake_channel = MagicMock()
        fake_channel.send = AsyncMock(return_value=True)
        registry = MagicMock()
        registry.get = MagicMock(return_value=fake_channel)

        mock_graph = MagicMock()
        worker = GentleWorker(
            graph=mock_graph,
            proactive_engine=engine,
            channel_registry=registry,
        )
        await worker._async_proactive_checkin()
        assert fake_channel.send.await_count >= 1
