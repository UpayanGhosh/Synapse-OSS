"""Behavioral acceptance for the production inbound conversation boundary."""

from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from sci_fi_dashboard.personal_memory import PersonalizedReply, PersonMemoryContext

try:
    from sci_fi_dashboard import pipeline_helpers
except ModuleNotFoundError as exc:
    if exc.name != "pyarrow":
        raise
    sys.modules["sci_fi_dashboard._deps"] = ModuleType("sci_fi_dashboard._deps")
    from sci_fi_dashboard import pipeline_helpers


class CaptureSpy:
    def __init__(self) -> None:
        self.calls = []
        self.assistant_calls = []

    def capture_user_turn(self, context, **kwargs):
        self.calls.append((context, kwargs))
        return "episode-1"

    def record_assistant_reply(self, context, **kwargs):
        self.assistant_calls.append((context, kwargs))


class CacheSpy:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        self.values[key] = list(value)

    def append(self, key, value):
        self.values.setdefault(key, []).append(value)

    def invalidate(self, key):
        self.values.pop(key, None)


@pytest.fixture
def inbound_runtime(monkeypatch: pytest.MonkeyPatch):
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "runtime-wiring" / uuid4().hex
    root.mkdir(parents=True)
    cfg = SimpleNamespace(
        data_root=root,
        db_dir=root / "db",
        session={"dmScope": "main", "identityLinks": {}},
        channels={},
        tts={"enabled": False},
    )
    monkeypatch.setattr(pipeline_helpers.SynapseConfig, "load", lambda: cfg)
    monkeypatch.setattr(pipeline_helpers.deps, "_resolve_target", lambda _chat: "the_creator", raising=False)
    capture = CaptureSpy()
    monkeypatch.setattr(pipeline_helpers.deps, "personal_memory_service", capture, raising=False)
    seen = []
    spawn = ModuleType("sci_fi_dashboard.subagent.spawn")

    async def maybe_spawn_agent(**kwargs):
        seen.append((kwargs, len(capture.calls)))
        return "Agent started"

    spawn.maybe_spawn_agent = maybe_spawn_agent
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.subagent.spawn", spawn)
    return capture, seen


def test_channel_turn_is_durably_captured_before_early_spawn_and_person_scoped(inbound_runtime):
    capture, seen = inbound_runtime
    received = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)
    for peer, message_id in (("alice-phone", "wa-a"), ("bob-phone", "wa-b")):
        kwargs = {
            "channel_id": "whatsapp",
            "source_message_key": message_id,
        }
        if "source_received_at" in inspect.signature(pipeline_helpers.process_message_pipeline).parameters:
            kwargs["source_received_at"] = received
        asyncio.run(
            pipeline_helpers.process_message_pipeline(
                f"My tiny umbrella joke was funny, {peer}.",
                peer,
                **kwargs,
            )
        )
    assert len(seen) == 2
    assert len(capture.calls) == 2
    assert all(count == 1 for _kwargs, count in seen[:1])
    assert seen[1][1] == 2
    alice, bob = (item[0] for item in capture.calls)
    assert alice.person_id != bob.person_id
    assert alice.conversation_id != bob.conversation_id
    assert seen[0][0]["session_key"] != seen[1][0]["session_key"]
    assert capture.calls[0][1]["source_message_id"] == "wa-a"
    assert capture.calls[0][1]["occurred_at"] == received


