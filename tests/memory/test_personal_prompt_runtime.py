"""The production composer must use only server-scoped personal evidence."""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

try:
    from sci_fi_dashboard import chat_pipeline
except ModuleNotFoundError as exc:
    if exc.name != "pyarrow":
        raise
    sys.modules["sci_fi_dashboard._deps"] = ModuleType("sci_fi_dashboard._deps")
    from sci_fi_dashboard import chat_pipeline

from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.style_policy import StylePolicy
from sci_fi_dashboard.user_memory import UserMemoryFact, upsert_user_memory_facts


class GlobalMemorySpy:
    def __init__(self):
        self.calls = 0

    def query(self, *_args, **_kwargs):
        self.calls += 1
        return {"results": [{"content": "Bob private detail SECRET-B-900"}], "tier": "normal"}


class FakeSBS:
    def __init__(self):
        self.profile_mgr = SimpleNamespace(load_layer=lambda _name: {})

    def on_message(self, *_args, **_kwargs):
        return {"msg_id": "sbs-msg"}

    def get_system_prompt(self, base, _proactive):
        return base


class CapturingRouter:
    def __init__(self):
        self.prompts = []

    async def call_with_metadata(self, _role, messages, **_kwargs):
        self.prompts.append(messages)
        return SimpleNamespace(
            text="Yep, the tiny umbrella bit.",
            model="fake-local-model",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
        )


