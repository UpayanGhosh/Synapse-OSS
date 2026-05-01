"""Unit tests for persona_chat foreground cloud-call budgeting."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sci_fi_dashboard.dual_cognition import CognitiveMerge
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
    assert "**Context Usage:**" not in result["reply"]


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
async def test_practical_service_lookup_prefetches_before_reply(fresh_pipeline):
    """Local service/help requests should do a safe web lookup before answering."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    web_query = types.SimpleNamespace(
        name="web_query",
        description="Search web",
        serial=False,
        execute=AsyncMock(
            return_value=types.SimpleNamespace(
                content='{"query":"scooter service center Indiranagar","results":[{"title":"Indiranagar Scooter Repair","url":"https://example.test/scooter"}]}',
                is_error=False,
            )
        ),
    )
    deps.tool_registry.resolve.return_value = [web_query]
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
    deps.synapse_llm_router.call_with_tools = AsyncMock(
        return_value=_make_llm_result("I found a nearby scooter repair option.")
    )

    request = ChatRequest(
        message="My scooter broke near Indiranagar. Find a service center nearby.",
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert web_query.execute.await_count == 1
    query = web_query.execute.await_args.args[0]["query"].lower()
    assert "scooter" in query
    assert "indiranagar" in query
    assert deps.synapse_llm_router.call_with_tools.call_count == 1


@pytest.mark.asyncio
async def test_prefetched_lookup_adds_action_receipt_contract(fresh_pipeline):
    """A successful prefetch must give the model a concrete receipt to speak from."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    web_query = types.SimpleNamespace(
        name="web_query",
        description="Search web",
        serial=False,
        execute=AsyncMock(
            return_value=types.SimpleNamespace(
                content='{"query":"TVS RSA Kolkata","results":[{"title":"Roadside Assistance - TVS Motor Company","url":"https://www.tvsmotor.com/our-service/rsa"}]}',
                is_error=False,
            )
        ),
    )
    deps.tool_registry.resolve.return_value = [web_query]
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
    captured = {}

    async def _capture(_role, messages, **_kwargs):
        captured["messages"] = messages
        return _make_llm_result("I searched the web and found TVS RSA.")

    deps.synapse_llm_router.call_with_tools = AsyncMock(side_effect=_capture)

    request = ChatRequest(
        message="Bro can you check TVS towing help around Kolkata?",
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    prompt_text = "\n".join(str(m.get("content", "")) for m in captured["messages"])
    assert "ACTION RECEIPTS" in prompt_text
    assert "web_query" in prompt_text
    assert "verified" in prompt_text
    assert "Only claim an action happened when its receipt status supports it" in prompt_text
    assert "I searched the web" in result["reply"]


@pytest.mark.asyncio
async def test_unreceipted_action_claim_is_repaired_before_reply(fresh_pipeline):
    """The final answer cannot say it checked/searched when no receipt exists."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=_make_llm_result("I checked the live results and everything is fine.")
    )

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(
            _make_request("Can you sanity check this?"),
            target="the_creator",
        )

    assert "I checked the live results" not in result["reply"]
    assert "I haven't verified that live in this turn" in result["reply"]