def test_normal_channel_reply_passes_verified_scope_and_never_syncs_global_personal_profile(
    inbound_runtime, monkeypatch: pytest.MonkeyPatch
):
    capture, _seen = inbound_runtime
    monkeypatch.setattr(pipeline_helpers.deps, "conversation_cache", CacheSpy(), raising=False)
    monkeypatch.setattr(pipeline_helpers, "_maybe_handle_reminder_control", lambda *_a, **_k: None)

    async def no_reminder(*_a, **_k):
        return None

    async def no_flush(**_kwargs):
        return None

    monkeypatch.setattr(pipeline_helpers, "_maybe_handle_reminder_command", no_reminder)
    monkeypatch.setattr(pipeline_helpers, "_maybe_schedule_passive_commitment_nudge", no_reminder)
    monkeypatch.setattr(pipeline_helpers, "_maybe_schedule_periodic_memory_flush", no_flush)
    sync_calls = []
    monkeypatch.setattr(
        pipeline_helpers,
        "_sync_user_turn_memory",
        lambda **kwargs: sync_calls.append(kwargs) or 0,
    )
    spawn = sys.modules["sci_fi_dashboard.subagent.spawn"]

    async def no_spawn(**_kwargs):
        return None

    monkeypatch.setattr(spawn, "maybe_spawn_agent", no_spawn)
    chat_module = ModuleType("sci_fi_dashboard.chat_pipeline")
    calls = []

    async def persona_chat(request, _target, _background_tasks, **kwargs):
        calls.append((request, kwargs, len(capture.calls)))
        return {"reply": "Yep, tiny umbrella."}

    chat_module.persona_chat = persona_chat
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.chat_pipeline", chat_module)

    reply = asyncio.run(
        pipeline_helpers.process_message_pipeline(
            "Our tiny umbrella joke is back.",
            "alice-phone",
            channel_id="whatsapp",
            source_message_key="wa-normal-1",
        )
    )

    assert "tiny umbrella" in str(reply)
    assert isinstance(reply, PersonalizedReply)
    assert reply.source_episode_id == "episode-1"
    assert calls[0][2] == 1
    assert calls[0][1]["person_context"] == capture.calls[0][0]
    assert calls[0][1]["exclude_episode_id"] == "episode-1"
    assert len(sync_calls) == 1
    assert sync_calls[0]["person_context"] == capture.calls[0][0]
    assert sync_calls[0]["source_episode_id"] == "episode-1"


def test_direct_api_route_uses_server_token_principal_not_caller_identity(
    inbound_runtime, monkeypatch: pytest.MonkeyPatch
):
    from fastapi import BackgroundTasks
    from sci_fi_dashboard import middleware
    from sci_fi_dashboard.schemas import ChatRequest

    monkeypatch.setattr(pipeline_helpers.deps, "PERSONAS_CONFIG", {"personas": []}, raising=False)
    monkeypatch.setattr(pipeline_helpers.deps, "_check_rate_limit", lambda _request: None, raising=False)
    from sci_fi_dashboard.routes import chat as chat_routes

    observed = []

    async def fake_direct(_request, _target, _background_tasks, **kwargs):
        observed.append(kwargs.get("person_context"))
        return {"reply": "okay"}

    monkeypatch.setattr(chat_routes, "process_direct_persona_chat", fake_direct)
    handler = chat_routes._make_persona_handler("the_creator")
    body = ChatRequest(
        message="Remember my umbrella joke",
        user_id="pretend-to-be-bob",
        session_key="pretend-to-be-bob-session",
    )
    request = SimpleNamespace(headers={"x-api-key": "known-token"})
    monkeypatch.setattr(middleware, "_expected_gateway_token", lambda: "known-token")
    monkeypatch.setattr(chat_routes, "_expected_gateway_token", lambda: "known-token")
    asyncio.run(handler(body, BackgroundTasks(), request))
    assert observed[-1] is not None
    assert observed[-1].person_id == "local-api-owner"

    monkeypatch.setattr(middleware, "_expected_gateway_token", lambda: "")
    monkeypatch.setattr(chat_routes, "_expected_gateway_token", lambda: "")
    asyncio.run(handler(body, BackgroundTasks(), request))
    assert observed[-1] is None


