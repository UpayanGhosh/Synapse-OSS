from __future__ import annotations

import asyncio
import inspect
import sys
from types import ModuleType

import pytest

try:
    from sci_fi_dashboard.subagent import spawn as spawn_module
except ModuleNotFoundError as exc:
    if exc.name != "pyarrow":
        raise
    sys.modules["sci_fi_dashboard._deps"] = ModuleType("sci_fi_dashboard._deps")
    from sci_fi_dashboard.subagent import spawn as spawn_module

from sci_fi_dashboard.personal_memory import PersonMemoryContext


class GlobalMemorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, *_args, **_kwargs):
        self.calls += 1
        return {"results": [{"content": "B private secret: SECRET-B-900"}]}


class ScopedMemorySpy:
    def __init__(self) -> None:
        self.calls = []

    def recall(self, context: PersonMemoryContext, query: str, *, limit: int = 3):
        self.calls.append((context.person_id, context.conversation_id, query, limit))
        return [{"content": "Alice's scoped umbrella episode."}]


class AgentRunner:
    def __init__(self) -> None:
        self.spawned = []

    async def spawn_agent(self, agent) -> None:
        self.spawned.append(agent)


def _scoped_kwargs(context, store):
    signature = inspect.signature(spawn_module.maybe_spawn_agent).parameters
    kwargs = {}
    if "person_context" in signature:
        kwargs["person_context"] = context
    if "personal_memory_store" in signature:
        kwargs["personal_memory_store"] = store
    return kwargs


@pytest.fixture
def spawn_runtime(monkeypatch: pytest.MonkeyPatch):
    global_memory = GlobalMemorySpy()
    scoped_memory = ScopedMemorySpy()
    runner = AgentRunner()
    monkeypatch.setattr(spawn_module.deps, "memory_engine", global_memory, raising=False)
    monkeypatch.setattr(spawn_module.deps, "agent_runner", runner, raising=False)
    monkeypatch.setattr(spawn_module.deps, "conversation_cache", None, raising=False)
    monkeypatch.setattr(
        spawn_module,
        "detect_spawn_intent",
        lambda _text: (True, "find the latest calendar API docs"),
    )
    return global_memory, scoped_memory, runner


def test_spawn_uses_only_scoped_person_memory(spawn_runtime) -> None:
    global_memory, scoped_memory, runner = spawn_runtime
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")

    result = asyncio.run(
        spawn_module.maybe_spawn_agent(
            "research this",
            "+15550000001",
            "whatsapp",
            "agent:creator:whatsapp:dm:alice",
            **_scoped_kwargs(context, scoped_memory),
        )
    )

    assert result is not None
    assert len(runner.spawned) == 1
    assert runner.spawned[0].memory_snapshot == [
        {"content": "Alice's scoped umbrella episode."}
    ]
    assert scoped_memory.calls == [
        ("person:alice", "whatsapp:alice", "find the latest calendar API docs", 3)
    ]
    assert global_memory.calls == 0
    assert "SECRET-B-900" not in repr(runner.spawned[0].memory_snapshot)


def test_spawn_without_verified_person_context_has_no_personal_memory(spawn_runtime) -> None:
    global_memory, scoped_memory, runner = spawn_runtime

    asyncio.run(
        spawn_module.maybe_spawn_agent(
            "research this",
            "family-room",
            "whatsapp",
            "agent:creator:whatsapp:group:family-room",
            **_scoped_kwargs(None, scoped_memory),
        )
    )

    assert len(runner.spawned) == 1
    assert runner.spawned[0].memory_snapshot == []
    assert scoped_memory.calls == []
    assert global_memory.calls == 0
