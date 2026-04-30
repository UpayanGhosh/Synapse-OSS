"""Unit tests for persona_chat foreground cloud-call budgeting."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sci_fi_dashboard.dual_cognition import DualCognitionEngine
from sci_fi_dashboard.llm_router import LLMResult
from sci_fi_dashboard.schemas import ChatRequest


class _GraphStub:
    def get_entity_neighborhood(self, _entity: str) -> str:
        return ""


def _make_request(message: str) -> ChatRequest:
    return ChatRequest(
        message=message,
        user_id="test_user",
        history=[],
        session_type="safe",
    )


def _make_llm_result(text: str = "Sure, I can help!") -> LLMResult:
    return LLMResult(
        text=text,
        model="test/mock",
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
    )


def _make_deps(tmp_path: Path) -> types.SimpleNamespace:
    deps = types.SimpleNamespace()
    deps.pending_consents = {}
    deps.consent_protocol = None

    deps.memory_engine = MagicMock()
    deps.memory_engine.query.return_value = {
        "results": [],
        "tier": "unit",
        "graph_context": "",
    }
    deps.memory_engine.add_memory.return_value = None

    deps.dual_cognition = DualCognitionEngine(
        memory_engine=deps.memory_engine,
        graph=_GraphStub(),
    )
    deps.toxic_scorer = MagicMock()
    deps.toxic_scorer.score.return_value = 0.1

    deps._synapse_cfg = types.SimpleNamespace(
        session={
            "dual_cognition_enabled": True,
            "dual_cognition_timeout": 10.0,
        },
        raw={},
        image_gen={"enabled": True},
        model_mappings={
            "casual": {
                "model": "google_antigravity/gemini-3-flash",
                "prompt_tier": "frontier",
            },
            "analysis": {"model": "google_antigravity/gemini-3-flash"},
            "oracle": {"model": "google_antigravity/gemini-3-flash"},
            "vault": {"model": "ollama_chat/gemma4:e4b"},
        },
        data_root=tmp_path,
    )

    deps.synapse_llm_router = types.SimpleNamespace()
    deps.synapse_llm_router.call = AsyncMock(return_value="{}")
    deps.synapse_llm_router.call_with_metadata = AsyncMock(return_value=_make_llm_result())

    deps._proactive_engine = None
    deps.get_sbs_for_target = MagicMock()
    sbs = MagicMock()
    sbs.on_message.return_value = {"msg_id": "msg-1"}
    sbs.get_system_prompt.return_value = "You are Synapse."
    deps.get_sbs_for_target.return_value = sbs

    deps._SKILL_SYSTEM_AVAILABLE = False
    deps.skill_router = None
    deps.tool_registry = None
    deps._TOOL_REGISTRY_AVAILABLE = False
    deps._TOOL_SAFETY_AVAILABLE = False
    deps._TOOL_FEATURES_AVAILABLE = False
    deps.MAX_TOOL_ROUNDS = 12
    deps.TOOL_RESULT_MAX_CHARS = 4000
    deps.MAX_TOTAL_TOOL_RESULT_CHARS = 20_000
    deps.TOOL_LOOP_WALL_CLOCK_S = 30.0
    deps.TOOL_LOOP_TOKEN_RATIO_ABORT = 0.85
    deps.WORKSPACE_ROOT = tmp_path
    deps.channel_registry = {}
    return deps


@pytest.fixture
def fresh_pipeline(tmp_path, monkeypatch):
    fake_deps = _make_deps(tmp_path)
    import sci_fi_dashboard as pkg

    original_deps = sys.modules.get("sci_fi_dashboard._deps")
    original_pkg_deps = getattr(pkg, "_deps", None)
    original_chat_pipeline = sys.modules.pop("sci_fi_dashboard.chat_pipeline", None)
    original_llm_wrappers = sys.modules.pop("sci_fi_dashboard.llm_wrappers", None)
    monkeypatch.setitem(sys.modules, "sci_fi_dashboard._deps", fake_deps)
    monkeypatch.setattr(pkg, "_deps", fake_deps, raising=False)

    module = importlib.import_module("sci_fi_dashboard.chat_pipeline")
    llm_wrappers = importlib.import_module("sci_fi_dashboard.llm_wrappers")
    try:
        yield module, llm_wrappers, fake_deps
    finally:
        sys.modules.pop("sci_fi_dashboard.chat_pipeline", None)
        sys.modules.pop("sci_fi_dashboard.llm_wrappers", None)
        if original_chat_pipeline is not None:
            sys.modules["sci_fi_dashboard.chat_pipeline"] = original_chat_pipeline
            pkg.chat_pipeline = original_chat_pipeline
        elif hasattr(pkg, "chat_pipeline"):
            delattr(pkg, "chat_pipeline")
        if original_llm_wrappers is not None:
            sys.modules["sci_fi_dashboard.llm_wrappers"] = original_llm_wrappers
            pkg.llm_wrappers = original_llm_wrappers
        elif hasattr(pkg, "llm_wrappers"):
            delattr(pkg, "llm_wrappers")
        if original_deps is not None:
            sys.modules["sci_fi_dashboard._deps"] = original_deps
        if original_pkg_deps is not None:
            pkg._deps = original_pkg_deps


@pytest.mark.asyncio
async def test_casual_status_turn_skips_oracle_cognition(fresh_pipeline):
    """Casual status updates should spend one foreground LLM call, not oracle calls first."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    mock_oracle = AsyncMock(return_value='{"response_strategy":"acknowledge"}')

    with (
        patch.object(llm_wrappers, "call_ag_oracle", mock_oracle),
        patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")),
    ):
        result = await chat_pipeline.persona_chat(
            _make_request("Nice. I'm not doing much chilling on my pc with my GF."),
            target="the_creator",
        )

    assert isinstance(result, dict)
    assert mock_oracle.await_count == 0
    assert deps.synapse_llm_router.call_with_metadata.call_count == 1