@pytest.mark.parametrize("identity", ["alice", None])
@pytest.mark.parametrize("depth", ["full", "casual_light", "casual_reflective"])
@pytest.mark.parametrize("turn_override", [False, True])
def test_persona_chat_uses_relevant_scoped_evidence_without_global_personal_leak(
    monkeypatch: pytest.MonkeyPatch, identity, depth, turn_override
):
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "prompt-runtime" / uuid4().hex
    root.mkdir(parents=True)
    memory = PersonalMemoryStore(root / "memory.db")
    alice = PersonMemoryContext("whatsapp:alice", "session:alice")
    source_episode_id = memory.capture_episode(
        alice,
        source_message_id="alice-umbrella",
        content="Our tiny umbrella joke made me laugh yesterday.",
        occurred_at=datetime(2026, 9, 22, tzinfo=UTC),
    )
    style_source = memory.capture_episode(
        alice,
        source_message_id="alice-explicit-style",
        content="Please use a formal tone and keep replies concise.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    memory.apply_relationship_update(
        alice, {"tone": "formal", "verbosity": "concise"},
        source_episode_id=style_source,
        evidence="Please use a formal tone and keep replies concise.",
    )
    correction_source = memory.capture_episode(
        alice,
        source_message_id="alice-mascot-correction",
        content="Please call our umbrella mascot red.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    active_episode_id = memory.capture_episode(
        alice,
        source_message_id="alice-active-question",
        content="ACTIVE QUERY EPISODE SENTINEL: Remember our tiny umbrella joke?",
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    with sqlite3.connect(root / "memory.db") as conn:
        upsert_user_memory_facts(conn, [
            UserMemoryFact(
                user_id="whatsapp:alice", kind="preference", key="reply_style",
                value="concise", summary="Alice prefers concise replies.",
                confidence=0.93, source_doc_id=None,
                evidence="tiny umbrella joke made me laugh", source_episode_id=source_episode_id,
            ),
            UserMemoryFact(
                user_id="whatsapp:alice", kind="preference", key="old_legacy_style",
                value="formal", summary="Legacy unowned profile says formal replies.",
                confidence=0.8, source_doc_id=None,
                evidence="unowned old transcript",
            ),
            UserMemoryFact(
                user_id="whatsapp:alice", kind="preference", key="mascot_color",
                value="tiny", summary="The mascot was a tiny umbrella.",
                confidence=0.9, source_doc_id=None,
                evidence="tiny umbrella joke", source_episode_id=source_episode_id,
            ),
            UserMemoryFact(
                user_id="whatsapp:alice", kind="preference", key="mascot_color",
                value="red", summary="The mascot is a red umbrella.",
                confidence=0.9, source_doc_id=None,
                evidence="Please call our umbrella mascot red.",
                source_episode_id=correction_source,
            ),
        ])
    class ScopedService:
        async def recall(self, context, query, *, limit=3, exclude_episode_id=None):
            return memory.recall(
                context, query, limit=limit, exclude_episode_id=exclude_episode_id,
            )

        store = memory

    global_spy = GlobalMemorySpy()
    router = CapturingRouter()
    deps = chat_pipeline.deps
    monkeypatch.setattr(deps, "pending_consents", {}, raising=False)
    monkeypatch.setattr(deps, "consent_protocol", None, raising=False)
    monkeypatch.setattr(deps, "memory_engine", global_spy, raising=False)
    monkeypatch.setattr(deps, "personal_memory_service", ScopedService(), raising=False)
    monkeypatch.setattr(deps, "toxic_scorer", SimpleNamespace(score=lambda _text: 0.0), raising=False)
    monkeypatch.setattr(
        deps, "dual_cognition",
        SimpleNamespace(trajectory=None, build_cognitive_context=lambda *_a, **_k: ""),
        raising=False,
    )
    monkeypatch.setattr(deps, "get_sbs_for_target", lambda _target, **_kwargs: FakeSBS(), raising=False)
    monkeypatch.setattr(deps, "_proactive_engine", None, raising=False)
    monkeypatch.setattr(deps, "tool_registry", None, raising=False)
    monkeypatch.setattr(deps, "synapse_llm_router", router, raising=False)
    monkeypatch.setattr(deps, "_synapse_cfg", SimpleNamespace(
        session={"dual_cognition_enabled": False},
        model_mappings={}, image_gen={}, db_dir=root, raw={},
    ), raising=False)
    monkeypatch.setattr(chat_pipeline, "_load_agent_workspace_prefix_for_session", lambda *_a, **_k: "CANONICAL BASE")
    if depth != "full":
        monkeypatch.setattr(chat_pipeline, "_prompt_depth_for_turn", lambda *_a, **_k: depth)
    monkeypatch.setattr(chat_pipeline, "_fetch_recent_session_recall_context", lambda *_a, **_k: "Bob private recent SECRET-B-900")
    db_module = ModuleType("sci_fi_dashboard.db")

    def global_db():
        conn = sqlite3.connect(root / "legacy.db")
        conn.execute("CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, filename TEXT, content TEXT)")
        conn.execute("INSERT INTO documents(filename,content) VALUES ('relationship_memory','Bob private profile SECRET-B-900')")
        conn.commit()
        return conn

    db_module.get_db_connection = global_db
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard.db", db_module)
    context = alice if identity == "alice" else None
    kwargs = {"person_context": context} if "person_context" in inspect.signature(chat_pipeline.persona_chat).parameters else {}
    if context is not None:
        kwargs["exclude_episode_id"] = active_episode_id
    request = ChatRequest(
        message=(
            "Please be casual and give more detail about our tiny umbrella joke"
            if turn_override else "Remember our tiny umbrella joke?"
        ),
        user_id="caller-bob", session_type="spicy",
        session_key=f"session:{identity or 'anonymous'}", history=[],
    )

    result = asyncio.run(chat_pipeline.persona_chat(request, "the_creator", **kwargs))
    prompt = "\n".join(str(message.get("content", "")) for message in router.prompts[0])
    assert result["reply"].startswith("Yep")
    assert global_spy.calls == 0
    assert "SECRET-B-900" not in prompt
    assert "Legacy unowned profile says formal replies" not in prompt
    assert "ACTIVE QUERY EPISODE SENTINEL" not in prompt
    if identity == "alice":
        assert "tiny umbrella joke made me laugh" in prompt
        assert "Alice prefers concise replies" in prompt
        assert "CORRECTED CLAIM" in prompt
        assert "mascot_color" in prompt and "red" in prompt
        if turn_override:
            assert "Tone: casual_witty." in prompt
            assert "Length: detailed." in prompt
        else:
            assert "Tone: professional_precise." in prompt
            assert "Length: concise." in prompt
    else:
        assert "tiny umbrella joke made me laugh" not in prompt


def test_explicit_formality_beats_inferred_tone_and_current_turn_beats_both() -> None:
    base = StylePolicy(
        tone="casual_witty", length="normal", scope="session", source="default",
        session_key="alice", reason="default", updated_at=0,
    )
    relationship = {
        "preferences": {"tone": "formal", "verbosity": "balanced"},
        "inferred": {"tone": {"value": "playful"}},
    }
    persisted = chat_pipeline._apply_scoped_relationship_style(
        base, "What is the plan?", relationship
    )
    assert (persisted.tone, persisted.length) == ("professional_precise", "normal")
    current = chat_pipeline._apply_scoped_relationship_style(
        base, "Please be casual and give more detail", relationship
    )
    assert (current.tone, current.length) == ("casual_witty", "detailed")


def test_scoped_correction_budget_preserves_complete_labels_before_raw() -> None:
    episode = SimpleNamespace(
        corrections=({
            "kind": "preference", "key": "tone",
            "obsolete_evidence": "old claim " + "x" * 50,
            "current_value": "current value " + "y" * 30,
            "current_occurred_at": "2026-09-24T00:00:00+00:00",
        },),
        occurred_at="2026-09-20T00:00:00+00:00",
        occurred_at_source="received_at",
        role="user",
        content="RAW-CONTEXT " + "z" * 500,
    )
    label = (
        "CORRECTED CLAIM preference/tone: "
        f"{episode.corrections[0]['obsolete_evidence']!r} is historical; "
        f"current value is {episode.corrections[0]['current_value']!r} "
        "(source 2026-09-24T00:00:00+00:00)."
    )
    labels, raw = chat_pipeline._scoped_recalled_episode_parts(episode)
    item = {"content": chat_pipeline._format_scoped_recalled_episode(episode),
            "correction_labels": labels, "raw_memory": raw,
            "score": 1.0, "has_corrections": True}
    rendered = chat_pipeline._format_memory_context_for_tier(
        [], {"results": [item]}, chat_pipeline.get_prompt_tier_policy("small")
    )
    assert label in rendered
    assert "RAW-CONTEXT" in rendered
    assert "z" * 500 not in rendered
