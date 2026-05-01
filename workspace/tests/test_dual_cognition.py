"""
Test Suite: Dual Cognition Engine (Unit Tests)
===============================================
Tests for DualCognitionEngine — the inner-monologue and tension-scoring
module that merges a "present" analysis stream with a "memory" recall stream.

Coverage targets:
  - classify_complexity() — FAST / STANDARD / DEEP routing
  - think() — full pipeline including FAST short-circuit and error recovery
  - _analyze_present() — LLM JSON parsing + edge cases
  - _recall_memory() — memory engine integration + error paths
  - _merge_streams() — CoT vs non-CoT merge, JSON parsing
  - _extract_search_intent() — deep-path pre-retrieval intent extraction
  - build_cognitive_context() — prompt injection string assembly
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.dual_cognition import (
    FAST_PHRASES,
    CognitiveMerge,
    DualCognitionEngine,
    MemoryStream,
    PresentStream,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_memory():
    """Mock MemoryEngine with a working query() method."""
    mem = MagicMock()
    mem.query.return_value = {
        "results": [
            {"content": "User loves Python and hates Java."},
            {"content": "User is preparing for a job interview."},
        ],
        "graph_context": "Python -> loves -> User",
    }
    return mem


@pytest.fixture
def mock_graph():
    """Mock SQLiteGraph with a working get_entity_neighborhood()."""
    graph = MagicMock()
    graph.get_entity_neighborhood.return_value = "primary_user -> friend -> AI"
    return graph


@pytest.fixture
def engine(mock_memory, mock_graph):
    """DualCognitionEngine wired to mock dependencies."""
    return DualCognitionEngine(memory_engine=mock_memory, graph=mock_graph)


@pytest.fixture
def llm_fn_analyze():
    """AsyncMock LLM function that returns a valid _analyze_present JSON."""
    fn = AsyncMock()
    fn.return_value = json.dumps(
        {
            "sentiment": "positive",
            "intent": "statement",
            "claims": ["I finished the project"],
            "emotional_state": "excited",
            "topics": ["project", "work"],
            "conversational_pattern": "continuation",
        }
    )
    return fn


@pytest.fixture
def llm_fn_merge():
    """AsyncMock LLM function returning valid merge JSON (used for merge calls)."""
    fn = AsyncMock()
    fn.return_value = json.dumps(
        {
            "thought": "User seems happy about finishing the project.",
            "tension_level": 0.1,
            "tension_type": "none",
            "contradictions": [],
            "response_strategy": "celebrate",
            "suggested_tone": "proud",
            "inner_monologue": "They finished it — time to celebrate.",
        }
    )
    return fn


def _make_llm_fn(*responses):
    """Create an AsyncMock that returns successive responses on each call."""
    fn = AsyncMock()
    fn.side_effect = list(responses)
    return fn


# ---------------------------------------------------------------------------
# classify_complexity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassifyComplexity:
    def test_fast_phrase_returns_fast(self, engine):
        for phrase in ["hi", "hello", "ok", "thanks", "bye", "lol"]:
            assert engine.classify_complexity(phrase) == "fast"

    def test_fast_phrases_case_insensitive(self, engine):
        assert engine.classify_complexity("Hi") == "fast"
        assert engine.classify_complexity("HELLO") == "fast"
        assert engine.classify_complexity("  Ok  ") == "fast"

    def test_short_message_no_punctuation_returns_fast(self, engine):
        assert engine.classify_complexity("sounds good") == "fast"
        assert engine.classify_complexity("not bad") == "fast"

    def test_short_message_with_question_mark_not_fast(self, engine):
        result = engine.classify_complexity("why?")
        assert result in ("standard", "deep")  # question mark blocks fast path

    def test_short_message_with_exclamation_not_fast(self, engine):
        result = engine.classify_complexity("what!")
        assert result in ("standard", "deep")

    def test_normal_message_returns_standard(self, engine):
        assert (
            engine.classify_complexity("How was your weekend trip to the mountains") == "standard"
        )

    def test_long_message_plus_contradictions_returns_deep(self, engine):
        msg = "I told you before that I never liked this approach however " + " ".join(
            ["word"] * 60
        )
        assert engine.classify_complexity(msg) == "deep"

    def test_emotional_markers_plus_sentences_returns_deep(self, engine):
        msg = "I'm stuck and frustrated. I can't figure this out. Help me please."
        assert engine.classify_complexity(msg) == "deep"

    def test_long_history_adds_deep_signal(self, engine):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(7)]
        msg = "But actually I don't think that's correct"  # 1 contradiction signal
        assert engine.classify_complexity(msg, history) == "deep"

    def test_ambiguity_markers_contribute_deep_signal(self, engine):
        msg = "Remember when we talked about that thing? I'm frustrated about it."
        assert engine.classify_complexity(msg) == "deep"

    def test_none_history_safe(self, engine):
        assert engine.classify_complexity("hello", None) == "fast"

    def test_empty_history_safe(self, engine):
        assert engine.classify_complexity("hello", []) == "fast"


# ---------------------------------------------------------------------------
# think (full pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThink:
    async def test_fast_path_no_llm_calls(self, engine):
        llm_fn = AsyncMock()
        merge = await engine.think("hi", chat_id="c1", llm_fn=llm_fn)
        assert isinstance(merge, CognitiveMerge)
        assert merge.tension_level == 0.0
        assert merge.response_strategy == "acknowledge"
        llm_fn.assert_not_called()

    async def test_standard_path_returns_cognitive_merge(self, engine):
        analyze_resp = json.dumps(
            {
                "sentiment": "neutral",
                "intent": "statement",
                "claims": [],
                "emotional_state": "calm",
                "topics": ["test"],
                "conversational_pattern": "single_turn",
            }
        )
        merge_resp = json.dumps(
            {
                "thought": "",
                "tension_level": 0.2,
                "tension_type": "none",
                "contradictions": [],
                "response_strategy": "acknowledge",
                "suggested_tone": "warm",
                "inner_monologue": "Standard reply.",
            }
        )
        llm_fn = _make_llm_fn(analyze_resp, merge_resp)
        merge = await engine.think(
            "Tell me about Python web frameworks",
            chat_id="c1",
            llm_fn=llm_fn,
        )
        assert isinstance(merge, CognitiveMerge)
        assert merge.tension_type == "none"
        assert llm_fn.call_count == 2  # analyze + merge

    async def test_deep_path_uses_analyze_and_merge(self, engine):
        intent_resp = json.dumps(["Python", "interview", "preparation"])
        analyze_resp = json.dumps(
            {
                "sentiment": "negative",
                "intent": "venting",
                "claims": ["I'm failing"],
                "emotional_state": "frustrated",
                "topics": ["interview"],
                "conversational_pattern": "escalation",
            }
        )
        merge_resp = json.dumps(
            {
                "thought": "They're stressed about interviews.",
                "tension_level": 0.6,
                "tension_type": "growth",
                "contradictions": [],
                "response_strategy": "support",
                "suggested_tone": "concerned",
                "inner_monologue": "Need to help them.",
            }
        )
        llm_fn = _make_llm_fn(intent_resp, analyze_resp, merge_resp)
        # Build a message that triggers deep path (emotional + contradiction + long history)
        history = [{"role": "user", "content": f"msg {i}"} for i in range(8)]
        msg = "I'm stuck and can't do this anymore. I told you I'd never fail but actually I did."
        merge = await engine.think(msg, chat_id="c1", conversation_history=history, llm_fn=llm_fn)
        assert isinstance(merge, CognitiveMerge)
        assert llm_fn.call_count == 2  # analyze + merge

    async def test_foreground_single_llm_mode_skips_present_analysis(self, engine):
        merge_resp = json.dumps(
            {
                "thought": "The user is venting about unfair office politics.",
                "tension_level": 0.5,
                "tension_type": "growth",
                "contradictions": [],
                "response_strategy": "support",
                "suggested_tone": "firm",
                "inner_monologue": "Side with the fair frustration before giving advice.",
            }
        )
        llm_fn = AsyncMock(return_value=merge_resp)
        msg = "I'm pissed because Rohan dumped cleanup on me. I can't sleep and feel anxious."

        merge = await engine.think(msg, chat_id="c1", llm_fn=llm_fn, max_llm_calls=1)

        assert isinstance(merge, CognitiveMerge)
        assert llm_fn.call_count == 1
        prompt_text = llm_fn.call_args.args[0][0]["content"]
        assert "Intent: venting" in prompt_text
        assert "Emotional state: anxious" in prompt_text

    async def test_none_history_safe(self, engine):
        merge = await engine.think("hi", chat_id="c1", conversation_history=None)
        assert isinstance(merge, CognitiveMerge)

    async def test_llm_exception_returns_fallback(self, engine):
        llm_fn = AsyncMock(side_effect=RuntimeError("LLM is down"))
        merge = await engine.think(
            "How is Python different from Java",
            chat_id="c1",
            llm_fn=llm_fn,
        )
        assert isinstance(merge, CognitiveMerge)
        assert merge.tension_level == 0.0
        assert "trouble" in merge.inner_monologue.lower()

    async def test_llm_timeout_returns_fallback(self, engine):
        llm_fn = AsyncMock(side_effect=TimeoutError())
        merge = await engine.think(
            "Explain quantum computing in detail",
            chat_id="c1",
            llm_fn=llm_fn,
        )
        assert isinstance(merge, CognitiveMerge)
        assert merge.response_strategy == "acknowledge"


# ---------------------------------------------------------------------------
# _analyze_present
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalyzePresent:
    async def test_json_parsing_success(self, engine, llm_fn_analyze):
        result = await engine._analyze_present("I finished the project", None, llm_fn_analyze)
        assert isinstance(result, PresentStream)
        assert result.sentiment == "positive"
        assert result.intent == "statement"
        assert "project" in result.topics

    async def test_no_llm_fn_returns_defaults(self, engine):
        result = await engine._analyze_present("test message", None, None)
        assert result.sentiment == "neutral"
        assert result.intent == "statement"

    async def test_malformed_json_returns_defaults(self, engine):
        llm_fn = AsyncMock(return_value="this is not json at all")
        result = await engine._analyze_present("test", None, llm_fn)
        assert isinstance(result, PresentStream)
        assert result.sentiment == "neutral"

    async def test_markdown_fenced_json_parsed(self, engine):
        fenced = (
            '```json\n{"sentiment":"negative","intent":"venting","claims":[],'
            '"emotional_state":"angry","topics":["work"],'
            '"conversational_pattern":"escalation"}\n```'
        )
        llm_fn = AsyncMock(return_value=fenced)
        result = await engine._analyze_present("I hate this", None, llm_fn)
        assert result.sentiment == "negative"
        assert result.emotional_state == "angry"

    async def test_thinking_block_stripped(self, engine):
        response = "[THINKING]some reasoning[/THINKING]" + json.dumps(
            {
                "sentiment": "positive",
                "intent": "bragging",
                "claims": ["I got promoted"],
                "emotional_state": "excited",
                "topics": ["career"],
                "conversational_pattern": "single_turn",
            }
        )
        llm_fn = AsyncMock(return_value=response)
        result = await engine._analyze_present("I got promoted!", None, llm_fn)
        assert result.sentiment == "positive"
        assert result.intent == "bragging"

    async def test_llm_exception_returns_present_with_defaults(self, engine):
        llm_fn = AsyncMock(side_effect=Exception("LLM crashed"))
        result = await engine._analyze_present("test", None, llm_fn)
        assert isinstance(result, PresentStream)
        assert result.raw_message == "test"
        assert result.sentiment == "neutral"

    async def test_history_context_injected(self, engine):
        llm_fn = AsyncMock(
            return_value=json.dumps(
                {
                    "sentiment": "neutral",
                    "intent": "statement",
                    "claims": [],
                    "emotional_state": "calm",
                    "topics": [],
                    "conversational_pattern": "continuation",
                }
            )
        )
        history = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Reply"},
            {"role": "user", "content": "Follow up"},
        ]
        await engine._analyze_present("another message", history, llm_fn)
        call_args = llm_fn.call_args[0][0]  # first positional arg (messages list)
        prompt_text = call_args[0]["content"]
        assert "First message" in prompt_text


# ---------------------------------------------------------------------------
# _recall_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecallMemory:
    async def test_memory_query_returns_results(self, engine, mock_memory):
        result = await engine._recall_memory("Python tips", "c1", "the_creator")
        assert isinstance(result, MemoryStream)
        assert len(result.relevant_facts) == 2
        assert "Python" in result.relevant_facts[0]

    async def test_graph_relationship_context(self, engine, mock_graph):
        result = await engine._recall_memory("test", "c1", "the_creator")
        mock_graph.get_entity_neighborhood.assert_called_with("primary_user")
        assert result.relationship_context != ""

    async def test_partner_target_queries_partner_entity(self, engine, mock_graph):
        await engine._recall_memory("test", "c1", "the_partner")
        mock_graph.get_entity_neighborhood.assert_called_with("primary_partner")

    async def test_memory_error_returns_default(self, engine, mock_memory):
        mock_memory.query.side_effect = RuntimeError("DB locked")
        result = await engine._recall_memory("test", "c1", "the_creator")
        assert isinstance(result, MemoryStream)
        assert result.relevant_facts == []

    async def test_graph_error_still_returns_memory(self, engine, mock_memory, mock_graph):
        mock_graph.get_entity_neighborhood.side_effect = Exception("Graph broken")
        result = await engine._recall_memory("Python tips", "c1", "the_creator")
        assert len(result.relevant_facts) == 2
        assert result.relationship_context == ""


# ---------------------------------------------------------------------------
# _merge_streams
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeStreams:
    async def test_no_llm_fn_returns_empty_merge(self, engine):
        present = PresentStream(raw_message="test")
        memory = MemoryStream()
        merge = await engine._merge_streams(present, memory, "the_creator", llm_fn=None)
        assert isinstance(merge, CognitiveMerge)
        assert merge.inner_monologue == "No LLM for merge."

    async def test_non_cot_path(self, engine, llm_fn_merge):
        present = PresentStream(raw_message="I finished the project")
        memory = MemoryStream(relevant_facts=["User works on project X"])
        merge = await engine._merge_streams(
            present, memory, "the_creator", llm_fn_merge, use_cot=False
        )
        assert isinstance(merge, CognitiveMerge)
        assert merge.response_strategy == "celebrate"
        # max_tokens should be 400 for non-CoT
        call_kwargs = llm_fn_merge.call_args[1]
        assert call_kwargs["max_tokens"] == 400

    async def test_cot_path_uses_higher_token_limit(self, engine, llm_fn_merge):
        present = PresentStream(raw_message="deep question")
        memory = MemoryStream()
        await engine._merge_streams(present, memory, "the_creator", llm_fn_merge, use_cot=True)
        call_kwargs = llm_fn_merge.call_args[1]
        assert call_kwargs["max_tokens"] == 500

    async def test_merge_populates_memory_insights(self, engine, llm_fn_merge):
        present = PresentStream(raw_message="test")
        memory = MemoryStream(relevant_facts=["fact1", "fact2", "fact3", "fact4"])
        merge = await engine._merge_streams(
            present, memory, "the_creator", llm_fn_merge, use_cot=False
        )
        assert merge.memory_insights == ["fact1", "fact2", "fact3"]

    async def test_merge_llm_error_returns_empty_merge(self, engine):
        llm_fn = AsyncMock(side_effect=Exception("API down"))
        present = PresentStream(raw_message="test")
        memory = MemoryStream()
        merge = await engine._merge_streams(present, memory, "the_creator", llm_fn)
        assert isinstance(merge, CognitiveMerge)
        assert merge.thought == ""

    async def test_trajectory_section_injected(self, engine, llm_fn_merge):
        engine.trajectory = MagicMock()
        engine.trajectory.get_summary.return_value = "Mood: improving over last 3 messages"
        present = PresentStream(raw_message="test")
        memory = MemoryStream()
        await engine._merge_streams(present, memory, "the_creator", llm_fn_merge, use_cot=False)
        prompt_text = llm_fn_merge.call_args[0][0][0]["content"]
        assert "Mood: improving" in prompt_text


# ---------------------------------------------------------------------------
# _extract_search_intent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSearchIntent:
    async def test_returns_search_terms(self, engine):
        llm_fn = AsyncMock(return_value='["Python", "interview"]')
        result = await engine._extract_search_intent("prepare me for interview", None, llm_fn)
        assert "Python" in result
        assert "interview" in result

    async def test_no_llm_fn_returns_empty(self, engine):
        result = await engine._extract_search_intent("test", None, None)
        assert result == ""

    async def test_malformed_json_returns_empty(self, engine):
        llm_fn = AsyncMock(return_value="not json")
        result = await engine._extract_search_intent("test", None, llm_fn)
        assert result == ""

    async def test_llm_error_returns_empty(self, engine):
        llm_fn = AsyncMock(side_effect=Exception("timeout"))
        result = await engine._extract_search_intent("test", None, llm_fn)
        assert result == ""

    async def test_fenced_json_array_parsed(self, engine):
        llm_fn = AsyncMock(return_value='```json\n["topic1", "topic2"]\n```')
        result = await engine._extract_search_intent("test", None, llm_fn)
        assert "topic1" in result
        assert "topic2" in result

    async def test_limits_to_three_terms(self, engine):
        llm_fn = AsyncMock(return_value='["a", "b", "c", "d", "e"]')
        result = await engine._extract_search_intent("test", None, llm_fn)
        terms = result.split()
        assert len(terms) == 3


# ---------------------------------------------------------------------------
# build_cognitive_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildCognitiveContext:
    def test_empty_merge_returns_string_with_defaults(self, engine):
        ctx = engine.build_cognitive_context(CognitiveMerge())
        assert isinstance(ctx, str)
        assert "Tension Level" in ctx
        assert "0.0/1.0" in ctx
        assert "- None" in ctx  # no memory insights

    def test_populated_merge_includes_all_fields(self, engine):
        merge = CognitiveMerge(
            thought="Deep thinking here",
            tension_level=0.7,
            tension_type="direct_contradiction",
            response_strategy="challenge",
            memory_insights=["User said X before", "Pattern of Y"],
            suggested_tone="firm",
            inner_monologue="Something doesn't add up.",
            contradictions=["Said A but now says B"],
        )
        ctx = engine.build_cognitive_context(merge)
        assert "Something doesn't add up." in ctx
        assert "0.7/1.0" in ctx
        assert "direct_contradiction" in ctx
        assert "challenge" in ctx
        assert "firm" in ctx
        assert "User said X before" in ctx
        assert "Said A but now says B" in ctx

    def test_partial_merge_fields(self, engine):
        merge = CognitiveMerge(
            inner_monologue="Just a thought.",
            tension_level=0.3,
        )
        ctx = engine.build_cognitive_context(merge)
        assert "Just a thought." in ctx
        assert "0.3/1.0" in ctx
        assert "- None" in ctx  # no contradictions

    def test_context_contains_behavioral_rules(self, engine):
        ctx = engine.build_cognitive_context(CognitiveMerge())
        assert "BEHAVIORAL RULES" in ctx
        assert "tension > 0.5" in ctx


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDataclasses:
    def test_cognitive_merge_defaults(self):
        m = CognitiveMerge()
        assert m.thought == ""
        assert m.tension_level == 0.0
        assert m.tension_type == "none"
        assert m.response_strategy == "acknowledge"
        assert m.memory_insights == []
        assert m.suggested_tone == "warm"
        assert m.inner_monologue == ""
        assert m.contradictions == []

    def test_present_stream_defaults(self):
        p = PresentStream(raw_message="test")
        assert p.sentiment == "neutral"
        assert p.intent == "statement"
        assert p.topics == []
        assert p.claims == []
        assert p.emotional_state == "calm"
        assert p.conversational_pattern == "single_turn"

    def test_memory_stream_defaults(self):
        m = MemoryStream()
        assert m.relevant_facts == []
        assert m.relationship_context == ""
        assert m.graph_connections == ""
        assert m.contradictions == []

    def test_fast_phrases_is_frozenset(self):
        assert isinstance(FAST_PHRASES, frozenset)
        assert "hi" in FAST_PHRASES
        assert "hello" in FAST_PHRASES
        assert len(FAST_PHRASES) > 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
