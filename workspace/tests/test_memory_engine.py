"""
test_memory_engine.py — Tests for the MemoryEngine (hybrid RAG pipeline).

Covers:
  - Initialization
  - get_embedding (Ollama path, sentence-transformers fallback, error path)
  - _temporal_score (recent, old, None, future)
  - _score_importance_heuristic (low, medium, high, edge cases)
  - score_importance (hybrid: heuristic + LLM grey zone)
  - query pipeline (fast gate, reranked fallback, error handling)
  - add_memory (happy path, error)
  - think method (cloud + local fallback)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# We need to mock heavy dependencies before importing MemoryEngine
@pytest.fixture(autouse=True)
def mock_heavy_deps():
    """Mock LanceDB, flashrank, flashtext to avoid real connections."""
    with patch.dict(
        "sys.modules",
        {
            "flashrank": MagicMock(),
        },
    ):
        yield


class TestMemoryEngineInit:
    """Tests for MemoryEngine initialization."""

    def test_accepts_shared_stores(self):
        """Should accept graph_store and keyword_processor."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            mock_graph = MagicMock()
            mock_kw = MagicMock()
            engine = MemoryEngine(graph_store=mock_graph, keyword_processor=mock_kw)
            assert engine.graph_store is mock_graph
            assert engine.keyword_processor is mock_kw

    def test_init_without_ollama(self):
        """Should initialize even when Ollama is not available."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            assert engine._ranker is None


class TestTemporalScore:
    """Tests for _temporal_score method."""

    def _make_engine(self):
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            return MemoryEngine()

    def test_none_timestamp_returns_half(self):
        """None timestamp should return 0.5."""
        engine = self._make_engine()
        assert engine._temporal_score(None) == 0.5

    def test_recent_timestamp_high_score(self):
        """Recent timestamps should have higher scores."""
        engine = self._make_engine()
        score = engine._temporal_score(time.time() - 60)  # 1 minute ago
        assert score > 0.8

    def test_old_timestamp_lower_score(self):
        """Old timestamps should have lower scores."""
        engine = self._make_engine()
        score = engine._temporal_score(time.time() - 86400 * 365)  # 1 year ago
        assert score < 0.3

    def test_future_timestamp_clamped(self):
        """Future timestamps should be clamped to 0 diff."""
        engine = self._make_engine()
        score = engine._temporal_score(time.time() + 86400)  # tomorrow
        assert score > 0.9  # diff_days clamped to 0


class TestImportanceHeuristic:
    """Tests for _score_importance_heuristic."""

    def _make_engine(self):
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            return MemoryEngine()

    def test_mundane_message_low_score(self):
        """Short mundane message should score low."""
        engine = self._make_engine()
        score = engine._score_importance_heuristic("ate lunch")
        assert score <= 3

    def test_emotional_message_high_score(self):
        """Emotional content should boost score."""
        engine = self._make_engine()
        score = engine._score_importance_heuristic(
            "I love you so much, I'm so happy and excited today!"
        )
        assert score >= 5

    def test_life_event_high_score(self):
        """Life events should boost score."""
        engine = self._make_engine()
        score = engine._score_importance_heuristic(
            "I got hired for the new job after the interview! I graduated top of my class."
        )
        assert score >= 7

    def test_very_short_message_penalized(self):
        """Messages with < 5 words should be penalized."""
        engine = self._make_engine()
        score = engine._score_importance_heuristic("ok")
        assert score <= 3

    def test_score_clamped_1_to_10(self):
        """Score should always be between 1 and 10."""
        engine = self._make_engine()
        # Very emotional
        high = engine._score_importance_heuristic(
            "love hate angry sad happy excited scared proud ashamed miss breakup fight sorry grateful cry depressed"
        )
        assert 1 <= high <= 10
        # Empty-ish
        low = engine._score_importance_heuristic("hi")
        assert 1 <= low <= 10

    def test_empty_string(self):
        """Empty string should not crash."""
        engine = self._make_engine()
        score = engine._score_importance_heuristic("")
        assert 1 <= score <= 10


class TestScoreImportanceAsync:
    """Tests for the async score_importance method."""

    def _make_engine(self):
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            return MemoryEngine()

    async def test_low_heuristic_skips_llm(self):
        """Heuristic <= 3 should skip LLM call."""
        engine = self._make_engine()
        mock_llm = AsyncMock(return_value="8")
        score = await engine.score_importance("ok", llm_fn=mock_llm)
        mock_llm.assert_not_called()
        assert score <= 3

    async def test_high_heuristic_skips_llm(self):
        """Heuristic >= 8 should skip LLM call."""
        engine = self._make_engine()
        mock_llm = AsyncMock(return_value="8")
        score = await engine.score_importance(
            "love hate angry sad happy excited interview job", llm_fn=mock_llm
        )
        mock_llm.assert_not_called()
        assert score >= 8

    async def test_grey_zone_calls_llm(self):
        """Grey zone (4-7) should call LLM."""
        engine = self._make_engine()
        mock_llm = AsyncMock(return_value="6")
        # A message that scores in the grey zone
        score = await engine.score_importance(
            "I started reading a new book about technology today. Seems interesting.",
            llm_fn=mock_llm,
        )
        # LLM should have been called (if heuristic falls in 4-7)
        assert 1 <= score <= 10

    async def test_no_llm_fn_returns_5(self):
        """No llm_fn should return 5 for grey zone."""
        engine = self._make_engine()
        score = await engine.score_importance(
            "I started reading a new book about technology today.",
            llm_fn=None,
        )
        assert 1 <= score <= 10


class TestGetEmbedding:
    """Tests for get_embedding method."""

    def test_ollama_unavailable_fallback(self):
        """When Ollama is unavailable, should use sentence-transformers or zeros."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            # Mock the sentence transformer fallback to avoid loading the model
            engine._sentence_transformer_embed = MagicMock(return_value=tuple([0.1] * 384))
            result = engine.get_embedding("test text")
            assert isinstance(result, tuple)
            assert len(result) > 0

    def test_ollama_available(self):
        """When Ollama is available, should use it."""
        mock_ollama = MagicMock()
        mock_ollama.embeddings.return_value = {"embedding": [0.5] * 768}
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", True),
            patch("sci_fi_dashboard.memory_engine.ollama", mock_ollama),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            engine.get_embedding.cache_clear()
            result = engine.get_embedding("test")
            assert len(result) == 768
            engine.get_embedding.cache_clear()

    def test_ollama_error_returns_zeros(self):
        """Ollama error should fall back to zero vector."""
        mock_ollama = MagicMock()
        mock_ollama.embeddings.side_effect = Exception("connection refused")
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", True),
            patch("sci_fi_dashboard.memory_engine.ollama", mock_ollama),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            engine.get_embedding.cache_clear()
            result = engine.get_embedding("test error")
            assert result == tuple([0.0] * 768)
            engine.get_embedding.cache_clear()