@pytest.mark.asyncio
async def test_practical_lookup_prefetches_for_check_fastest_legit_route(fresh_pipeline):
    """Users say "check the fastest legit way", not always "find nearby"."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    web_query = types.SimpleNamespace(
        name="web_query",
        description="Search web",
        serial=False,
        execute=AsyncMock(
            return_value=types.SimpleNamespace(
                content='{"query":"tvs rsa","results":[{"title":"Roadside Assistance - TVS Motor","url":"https://example.test/tvs-rsa"}]}',
                is_error=False,
            )
        ),
    )
    deps.tool_registry.resolve.return_value = [web_query]
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
    deps.synapse_llm_router.call_with_tools = AsyncMock(
        return_value=_make_llm_result("I found the official TVS RSA page.")
    )

    request = ChatRequest(
        message=(
            "Bro my scooter just gave up near south Kolkata. Can you check the "
            "fastest legit way to get TVS roadside/towing help here?"
        ),
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert web_query.execute.await_count == 1
    query = web_query.execute.await_args.args[0]["query"].lower()
    assert "tvs" in query
    assert "kolkata" in query
    assert "roadside" in query
    assert "towing" in query
    assert "official" in query
    assert "bro" not in query
    assert "gave up" not in query


@pytest.mark.asyncio
async def test_prefetched_lookup_promise_reply_falls_back_to_results(fresh_pipeline):
    """If a model says it will check after prefetch, send the checked result."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    web_query = types.SimpleNamespace(
        name="web_query",
        description="Search web",
        serial=False,
        execute=AsyncMock(
            return_value=types.SimpleNamespace(
                content='{"query":"TVS RSA Kolkata","results":[{"title":"Roadside Assistance - TVS Motor Company","url":"https://www.tvsmotor.com/our-service/rsa"}]}',
                is_error=False,
            )
        ),
    )
    deps.tool_registry.resolve.return_value = [web_query]
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
    deps.synapse_llm_router.call_with_tools = AsyncMock(
        return_value=_make_llm_result("Lemme check the official route - one sec.")
    )

    request = ChatRequest(
        message=(
            "Bro my scooter is stuck near Kolkata. Can you check TVS towing help?"
        ),
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    reply = result["reply"]
    assert "Roadside Assistance - TVS Motor Company" in reply
    assert "https://www.tvsmotor.com/our-service/rsa" in reply
    assert "one sec" not in reply.lower()


@pytest.mark.asyncio
async def test_lookup_helper_ending_is_sharpened_to_next_move(fresh_pipeline):
    """Friend-mode replies should avoid generic assistant offer endings."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps.tool_registry = MagicMock()
    web_query = types.SimpleNamespace(
        name="web_query",
        description="Search web",
        serial=False,
        execute=AsyncMock(
            return_value=types.SimpleNamespace(
                content='{"query":"TVS RSA Kolkata","results":[{"title":"Roadside Assistance - TVS Motor Company","url":"https://www.tvsmotor.com/our-service/rsa"}]}',
                is_error=False,
            )
        ),
    )
    deps.tool_registry.resolve.return_value = [web_query]
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
    deps.synapse_llm_router.call_with_tools = AsyncMock(
        return_value=_make_llm_result(
            "Use the official TVS RSA page first. If you want, send me the exact area and I'll sanity-check the fallback listing."
        )
    )

    request = ChatRequest(
        message="Bro my scooter is stuck near Kolkata. Can you check TVS towing help?",
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    reply = result["reply"]
    assert "If you want" not in reply
    assert "Send me the exact area" in reply


def test_generic_help_offer_ending_is_sharpened():
    from sci_fi_dashboard.chat_pipeline import _sharpen_generic_helper_ending

    reply = _sharpen_generic_helper_ending(
        "Do the three-point prep first. If you want, I can help you make the 3 call points right now."
    )

    assert "If you want" not in reply
    assert reply.endswith("Send me the raw details and I'll help you make the 3 call points right now.")


def test_blank_template_slots_are_repaired():
    from sci_fi_dashboard.chat_pipeline import _repair_empty_template_slots

    reply = _repair_empty_template_slots(
        "On timeline, we're still aiming for , with  as the next milestone.\n"
        "The main risk right now is , and we're handling it by .\n"
        "The tradeoff is , so the safest path is ."
    )

    assert "for ," not in reply
    assert "with  as" not in reply
    assert "is ," not in reply
    assert "[target date]" in reply
    assert "[risk]" in reply
    assert "[tradeoff]" in reply


def test_user_nickname_placeholder_is_repaired():
    from sci_fi_dashboard.chat_pipeline import _repair_empty_template_slots

    reply = _repair_empty_template_slots(
        "Straight answer, user_nickname: I actually searched that turn."
    )

    assert "user_nickname" not in reply
    assert reply == "Straight answer, friend: I actually searched that turn."


@pytest.mark.asyncio
async def test_empty_tool_reply_gets_plain_text_recovery(fresh_pipeline):
    """Tool-enabled turns must recover with visible text instead of generic empty fallback."""
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
    deps.synapse_llm_router.call_with_tools = AsyncMock(
        return_value=LLMResult(
            text="",
            model="test/tool-empty",
            prompt_tokens=500,
            completion_tokens=132,
            total_tokens=632,
        )
    )
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=_make_llm_result(
            "I remember the demo anxiety, Rohan dumping cleanup on you, and Mira being in your head."
        )
    )

    request = ChatRequest(
        message="What do you remember about why I'm anxious tonight?",
        user_id="tg-chat",
        channel_id="telegram",
        history=[],
        session_type="safe",
    )
    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert deps.synapse_llm_router.call_with_tools.call_count == 1
    assert deps.synapse_llm_router.call_with_metadata.call_count == 1
    assert "demo anxiety" in result["reply"]
    assert "empty response" not in result["reply"].lower()


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
async def test_turn_stance_contract_is_injected_next_to_user_turn(fresh_pipeline):
    """Every casual reply gets an explicit stance object, not just vibe text."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline

    with patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")):
        result = await chat_pipeline.persona_chat(
            _make_request("I am scared this dinner will get awkward and I will look stupid."),
            target="the_creator",
        )

    assert isinstance(result, dict)
    messages = deps.synapse_llm_router.call_with_metadata.call_args.args[1]
    assert messages[-2]["role"] == "system"
    assert "TURN STANCE DECISION" in messages[-2]["content"]
    assert "steady close friend" in messages[-2]["content"]
    assert "No therapy-template phrasing" in messages[-2]["content"]
    assert messages[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_dual_cognition_default_timeout_is_not_too_short(fresh_pipeline):
    """Default installs should give dual cognition enough time to finish."""
    chat_pipeline, llm_wrappers, deps = fresh_pipeline
    deps._synapse_cfg.session = {"dual_cognition_enabled": True}
    deps.dual_cognition.think = AsyncMock(
        return_value=CognitiveMerge(
            inner_monologue="The user needs grounded reassurance.",
            tension_level=0.4,
            response_strategy="support",
            suggested_tone="warm",
        )
    )
    captured = {}
    async def _capture_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        return await awaitable

    with (
        patch.object(llm_wrappers, "route_traffic_cop", AsyncMock(return_value="CASUAL")),
        patch.object(chat_pipeline.asyncio, "wait_for", _capture_wait_for),
    ):
        result = await chat_pipeline.persona_chat(
            _make_request("I'm anxious about this demo and I need you to talk me down."),
            target="the_creator",
        )

    assert isinstance(result, dict)
    assert captured["timeout"] >= 10.0


def test_relationship_voice_contract_prioritizes_venting_over_coaching(fresh_pipeline):
    """Vent turns should ask the model to join the rant before offering fixes."""
    chat_pipeline, _llm_wrappers, _deps = fresh_pipeline

    contract = chat_pipeline._build_relationship_voice_contract(
        "Rohan dumped the cleanup on me again and I'm pissed.",
        role="casual",
        session_mode="safe",
        prompt_depth="full",
    )

    assert "side with the user's frustration first" in contract
    assert "Do not rush into coaching" in contract
    assert "Do not end every vent reply with an offer" in contract


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
