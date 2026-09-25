from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import sys
import types
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from sci_fi_dashboard.gateway.durable_io import InboxStore
from sci_fi_dashboard.gateway.flood import FloodGate

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "inbox-tests"


@pytest.fixture
def inbox_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_inbound_is_durable_before_gate_accepts_and_replay_survives_restart(inbox_root: Path) -> None:
    store = InboxStore(inbox_root)
    gate = FloodGate(batch_window_seconds=0.01)
    gate.set_inbox_store(store)
    observed: list[tuple[str, bool]] = []

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        pending = store.unfinished()
        observed.append((text, any(row["message_id"] == metadata["message_id"] for row in pending)))

    gate.set_callback(on_batch)

    async def scenario() -> None:
        is_new = await gate.incoming(
            chat_id="whatsapp:+91-user-a",
            message="Remind me Saturday at 9 to get movie tickets",
            metadata={"message_id": "wa-event-1", "channel_id": "whatsapp"},
        )
        assert is_new is True
        assert [row["message_id"] for row in store.unfinished()] == ["wa-event-1"]
        await asyncio.sleep(0.03)
        assert observed == [
            ("Remind me Saturday at 9 to get movie tickets", True)
        ], "the callback must never see an acknowledged-but-uncaptured message"

    asyncio.run(scenario())

    restarted = InboxStore(inbox_root)
    assert [row["message_id"] for row in restarted.unfinished()] == ["wa-event-1"]
    restarted.mark_completed([restarted.unfinished()[0]["id"]])
    assert restarted.unfinished() == []


def test_duplicate_inbound_is_not_buffered_twice(inbox_root: Path) -> None:
    store = InboxStore(inbox_root)
    gate = FloodGate(batch_window_seconds=0.01)
    gate.set_inbox_store(store)
    delivered: list[str] = []

    async def on_batch(_chat_id: str, text: str, _metadata: dict) -> None:
        delivered.append(text)

    gate.set_callback(on_batch)

    async def scenario() -> None:
        first = await gate.incoming(
            "telegram:42", "hello", {"message_id": "tg-event-1", "channel_id": "telegram"}
        )
        second = await gate.incoming(
            "telegram:42", "hello", {"message_id": "tg-event-1", "channel_id": "telegram"}
        )
        assert first is True
        assert second is False
        await asyncio.sleep(0.03)
        assert delivered == ["hello"]

    asyncio.run(scenario())


def test_inbox_write_failure_prevents_acknowledgement_or_processing(inbox_root: Path) -> None:
    store = InboxStore(inbox_root)
    gate = FloodGate(batch_window_seconds=0.01)
    gate.set_inbox_store(store)
    processed: list[str] = []

    def fail_capture(*_args, **_kwargs):
        raise OSError("synthetic inbox disk failure")

    store.capture = fail_capture

    async def on_batch(_chat_id: str, text: str, _metadata: dict) -> None:
        processed.append(text)

    gate.set_callback(on_batch)

    async def scenario() -> None:
        with pytest.raises(OSError, match="synthetic inbox disk failure"):
            await gate.incoming(
                "discord:person-a", "do not lose me", {"message_id": "discord-event-1"}
            )
        await asyncio.sleep(0.03)
        assert processed == []

    asyncio.run(scenario())


class FakeInboundChannel:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    async def receive(self, raw: dict):
        return types.SimpleNamespace(
            channel_id=self.channel_id,
            chat_id=raw["chat_id"],
            text=raw["text"],
            message_id=raw["message_id"],
            sender_name="Synthetic user",
            is_group=False,
        )


class FakeChannelRegistry:
    def __init__(self):
        self.channels = {
            channel_id: FakeInboundChannel(channel_id)
            for channel_id in ("whatsapp", "telegram")
        }

    def get(self, channel_id: str):
        return self.channels.get(channel_id)


