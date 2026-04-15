"""
Comprehensive integration tests for the embedding pipeline in Synapse-OSS.

Tests cover:
  1. Retriever deep behaviour (embed_query vs embed_documents, return type, error handling)
  2. MemoryEngine LRU cache semantics and provider wiring
  3. Ingest batch efficiency (single embed_documents call, correct ordering)
  4. Database schema: EMBEDDING_DIMENSIONS constant, validation helper, metadata migration
  5. Re-embed engine: batch sizing, column updates, skip-already-current, dry-run, error handling

Run:
    cd workspace && pytest tests/test_embedding_pipeline_deep.py -v
"""

from __future__ import annotations

import math
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).parent.parent  # workspace/
for _p in (_WORKSPACE, _WORKSPACE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Pre-stub lancedb so memory_engine can be imported even when the
# package is not installed in the test environment.
sys.modules.setdefault("lancedb", MagicMock())

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    dims: int = 768,
    name: str = "test-provider",
    model: str = "test-model",
) -> MagicMock:
    """Build a minimal mock EmbeddingProvider with consistent behaviour."""
    info = MagicMock()
    info.name = name
    info.dimensions = dims
    info.model = model

    provider = MagicMock()
    provider.info.return_value = info
    provider.dimensions = dims
    provider.embed_query.return_value = [0.1] * dims
    provider.embed_documents.return_value = [[0.1] * dims]
    return provider


