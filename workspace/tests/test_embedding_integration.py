"""
Integration tests for the EmbeddingProvider abstraction rewire (Phase 2).

Verifies that retriever.py, memory_engine.py, and ingest.py all route
embedding calls through the EmbeddingProvider abstraction rather than
calling ollama or sentence_transformers directly.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Pre-stub lancedb so memory_engine is importable without the package installed.
sys.modules.setdefault("lancedb", MagicMock())


def _make_provider(dims: int = 768, name: str = "test-provider") -> MagicMock:
    """Build a minimal mock EmbeddingProvider."""
    info = MagicMock()
    info.name = name
    info.dimensions = dims

    provider = MagicMock()
    provider.info.return_value = info
    provider.dimensions = dims
    provider.embed_query.return_value = [0.1] * dims
    provider.embed_documents.return_value = [[0.1] * dims]
    return provider


class TestRetrieverGetEmbedding(unittest.TestCase):
    """retriever.get_embedding() must delegate to the provider."""

    def test_get_embedding_uses_provider(self):
        """embed_query() on the provider is called with the query text."""
        mock_provider = _make_provider()

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            from sci_fi_dashboard import retriever

            result = retriever.get_embedding("hello")

        mock_provider.embed_query.assert_called_once_with("hello")
        self.assertEqual(result, [0.1] * 768)

    def test_retriever_fallback_to_none_when_no_provider(self):
        """get_embedding() returns None when get_provider() returns None."""
        with patch("sci_fi_dashboard.retriever.get_provider", return_value=None):
            from sci_fi_dashboard import retriever

            result = retriever.get_embedding("text")

        self.assertIsNone(result)


class TestMemoryEngineGetEmbedding(unittest.TestCase):
    """MemoryEngine.get_embedding() must delegate to the provider."""

    def _make_engine(self, provider):
        """Create MemoryEngine with patched dependencies."""
        lancedb_patch = patch(
            "sci_fi_dashboard.memory_engine.LanceDBVectorStore", return_value=MagicMock()
        )
        get_provider_patch = patch(
            "sci_fi_dashboard.memory_engine.get_provider", return_value=provider
        )
        with lancedb_patch, get_provider_patch:
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            # Clear LRU cache so tests are independent
            engine.get_embedding.cache_clear()
        return engine

    def test_memory_engine_get_embedding_uses_provider(self):
        """embed_query() is called on the provider with the query text."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        result = engine.get_embedding("test")

        mock_provider.embed_query.assert_called_once_with("test")
        self.assertEqual(result, tuple([0.1] * 768))

    def test_memory_engine_lru_cache_works(self):
        """Calling get_embedding() with the same text twice only calls embed_query once."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        engine.get_embedding("same text")
        engine.get_embedding("same text")

        mock_provider.embed_query.assert_called_once_with("same text")

    def test_memory_engine_zero_vector_on_failure(self):
        """Returns a tuple of zeros when embed_query raises an exception."""
        mock_provider = _make_provider(dims=768)
        mock_provider.embed_query.side_effect = RuntimeError("connection refused")
        engine = self._make_engine(mock_provider)

        result = engine.get_embedding("bad text")

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 768)
        self.assertTrue(all(v == 0.0 for v in result))

    def test_memory_engine_zero_vector_when_no_provider(self):
        """Returns a tuple of 768 zeros when get_provider() returns None."""
        engine = self._make_engine(None)

        result = engine.get_embedding("text")

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 768)
        self.assertTrue(all(v == 0.0 for v in result))


class TestIngestUsesEmbedDocuments(unittest.TestCase):
    """ingest_atomic() must use provider.embed_documents() for batch embedding."""

    def test_ingest_uses_embed_documents(self):
        """embed_documents() is called (not embed_query) during ingestion."""
        mock_provider = _make_provider()

        # Build a lightweight mock for get_db_connection that returns a usable connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        # Simulate one new item found during scan
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []  # no existing hashes
        mock_cursor.lastrowid = 1

        import sci_fi_dashboard.ingest as ingest_mod

        original_walk = __import__("os").walk

        def _fake_walk(path):
            # Yield a single .txt file
            yield (path, [], ["test_memory.txt"])

        fake_file_content = "This is a test memory chunk."

        import builtins

        real_open = builtins.open

        def _fake_open(path, *args, **kwargs):
            if path.endswith("test_memory.txt"):
                import io

                return io.StringIO(fake_file_content)
            return real_open(path, *args, **kwargs)

        with (
            patch("sci_fi_dashboard.ingest.get_provider", return_value=mock_provider),
            patch("sci_fi_dashboard.ingest.get_db_connection", return_value=mock_conn),
            patch("os.path.exists", return_value=True),
            patch("os.walk", side_effect=_fake_walk),
            patch("builtins.open", side_effect=_fake_open),
        ):
            ingest_mod.ingest_atomic()

        # embed_documents must have been called; embed_query must NOT have been called
        mock_provider.embed_documents.assert_called_once()
        mock_provider.embed_query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
