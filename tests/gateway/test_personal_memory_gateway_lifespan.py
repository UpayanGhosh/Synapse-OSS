from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytest.importorskip("pyarrow", reason="run with the isolated gateway runtime target")

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard import api_gateway
from sci_fi_dashboard.personal_memory import PersonMemoryContext

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "gateway-lifespan"


class FakeChannelRegistry:
    def __init__(self) -> None:
        self.send_count = 0

    async def start_all(self) -> None:
        return None

    async def stop_all(self) -> None:
        return None

    def get(self, _channel_id: str):
        return None


class FakeRouter:
    async def call(self, *_args, **_kwargs) -> str:
        return json.dumps({"confirmed_facts": [], "relationship_updates": []})


def test_gateway_lifespan_runs_personal_enrichment_without_proactive_or_live_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = TEST_DATA_ROOT / uuid4().hex
    data_root.mkdir(parents=True, exist_ok=False)
    cfg = deps._synapse_cfg
    isolated_cfg = replace(
        cfg,
        data_root=data_root,
        db_dir=data_root,
        session_auto_flush=replace(cfg.session_auto_flush, enabled=False),
        heartbeat={"enabled": False},
    )
    monkeypatch.setattr(deps, "_synapse_cfg", isolated_cfg)
    monkeypatch.setattr(api_gateway, "apply_logging_config", lambda *_args: None)
    monkeypatch.setattr(api_gateway, "ensure_bridge_db", lambda: None)
    monkeypatch.setattr(api_gateway, "gentle_worker_loop", _wait_forever)
    monkeypatch.setattr(deps, "channel_registry", FakeChannelRegistry())
    monkeypatch.setattr(deps, "synapse_llm_router", FakeRouter())
    monkeypatch.setattr(deps, "personal_memory_service", None, raising=False)
    monkeypatch.setattr(deps, "_TOOL_REGISTRY_AVAILABLE", False)
    monkeypatch.setattr(deps, "_TOOL_SAFETY_AVAILABLE", False)
    monkeypatch.setattr(deps, "_SKILL_SYSTEM_AVAILABLE", False)
    monkeypatch.setattr(deps, "sbs_registry", {})
    monkeypatch.setattr(deps.brain, "save_graph", lambda: None)
    monkeypatch.setattr(deps, "init_diary_engine", lambda: None)
    monkeypatch.setattr(deps, "skill_watcher", None)
    monkeypatch.setattr("sci_fi_dashboard.gentle_worker.GentleWorker.start", lambda _self: None)
    monkeypatch.setattr(
        "mcp_config.load_mcp_config",
        lambda *_args: SimpleNamespace(
            enabled=False,
            proactive=SimpleNamespace(enabled=False),
        ),
    )

    async def scenario() -> None:
        app = api_gateway.FastAPI(lifespan=api_gateway.lifespan)
        async with api_gateway.lifespan(app):
            assert app.state.proactive_engine is None
            service = app.state.personal_memory_service
            pump = service._task
            assert pump is not None and not pump.done()
            assert deps.personal_memory_service is service
            assert app.state.worker.personal_memory_service is service
            context = PersonMemoryContext("person:lifespan-test", "test:direct", "private")
            episode_id = service.capture_user_turn(
                context,
                source_message_id="lifespan-user-turn",
                content="Please keep replies concise.",
                occurred_at="2026-09-24T10:00:00+00:00",
            )
            assert episode_id
            deadline = asyncio.get_running_loop().time() + 8
            while asyncio.get_running_loop().time() < deadline:
                with sqlite3.connect(service.store.db_path) as conn:
                    row = conn.execute(
                        "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
                        (episode_id,),
                    ).fetchone()
                if row and row[0] == "processed":
                    break
                await asyncio.sleep(0.05)
            assert row == ("processed",)
            assert deps.channel_registry.send_count == 0

        assert service._task is None or service._task.done()

    asyncio.run(asyncio.wait_for(scenario(), timeout=12))


async def _wait_forever() -> None:
    await asyncio.Event().wait()
