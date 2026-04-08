"""
test_phase6_end_to_end.py — Phase 6: End-to-end persona_chat() tests.

Tests cover:
  1.  persona_chat() returns a dict with a non-empty 'reply' string
  2.  Fast-path greeting ('hi') goes through exactly one LLM router call
  3.  memory.query() is invoked exactly once per persona_chat() call
  4.  CASUAL classification reaches the LLM router
  5.  STRATEGY_TO_ROLE shortcut skips route_traffic_cop when strategy matches
  6.  spicy session_type routes to 'vault' role
  7.  dual_cognition_enabled=False skips DualCognitionEngine.think()
  8.  Cognition timeout is handled gracefully — no crash, valid reply returned
  9.  10-turn conversation loop completes without errors
  10. Memory engine error is handled gracefully — pipeline continues

Run:
    cd workspace && pytest tests/pipeline/test_phase6_end_to_end.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_WORKSPACE = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _p in (_WORKSPACE, os.path.dirname(_WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sci_fi_dashboard.chat_pipeline import persona_chat
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.dual_cognition import CognitiveMerge
from sci_fi_dashboard.llm_router import LLMResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    msg: str,
    user_id: str = "test_user",
    history: list | None = None,
    session_type: str = "safe",
) -> ChatRequest:
    return ChatRequest(
        message=msg,
        user_id=user_id,
        history=history or [],
        session_type=session_type,
    )


def _make_llm_result(text: str = "Sure, I can help!") -> LLMResult:
    return LLMResult(
        text=text,
        model="test/mock",
        prompt_tokens=50,
        completion_tokens=20,
        total_tokens=70,
    )


def _make_mock_deps(memory_engine, dual_cognition) -> MagicMock:
    """Build a fully-stubbed deps module that satisfies all persona_chat() branches.

    - memory_engine / dual_cognition are the real fixtures from conftest.py so that
      retrieval and cognition paths are exercised.
    - synapse_llm_router is mocked so no real LLM calls are made.
    - Tool registry flags are all False so the tool-loop is skipped.
    """
    deps = MagicMock()

    # Core dependencies
    deps.memory_engine = memory_engine
    deps.dual_cognition = dual_cognition

    # Toxicity scorer — return low score (safe mode, no override triggered)
    deps.toxic_scorer.score.return_value = 0.1

    # Config — matches the shape of SynapseConfig.session (a plain dict)
    deps._synapse_cfg.session = {
        "dual_cognition_enabled": True,
        "dual_cognition_timeout": 10.0,
    }
    deps._synapse_cfg.raw = {}

    # LLM router — no real API calls
    deps.synapse_llm_router.call_with_metadata = AsyncMock(
        return_value=_make_llm_result()
    )
    # call_with_tools is not exposed by default so the pipeline falls back to
    # call_with_metadata — ensure hasattr() returns False for this attribute.
    del deps.synapse_llm_router.call_with_tools

    # Tool execution loop — disable all phases so no tool call machinery runs
    deps.tool_registry = None
    deps._TOOL_REGISTRY_AVAILABLE = False
    deps._TOOL_SAFETY_AVAILABLE = False
    deps._TOOL_FEATURES_AVAILABLE = False
    deps.MAX_TOOL_ROUNDS = 5
    deps.TOOL_RESULT_MAX_CHARS = 4000
    deps.MAX_TOTAL_TOOL_RESULT_CHARS = 20_000

    # Proactive engine (optional, can be None)
    deps._proactive_engine = None

    # SBS orchestrator stub — returns minimal data so the pipeline doesn't crash
    mock_sbs = MagicMock()
    mock_sbs.on_message.return_value = {"msg_id": "test-msg-id"}
    mock_sbs.get_system_prompt.return_value = "You are Synapse."
    deps.get_sbs_for_target.return_value = mock_sbs

    return deps


# ===========================================================================
# Test 1 — persona_chat() returns a dict with a non-empty reply
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_returns_dict_with_reply(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """persona_chat() must return a dict containing a non-empty 'reply' string."""
    request = _make_request("Hello!")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict), f"persona_chat() must return a dict, got {type(result)}"
    assert "reply" in result, f"Result dict must contain 'reply', got keys: {list(result.keys())}"
    assert isinstance(result["reply"], str), "result['reply'] must be a string"
    assert len(result["reply"]) > 0, "result['reply'] must be non-empty"


# ===========================================================================
# Test 2 — Fast-path greeting uses exactly one LLM router call
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_fast_path_greeting(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """Short greeting 'hi' should complete with exactly one call to call_with_metadata."""
    request = _make_request("hi")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert "reply" in result
    # In the safe hemisphere, no tool calls → exactly one call_with_metadata invocation
    assert mock_deps.synapse_llm_router.call_with_metadata.call_count == 1, (
        f"Expected exactly 1 LLM call for a simple greeting, "
        f"got {mock_deps.synapse_llm_router.call_with_metadata.call_count}"
    )


# ===========================================================================
# Test 3 — memory.query() is called exactly once per persona_chat() invocation
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_memory_queried_once(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """memory_engine.query() must be called exactly once — shared with dual cognition."""
    request = _make_request("Tell me about technology")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    # Wrap the real memory engine in a spy so we can count calls
    from unittest.mock import patch as _patch

    real_query = pipeline_memory_engine.query
    call_count = []

    def _spy_query(*args, **kwargs):
        call_count.append(1)
        return real_query(*args, **kwargs)

    mock_deps.memory_engine.query = _spy_query

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert len(call_count) == 1, (
        f"memory.query() must be called exactly once per request, "
        f"but was called {len(call_count)} time(s)"
    )


# ===========================================================================
# Test 4 — CASUAL classification causes the LLM router to be called
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_traffic_cop_casual_uses_llm_router(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """When traffic cop returns CASUAL, call_with_metadata must be invoked."""
    request = _make_request("What's up? Just chatting about random stuff.")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    # Force response_strategy not in STRATEGY_TO_ROLE so the traffic cop fallback runs.
    # "explore_with_care" is not a key in STRATEGY_TO_ROLE, so the pipeline calls cop.
    mock_dc = MagicMock()
    mock_dc.think = AsyncMock(return_value=CognitiveMerge(response_strategy="explore_with_care"))
    mock_dc.build_cognitive_context.return_value = ""
    mock_deps.dual_cognition = mock_dc

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ) as mock_cop:
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    assert "reply" in result
    assert mock_deps.synapse_llm_router.call_with_metadata.called, (
        "call_with_metadata must be invoked after CASUAL classification"
    )
    mock_cop.assert_called_once()


# ===========================================================================
# Test 5 — STRATEGY_TO_ROLE shortcut skips route_traffic_cop
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_strategy_shortcut_skips_traffic_cop(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """When CognitiveMerge.response_strategy maps to a role via STRATEGY_TO_ROLE,
    route_traffic_cop must NOT be called (the traffic-cop LLM call is skipped).

    'acknowledge' maps to 'CASUAL' in STRATEGY_TO_ROLE (verified from source).
    """
    request = _make_request("I see, makes sense to me.")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    # Inject a CognitiveMerge whose strategy is in STRATEGY_TO_ROLE
    fixed_merge = CognitiveMerge(
        response_strategy="acknowledge",  # maps to "CASUAL" in STRATEGY_TO_ROLE
        tension_level=0.0,
        inner_monologue="All clear.",
    )
    mock_dc = MagicMock()
    mock_dc.think = AsyncMock(return_value=fixed_merge)
    mock_dc.build_cognitive_context.return_value = "Acknowledge mode."
    mock_deps.dual_cognition = mock_dc

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
        ) as mock_cop:
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    mock_cop.assert_not_called(), (
        "route_traffic_cop must NOT be called when response_strategy maps to a known role"
    )


# ===========================================================================
# Test 6 — spicy session_type routes to 'vault' role
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_spicy_routes_to_vault(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """A request with session_type='spicy' must call call_with_metadata with role='vault'."""
    request = _make_request("Tell me something private", session_type="spicy")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    calls = mock_deps.synapse_llm_router.call_with_metadata.call_args_list
    assert len(calls) >= 1, "call_with_metadata must be invoked at least once for spicy requests"

    # First positional argument to call_with_metadata is the role
    roles_used = [call.args[0] if call.args else call.kwargs.get("role") for call in calls]
    assert "vault" in roles_used, (
        f"spicy session_type must route to 'vault' role. Roles seen: {roles_used}"
    )


# ===========================================================================
# Test 7 — dual_cognition_enabled=False skips DualCognitionEngine.think()
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_dual_cognition_disabled(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """When dual_cognition_enabled=False, think() must not be called."""
    request = _make_request("Hello there!")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)
    mock_deps._synapse_cfg.session = {
        "dual_cognition_enabled": False,
        "dual_cognition_timeout": 5.0,
    }

    # Replace the real dual_cognition with a mock so we can assert on .think
    mock_dc = MagicMock()
    mock_dc.think = AsyncMock(return_value=CognitiveMerge())
    mock_dc.build_cognitive_context.return_value = ""
    mock_deps.dual_cognition = mock_dc

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict)
    mock_dc.think.assert_not_called(), (
        "dual_cognition.think() must NOT be called when dual_cognition_enabled=False"
    )


# ===========================================================================
# Test 8 — Cognition timeout handled gracefully
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_cognition_timeout_handled(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """A think() that exceeds dual_cognition_timeout must not crash persona_chat().

    The pipeline must return a valid reply even when cognition times out.
    """
    request = _make_request("What do you think about complex topics?")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)
    mock_deps._synapse_cfg.session = {
        "dual_cognition_enabled": True,
        "dual_cognition_timeout": 0.001,  # 1 ms — guaranteed to expire
    }

    async def slow_think(*args, **kwargs):
        await asyncio.sleep(1.0)  # much longer than the 1 ms timeout
        return CognitiveMerge()

    mock_deps.dual_cognition.think = slow_think

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict), "persona_chat() must return a dict even on cognition timeout"
    assert "reply" in result
    assert isinstance(result["reply"], str) and len(result["reply"]) > 0, (
        "reply must be a non-empty string even when cognition times out"
    )


# ===========================================================================
# Test 9 — 10-turn conversation loop completes without errors
# ===========================================================================


@pytest.mark.asyncio
async def test_10_turn_conversation_no_crash(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """A 10-turn simulated conversation must not raise any exception."""
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)
    history: list[dict] = []

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            for i in range(10):
                request = _make_request(
                    f"Message {i}: What do you think?",
                    history=list(history),  # pass a copy
                )
                result = await persona_chat(request, target="the_creator")

                assert isinstance(result, dict), (
                    f"Turn {i}: persona_chat() must return a dict"
                )
                assert "reply" in result, f"Turn {i}: result must contain 'reply'"
                assert isinstance(result["reply"], str) and len(result["reply"]) > 0, (
                    f"Turn {i}: reply must be a non-empty string"
                )

                # Extend history as a real client would
                history.append({"role": "user", "content": f"Message {i}: What do you think?"})
                history.append({"role": "assistant", "content": result["reply"]})


# ===========================================================================
# Test 10 — Memory engine error handled gracefully
# ===========================================================================


@pytest.mark.asyncio
async def test_persona_chat_memory_error_handled_gracefully(
    pipeline_memory_engine, pipeline_dual_cognition
):
    """When memory_engine.query() raises, persona_chat() must continue and return a valid reply.

    The pipeline catches the exception internally and sets memory_context to a
    fallback string, so the LLM call proceeds normally.
    """
    request = _make_request("Hello!")
    mock_deps = _make_mock_deps(pipeline_memory_engine, pipeline_dual_cognition)
    # Force the memory engine to raise on every query() call
    mock_deps.memory_engine.query = MagicMock(
        side_effect=RuntimeError("DB connection failed")
    )

    with patch("sci_fi_dashboard.chat_pipeline.deps", mock_deps):
        with patch(
            "sci_fi_dashboard.llm_wrappers.route_traffic_cop",
            new_callable=AsyncMock,
            return_value="CASUAL",
        ):
            result = await persona_chat(request, target="the_creator")

    assert isinstance(result, dict), (
        "persona_chat() must return a dict even when memory engine raises"
    )
    assert "reply" in result
    assert isinstance(result["reply"], str) and len(result["reply"]) > 0, (
        "reply must be non-empty even when memory retrieval fails"
    )
    # The LLM router must still have been called (pipeline continued after memory failure)
    assert mock_deps.synapse_llm_router.call_with_metadata.called, (
        "LLM router must still be invoked even when memory engine raises"
    )
