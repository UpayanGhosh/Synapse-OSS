"""
test_retriever.py — Tests for the RetrievalPipeline (retriever module).

Covers:
  - _init_embedder (Ollama, sentence-transformers, FTS-only)
  - get_embedding
  - _serialize_f32
  - query_memories (vector, FTS fallback, hemisphere filtering)
  - format_context_for_prompt
  - get_db_stats
"""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


class TestSerializeF32:
    """Tests for the _serialize_f32 helper."""

    def test_basic_serialization(self):
        """Should pack floats into binary."""
        from sci_fi_dashboard.retriever import _serialize_f32

        vec = [1.0, 2.0, 3.0]
        result = _serialize_f32(vec)
        assert isinstance(result, bytes)
        assert len(result) == 12  # 3 floats * 4 bytes

    def test_round_trip(self):
        """Should survive a pack/unpack round trip."""
        from sci_fi_dashboard.retriever import _serialize_f32

        vec = [0.5, -1.0, 3.14]
        blob = _serialize_f32(vec)
        unpacked = struct.unpack(f"{len(vec)}f", blob)
        for a, b in zip(vec, unpacked, strict=False):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self):
        """Empty vector should produce empty bytes."""
        from sci_fi_dashboard.retriever import _serialize_f32

        assert _serialize_f32([]) == b""

    def test_large_vector(self):
        """Large vectors should serialize correctly."""
        from sci_fi_dashboard.retriever import _serialize_f32

        vec = [float(i) for i in range(768)]
        result = _serialize_f32(vec)
        assert len(result) == 768 * 4


class TestInitEmbedder:
    """Tests for embedder initialization."""

    def test_fts_only_when_nothing_available(self):
        """When neither Ollama nor sentence-transformers, should use FTS-only."""
        import sci_fi_dashboard.retriever as ret

        old_mode = ret._embed_mode
        old_embedder = ret._embedder
        try:
            ret._embed_mode = None
            ret._embedder = None
            with (
                patch.dict("sys.modules", {"ollama": None}),
                patch("sci_fi_dashboard.retriever.ollama", None),
            ):
                # Force Ollama to fail
                mock_ollama = MagicMock()
                mock_ollama.embeddings.side_effect = Exception("no ollama")
                with patch("sci_fi_dashboard.retriever.ollama", mock_ollama):
                    # Also fail sentence-transformers
                    orig_import = (
                        __builtins__.__import__
                        if hasattr(__builtins__, "__import__")
                        else __import__
                    )

                    def fake_import(name, *args, **kwargs):
                        if name == "sentence_transformers":
                            raise ImportError("no ST")
                        return orig_import(name, *args, **kwargs)

                    with patch("builtins.__import__", side_effect=fake_import):
                        ret._init_embedder()
                        assert ret._embed_mode == "fts_only"
        finally:
            ret._embed_mode = old_mode
            ret._embedder = old_embedder


class TestGetEmbedding:
    """Tests for the get_embedding function."""

    def test_fts_only_returns_none(self):
        """FTS-only mode should return None."""
        import sci_fi_dashboard.retriever as ret

        old_mode = ret._embed_mode
        try:
            ret._embed_mode = "fts_only"
            from sci_fi_dashboard.retriever import get_embedding

            result = get_embedding("test text")
            assert result is None
        finally:
            ret._embed_mode = old_mode

    def test_ollama_mode(self):
        """Ollama mode should call ollama.embeddings."""
        import sci_fi_dashboard.retriever as ret

        old_mode = ret._embed_mode
        mock_ollama = MagicMock()
        mock_ollama.embeddings.return_value = {"embedding": [0.1] * 768}
        try:
            ret._embed_mode = "ollama"
            with patch("sci_fi_dashboard.retriever.ollama", mock_ollama):
                from sci_fi_dashboard.retriever import get_embedding

                result = get_embedding("test")
                assert len(result) == 768
                mock_ollama.embeddings.assert_called_once()
        finally:
            ret._embed_mode = old_mode

    def test_sentence_transformers_mode(self):
        """Sentence-transformers mode should use the loaded model."""
        import sci_fi_dashboard.retriever as ret

        old_mode = ret._embed_mode
        old_embedder = ret._embedder
        mock_embedder = MagicMock()
        import numpy as np

        mock_embedder.encode.return_value = np.array([0.2] * 384)
        try:
            ret._embed_mode = "sentence-transformers"
            ret._embedder = mock_embedder
            from sci_fi_dashboard.retriever import get_embedding

            result = get_embedding("test")
            assert len(result) == 384
        finally:
            ret._embed_mode = old_mode
            ret._embedder = old_embedder