def load_route_with_fake_deps(monkeypatch, flood: FloodGate):
    package = importlib.import_module("sci_fi_dashboard")
    previous_modules = {
        name: sys.modules.get(name)
        for name in (
            "sci_fi_dashboard._deps",
            "sci_fi_dashboard.channels",
            "sci_fi_dashboard.channels.base",
            "sci_fi_dashboard.channels.whatsapp",
            "sci_fi_dashboard.observability",
            "sci_fi_dashboard.routes",
            "sci_fi_dashboard.routes.whatsapp",
        )
    }
    previous_attr = getattr(package, "_deps", None)
    routes_module = sys.modules.get("sci_fi_dashboard.routes")
    missing_route_attr = object()
    previous_route_attr = (
        getattr(routes_module, "whatsapp", missing_route_attr)
        if routes_module is not None
        else missing_route_attr
    )
    deps = types.ModuleType("sci_fi_dashboard._deps")
    deps.channel_registry = FakeChannelRegistry()
    deps.flood = flood
    deps.task_queue = types.SimpleNamespace(pending_count=0)
    deps._require_gateway_auth = lambda: None
    deps.WhatsAppLoopTestRequest = type(
        "WhatsAppLoopTestRequest",
        (BaseModel,),
        {"__annotations__": {"target": str}},
    )
    deps.get_inbound_message = lambda _message_id: None
    deps.validate_bridge_token = lambda _request: None
    deps.normalize_phone = lambda value: value
    deps._synapse_cfg = types.SimpleNamespace(heartbeat={})
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard._deps", deps)
    package._deps = deps

    channels_package = types.ModuleType("sci_fi_dashboard.channels")
    channels_package.__path__ = []
    base_module = types.ModuleType("sci_fi_dashboard.channels.base")
    base_module.ChannelMessage = type("ChannelMessage", (), {})
    whatsapp_module = types.ModuleType("sci_fi_dashboard.channels.whatsapp")
    whatsapp_module.WhatsAppChannel = type("WhatsAppChannel", (), {})
    channels_package.base = base_module
    channels_package.whatsapp = whatsapp_module
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.channels", channels_package)
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.channels.base", base_module)
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.channels.whatsapp", whatsapp_module)

    observability = types.ModuleType("sci_fi_dashboard.observability")
    observability.get_child_logger = lambda _name: logging.getLogger(_name)
    observability.mint_run_id = lambda: "synthetic-run-id"
    observability.redact_identifier = lambda value: value
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.observability", observability)
    # Another test module may have imported the route with its own `_deps`
    # already bound. Force a fresh import against this fixture's fake deps.
    sys.modules.pop("sci_fi_dashboard.routes.whatsapp", None)
    module = importlib.import_module("sci_fi_dashboard.routes.whatsapp")

    def cleanup() -> None:
        sys.modules.pop("sci_fi_dashboard.routes.whatsapp", None)
        for name, old in previous_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
        routes_module = sys.modules.get("sci_fi_dashboard.routes")
        if routes_module is not None:
            if previous_route_attr is missing_route_attr:
                with contextlib.suppress(AttributeError):
                    delattr(routes_module, "whatsapp")
            else:
                routes_module.whatsapp = previous_route_attr
        if previous_modules["sci_fi_dashboard.routes"] is None:
            with contextlib.suppress(AttributeError):
                delattr(package, "routes")
        if previous_attr is None:
            with contextlib.suppress(AttributeError):
                delattr(package, "_deps")
        else:
            package._deps = previous_attr

    return module, deps, cleanup


def make_request(raw: dict):
    from starlette.requests import Request

    body = __import__("json").dumps(raw).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/channels/webhook",
            "headers": [],
            "query_string": b"",
            "client": ("test", 1234),
            "server": ("test", 80),
            "scheme": "http",
        },
        receive,
    )


def test_webhook_ack_follows_inbox_commit_and_dedupes_by_channel(monkeypatch, inbox_root: Path) -> None:
    store = InboxStore(inbox_root)
    flood = FloodGate(batch_window_seconds=60)
    flood.set_inbox_store(store)
    route, deps, cleanup = load_route_with_fake_deps(monkeypatch, flood)
    raw = {"message_id": "provider-id-1", "chat_id": "peer-a", "text": "remember this"}

    async def scenario() -> None:
        first = await route.unified_webhook("whatsapp", make_request(raw))
        assert first["accepted"] is True
        assert first["status"] == "queued"
        assert len(store.unfinished()) == 1

        duplicate = await route.unified_webhook("whatsapp", make_request(raw))
        assert duplicate["accepted"] is True
        assert duplicate["status"] == "skipped"
        assert len(store.unfinished()) == 1

        other_channel = await route.unified_webhook("telegram", make_request(raw))
        assert other_channel["accepted"] is True
        assert other_channel["status"] == "queued"
        assert len(store.unfinished()) == 2

    try:
        asyncio.run(scenario())
    finally:
        for task in flood._tasks.values():
            task.cancel()
        cleanup()


def test_webhook_returns_503_when_inbox_commit_fails_then_accepts_retry(
    monkeypatch, inbox_root: Path
) -> None:
    store = InboxStore(inbox_root)
    flood = FloodGate(batch_window_seconds=60)
    flood.set_inbox_store(store)
    route, _deps, cleanup = load_route_with_fake_deps(monkeypatch, flood)
    raw = {"message_id": "provider-id-2", "chat_id": "peer-a", "text": "do not lose this"}
    original_capture = store.capture

    def failed_capture(*_args, **_kwargs):
        raise OSError("synthetic disk full")

    store.capture = failed_capture

    async def scenario() -> None:
        with pytest.raises(HTTPException) as failure:
            await route.unified_webhook("whatsapp", make_request(raw))
        assert failure.value.status_code == 503
        assert store.unfinished() == []

        store.capture = original_capture
        accepted = await route.unified_webhook("whatsapp", make_request(raw))
        assert accepted["status"] == "queued"
        assert accepted["accepted"] is True
        assert len(store.unfinished()) == 1

    try:
        asyncio.run(scenario())
    finally:
        for task in flood._tasks.values():
            task.cancel()
        cleanup()
