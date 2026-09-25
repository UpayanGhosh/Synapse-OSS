from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from sci_fi_dashboard.tool_registry import ToolContext, _query_memory_factory

try:
    from sci_fi_dashboard.personal_memory import PersonMemoryContext
except ModuleNotFoundError:
    # Let this integration test exercise the still-unscoped factory before
    # the approved DTO exists; once implemented, use the real immutable DTO.
    PersonMemoryContext = SimpleNamespace


class GlobalMemorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, *_args, **_kwargs):
        self.calls += 1
        return {"results": [{"content": "B private secret: SECRET-B-900"}]}


class ScopedMemorySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def recall(self, context: PersonMemoryContext, query: str, *, limit: int = 3):
        self.calls.append((context.person_id or "", query, limit))
        if context.visibility == "group":
            content = "The family shared an umbrella story."
        elif context.person_id == "person:alice":
            content = "Alice's tiny red umbrella joke."
        else:
            content = "Bob's private secret: SECRET-B-900"
        return [
            SimpleNamespace(
                episode_id=f"episode:{context.person_id}",
                person_id=context.person_id,
                conversation_id=context.conversation_id,
                source_message_id="message-1",
                content=content,
                occurred_at="2026-09-23T00:00:00+00:00",
                recorded_at="2026-09-25T00:00:00+00:00",
                visibility=context.visibility,
                score=0.9,
                status="active",
                superseded_by=None,
            )
        ]


def _tool_context(
    *,
    person_context: PersonMemoryContext | None,
    personal_memory_store: ScopedMemorySpy | None,
) -> ToolContext:
    context = ToolContext(
        chat_id="request-session",
        sender_id="sender",
        sender_is_owner=False,
        workspace_dir=".",
        config={},
    )
    # Keep the test behavioral against the pre-contract ToolContext, while the
    # approved runtime contract adds these fields directly to the dataclass.
    context.person_context = person_context
    context.personal_memory_store = personal_memory_store
    return context


def test_native_memory_tool_uses_only_the_person_scoped_store() -> None:
    global_memory = GlobalMemorySpy()
    scoped_memory = ScopedMemorySpy()
    factory = _query_memory_factory(global_memory)
    alice_context = _tool_context(
        person_context=PersonMemoryContext("person:alice", "whatsapp:alice", "private"),
        personal_memory_store=scoped_memory,
    )
    tool = factory(alice_context)

    result = asyncio.run(tool.execute({"query": "tiny red umbrella", "limit": 2}))
    payload = json.loads(result.content)

    assert global_memory.calls == 0
    assert scoped_memory.calls == [("person:alice", "tiny red umbrella", 2)]
    assert payload[0]["content"] == "Alice's tiny red umbrella joke."
    assert payload[0]["occurred_at"] == "2026-09-23T00:00:00+00:00"
    assert payload[0]["source_message_id"] == "message-1"
    assert "SECRET-B-900" not in result.content


def test_native_memory_tool_fails_closed_without_verified_person_context() -> None:
    global_memory = GlobalMemorySpy()
    scoped_memory = ScopedMemorySpy()
    factory = _query_memory_factory(global_memory)
    context = _tool_context(person_context=None, personal_memory_store=scoped_memory)
    result = asyncio.run(factory(context).execute({"query": "private details"}))
    assert json.loads(result.content) == []

    assert scoped_memory.calls == []
    assert global_memory.calls == 0


def test_native_memory_tool_can_read_group_shared_memory_without_member_private_memory() -> None:
    global_memory = GlobalMemorySpy()
    scoped_memory = ScopedMemorySpy()
    factory = _query_memory_factory(global_memory)
    group = _tool_context(
        person_context=PersonMemoryContext(None, "family-group", "group"),
        personal_memory_store=scoped_memory,
    )

    result = asyncio.run(factory(group).execute({"query": "umbrella story"}))

    assert "family shared an umbrella story" in result.content
    assert "SECRET-B-900" not in result.content
    assert scoped_memory.calls == [("", "umbrella story", 3)]
    assert global_memory.calls == 0


def test_native_memory_tool_keeps_two_people_scoped_even_with_same_query() -> None:
    global_memory = GlobalMemorySpy()
    scoped_memory = ScopedMemorySpy()
    factory = _query_memory_factory(global_memory)
    alice = _tool_context(
        person_context=PersonMemoryContext("person:alice", "dm:alice", "private"),
        personal_memory_store=scoped_memory,
    )
    bob = _tool_context(
        person_context=PersonMemoryContext("person:bob", "dm:bob", "private"),
        personal_memory_store=scoped_memory,
    )

    alice_result = asyncio.run(factory(alice).execute({"query": "inside joke"}))
    bob_result = asyncio.run(factory(bob).execute({"query": "inside joke"}))

    assert "Alice's tiny red umbrella joke." in alice_result.content
    assert "Bob's private secret" in bob_result.content
    assert global_memory.calls == 0
    assert [call[0] for call in scoped_memory.calls] == ["person:alice", "person:bob"]