@pytest.mark.asyncio
async def test_rate_limit_stops_after_one_final_attempt(fresh_pipeline):
    """A 429/rate-limit response must not retry the final cloud call 12 times."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        side_effect=Exception("rate limit exceeded: token quota")
    )

    with (
        patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")),
        patch.object(chat_pipeline.asyncio, "sleep", new_callable=AsyncMock),
    ):
        result = await chat_pipeline.persona_chat(_make_request("hi"), target="the_creator")

    assert isinstance(result, dict)
    assert deps.synapse_llm_router.call_with_metadata.call_count == 1
    assert "rate-limited" in result["reply"].lower()


@pytest.mark.asyncio
async def test_empty_model_text_does_not_send_metadata_only_reply(fresh_pipeline):
    """Empty provider text must not become a stats-only user-visible reply."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=LLMResult(
            text="",
            model="test/mock",
            prompt_tokens=120,
            completion_tokens=0,
            total_tokens=120,
        )
    )

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(_make_request("hi"), target="the_creator")

    assert isinstance(result, dict)
    assert not result["reply"].lstrip().startswith("---")
    assert "empty response" in result["reply"]
    assert "**Context Usage:**" in result["reply"]


@pytest.mark.asyncio
async def test_invisible_model_text_does_not_send_metadata_only_reply(fresh_pipeline):
    """Invisible/control-only provider text is also an empty user-visible reply."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=LLMResult(
            text="\u200b\n\t",
            model="test/mock",
            prompt_tokens=120,
            completion_tokens=1,
            total_tokens=121,
        )
    )

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(_make_request("hi"), target="the_creator")

    assert isinstance(result, dict)
    assert not result["reply"].lstrip().startswith("---")
    assert "empty response" in result["reply"]


@pytest.mark.asyncio
async def test_simple_greeting_does_not_use_native_tool_calling(fresh_pipeline):
    """Simple chat should not spend the final call on native tool schemas."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    deps.tool_registry.resolve.return_value = [
        types.SimpleNamespace(name="memory_search", description="Search memory", serial=False)
    ]
    deps.tool_registry.get_schemas.return_value = [
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": "Search memory",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    deps.synapse_llm_router.call_with_tools = AsyncMock(return_value=_make_llm_result())

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(_make_request("hi"), target="the_creator")

    assert isinstance(result, dict)
    assert deps.synapse_llm_router.call_with_tools.call_count == 0
    assert deps.synapse_llm_router.call_with_metadata.call_count == 1


@pytest.mark.asyncio
async def test_tool_context_preserves_channel_id(fresh_pipeline):
    """Channel messages must resolve tools with the real channel policy."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    captured = {}
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()

    def _resolve(context):
        captured["channel_id"] = context.channel_id
        return [types.SimpleNamespace(name="web_query", description="Search web", serial=False)]

    deps.tool_registry.resolve.side_effect = _resolve
    deps.tool_registry.get_schemas.return_value = [
        {
            "type": "function",
            "function": {
                "name": "web_query",
                "description": "Search web",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    deps.synapse_llm_router.call_with_tools = AsyncMock(return_value=_make_llm_result("found it"))

    request = ChatRequest(
        message="search the web for current onboarding ideas",
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert captured["channel_id"] == "telegram"
    assert deps.synapse_llm_router.call_with_tools.call_count == 1


@pytest.mark.asyncio
async def test_light_casual_prompt_stays_compact(fresh_pipeline):
    """Tiny casual turns must not compile the full 16k-token workspace prompt."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(_make_request("hi"), target="the_creator")

    assert isinstance(result, dict)
    messages = deps.synapse_llm_router.call_with_metadata.call_args.args[1]
    assert chat_pipeline._estimate_message_tokens(messages) < 3_000


@pytest.mark.asyncio
async def test_reflective_casual_keeps_emotional_context_while_compact(fresh_pipeline):
    """Casual tone with worry/anxiety still needs affect and memory context."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.memory_engine.query.return_value = {
        "results": [
            {
                "content": "The user worries the memory architecture may still feel generic.",
                "score": 0.94,
            },
            {
                "content": "The user's goal is human-like replies with emotional trajectory.",
                "score": 0.91,
            },
            {
                "content": "Dual cognition exists to make replies less like generic AI.",
                "score": 0.88,
            },
        ],
        "tier": "unit",
        "graph_context": "GRAPH CONTEXT SHOULD NOT BE IN REFLECTIVE CASUAL",
        "affect_hints": "Affect: user is worried but engaged; respond with grounded reassurance.",
    }

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(
            _make_request(
                "Bro I'm kinda worried all this memory architecture still won't make the replies feel human."
            ),
            target="the_creator",
        )

    assert isinstance(result, dict)
    messages = deps.synapse_llm_router.call_with_metadata.call_args.args[1]
    prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
    assert chat_pipeline._estimate_message_tokens(messages) < 8_000
    assert "Affect: user is worried" in prompt_text
    assert "memory architecture may still feel generic" in prompt_text
    assert "GRAPH CONTEXT SHOULD NOT BE IN REFLECTIVE CASUAL" not in prompt_text


@pytest.mark.asyncio
async def test_markdown_terminal_reply_does_not_auto_continue(fresh_pipeline):
    """A complete reply ending in markdown emphasis must not trigger a second cloud call."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=_make_llm_result(
            "Arre bhai, this is a complete reflective answer with warmth and nuance, *bujhli toh?*"
        )
    )

    with (
        patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")),
        patch.object(chat_pipeline.asyncio, "create_task") as mock_create_task,
    ):
        result = await chat_pipeline.persona_chat(
            _make_request(
                "Bro I'm kinda worried all this memory architecture still won't make the replies feel human."
            ),
            target="the_creator",
        )

    assert isinstance(result, dict)
    assert deps.synapse_llm_router.call_with_metadata.call_count == 1
    mock_create_task.assert_not_called()