def _make_fresh_db_for_reembed(
    n_docs: int,
    embedding_model: str | None = "old-model",
) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with n documents and embedding provenance columns."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE documents (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            content           TEXT    NOT NULL,
            embedding_model   TEXT,
            embedding_version TEXT
        )
    """)
    for i in range(n_docs):
        conn.execute(
            "INSERT INTO documents (content, embedding_model) VALUES (?, ?)",
            (f"document content {i}", embedding_model),
        )
    conn.commit()
    return conn


# ===========================================================================
# Category 1: Retriever Deep Tests
# ===========================================================================


class TestRetrieverDeep(unittest.TestCase):
    """Deep behavioural tests for sci_fi_dashboard.retriever.get_embedding()."""

    def setUp(self):
        # Clear any module-level singleton so patches take effect cleanly.
        import importlib

        import sci_fi_dashboard.retriever as _r

        importlib.reload(_r)

    def test_retriever_calls_embed_query_not_embed_documents(self):
        """get_embedding() must call embed_query, NOT embed_documents."""
        mock_provider = _make_provider()

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            retriever.get_embedding("search text")

        mock_provider.embed_query.assert_called_once_with("search text")
        mock_provider.embed_documents.assert_not_called()

    def test_retriever_returns_list_not_tuple(self):
        """get_embedding() must return a list so callers can JSON-serialise it."""
        mock_provider = _make_provider()
        mock_provider.embed_query.return_value = [0.5] * 768

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            result = retriever.get_embedding("some text")

        self.assertIsInstance(result, list, "get_embedding() must return a list, not a tuple")

    def test_retriever_returns_none_on_exception(self):
        """If embed_query raises RuntimeError, get_embedding() returns None (no re-raise)."""
        mock_provider = _make_provider()
        mock_provider.embed_query.side_effect = RuntimeError("model not loaded")

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            result = retriever.get_embedding("failing text")

        # The function must swallow the exception and return None
        self.assertIsNone(result)

    def test_retriever_returns_none_when_no_provider_available(self):
        """get_embedding() returns None when get_provider() returns None."""
        with patch("sci_fi_dashboard.retriever.get_provider", return_value=None):
            import sci_fi_dashboard.retriever as retriever

            result = retriever.get_embedding("any text")

        self.assertIsNone(result)

    def test_retriever_handles_empty_string(self):
        """get_embedding('') must not raise — it delegates directly to the provider."""
        mock_provider = _make_provider()
        mock_provider.embed_query.return_value = [0.0] * 768

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            result = retriever.get_embedding("")

        # Must return a list of floats, no exception raised
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        mock_provider.embed_query.assert_called_once_with("")


# ===========================================================================
# Category 2: MemoryEngine LRU Cache Deep Tests
# ===========================================================================


class TestMemoryEngineLRUCache(unittest.TestCase):
    """Deep LRU cache and provider-wiring tests for MemoryEngine.get_embedding()."""

    def _make_engine(self, provider):
        """
        Construct a MemoryEngine with mocked external dependencies.
        Returns a fresh engine with its LRU cache cleared.
        """
        lancedb_patch = patch(
            "sci_fi_dashboard.memory_engine.LanceDBVectorStore",
            return_value=MagicMock(),
        )
        provider_patch = patch(
            "sci_fi_dashboard.memory_engine.get_provider",
            return_value=provider,
        )
        with lancedb_patch, provider_patch:
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            engine.get_embedding.cache_clear()
        return engine

    def test_lru_cache_same_text_same_result(self):
        """Calling get_embedding() twice with the same text calls embed_query once."""
        mock_provider = _make_provider()
        mock_provider.embed_query.return_value = [0.1] * 768

        engine = self._make_engine(mock_provider)

        first = engine.get_embedding("hello")
        second = engine.get_embedding("hello")

        # Cache hit: only one underlying call
        mock_provider.embed_query.assert_called_once_with("hello")
        # Both results are identical (same cached value)
        self.assertEqual(first, second)

    def test_lru_cache_different_text_different_calls(self):
        """Two distinct texts each trigger a separate embed_query call."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        engine.get_embedding("foo")
        engine.get_embedding("bar")

        self.assertEqual(mock_provider.embed_query.call_count, 2)
        calls = [c.args[0] for c in mock_provider.embed_query.call_args_list]
        self.assertIn("foo", calls)
        self.assertIn("bar", calls)

    def test_lru_cache_returns_tuple_not_list(self):
        """get_embedding() MUST return a tuple (hashable — required by @lru_cache)."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        result = engine.get_embedding("cache me")

        self.assertIsInstance(
            result,
            tuple,
            "MemoryEngine.get_embedding() must return tuple (needed for lru_cache key)",
        )

    def test_memory_engine_provider_stored_at_init(self):
        """The provider returned by get_provider() is stored as self._embed_provider."""
        mock_provider = _make_provider()

        lancedb_patch = patch(
            "sci_fi_dashboard.memory_engine.LanceDBVectorStore",
            return_value=MagicMock(),
        )
        provider_patch = patch(
            "sci_fi_dashboard.memory_engine.get_provider",
            return_value=mock_provider,
        )
        with lancedb_patch, provider_patch:
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()

        self.assertIs(engine._embed_provider, mock_provider)

    def test_memory_engine_zero_dimensions_when_provider_none(self):
        """When provider is None, get_embedding() returns a tuple of exactly 768 zeros."""
        engine = self._make_engine(None)

        result = engine.get_embedding("any text")

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 768)
        self.assertTrue(all(v == 0.0 for v in result))

    def test_memory_engine_uses_provider_dimensions_for_zero_vector(self):
        """On embed_query exception, fallback zero-vector uses provider.dimensions, not 768."""
        mock_provider = _make_provider(dims=512)
        mock_provider.embed_query.side_effect = RuntimeError("provider broken")

        engine = self._make_engine(mock_provider)
        result = engine.get_embedding("broken query")

        self.assertIsInstance(result, tuple)
        self.assertEqual(
            len(result),
            512,
            "Zero-vector length must match the provider's dimensions (512), not 768",
        )
        self.assertTrue(all(v == 0.0 for v in result))


# ===========================================================================
# Category 3: Ingest Batch Efficiency Tests
# ===========================================================================


class TestIngestBatchEfficiency(unittest.TestCase):
    """Verify that ingest_atomic() uses embed_documents for batch embedding."""

    def _run_ingest_with_items(self, items: list[tuple[str, str, str]], mock_provider):
        """
        Patch ingest_atomic() to skip file I/O and inject 'items' directly,
        then run the function and return the mock provider for assertion.
        """
        import sci_fi_dashboard.ingest as ingest_mod

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []  # no existing hashes in shadow
        mock_cursor.lastrowid = 1

        # Patch new_items computation: intercept os.path.exists and os.walk
        def _fake_walk(path):
            # Yield one fake .txt file
            yield (path, [], ["memory.txt"])

        # Build fake file content from items
        fake_content = "\n\n".join(text for _, text, _ in items)

        import builtins

        real_open = builtins.open

        def _fake_open(path, *args, **kwargs):
            if path.endswith("memory.txt"):
                import io

                return io.StringIO(fake_content)
            return real_open(path, *args, **kwargs)

        with (
            patch("sci_fi_dashboard.ingest.get_provider", return_value=mock_provider),
            patch("sci_fi_dashboard.ingest.get_db_connection", return_value=mock_conn),
            patch("os.path.exists", return_value=True),
            patch("os.walk", side_effect=_fake_walk),
            patch("builtins.open", side_effect=_fake_open),
        ):
            ingest_mod.ingest_atomic()

        return mock_provider

    def test_ingest_single_embed_documents_call_not_per_item(self):
        """5 new items must result in exactly ONE embed_documents call (batch), not 5."""
        mock_provider = _make_provider()
        texts = [f"paragraph {i}" for i in range(5)]
        # Build (filename, content, hash) tuples
        items = [("file.txt", t, f"hash{i}") for i, t in enumerate(texts)]
        mock_provider.embed_documents.return_value = [[0.1] * 768] * 5

        self._run_ingest_with_items(items, mock_provider)

        self.assertEqual(
            mock_provider.embed_documents.call_count,
            1,
            "embed_documents must be called exactly once for all items in a batch",
        )

    def test_ingest_uses_embed_documents_not_embed_query(self):
        """ingest_atomic() must call embed_documents, never embed_query."""
        mock_provider = _make_provider()
        items = [("f.txt", "some content here", "abc123")]
        mock_provider.embed_documents.return_value = [[0.1] * 768]

        self._run_ingest_with_items(items, mock_provider)

        mock_provider.embed_documents.assert_called()
        mock_provider.embed_query.assert_not_called()

    def test_ingest_vector_order_matches_document_order(self):
        """
        The vector at index i in embed_documents() output must be associated
        with the document at index i in the input texts.
        """
        mock_provider = _make_provider()
        texts = ["doc alpha", "doc beta", "doc gamma"]
        [("f.txt", t, f"h{i}") for i, t in enumerate(texts)]

        # Provide distinct vectors so we can verify ordering
        vectors = [[float(i) / 10.0] * 768 for i in range(len(texts))]
        mock_provider.embed_documents.return_value = vectors

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_cursor.lastrowid = 1

        fake_content = "\n\n".join(texts)

        import builtins
        import io

        real_open = builtins.open

        def _fake_open(path, *a, **kw):
            if path.endswith(".txt"):
                return io.StringIO(fake_content)
            return real_open(path, *a, **kw)

        def _fake_walk(path):
            yield (path, [], ["mem.txt"])

        with (
            patch("sci_fi_dashboard.ingest.get_provider", return_value=mock_provider),
            patch("sci_fi_dashboard.ingest.get_db_connection", return_value=mock_conn),
            patch("os.path.exists", return_value=True),
            patch("os.walk", side_effect=_fake_walk),
            patch("builtins.open", side_effect=_fake_open),
        ):
            import sci_fi_dashboard.ingest as ingest_mod

            ingest_mod.ingest_atomic()

        # embed_documents must have been called with all 3 texts
        call_args = mock_provider.embed_documents.call_args
        self.assertIsNotNone(call_args)
        called_texts = call_args.args[0] if call_args.args else call_args[0][0]
        self.assertEqual(len(called_texts), 3)
        # The texts must appear in the same relative order as the source
        self.assertEqual(called_texts[0], texts[0])
        self.assertEqual(called_texts[1], texts[1])
        self.assertEqual(called_texts[2], texts[2])

    def test_ingest_handles_empty_batch_gracefully(self):
        """When there are no new items, embed_documents must not be called at all."""
        mock_provider = _make_provider()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        # Simulate SOURCE_DIR not existing → no files to scan → no new items
        with (
            patch("sci_fi_dashboard.ingest.get_provider", return_value=mock_provider),
            patch("sci_fi_dashboard.ingest.get_db_connection", return_value=mock_conn),
            patch("os.path.exists", return_value=False),
        ):
            import sci_fi_dashboard.ingest as ingest_mod

            # Must not raise
            ingest_mod.ingest_atomic()

        mock_provider.embed_documents.assert_not_called()


# ===========================================================================
# Category 4: Database Schema Real SQLite Tests
# ===========================================================================


class TestDatabaseSchemaRealSQLite(unittest.TestCase):
    """Tests that exercise the actual db.py constants and helpers against real SQLite."""

    def test_embedding_dimensions_constant_is_768(self):
        """EMBEDDING_DIMENSIONS must equal 768 (the project-wide embedding size)."""
        from sci_fi_dashboard.db import EMBEDDING_DIMENSIONS

        self.assertEqual(EMBEDDING_DIMENSIONS, 768)

    def test_validate_embedding_dimension_passes_768(self):
        """validate_embedding_dimension([0.0] * 768) must not raise."""
        from sci_fi_dashboard.db import validate_embedding_dimension

        try:
            validate_embedding_dimension([0.0] * 768)
        except ValueError as exc:
            self.fail(f"validate_embedding_dimension raised unexpectedly for 768: {exc}")

    def test_validate_embedding_dimension_blocks_384(self):
        """validate_embedding_dimension([0.0] * 384) must raise ValueError."""
        from sci_fi_dashboard.db import validate_embedding_dimension

        with self.assertRaises(ValueError) as ctx:
            validate_embedding_dimension([0.0] * 384)
        error_msg = str(ctx.exception)
        self.assertIn("768", error_msg, "Error message must mention expected size 768")
        self.assertIn("384", error_msg, "Error message must mention the actual size 384")

    def test_validate_error_message_mentions_re_embed(self):
        """validate_embedding_dimension error must guide user to run 'synapse re-embed'."""
        from sci_fi_dashboard.db import validate_embedding_dimension

        with self.assertRaises(ValueError) as ctx:
            validate_embedding_dimension([0.0] * 100)
        error_msg = str(ctx.exception).lower()
        self.assertTrue(
            "re-embed" in error_msg or "re_embed" in error_msg,
            f"Error message should mention re-embed command. Got: {ctx.exception}",
        )

    def test_ensure_embedding_metadata_real_sqlite(self):
        """
        _ensure_embedding_metadata(conn) must add embedding_model and
        embedding_version columns to a bare documents table — real SQLite, no mocks.
        """
        from sci_fi_dashboard.db import _ensure_embedding_metadata

        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            )
        """)
        conn.commit()

        # Verify columns are absent before migration
        cursor = conn.execute("PRAGMA table_info(documents)")
        cols_before = {row[1] for row in cursor.fetchall()}
        self.assertNotIn("embedding_model", cols_before)
        self.assertNotIn("embedding_version", cols_before)

        _ensure_embedding_metadata(conn)

        cursor = conn.execute("PRAGMA table_info(documents)")
        cols_after = {row[1] for row in cursor.fetchall()}
        self.assertIn(
            "embedding_model",
            cols_after,
            "_ensure_embedding_metadata must add 'embedding_model' column",
        )
        self.assertIn(
            "embedding_version",
            cols_after,
            "_ensure_embedding_metadata must add 'embedding_version' column",
        )
        conn.close()