class TestFormatContextForPrompt:
    """Tests for format_context_for_prompt."""

    def test_empty_results(self):
        """No results should return 'no relevant memories' message."""
        from sci_fi_dashboard.retriever import format_context_for_prompt

        result = format_context_for_prompt({})
        assert "No relevant memories" in result

    def test_with_facts(self):
        """Should format facts section."""
        from sci_fi_dashboard.retriever import format_context_for_prompt

        memory_results = {
            "facts": [{"content": "Python is a language", "category": "tech"}],
            "documents": [],
            "relationships": [],
        }
        result = format_context_for_prompt(memory_results)
        assert "Known Facts" in result
        assert "Python is a language" in result

    def test_with_documents(self):
        """Should format documents section."""
        from sci_fi_dashboard.retriever import format_context_for_prompt

        memory_results = {
            "facts": [],
            "documents": [{"content": "Doc content here" * 10, "source": "test.txt"}],
            "relationships": [],
        }
        result = format_context_for_prompt(memory_results)
        assert "Relevant Context" in result

    def test_with_relationships(self):
        """Should format relationships section."""
        from sci_fi_dashboard.retriever import format_context_for_prompt

        memory_results = {
            "facts": [],
            "documents": [],
            "relationships": [
                {"category": "friendship", "content": "Best friends", "source": "chat"}
            ],
        }
        result = format_context_for_prompt(memory_results)
        assert "Relationship Notes" in result

    def test_truncates_documents(self):
        """Document content should be truncated to 200 chars."""
        from sci_fi_dashboard.retriever import format_context_for_prompt

        memory_results = {
            "facts": [],
            "documents": [{"content": "x" * 500, "source": "test"}],
            "relationships": [],
        }
        result = format_context_for_prompt(memory_results)
        # The formatted doc line should have truncated content
        assert len(result) < 500 + 100  # some overhead for headers


class TestGetDbStats:
    """Tests for get_db_stats."""

    def test_returns_dict(self):
        """Should return a dict with expected keys."""
        with patch("sci_fi_dashboard.retriever.get_db_connection") as mock_conn:
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (0,)
            conn.cursor.return_value = cursor
            conn.execute.return_value = cursor
            mock_conn.return_value = conn

            with patch("sci_fi_dashboard.retriever.os.path.getsize", return_value=1024 * 1024):
                import sci_fi_dashboard.retriever as ret
                from sci_fi_dashboard.retriever import get_db_stats

                old_mode = ret._embed_mode
                ret._embed_mode = "test"
                try:
                    stats = get_db_stats()
                    assert isinstance(stats, dict)
                    assert "atomic_facts" in stats
                    assert "documents" in stats
                    assert "embed_mode" in stats
                finally:
                    ret._embed_mode = old_mode

    def test_handles_missing_tables(self):
        """Should handle missing tables gracefully (return 0 counts)."""
        with patch("sci_fi_dashboard.retriever.get_db_connection") as mock_conn:
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.side_effect = Exception("no such table")
            conn.cursor.return_value = cursor
            conn.execute.side_effect = Exception("no such table")
            mock_conn.return_value = conn

            with patch("sci_fi_dashboard.retriever.os.path.getsize", return_value=0):
                import sci_fi_dashboard.retriever as ret
                from sci_fi_dashboard.retriever import get_db_stats

                old_mode = ret._embed_mode
                ret._embed_mode = "test"
                try:
                    stats = get_db_stats()
                    assert stats.get("atomic_facts", 0) == 0
                finally:
                    ret._embed_mode = old_mode
