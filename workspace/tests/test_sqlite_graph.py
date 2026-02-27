"""
Test Suite: SQLite Knowledge Graph (Unit Tests)
===============================================
Tests the SQLiteGraph class which provides a knowledge graph
backed by SQLite instead of NetworkX.
"""

import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sqlite_graph import SQLiteGraph


class TestSQLiteGraph:
    """Test cases for SQLite-backed knowledge graph."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def graph(self, temp_dir):
        """Create a graph instance with temp database."""
        db_path = os.path.join(temp_dir, "test.db")
        return SQLiteGraph(db_path=db_path)

    def test_schema_initialized(self, graph):
        """Database schema should be created on init."""
        conn = graph._conn()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "nodes" in tables
        assert "edges" in tables

    def test_add_node(self, graph):
        """Should be able to add a node."""
        graph.add_node("John", "person", age=30)

        conn = graph._conn()
        cursor = conn.execute("SELECT name, type FROM nodes WHERE name = ?", ("John",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "John"
        assert row[1] == "person"

    def test_add_node_with_type(self, graph):
        """Should be able to specify node type."""
        graph.add_node("ProjectX", "project", status="active")

        conn = graph._conn()
        cursor = conn.execute("SELECT name, type FROM nodes WHERE name = ?", ("ProjectX",))
        row = cursor.fetchone()
        conn.close()

        assert row[1] == "project"

    def test_add_edge(self, graph):
        """Should be able to add an edge between nodes."""
        graph.add_node("Alice", "person")
        graph.add_node("Bob", "person")
        graph.add_edge("Alice", "Bob", "friend", weight=0.8)

        conn = graph._conn()
        cursor = conn.execute(
            "SELECT source, target, relation, weight FROM edges WHERE source = ? AND target = ?",
            ("Alice", "Bob"),
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[2] == "friend"
        assert row[3] == 0.8

    def test_add_edge_creates_missing_nodes(self, graph):
        """Adding edge should auto-create missing nodes."""
        graph.add_edge("Charlie", "Dave", "colleague", weight=0.5)

        conn = graph._conn()
        cursor = conn.execute("SELECT name FROM nodes WHERE name IN (?, ?)", ("Charlie", "Dave"))
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2

    def test_get_entity_neighborhood(self, graph):
        """Should retrieve neighborhood around an entity."""
        graph.add_edge("Alice", "Bob", "friend")
        graph.add_edge("Bob", "Charlie", "friend")
        graph.add_edge("Alice", "Dave", "colleague")

        result = graph.get_entity_neighborhood("Alice", hops=1)

        assert "Alice" in result
        assert "Bob" in result
        assert "Dave" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