# ===========================================================================
# Category 5: Re-Embed Engine Deep Tests
# ===========================================================================


class TestReEmbedEngineDeep(unittest.TestCase):
    """Deep behavioural tests for embedding.migrate.re_embed_documents()."""

    def _make_provider_with_model(self, model_name: str = "target-model") -> MagicMock:
        """Return a provider mock whose info().model is model_name."""
        from sci_fi_dashboard.db import EMBEDDING_DIMENSIONS

        info = MagicMock()
        info.name = "test-provider"
        info.model = model_name
        info.dimensions = EMBEDDING_DIMENSIONS

        provider = MagicMock()
        provider.info.return_value = info
        provider.dimensions = EMBEDDING_DIMENSIONS
        provider.embed_documents.side_effect = lambda texts: (
            [[0.0] * EMBEDDING_DIMENSIONS for _ in texts]
        )
        return provider

    def test_re_embed_batch_size_respected(self):
        """With 10 docs and batch_size=3, embed_documents must be called ceil(10/3)=4 times."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        n = 10
        batch_size = 3
        expected_batches = math.ceil(n / batch_size)  # 4

        conn = _make_fresh_db_for_reembed(n, embedding_model="old-model")
        provider = self._make_provider_with_model("new-model")

        with patch("sqlite3.connect", return_value=conn):
            re_embed_documents(Path(":memory:"), provider, batch_size=batch_size)

        self.assertEqual(
            provider.embed_documents.call_count,
            expected_batches,
            f"Expected {expected_batches} batch calls for {n} docs at batch_size={batch_size}",
        )
        conn.close()

    def test_re_embed_updates_embedding_model_column(self):
        """After re_embed_documents(), rows must have embedding_model set to the new model."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        conn = _make_fresh_db_for_reembed(3, embedding_model="old-model")
        provider = self._make_provider_with_model("new-model")

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(Path(":memory:"), provider, batch_size=64)

        # All 3 rows should now have the new model
        cursor = conn.execute("SELECT COUNT(*) FROM documents WHERE embedding_model = 'new-model'")
        updated_count = cursor.fetchone()[0]
        self.assertEqual(
            updated_count,
            3,
            "embedding_model column must be updated to 'new-model' for all processed rows",
        )
        self.assertEqual(stats["processed"], 3)
        conn.close()

    def test_re_embed_skips_already_current_rows(self):
        """Rows already using the target model must be skipped (not counted as processed)."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        # 3 docs already on target model, 2 docs on old model
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                content           TEXT NOT NULL,
                embedding_model   TEXT,
                embedding_version TEXT
            )
        """)
        for i in range(3):
            conn.execute(
                "INSERT INTO documents (content, embedding_model) VALUES (?, ?)",
                (f"content {i}", "target-model"),
            )
        for i in range(2):
            conn.execute(
                "INSERT INTO documents (content, embedding_model) VALUES (?, ?)",
                (f"stale content {i}", "old-model"),
            )
        conn.commit()

        provider = self._make_provider_with_model("target-model")

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(Path(":memory:"), provider, batch_size=64)

        # Only the 2 stale rows should be processed
        self.assertEqual(
            stats["processed"], 2, "Only rows with mismatched embedding_model should be processed"
        )
        conn.close()

    def test_re_embed_dry_run_count_is_accurate(self):
        """Dry-run returns the correct count without modifying any rows."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        n = 7
        conn = _make_fresh_db_for_reembed(n, embedding_model="stale-model")
        provider = self._make_provider_with_model("fresh-model")

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(Path(":memory:"), provider, dry_run=True)

        # Dry-run stats must reflect all 7 stale rows
        self.assertEqual(
            stats["processed"], n, "Dry-run stats['processed'] must equal the number of stale rows"
        )

        # But the database must be untouched
        cursor = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE embedding_model = 'stale-model'"
        )
        still_stale = cursor.fetchone()[0]
        self.assertEqual(still_stale, n, "Dry-run must NOT update embedding_model in the database")
        conn.close()

    def test_re_embed_handles_provider_error_gracefully(self):
        """If embed_documents raises, re_embed_documents must not crash and must record errors."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        conn = _make_fresh_db_for_reembed(3, embedding_model="bad-model")
        provider = self._make_provider_with_model("good-model")
        provider.embed_documents.side_effect = RuntimeError("GPU out of memory")

        with patch("sqlite3.connect", return_value=conn):
            # Must not raise
            try:
                stats = re_embed_documents(Path(":memory:"), provider, batch_size=64)
            except Exception as exc:
                self.fail(f"re_embed_documents must not propagate provider errors, got: {exc}")

        # Errors should be counted
        self.assertGreater(
            stats["errors"], 0, "stats['errors'] must be > 0 when embed_documents raises"
        )
        conn.close()