def test_direct_api_helper_captures_under_server_owner_and_passes_scoped_context(
    inbound_runtime, monkeypatch: pytest.MonkeyPatch
):
    from sci_fi_dashboard.schemas import ChatRequest

    capture, _seen = inbound_runtime
    monkeypatch.setattr(pipeline_helpers.deps, "conversation_cache", CacheSpy(), raising=False)
    async def no_nudge(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline_helpers, "_maybe_schedule_passive_commitment_nudge", no_nudge)

    async def no_flush(**_kwargs):
        return None

    monkeypatch.setattr(pipeline_helpers, "_maybe_schedule_periodic_memory_flush", no_flush)
    sync_calls = []
    monkeypatch.setattr(
        pipeline_helpers,
        "_sync_user_turn_memory",
        lambda **kwargs: sync_calls.append(kwargs) or 0,
    )
    chat_module = ModuleType("sci_fi_dashboard.chat_pipeline")
    calls = []

    async def persona_chat(request, _target, _background_tasks, **kwargs):
        calls.append((request, kwargs, len(capture.calls)))
        return {"reply": "Yep, I remember that umbrella."}

    chat_module.persona_chat = persona_chat
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.chat_pipeline", chat_module)
    request = ChatRequest(
        message="That tiny umbrella joke cracked me up.",
        user_id="caller-supplied-bob",
        session_key="caller-supplied-bob-session",
    )
    context = PersonMemoryContext("local-api-owner", "api:local-api-owner")
    kwargs = {"person_context": context} if "person_context" in inspect.signature(pipeline_helpers.process_direct_persona_chat).parameters else {}
    result = asyncio.run(
        pipeline_helpers.process_direct_persona_chat(request, "the_creator", **kwargs)
    )

    assert result["reply"].startswith("Yep")
    assert len(capture.calls) == 1
    assert capture.calls[0][0].person_id == "local-api-owner"
    assert calls[0][2] == 1
    assert calls[0][1]["person_context"].person_id == "local-api-owner"
    assert calls[0][1]["exclude_episode_id"] == "episode-1"
    assert sync_calls[0]["person_context"].person_id == "local-api-owner"
    assert "caller-supplied-bob" not in calls[0][0].session_key
    assert len(capture.assistant_calls) == 1
    assert capture.assistant_calls[0][1]["source_episode_id"] == "episode-1"
    assert capture.assistant_calls[0][1]["delivery_state"] == "returned"


def test_generic_chat_webhook_marks_server_verified_api_origin(inbound_runtime, monkeypatch):
    monkeypatch.setattr(
        pipeline_helpers.deps, "_check_rate_limit", lambda _request: None, raising=False
    )
    monkeypatch.setattr(pipeline_helpers.deps, "PERSONAS_CONFIG", {"personas": []}, raising=False)
    from sci_fi_dashboard.routes import chat as chat_routes

    seen = []

    class Flood:
        async def incoming(self, **kwargs):
            seen.append(kwargs)

    class Request:
        headers = {}

        async def json(self):
            return {
                "message": "My private umbrella story",
                "chat_id": "alice-phone",
                "user_id": "pretend-to-be-bob",
                "message_id": "api-message-1",
                "person_origin": "channel",
                "api_authenticated": True,
                "person_context": {"person_id": "whatsapp:bob-phone"},
            }

    monkeypatch.setattr(chat_routes.deps, "validate_api_key", lambda _request: None, raising=False)
    monkeypatch.setattr(chat_routes.deps, "flood", Flood(), raising=False)
    monkeypatch.setattr(chat_routes.deps, "dedup", SimpleNamespace(is_duplicate=lambda _id: False), raising=False)
    monkeypatch.setattr(chat_routes.deps, "task_queue", SimpleNamespace(pending_count=0), raising=False)
    monkeypatch.setattr(chat_routes, "_expected_gateway_token", lambda: "")
    asyncio.run(chat_routes.chat_webhook(Request()))
    assert seen[0]["metadata"]["person_origin"] == "api"
    assert seen[0]["metadata"]["api_authenticated"] is False

    monkeypatch.setattr(chat_routes, "_expected_gateway_token", lambda: "known-token")
    asyncio.run(chat_routes.chat_webhook(Request()))
    assert seen[1]["metadata"]["person_origin"] == "api"
    assert seen[1]["metadata"]["api_authenticated"] is True


def test_batch_serialization_separates_api_origin_and_two_private_people(
    inbound_runtime, monkeypatch
):
    tasks = []

    async def enqueue(task):
        tasks.append(task)

    monkeypatch.setattr(
        pipeline_helpers.deps, "task_queue", SimpleNamespace(enqueue=enqueue), raising=False
    )
    async def add(chat_id, metadata):
        await pipeline_helpers.on_batch_ready(chat_id, "same sentence", metadata)

    asyncio.run(add("alice-phone", {"channel_id": "whatsapp", "message_id": "a"}))
    asyncio.run(add("bob-phone", {"channel_id": "whatsapp", "message_id": "b"}))
    asyncio.run(add("alice-phone", {
        "channel_id": "whatsapp", "message_id": "api",
        "person_origin": "api", "api_authenticated": False,
    }))
    assert tasks[0].session_key != tasks[1].session_key
    assert tasks[2].session_key not in {tasks[0].session_key, tasks[1].session_key}
    assert getattr(tasks[2], "person_origin", "channel") == "api"
