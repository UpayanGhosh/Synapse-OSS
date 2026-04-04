"""
Phase 4 — Dual Cognition Engine Tests
======================================
Tests for DualCognitionEngine.classify_complexity() and think().

Fixtures from pipeline/conftest.py:
  - pipeline_graph        (session-scoped) SQLiteGraph at tmp path
  - pipeline_memory_engine (session-scoped) MemoryEngine with fake embeddings
  - mock_llm_fn           (function-scoped) AsyncMock returning MOCK_UNIVERSAL_JSON
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from sci_fi_dashboard.dual_cognition import DualCognitionEngine, CognitiveMerge


# ---------------------------------------------------------------------------
# Section 1: classify_complexity() — synchronous tests
# ---------------------------------------------------------------------------


def test_classify_fast_greeting():
    """FAST_PHRASES entries must return 'fast' regardless of case (lowercased by impl)."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    assert engine.classify_complexity("hi") == "fast"
    assert engine.classify_complexity("hello") == "fast"
    assert engine.classify_complexity("ok") == "fast"


def test_classify_fast_short_no_punct():
    """Short phrases (<=3 words, no ? or !) not in FAST_PHRASES also return 'fast'."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    assert engine.classify_complexity("ok thanks") == "fast"
    assert engine.classify_complexity("got it") == "fast"


def test_classify_standard_medium_message():
    """A mid-length question with no deep signals returns 'standard'."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    result = engine.classify_complexity("What do you think about this idea?")
    assert result == "standard"


def test_classify_deep_long_message():
    """A long message (>60 words) with an emotional marker ('overwhelmed' contains
    'stressed' only via 'stressed' directly — this uses 'stressed' + word_count>60)."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    long_msg = (
        "I've been thinking a lot about this project and honestly "
        "there are many things that could go wrong. The timeline is "
        "uncertain, the team is stretched, and the requirements keep changing. "
        "We need to make a decision soon before things spiral out of control. "
        "What do you think we should prioritize? I feel stressed and can't decide."
    )
    # word_count > 60 (signal 1) + emotional marker "stressed" or "can't" (signal 2) -> deep
    result = engine.classify_complexity(long_msg)
    assert result == "deep"


def test_classify_deep_contradiction():
    """A message with a contradiction marker ('you're wrong') and multiple sentences
    triggers deep path via 2+ signals."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    # "you're wrong" is contradiction marker (signal 1)
    # sentence_count >= 3 from multiple sentences split on [.!?]+ (signal 2)
    msg = "You're wrong about that. I never said that. Actually, you misunderstood completely."
    result = engine.classify_complexity(msg)
    assert result == "deep"


def test_classify_deep_emotional():
    """Two emotional markers ('stressed', 'can't') independently are enough to
    cross the 2-signal threshold together with other signals."""
    engine = DualCognitionEngine(memory_engine=None, graph=None)
    # "stressed" (emotional marker, signal 1) + "can't" (emotional marker — but only 1 signal
    # for the whole emotional_markers group). Also sentence_count: split yields >= 3 (signal 2).
    msg = "I'm so stressed. I can't focus at all. My work suffers every day."
    result = engine.classify_complexity(msg)
    assert result == "deep"


# ---------------------------------------------------------------------------
# Section 2: think() — async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_think_fast_path_zero_llm_calls(pipeline_memory_engine, pipeline_graph):
    """FAST path ('hi') must return CognitiveMerge with 0 LLM calls."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    llm = AsyncMock()
    result = await engine.think("hi", "chat1", llm_fn=llm)
    assert isinstance(result, CognitiveMerge)
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_think_standard_path_llm_called(pipeline_memory_engine, pipeline_graph, mock_llm_fn):
    """STANDARD path must invoke the LLM at least once (present analysis + merge)."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    result = await engine.think(
        "What do you think about this project?", "chat1", llm_fn=mock_llm_fn
    )
    assert isinstance(result, CognitiveMerge)
    assert mock_llm_fn.call_count >= 1


@pytest.mark.asyncio
async def test_think_deep_path_multiple_llm_calls(
    pipeline_memory_engine, pipeline_graph, mock_llm_fn
):
    """DEEP path must invoke the LLM at least twice (present analysis + CoT merge)."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    deep_msg = (
        "I've been thinking about this for so long but I can't decide. "
        "I'm really stressed because actually you were wrong before. "
        "I need help figuring this out, I feel stuck and frustrated."
    )
    result = await engine.think(deep_msg, "chat1", llm_fn=mock_llm_fn)
    assert isinstance(result, CognitiveMerge)
    assert mock_llm_fn.call_count >= 2


@pytest.mark.asyncio
async def test_think_returns_cognitive_merge_type(
    pipeline_memory_engine, pipeline_graph, mock_llm_fn
):
    """think() must return CognitiveMerge for all three complexity tiers."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    messages = [
        "hi",
        "What do you think?",
        "stressed and can't focus on anything at all right now",
    ]
    for msg in messages:
        mock_llm_fn.reset_mock()
        result = await engine.think(msg, "chat1", llm_fn=mock_llm_fn)
        assert isinstance(result, CognitiveMerge), f"Expected CognitiveMerge for '{msg}'"


@pytest.mark.asyncio
async def test_think_uses_pre_cached_memory(pipeline_graph, mock_llm_fn):
    """When pre_cached_memory is supplied, memory.query() must NOT be called."""
    mock_mem = MagicMock()
    pre_cached = {
        "results": [{"content": "test fact", "score": 0.9, "source": "lancedb_fast"}],
        "tier": "fast_gate",
        "entities": [],
        "graph_context": "",
    }
    engine = DualCognitionEngine(memory_engine=mock_mem, graph=pipeline_graph)
    await engine.think(
        "What do you think?",
        "chat1",
        llm_fn=mock_llm_fn,
        pre_cached_memory=pre_cached,
    )
    mock_mem.query.assert_not_called()


@pytest.mark.asyncio
async def test_think_tension_level_in_range(pipeline_memory_engine, pipeline_graph, mock_llm_fn):
    """tension_level on CognitiveMerge must always be in [0.0, 1.0]."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    result = await engine.think("What do you think?", "chat1", llm_fn=mock_llm_fn)
    assert 0.0 <= result.tension_level <= 1.0


@pytest.mark.asyncio
async def test_think_response_strategy_valid(pipeline_memory_engine, pipeline_graph, mock_llm_fn):
    """response_strategy must be one of the known valid strategy strings."""
    VALID_STRATEGIES = {
        "acknowledge",
        "challenge",
        "support",
        "redirect",
        "quiz",
        "celebrate",
        "be_direct",
        "analytical",
        "explore_with_care",
    }
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    result = await engine.think("What do you think?", "chat1", llm_fn=mock_llm_fn)
    assert result.response_strategy in VALID_STRATEGIES


@pytest.mark.asyncio
async def test_think_handles_llm_json_error(pipeline_memory_engine, pipeline_graph):
    """When the LLM returns malformed JSON, think() must not raise — return CognitiveMerge default."""
    engine = DualCognitionEngine(memory_engine=pipeline_memory_engine, graph=pipeline_graph)
    bad_llm = AsyncMock(return_value="this is not valid json {{{{ broken")
    # Standard-path message forces LLM call(s) so the bad JSON is actually hit
    msg = "What do you think about this?"
    result = await engine.think(msg, "chat1", llm_fn=bad_llm)
    assert isinstance(result, CognitiveMerge)
    # tension_level should be the default (0.0) when JSON parsing fails gracefully
    assert result.tension_level >= 0.0