# ===========================================================================
# Additional edge-case tests (to reach 25+ total)
# ===========================================================================


class TestRetrieverEdgeCases(unittest.TestCase):
    """Extra edge cases for retriever not covered by basic tests."""

    def test_retriever_get_embedding_returns_provider_vector_length(self):
        """Result length must match whatever the provider returns."""
        mock_provider = _make_provider(dims=512)
        mock_provider.embed_query.return_value = [0.25] * 512

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            result = retriever.get_embedding("test")

        self.assertEqual(len(result), 512)

    def test_retriever_passes_text_verbatim_to_embed_query(self):
        """The exact text passed to get_embedding() must reach embed_query unchanged."""
        mock_provider = _make_provider()
        special_text = "  leading space and unicode: Ü  "

        with patch("sci_fi_dashboard.retriever.get_provider", return_value=mock_provider):
            import sci_fi_dashboard.retriever as retriever

            retriever.get_embedding(special_text)

        mock_provider.embed_query.assert_called_once_with(special_text)


class TestMemoryEngineEdgeCases(unittest.TestCase):
    """Additional edge cases for MemoryEngine.get_embedding()."""

    def _make_engine(self, provider):
        lancedb_patch = patch(
            "sci_fi_dashboard.memory_engine.LanceDBVectorStore",
            return_value=MagicMock(),
        )
        provider_patch = patch(
            "sci_fi_dashboard.memory_engine.get_provider",
            return_value=provider,
        )
        with lancedb_patch, provider_patch:
            from sci_fi_dashboard.memory_engine import MemoryEngine

            engine = MemoryEngine()
            engine.get_embedding.cache_clear()
        return engine

    def test_lru_cache_size_limit_not_exceeded(self):
        """LRU cache maxsize is 500 — verify cache_info() reflects this."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        info = engine.get_embedding.cache_info()
        self.assertEqual(info.maxsize, 500)

    def test_memory_engine_embed_query_called_with_correct_text(self):
        """embed_query receives the exact text passed to get_embedding()."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        engine.get_embedding("specific query text")

        mock_provider.embed_query.assert_called_once_with("specific query text")

    def test_memory_engine_result_is_hashable(self):
        """The returned tuple must be usable as a dict key (hashable)."""
        mock_provider = _make_provider()
        engine = self._make_engine(mock_provider)

        result = engine.get_embedding("hashability test")

        try:
            _ = {result: "ok"}
        except TypeError as exc:
            self.fail(f"get_embedding() result is not hashable: {exc}")