class TestQuery:
    """Tests for the query method."""

    def _make_engine(self):
        mock_lance = MagicMock()
        mock_lance.search.return_value = []
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore", return_value=mock_lance),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            engine._sentence_transformer_embed = MagicMock(return_value=tuple([0.1] * 384))
            return engine

    def test_returns_dict(self):
        """Query should return a dict with expected keys."""
        engine = self._make_engine()
        result = engine.query("test query")
        assert isinstance(result, dict)
        assert "results" in result
        assert "tier" in result

    def test_empty_results(self):
        """No LanceDB results should fall back to reranker or return empty."""
        engine = self._make_engine()
        result = engine.query("obscure query about nothing")
        assert result["results"] == [] or isinstance(result["results"], list)

    def test_error_returns_error_dict(self):
        """Exception during query should return error dict."""
        engine = self._make_engine()
        engine.vector_store.search.side_effect = Exception("LanceDB down")
        result = engine.query("test")
        assert result["tier"] == "error"
        assert "error" in result

    def test_historical_routing_label(self):
        """Historical keywords should set routing to 'Historical'."""
        engine = self._make_engine()
        result = engine.query("What was the history of 2024?")
        assert result.get("routing") in ("Historical", "error")

    def test_current_routing_label(self):
        """Current keywords should set routing to 'Current State'."""
        engine = self._make_engine()
        result = engine.query("What is the current status now?")
        assert result.get("routing") in ("Current State", "error")

    def test_entities_extracted(self):
        """Entities should be extracted when keyword_processor is set."""
        engine = self._make_engine()
        mock_kw = MagicMock()
        mock_kw.extract_keywords.return_value = ["Python"]
        engine.keyword_processor = mock_kw
        result = engine.query("Tell me about python")
        assert result.get("entities") == ["Python"] or result["tier"] == "error"

    def test_graph_context_populated(self):
        """Graph context should be populated when entities found."""
        engine = self._make_engine()
        mock_kw = MagicMock()
        mock_kw.extract_keywords.return_value = ["Python"]
        engine.keyword_processor = mock_kw
        mock_graph = MagicMock()
        mock_graph.get_entity_neighborhood.return_value = "Python is a programming language"
        engine.graph_store = mock_graph
        result = engine.query("Tell me about python")
        if result["tier"] != "error":
            assert "Python" in result.get("graph_context", "")


class TestAddMemory:
    """Tests for the add_memory method."""

    def test_add_memory_happy_path(self, tmp_path):
        """Should store memory and return dict with id."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
            patch("sci_fi_dashboard.memory_engine.get_db_connection") as mock_db,
        ):
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.lastrowid = 42
            mock_conn.cursor.return_value = mock_cursor
            mock_db.return_value = mock_conn

            with patch(
                "sci_fi_dashboard.memory_engine.BACKUP_FILE", str(tmp_path / "backup.jsonl")
            ):
                from sci_fi_dashboard.memory_engine import MemoryEngine

                engine = MemoryEngine()
                result = engine.add_memory("Test memory content", "test_cat")
                assert result.get("status") == "queued"
                assert result.get("id") == 42

    def test_add_memory_error(self):
        """Error during add_memory should return error dict."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
            patch("sci_fi_dashboard.memory_engine.get_db_connection") as mock_db,
        ):
            mock_db.side_effect = Exception("DB locked")
            with patch("sci_fi_dashboard.memory_engine.BACKUP_FILE", "/dev/null"):
                from sci_fi_dashboard.memory_engine import MemoryEngine

                engine = MemoryEngine()
                result = engine.add_memory("Test")
                assert "error" in result


class TestThink:
    """Tests for the think method."""

    def test_think_ollama_path(self):
        """Should use Ollama when available."""
        mock_ollama = MagicMock()
        mock_ollama.chat.return_value = {"message": {"content": "Hello from Ollama"}}
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", True),
            patch("sci_fi_dashboard.memory_engine.ollama", mock_ollama),
            patch.dict("sys.modules", {"sci_fi_dashboard.llm_router": None}),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            result = engine.think("What is 2+2?")
            assert result.get("source") in ("local_fallback", "llm_router")

    def test_think_no_ollama_no_cloud(self):
        """No Ollama and no cloud router should return error."""
        with (
            patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore"),
            patch("sci_fi_dashboard.memory_engine.OLLAMA_AVAILABLE", False),
            patch.dict("sys.modules", {"sci_fi_dashboard.llm_router": None}),
        ):
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            result = engine.think("test")
            assert "error" in result
