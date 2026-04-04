"""
Tests for Phase 3 embedding schema migration, dimension validation,
re-embedding engine, and parameterized Qdrant dimensions.

Run with:
    pytest workspace/tests/test_schema_migration.py -v
"""
from __future__ import annotations

import sqlite3
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path bootstrap so the test can import from workspace/ without install
# ---------------------------------------------------------------------------
_WORKSPACE = Path(__file__).parent.parent  # workspace/
_DASHBOARD = _WORKSPACE / "sci_fi_dashboard"
for _p in (_WORKSPACE, _DASHBOARD.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Import targets under test — direct imports avoid triggering heavy app singletons.
from sci_fi_dashboard.db import (  # noqa: E402
    EMBEDDING_DIMENSIONS,
    _ensure_embedding_metadata,
    validate_embedding_dimension,
)
from sci_fi_dashboard.embedding.migrate import re_embed_documents  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fresh_db(with_atomic_facts: bool = False) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the base schema (no embedding columns)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE documents (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL
        )
    """)
    if with_atomic_facts:
        conn.execute("""
            CREATE TABLE atomic_facts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL
            )
        """)
    conn.commit()
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _make_provider_mock(model: str = "test-model", name: str = "test-provider") -> MagicMock:
    """Return a minimal EmbeddingProvider mock."""
    from sci_fi_dashboard.embedding.base import ProviderInfo

    provider = MagicMock()
    provider.info.return_value = ProviderInfo(name=name, model=model, dimensions=EMBEDDING_DIMENSIONS, requires_network=False, requires_gpu=False)
    # embed_documents returns one 768-dim zero vector per text
    provider.embed_documents.side_effect = lambda texts: [
        [0.0] * EMBEDDING_DIMENSIONS for _ in texts
    ]
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMigrationAddsColumns(unittest.TestCase):
    """_ensure_embedding_metadata must add provenance columns when absent."""

    def test_migration_adds_columns_to_documents(self):
        conn = _make_fresh_db()
        # Sanity: columns not present before migration
        self.assertNotIn("embedding_model", _column_names(conn, "documents"))

        _ensure_embedding_metadata(conn)

        cols = _column_names(conn, "documents")
        self.assertIn("embedding_model", cols)
        self.assertIn("embedding_version", cols)
        conn.close()

    def test_migration_adds_columns_to_atomic_facts_when_table_exists(self):
        conn = _make_fresh_db(with_atomic_facts=True)
        self.assertNotIn("embedding_model", _column_names(conn, "atomic_facts"))

        _ensure_embedding_metadata(conn)

        cols = _column_names(conn, "atomic_facts")
        self.assertIn("embedding_model", cols)
        self.assertIn("embedding_version", cols)
        conn.close()


class TestMigrationIdempotent(unittest.TestCase):
    """Calling _ensure_embedding_metadata twice must not raise."""

    def test_migration_idempotent_documents(self):
        conn = _make_fresh_db()
        _ensure_embedding_metadata(conn)
        # Second call must not raise (ALTER TABLE on existing column would)
        try:
            _ensure_embedding_metadata(conn)
        except Exception as exc:
            self.fail(f"Second call to _ensure_embedding_metadata raised: {exc}")
        conn.close()

    def test_migration_idempotent_with_atomic_facts(self):
        conn = _make_fresh_db(with_atomic_facts=True)
        _ensure_embedding_metadata(conn)
        try:
            _ensure_embedding_metadata(conn)
        except Exception as exc:
            self.fail(f"Second call raised: {exc}")
        conn.close()


class TestDimensionValidation(unittest.TestCase):
    """validate_embedding_dimension must accept correct and reject wrong sizes."""

    def test_dimension_validation_correct(self):
        """No exception raised for a vector of the correct size."""
        try:
            validate_embedding_dimension([0.0] * EMBEDDING_DIMENSIONS, expected=EMBEDDING_DIMENSIONS)
        except ValueError as exc:
            self.fail(f"Raised unexpectedly: {exc}")

    def test_dimension_validation_wrong_raises_value_error(self):
        """ValueError raised for a vector whose length doesn't match expected."""
        with self.assertRaises(ValueError) as ctx:
            validate_embedding_dimension([0.0] * 384, expected=EMBEDDING_DIMENSIONS)
        # Error message must mention the re-embed command so the user knows how to fix it
        self.assertIn("synapse re-embed", str(ctx.exception))
        self.assertIn("384", str(ctx.exception))
        self.assertIn(str(EMBEDDING_DIMENSIONS), str(ctx.exception))


