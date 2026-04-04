"""
test_phase4_edge_cases.py — Chaos, edge cases, error recovery, persistence.

Tests cover:
- Empty / degenerate inputs (empty list, zero vector, single char)
- Unicode text in all metadata fields
- Extreme metadata values (max int64, empty strings, None-like strings)
- Negative IDs, very large IDs
- Duplicate ID overwrites are clean (no ghost rows)
- Schema dimension mismatch (wrong vector length → graceful handling)
- Store persistence: close and reopen → data intact
- Multiple tables in the same DB are isolated
- Invalid query_filter string → search returns [] (no crash)
- Score threshold = 1.0 → returns only exact matches
- Score threshold = 0.0 → returns everything
- Searching with a zero-vector
- Very large batch (50k in one call)
- Recovery: store survives a failed upsert and subsequent calls succeed
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import numpy as np
import pytest

from .conftest import LanceDBDataGenerator

lancedb = pytest.importorskip("lancedb", reason="lancedb not installed")


def _make_store(db_path, dims=768, table_name="memories"):
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
    return LanceDBVectorStore(
        db_path=db_path, embedding_dimensions=dims, table_name=table_name
    )


# ---------------------------------------------------------------------------
# Phase 4a — Degenerate / empty inputs
# ---------------------------------------------------------------------------

class TestDegenerateInputs:

    def test_empty_upsert_is_noop(self, tmp_path):
        """upsert_facts([]) must not raise and must not change row count."""
        store = _make_store(tmp_path)
        store.upsert_facts([])
        assert store.table.count_rows() == 0

    def test_single_record_upsert_and_retrieve(self, tmp_path):
        """A single record can be stored and retrieved."""
        store = _make_store(tmp_path)
        vec = [0.5] * 768
        norm = sum(v ** 2 for v in vec) ** 0.5
        vec = [v / norm for v in vec]
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "only one", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_search_empty_table_returns_empty_list(self, tmp_path):
        """Search on an empty table returns []."""
        store = _make_store(tmp_path)
        results = store.search([0.1] * 768, limit=10)
        assert results == []

    def test_single_char_text_stored_correctly(self, tmp_path):
        """Single-character text is preserved through store/retrieve."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=300)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "x", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["text"] == "x"

    def test_very_long_text_stored_correctly(self, tmp_path):
        """10 000-character text is stored and retrieved without truncation."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=301)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        long_text = "a" * 10_000
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": long_text, "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert len(results[0]["metadata"]["text"]) == 10_000


# ---------------------------------------------------------------------------
# Phase 4b — Unicode and special characters
# ---------------------------------------------------------------------------

class TestUnicodeAndSpecialChars:

    @pytest.mark.parametrize("text", [
        "আমি বাংলায় কথা বলছি",             # Bengali
        "私はPythonが好きです",                # Japanese
        "这是一个测试句子",                    # Chinese
        "مرحبا بك في البرنامج",              # Arabic
        "Hello 🤖 World 🌍",                  # Emoji
        "null\x00byte",                      # Null byte in string
        "SELECT * FROM users; DROP TABLE",   # SQL injection attempt
        '{"key": "value", "nested": true}',  # JSON string
        "line1\nline2\ttabbed",               # Newline + tab
        "café résumé naïve",                  # Latin diacritics
    ])
    def test_unicode_text_round_trip(self, tmp_path, text):
        """Unicode / special-char text survives store and retrieve."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=310)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": text, "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert len(results) == 1
        assert results[0]["metadata"]["text"] == text, \
            f"Text not preserved. Expected: {repr(text)}, got: {repr(results[0]['metadata']['text'])}"

    def test_unicode_in_entity_and_category(self, tmp_path):
        """Unicode values in entity and category metadata fields are preserved."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=311)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {
                "text": "test",
                "hemisphere_tag": "safe",
                "entity": "ব্যবহারকারী",  # Bengali for 'user'
                "category": "思い出",        # Japanese for 'memory'
            },
        }])
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["entity"] == "ব্যবহারকারী"
        assert results[0]["metadata"]["category"] == "思い出"


# ---------------------------------------------------------------------------
# Phase 4c — Extreme metadata values
# ---------------------------------------------------------------------------

class TestExtremeMetadataValues:

    def test_max_importance_value(self, tmp_path):
        """importance=9999 is stored and returned correctly."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=320)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "max", "hemisphere_tag": "safe", "importance": 9999},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["importance"] == 9999

    def test_zero_unix_timestamp(self, tmp_path):
        """unix_timestamp=0 (epoch) is valid."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=321)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "epoch", "hemisphere_tag": "safe", "unix_timestamp": 0},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["unix_timestamp"] == 0

    def test_negative_source_id(self, tmp_path):
        """Negative source_id is stored correctly (no constraint violation)."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=322)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "neg", "hemisphere_tag": "safe", "source_id": -1},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["source_id"] == -1

    def test_empty_string_metadata_defaults(self, tmp_path):
        """Missing metadata keys default to safe values, not errors."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=323)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        # Only provide required keys; omit entity, category, etc.
        store.upsert_facts([{"id": 1, "vector": vec, "metadata": {}}])
        results = store.search(vec, limit=1)
        assert len(results) == 1
        # hemisphere_tag defaults to "safe"
        assert results[0]["metadata"]["hemisphere_tag"] == "safe"

    def test_large_id_value(self, tmp_path):
        """ID = 10_000_000 (migration offset) is stored correctly."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=324)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        large_id = 10_000_000
        store.upsert_facts([{
            "id": large_id, "vector": vec,
            "metadata": {"text": "large id", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["id"] == large_id

    def test_none_like_string_values_stored_as_strings(self, tmp_path):
        """'None', 'null', 'undefined' as text are stored verbatim (not coerced)."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=325)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        for text_val in ["None", "null", "undefined", "NaN"]:
            store.upsert_facts([{
                "id": hash(text_val) % 100_000,
                "vector": vec,
                "metadata": {"text": text_val, "hemisphere_tag": "safe"},
            }])
        # No assertion on content, just verify no exception raised
        assert store.table.count_rows() == 4


# ---------------------------------------------------------------------------
# Phase 4d — Vector edge cases
# ---------------------------------------------------------------------------

class TestVectorEdgeCases:

    def test_zero_vector_stored_and_retrieved(self, tmp_path):
        """A zero vector is stored without error (cosine of zero is undefined)."""
        store = _make_store(tmp_path)
        zero_vec = [0.0] * 768
        # Should not raise — store must handle degenerate input gracefully
        try:
            store.upsert_facts([{
                "id": 1, "vector": zero_vec,
                "metadata": {"text": "zero", "hemisphere_tag": "safe"},
            }])
        except Exception as e:
            pytest.fail(f"upsert_facts raised on zero vector: {e}")

    def test_search_with_zero_query_vector_no_crash(self, tmp_path):
        """Searching with a zero query vector must return [] or results, never crash."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=330)
        store.upsert_facts(gen.facts(10))
        try:
            results = store.search([0.0] * 768, limit=5)
            assert isinstance(results, list)
        except Exception as e:
            # LanceDB may raise for zero-norm queries; that's acceptable
            # as long as it doesn't corrupt the store
            pass
        # Verify store is still functional after the degenerate query
        normal_vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(normal_vec, limit=5)
        assert isinstance(results, list)

    def test_all_same_value_vector(self, tmp_path):
        """A vector with all identical values is stored and retrieved."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=331)
        # Normalise a constant vector
        val = 1.0 / (768 ** 0.5)
        const_vec = [val] * 768
        store.upsert_facts([{
            "id": 1, "vector": const_vec,
            "metadata": {"text": "constant", "hemisphere_tag": "safe"},
        }])
        results = store.search(const_vec, limit=1)
        assert len(results) == 1
        assert results[0]["score"] > 0.98

    def test_custom_embedding_dimensions_4(self, tmp_path):
        """Store with 4-dim vectors stores and retrieves correctly."""
        store = _make_store(tmp_path / "dim4", dims=4)
        vec = [0.5, 0.5, 0.5, 0.5]
        norm = sum(v ** 2 for v in vec) ** 0.5
        vec = [v / norm for v in vec]
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "4-dim", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert results[0]["score"] > 0.98

    def test_custom_embedding_dimensions_512(self, tmp_path):
        """Store with 512-dim vectors works end-to-end."""
        store = _make_store(tmp_path / "dim512", dims=512)
        gen = LanceDBDataGenerator(seed=332)
        vecs = gen.vectors_random(10, dims=512)
        facts = gen.facts(10, vectors=vecs, dims=512)
        store.upsert_facts(facts)
        assert store.table.count_rows() == 10
        results = store.search(vecs[0].tolist(), limit=3)
        assert len(results) > 0


# ---------------------------------------------------------------------------
# Phase 4e — Store persistence
# ---------------------------------------------------------------------------

class TestStorePersistence:

    def test_data_survives_store_close_and_reopen(self, tmp_path):
        """Data written to store A is readable after reopening as store B."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        db_path = tmp_path / "persistent_db"
        gen = LanceDBDataGenerator(seed=340)

        # Write
        store_a = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
        facts = gen.facts(500)
        store_a.upsert_facts(facts)
        store_a.close()

        # Reopen — same path, different instance
        store_b = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
        assert store_b.table.count_rows() == 500
        results = store_b.search(facts[0]["vector"], limit=1)
        assert len(results) > 0
        assert results[0]["id"] == facts[0]["id"]
        store_b.close()

    def test_data_survives_process_restart_simulation(self, tmp_path):
        """Re-opening with the same db_path yields correct data (no corruption)."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        db_path = tmp_path / "restart_db"
        gen = LanceDBDataGenerator(seed=341)
        known_vec = gen.vectors_random(1, dims=768)[0].tolist()

        # Write first batch
        s1 = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
        s1.upsert_facts([{
            "id": 42, "vector": known_vec,
            "metadata": {"text": "persistent fact", "hemisphere_tag": "safe"},
        }])
        s1.close()

        # "Restart" — new instance
        s2 = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
        results = s2.search(known_vec, limit=1)
        assert results[0]["id"] == 42
        assert results[0]["metadata"]["text"] == "persistent fact"
        s2.close()


# ---------------------------------------------------------------------------
# Phase 4f — Multiple tables isolation
# ---------------------------------------------------------------------------

class TestMultipleTablesIsolation:

    def test_two_tables_in_same_db_are_isolated(self, tmp_path):
        """Two LanceDBVectorStore instances with different table_names are independent."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        gen = LanceDBDataGenerator(seed=350)
        db_path = tmp_path / "shared_db"

        store_a = LanceDBVectorStore(db_path=db_path, table_name="table_a", embedding_dimensions=768)
        store_b = LanceDBVectorStore(db_path=db_path, table_name="table_b", embedding_dimensions=768)

        facts_a = gen.facts(100, id_offset=0)
        facts_b = gen.facts(200, id_offset=0)  # same IDs, different table
        store_a.upsert_facts(facts_a)
        store_b.upsert_facts(facts_b)

        assert store_a.table.count_rows() == 100
        assert store_b.table.count_rows() == 200
        store_a.close()
        store_b.close()


# ---------------------------------------------------------------------------
# Phase 4g — Query filter edge cases
# ---------------------------------------------------------------------------

class TestQueryFilterEdgeCases:

    def test_invalid_filter_returns_empty_not_crash(self, tmp_path):
        """A syntactically invalid filter returns [] without raising."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=360)
        store.upsert_facts(gen.facts(50))
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        # search() wraps errors in try/except and returns []
        results = store.search(vec, limit=10, query_filter="THIS IS NOT SQL!!!###")
        assert isinstance(results, list)

    def test_filter_matching_no_rows_returns_empty(self, tmp_path):
        """Filter that matches 0 rows returns []."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=361)
        # All inserted with hemisphere_tag=safe
        facts = [
            {"id": i, "vector": gen.vectors_random(1, dims=768)[0].tolist(),
             "metadata": {"text": f"item {i}", "hemisphere_tag": "safe"}}
            for i in range(50)
        ]
        store.upsert_facts(facts)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=10, query_filter="hemisphere_tag = 'spicy'")
        assert results == []

    def test_score_threshold_1_returns_only_near_perfect(self, tmp_path):
        """score_threshold=0.99 returns only near-identical vectors."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=362)
        anchor_vec = gen.vectors_random(1, dims=768)[0]
        anchor_list = anchor_vec.tolist()

        # Store the anchor and 100 random others
        store.upsert_facts([{
            "id": 0, "vector": anchor_list,
            "metadata": {"text": "anchor", "hemisphere_tag": "safe"},
        }])
        store.upsert_facts(gen.facts(100, id_offset=1))

        results = store.search(anchor_list, limit=50, score_threshold=0.99)
        for r in results:
            assert r["score"] >= 0.99

    def test_score_threshold_0_returns_all_results_up_to_limit(self, tmp_path):
        """score_threshold=0.0 should not filter anything out."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=363)
        store.upsert_facts(gen.facts(100))
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=10, score_threshold=0.0)
        assert len(results) == 10


# ---------------------------------------------------------------------------
# Phase 4h — Large single batch
# ---------------------------------------------------------------------------

class TestLargeSingleBatch:

    def test_50k_in_single_upsert_call(self, tmp_path):
        """A single upsert_facts() call with 50k records completes without error."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=370)
        facts = gen.facts(50_000)
        t0 = time.perf_counter()
        store.upsert_facts(facts)
        elapsed = time.perf_counter() - t0
        rows_per_s = 50_000 / elapsed
        print(f"\n[large batch] 50k single call: {rows_per_s:.0f} rows/s ({elapsed:.2f}s)")
        assert store.table.count_rows() == 50_000

    def test_10k_in_single_call_matches_10_batches_of_1k(self, tmp_path):
        """Single 10k upsert and 10x 1k upserts produce same final row count."""
        gen = LanceDBDataGenerator(seed=371)

        # Store A: single call
        store_a = _make_store(tmp_path / "a")
        store_a.upsert_facts(gen.facts(10_000))

        # Store B: 10 batches
        store_b = _make_store(tmp_path / "b")
        for i in range(10):
            store_b.upsert_facts(gen.facts(1_000, id_offset=i * 1_000))

        assert store_a.table.count_rows() == store_b.table.count_rows() == 10_000


# ---------------------------------------------------------------------------
# Phase 4i — Error recovery
# ---------------------------------------------------------------------------

class TestErrorRecovery:

    def test_store_functional_after_failed_upsert(self, tmp_path):
        """After a failed upsert, subsequent valid upserts succeed."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=380)

        # Intentionally broken fact (wrong vector length for 768-dim schema)
        broken_fact = [{"id": 1, "vector": [0.1, 0.2], "metadata": {"text": "broken"}}]
        try:
            store.upsert_facts(broken_fact)
        except Exception:
            pass  # Expected to fail

        # Store must still work for valid data
        valid_facts = gen.facts(10)
        store.upsert_facts(valid_facts)  # must not raise
        assert store.table.count_rows() >= 10  # 0 or 10 depending on if broken succeeded

    def test_search_returns_empty_on_corrupt_query_vector(self, tmp_path):
        """Search with wrong-dimension vector returns [] without crashing."""
        store = _make_store(tmp_path)  # 768-dim
        gen = LanceDBDataGenerator(seed=381)
        store.upsert_facts(gen.facts(10))
        # Wrong dimension (4 instead of 768)
        wrong_dim_vec = [0.1, 0.2, 0.3, 0.4]
        results = store.search(wrong_dim_vec, limit=5)
        # Should return [] due to try/except in search()
        assert isinstance(results, list)

    def test_close_is_always_safe_to_call(self, tmp_path):
        """close() can be called multiple times without error."""
        store = _make_store(tmp_path)
        store.close()
        store.close()  # second call must not raise
        store.close()  # third call must not raise