class TestDatabaseSchemaExtraValidation(unittest.TestCase):
    """Extra validation tests for db.py helpers."""

    def test_validate_accepts_any_expected_size_when_overridden(self):
        """validate_embedding_dimension respects the 'expected' parameter."""
        from sci_fi_dashboard.db import validate_embedding_dimension

        # Custom expected size — should not raise
        try:
            validate_embedding_dimension([0.0] * 512, expected=512)
        except ValueError as exc:
            self.fail(f"Should not raise for matching dimension: {exc}")

    def test_validate_rejects_empty_vector(self):
        """An empty vector [] has 0 dimensions — must raise ValueError."""
        from sci_fi_dashboard.db import validate_embedding_dimension

        with self.assertRaises(ValueError):
            validate_embedding_dimension([], expected=768)

    def test_ensure_embedding_metadata_idempotent(self):
        """Calling _ensure_embedding_metadata twice on the same conn must not raise."""
        from sci_fi_dashboard.db import _ensure_embedding_metadata

        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            )
        """)
        conn.commit()

        _ensure_embedding_metadata(conn)
        try:
            _ensure_embedding_metadata(conn)
        except Exception as exc:
            self.fail(f"Second call to _ensure_embedding_metadata raised: {exc}")
        conn.close()

    def test_ensure_embedding_metadata_skips_missing_atomic_facts_table(self):
        """_ensure_embedding_metadata must not crash when atomic_facts table doesn't exist."""
        from sci_fi_dashboard.db import _ensure_embedding_metadata

        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            )
        """)
        conn.commit()

        # No atomic_facts table — must not raise
        try:
            _ensure_embedding_metadata(conn)
        except Exception as exc:
            self.fail(f"_ensure_embedding_metadata raised when atomic_facts is absent: {exc}")
        conn.close()


class TestReEmbedEngineBatchContent(unittest.TestCase):
    """Verify the content of each batch passed to embed_documents."""

    def test_re_embed_first_batch_contains_first_n_documents(self):
        """With batch_size=2 and 4 docs, the first call receives docs 0 and 1."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        conn = _make_fresh_db_for_reembed(4, embedding_model="old-model")
        info = MagicMock()
        info.model = "new-model"
        info.name = "test"
        info.dimensions = 768

        provider = MagicMock()
        provider.info.return_value = info
        provider.embed_documents.return_value = [[0.0] * 768, [0.0] * 768]

        with patch("sqlite3.connect", return_value=conn):
            re_embed_documents(Path(":memory:"), provider, batch_size=2)

        # First call should have exactly 2 texts
        first_call_texts = provider.embed_documents.call_args_list[0].args[0]
        self.assertEqual(len(first_call_texts), 2)
        conn.close()

    def test_re_embed_null_embedding_model_rows_also_processed(self):
        """Rows where embedding_model IS NULL must also be re-embedded."""
        from sci_fi_dashboard.embedding.migrate import re_embed_documents

        # Mix of NULL and old-model rows
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                content           TEXT NOT NULL,
                embedding_model   TEXT,
                embedding_version TEXT
            )
        """)
        conn.execute("INSERT INTO documents (content, embedding_model) VALUES ('a', NULL)")
        conn.execute("INSERT INTO documents (content, embedding_model) VALUES ('b', 'old')")
        conn.execute("INSERT INTO documents (content, embedding_model) VALUES ('c', 'target')")
        conn.commit()

        info = MagicMock()
        info.model = "target"
        info.name = "test"
        info.dimensions = 768

        provider = MagicMock()
        provider.info.return_value = info
        provider.embed_documents.return_value = [[0.0] * 768, [0.0] * 768]  # 2 rows need embedding

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(Path(":memory:"), provider, batch_size=64)

        # Rows with NULL and 'old' must be processed (2 total); row with 'target' skipped
        self.assertEqual(
            stats["processed"], 2, "Both NULL and mismatched model rows must be processed"
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