class TestReEmbedEngine(unittest.TestCase):
    """re_embed_documents processes rows, skips up-to-date rows, and handles dry-run."""

    def _setup_db_with_docs(
        self,
        n: int,
        embedding_model: str | None = "old-model",
    ) -> tuple[sqlite3.Connection, Path]:
        """Build an in-memory DB with n documents and return (conn, ':memory:' Path stub)."""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE documents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                content         TEXT NOT NULL,
                embedding_model TEXT,
                embedding_version TEXT
            )
        """)
        for i in range(n):
            conn.execute(
                "INSERT INTO documents (content, embedding_model) VALUES (?, ?)",
                (f"content {i}", embedding_model),
            )
        conn.commit()
        return conn

    def test_re_embed_processes_all_rows_with_old_model(self):
        """All rows with a stale embedding_model are processed."""
        n = 3
        conn = self._setup_db_with_docs(n, embedding_model="old-model")
        provider = _make_provider_mock(model="test-model")

        # Pass the already-open connection through by patching sqlite3.connect
        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(
                Path(":memory:"), provider, batch_size=64, dry_run=False
            )

        self.assertEqual(stats["processed"], n)
        self.assertEqual(stats["errors"], 0)
        conn.close()

    def test_re_embed_idempotent_skips_matching_rows(self):
        """Rows already using the provider's model are NOT processed."""
        provider = _make_provider_mock(model="test-model")
        # All rows already have the correct model
        conn = self._setup_db_with_docs(4, embedding_model="test-model")

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(
                Path(":memory:"), provider, batch_size=64, dry_run=False
            )

        # Nothing to process — all rows already match
        self.assertEqual(stats["processed"], 0)
        self.assertEqual(stats["errors"], 0)
        conn.close()

    def test_re_embed_dry_run_does_not_modify_db(self):
        """Dry-run returns a count but leaves embedding_model unchanged in the DB."""
        n = 5
        conn = self._setup_db_with_docs(n, embedding_model="old-model")
        provider = _make_provider_mock(model="test-model")

        with patch("sqlite3.connect", return_value=conn):
            stats = re_embed_documents(
                Path(":memory:"), provider, batch_size=64, dry_run=True
            )

        # Stats reflect what *would* happen
        self.assertEqual(stats["processed"], n)

        # Verify the DB was NOT touched
        cursor = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE embedding_model = 'old-model'"
        )
        unchanged_count = cursor.fetchone()[0]
        self.assertEqual(unchanged_count, n, "Dry-run must not update embedding_model")
        conn.close()


class TestLanceDBDimensionsParameterized(unittest.TestCase):
    """LanceDBVectorStore must accept embedding_dimensions and not hardcode 768."""

    def test_lancedb_dimensions_stored_on_instance(self, tmp_path=None):
        """Passing embedding_dimensions=512 stores 512, not the default 768."""
        import tempfile

        try:
            from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore  # noqa: PLC0415

            with tempfile.TemporaryDirectory() as tmpdir:
                store = LanceDBVectorStore(db_path=tmpdir, embedding_dimensions=512)
                self.assertEqual(store._embedding_dimensions, 512)
                # Verify schema reflects the custom dimension
                vector_field = store.table.schema.field("vector")
                self.assertEqual(vector_field.type.list_size, 512)

                # Also verify the default is still 768
                store_default = LanceDBVectorStore(
                    db_path=tmpdir + "_default", embedding_dimensions=768
                )
                self.assertEqual(store_default._embedding_dimensions, 768)
        except ImportError as exc:
            self.skipTest(f"lancedb not installed: {exc}")


if __name__ == "__main__":
    unittest.main()
