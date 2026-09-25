"""Stable profile facts enter only the owner-scoped prompt projection."""

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
from sci_fi_dashboard.personal_memory_service import PersonalMemoryService
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.user_memory import UserMemoryFact, upsert_user_memory_facts

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "fact-prompt"


class GlobalMemorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, *_args, **_kwargs):
        self.calls += 1
        return {"results": [{"content": "Bob's hidden profile SECRET-B-901"}], "tier": "normal"}


class FakeSBS:
    def __init__(self) -> None:
        self.profile_mgr = SimpleNamespace(load_layer=lambda _name: {})

    def on_message(self, *_args, **_kwargs):
        return {"msg_id": "sbs-msg"}

    def get_system_prompt(self, base, _proactive):
        return base


class CapturingRouter:
    def __init__(self) -> None:
        self.prompts = []

    async def call_with_metadata(self, _role, messages, **_kwargs):
        self.prompts.append(messages)
        return SimpleNamespace(
            text="Sure, let's make a plan.",
            model="fake-local-model",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
        )


@pytest.mark.parametrize("depth", ["full", "casual_light"])
def test_persona_prompt_includes_provenance_fact_and_excludes_legacy_fact(
    monkeypatch: pytest.MonkeyPatch, depth: str
) -> None:
    root = TEST_DATA_ROOT / uuid4().hex
    root.mkdir(parents=True)
    store = PersonalMemoryStore(root / "memory.db")
    context = PersonMemoryContext("person:alice", "api:local-api-owner", "private")

    def extractor(_observation: dict) -> dict:
        return {
            "confirmed_facts": [
                {
                    "kind": "preference",
                    "key": "reply_style",
                    "value": "concise",
                    "summary": "Alice prefers concise replies.",
                    "confidence": 0.94,
                    "evidence": "Please keep replies concise.",
                }
            ],
            "relationship_updates": [],
        }

    service = PersonalMemoryService(store, extractor=extractor)
    service.capture_user_turn(
        context,
        source_message_id="prompt-fact-source",
        content="Please keep replies concise.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    assert asyncio.run(service.process_pending_once(limit=1)) == 1
    with sqlite3.connect(store.db_path) as conn:
        upsert_user_memory_facts(
            conn,
            [
                UserMemoryFact(
                    user_id="person:alice",
                    kind="preference",
                    key="old_unowned_preference",
                    value="formal",
                    summary="Legacy user profile says use formal replies.",
                    confidence=0.9,
                    source_doc_id=None,
                    evidence="Please keep my replies formal.",
                )
            ],
        )

    global_spy = GlobalMemorySpy()
    router = CapturingRouter()
    deps = chat_pipeline.deps
    monkeypatch.setattr(deps, "pending_consents", {}, raising=False)
    monkeypatch.setattr(deps, "consent_protocol", None, raising=False)
    monkeypatch.setattr(deps, "memory_engine", global_spy, raising=False)
    monkeypatch.setattr(deps, "personal_memory_service", service, raising=False)
    monkeypatch.setattr(deps, "toxic_scorer", SimpleNamespace(score=lambda _text: 0.0), raising=False)
    monkeypatch.setattr(
        deps,
        "dual_cognition",
        SimpleNamespace(trajectory=None, build_cognitive_context=lambda *_a, **_k: ""),
        raising=False,
    )
    monkeypatch.setattr(deps, "get_sbs_for_target", lambda _target, **_kwargs: FakeSBS(), raising=False)
    monkeypatch.setattr(deps, "_proactive_engine", None, raising=False)
    monkeypatch.setattr(deps, "tool_registry", None, raising=False)
    monkeypatch.setattr(deps, "synapse_llm_router", router, raising=False)
    monkeypatch.setattr(
        deps,
        "_synapse_cfg",
        SimpleNamespace(session={"dual_cognition_enabled": False}, model_mappings={}, image_gen={}, db_dir=root, raw={}),
        raising=False,
    )
    monkeypatch.setattr(
        chat_pipeline, "_load_agent_workspace_prefix_for_session", lambda *_a, **_k: "CANONICAL BASE"
    )
    monkeypatch.setattr(chat_pipeline, "_fetch_recent_session_recall_context", lambda *_a, **_k: "")
    if depth != "full":
        monkeypatch.setattr(chat_pipeline, "_prompt_depth_for_turn", lambda *_a, **_k: depth)

    kwargs = (
        {"person_context": context}
        if "person_context" in inspect.signature(chat_pipeline.persona_chat).parameters
        else {}
    )
    result = asyncio.run(
        chat_pipeline.persona_chat(
            ChatRequest(
                message="Can you help me plan a tricky work decision?",
                user_id="caller-supplied-bob",
                session_key="untrusted-session",
                history=[],
            ),
            "the_creator",
            **kwargs,
        )
    )
    prompt = "\n".join(str(message.get("content", "")) for message in router.prompts[0])

    assert result["reply"].startswith("Sure")
    assert "Alice prefers concise replies." in prompt
    assert "Legacy user profile says use formal replies." not in prompt
    assert "SECRET-B-901" not in prompt
    assert global_spy.calls == 0


@pytest.mark.parametrize(
    "corrections",
    [
        (
            {
                "kind": "preference",
                "key": "tone",
                "obsolete_evidence": "OBSOLETE-CUE-LONG-" + "x" * 420,
                "current_value": "casual",
                "current_occurred_at": "2026-09-24T00:00:00+00:00",
            },
        ),
        tuple(
            {
                "kind": "preference",
                "key": f"field_{index}",
                "obsolete_evidence": f"OBSOLETE-CUE-{index}-" + "x" * 90,
                "current_value": f"current-{index}",
                "current_occurred_at": "2026-09-24T00:00:00+00:00",
            }
            for index in range(3)
        ),
    ],
)
def test_memory_budget_never_keeps_obsolete_claim_without_full_correction_label(
    corrections: tuple[dict, ...],
) -> None:
    episode = SimpleNamespace(
        corrections=corrections,
        occurred_at="2026-09-20T00:00:00+00:00",
        occurred_at_source="received_at",
        role="user",
        content="RAW-EPISODE-SENTINEL with harmless context.",
    )
    content = chat_pipeline._format_scoped_recalled_episode(episode)
    rendered = chat_pipeline._format_memory_context_for_tier(
        [],
        {"results": [{"content": content, "score": 1.0, "has_corrections": True}]},
        chat_pipeline.get_prompt_tier_policy("small"),
    )

    for note in corrections:
        cue = note["obsolete_evidence"].split("x", 1)[0]
        full_label = (
            "CORRECTED CLAIM "
            f"{note['kind']}/{note['key']}: {note['obsolete_evidence']!r} is historical; "
            f"current value is {note['current_value']!r} "
            f"(source {note['current_occurred_at']})."
        )
        assert full_label in rendered or cue not in rendered
