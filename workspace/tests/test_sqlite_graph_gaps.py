"""
test_sqlite_graph_gaps.py — Gap-fill tests for sqlite_graph.py

Covers areas NOT in test_sqlite_graph.py:
  - Node update on conflict (upsert)
  - Edge evidence accumulation
  - find_connection_path (BFS)
  - get_all_node_names
  - number_of_nodes / number_of_edges
  - has_node
  - neighbors
  - add_relation (alias)
  - prune_weak_edges
  - prune_graph
  - save_graph (no-op)
  - graph property (self-reference)
  - Empty graph edge cases
"""

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sqlite_graph import SQLiteGraph


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def graph(temp_dir):
    return SQLiteGraph(db_path=os.path.join(temp_dir, "test.db"))


# ---------------------------------------------------------------------------
# Node operations
# ---------------------------------------------------------------------------


class TestNodeOperations:
    def test_upsert_node_updates_properties(self, graph):
        graph.add_node("Alice", "person", age=25)
        graph.add_node("Alice", "person", age=30)

        conn = graph._conn()
        row = conn.execute("SELECT properties FROM nodes WHERE name = ?", ("Alice",)).fetchone()
        conn.close()

        import json

        props = json.loads(row[0])
        assert props["age"] == 30

    def test_has_node_true(self, graph):
        graph.add_node("Bob")
        assert graph.has_node("Bob") is True

    def test_has_node_false(self, graph):
        assert graph.has_node("Nonexistent") is False

    def test_get_all_node_names_empty(self, graph):
        assert graph.get_all_node_names() == []

    def test_get_all_node_names(self, graph):
        graph.add_node("A")
        graph.add_node("B")
        graph.add_node("C")
        names = graph.get_all_node_names()
        assert set(names) == {"A", "B", "C"}

    def test_number_of_nodes_empty(self, graph):
        assert graph.number_of_nodes() == 0

    def test_number_of_nodes(self, graph):
        graph.add_node("X")
        graph.add_node("Y")
        assert graph.number_of_nodes() == 2


# ---------------------------------------------------------------------------
# Edge operations
# ---------------------------------------------------------------------------


class TestEdgeOperations:
    def test_edge_evidence_accumulation(self, graph):
        graph.add_edge("A", "B", "knows", evidence="from chat 1")
        graph.add_edge("A", "B", "knows", evidence="from chat 2")

        conn = graph._conn()
        row = conn.execute(
            "SELECT evidence FROM edges WHERE source = ? AND target = ? AND relation = ?",
            ("A", "B", "knows"),
        ).fetchone()
        conn.close()

        assert "from chat 1" in row[0]
        assert "from chat 2" in row[0]

    def test_number_of_edges_empty(self, graph):
        assert graph.number_of_edges() == 0

    def test_number_of_edges(self, graph):
        graph.add_edge("A", "B", "knows")
        graph.add_edge("B", "C", "likes")
        assert graph.number_of_edges() == 2

    def test_add_relation_alias(self, graph):
        graph.add_relation("A", "friend_of", "B", weight=0.9, evidence="test")
        conn = graph._conn()
        row = conn.execute(
            "SELECT relation, weight FROM edges WHERE source = ? AND target = ?",
            ("A", "B"),
        ).fetchone()
        conn.close()
        assert row[0] == "friend_of"
        assert row[1] == 0.9


# ---------------------------------------------------------------------------
# Neighborhood and path queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_get_entity_neighborhood_empty(self, graph):
        result = graph.get_entity_neighborhood("nobody")
        assert result == ""

    def test_get_entity_neighborhood_as_source(self, graph):
        graph.add_edge("A", "B", "knows")
        graph.add_edge("A", "C", "likes")
        result = graph.get_entity_neighborhood("A")
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_get_entity_neighborhood_as_target(self, graph):
        graph.add_edge("X", "Y", "employs")
        result = graph.get_entity_neighborhood("Y")
        assert "Y" in result
        assert "employs" in result

    def test_neighbors(self, graph):
        graph.add_edge("A", "B", "knows")
        graph.add_edge("A", "C", "likes")
        graph.add_edge("D", "A", "hates")  # A is target here

        neighbors = graph.neighbors("A")
        assert set(neighbors) == {"B", "C"}

    def test_neighbors_empty(self, graph):
        graph.add_node("Lonely")
        assert graph.neighbors("Lonely") == []

    def test_find_connection_path_direct(self, graph):
        graph.add_edge("A", "B", "knows")
        path = graph.find_connection_path("A", "B")
        assert path == ["A", "B"]

    def test_find_connection_path_two_hops(self, graph):
        graph.add_edge("A", "B", "knows")
        graph.add_edge("B", "C", "knows")
        path = graph.find_connection_path("A", "C")
        assert path == ["A", "B", "C"]

    def test_find_connection_path_not_found(self, graph):
        graph.add_edge("A", "B", "knows")
        graph.add_node("C")  # C is isolated
        path = graph.find_connection_path("A", "C")
        assert path == []

    def test_find_connection_path_max_depth(self, graph):
        # Chain: A -> B -> C -> D -> E
        graph.add_edge("A", "B", "r")
        graph.add_edge("B", "C", "r")
        graph.add_edge("C", "D", "r")
        graph.add_edge("D", "E", "r")

        # max_depth=2 should not reach E
        path = graph.find_connection_path("A", "E", max_depth=2)
        assert path == []

        # max_depth=4 should reach E
        path = graph.find_connection_path("A", "E", max_depth=4)
        assert path == ["A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    def test_prune_weak_edges(self, graph):
        graph.add_edge("A", "B", "strong", weight=0.9)
        graph.add_edge("C", "D", "weak", weight=0.05)
        graph.prune_weak_edges(min_weight=0.1)
        assert graph.number_of_edges() == 1

    def test_prune_graph_calls_prune_weak_edges(self, graph):
        graph.add_edge("A", "B", "weak", weight=0.05)
        graph.prune_graph()
        assert graph.number_of_edges() == 0

    def test_prune_no_weak_edges(self, graph):
        graph.add_edge("A", "B", "strong", weight=0.5)
        graph.prune_weak_edges(min_weight=0.1)
        assert graph.number_of_edges() == 1


# ---------------------------------------------------------------------------
# Compatibility layer
# ---------------------------------------------------------------------------


class TestCompatibilityLayer:
    def test_save_graph_noop(self, graph):
        graph.save_graph()  # should not raise

    def test_graph_property_self_reference(self, graph):
        assert graph.graph is graph

    def test_graph_property_has_node(self, graph):
        graph.add_node("Test")
        assert graph.graph.has_node("Test") is True
