"""
test_vector_store.py — Unit tests for LanceDBVectorStore.

All tests use tmp_path to avoid polluting real data.
Run with:
    cd workspace && pytest tests/test_vector_store.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

pytest.importorskip("lancedb", reason="lancedb not installed")

from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

DIM = 4  # tiny dimension for fast tests


def _make_store(tmp_path, dim=DIM, table="test_mem"):
    return LanceDBVectorStore(db_path=str(tmp_path), table_name=table, embedding_dimensions=dim)


def _vec(val=0.1, dim=DIM):
    return [val] * dim


def _fact(id, val=0.1, hemisphere="safe", text="hello", importance=5):
    return {
        "id": id,
        "vector": _vec(val),
        "metadata": {
            "text": text,
            "hemisphere_tag": hemisphere,
            "unix_timestamp": 1700000000,
            "importance": importance,
        },
    }


class TestInit:
    def test_init_creates_db_and_table(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.table is not None
        assert store._embedding_dimensions == DIM

    def test_custom_embedding_dimensions(self, tmp_path):
        store = LanceDBVectorStore(
            db_path=str(tmp_path), table_name="t512", embedding_dimensions=512
        )
        assert store._embedding_dimensions == 512
        vector_field = store.table.schema.field("vector")
        assert vector_field.type.list_size == 512


class TestUpsert:
    def test_upsert_single_fact(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(1)])
        assert store.table.count_rows() == 1

    def test_upsert_idempotent(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(1, text="first")])
        store.upsert_facts([_fact(1, text="updated")])
        assert store.table.count_rows() == 1
        row = store.table.to_pandas()
        assert row.iloc[0]["text"] == "updated"

    def test_upsert_batch(self, tmp_path):
        store = _make_store(tmp_path)
        facts = [_fact(i) for i in range(10)]
        store.upsert_facts(facts)
        assert store.table.count_rows() == 10

    def test_upsert_empty_list_noop(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([])
        assert store.table.count_rows() == 0


class TestSearch:
    def test_search_returns_correct_format(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(1, text="test")])
        results = store.search(_vec())
        assert isinstance(results, list)
        assert len(results) == 1
        r = results[0]
        assert "id" in r
        assert "score" in r
        assert "metadata" in r
        assert "text" in r["metadata"]

    def test_search_cosine_score_conversion(self, tmp_path):
        """Identical vector should give score ~1.0."""
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(1, val=0.5)])
        results = store.search(_vec(0.5))
        assert len(results) == 1
        assert results[0]["score"] > 0.99

    def test_search_hemisphere_filter_safe(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([
            _fact(1, hemisphere="safe", text="safe content"),
            _fact(2, hemisphere="spicy", text="spicy content"),
        ])
        results = store.search(_vec(), query_filter="hemisphere_tag = 'safe'")
        assert all(r["metadata"]["hemisphere_tag"] == "safe" for r in results)

    def test_search_hemisphere_filter_spicy(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([
            _fact(1, hemisphere="safe"),
            _fact(2, hemisphere="spicy"),
        ])
        results = store.search(
            _vec(), query_filter="hemisphere_tag IN ('safe', 'spicy')"
        )
        assert len(results) == 2

    def test_search_score_threshold(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(1, val=0.5)])
        # Very high threshold should exclude non-identical results
        results = store.search(_vec(0.1), score_threshold=0.999)
        assert results == []

    def test_search_empty_table(self, tmp_path):
        store = _make_store(tmp_path)
        results = store.search(_vec())
        assert results == []

    def test_search_limit(self, tmp_path):
        store = _make_store(tmp_path)
        store.upsert_facts([_fact(i) for i in range(10)])
        results = store.search(_vec(), limit=3)
        assert len(results) <= 3


class TestMissingMetadata:
    def test_missing_metadata_keys_default(self, tmp_path):
        """Facts with sparse metadata should use sensible defaults."""
        store = _make_store(tmp_path)
        store.upsert_facts([{
            "id": 1,
            "vector": _vec(),
            "metadata": {"text": "minimal"},  # no hemisphere_tag, importance, etc.
        }])
        results = store.search(_vec())
        assert len(results) == 1
        meta = results[0]["metadata"]
        assert meta["hemisphere_tag"] == "safe"
        assert meta["importance"] == 5


class TestClose:
    def test_close_is_noop(self, tmp_path):
        store = _make_store(tmp_path)
        store.close()  # should not raise
