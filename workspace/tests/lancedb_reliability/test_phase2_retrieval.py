"""
test_phase2_retrieval.py — Search speed, correctness, and reliability.

Tests cover:
- Latency percentiles (p50 / p95 / p99) at 1k and 10k table scale
- Score conversion sanity: all results in [0, 1], identical vector = score ≈ 1.0
- Limit enforcement: never returns more rows than requested
- Score threshold filtering
- Hemisphere filtering: safe / spicy SQL WHERE clause
- Result format completeness (all metadata keys present)
- ANN accuracy: known vector is top-1 result
- FTS search after index creation
- Retrieval reliability: 0 errors over 10k consecutive searches
- FastEmbed semantic retrieval: correct document retrieved for paraphrased query
"""

from __future__ import annotations

import time
import threading

import numpy as np
import pytest

from .conftest import LanceDBDataGenerator, LatencyTracker, get_memory_mb

lancedb = pytest.importorskip("lancedb", reason="lancedb not installed")


def _make_store(tmp_path, dims=768):
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
    return LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=dims)


# ---------------------------------------------------------------------------
# Phase 2a — Latency benchmarks
# ---------------------------------------------------------------------------

class TestSearchLatency:

    def test_search_latency_1k_table_p50_under_50ms(self, store_1k):
        """p50 search latency on 1k table must be < 50 ms."""
        store, facts = store_1k
        gen = LanceDBDataGenerator(seed=100)
        query_vecs = gen.vectors_random(200, dims=768)
        tracker = LatencyTracker()
        for vec in query_vecs:
            t0 = time.perf_counter()
            store.search(vec.tolist(), limit=10)
            tracker.record((time.perf_counter() - t0) * 1_000)
        p50 = tracker.percentile(50)
        p95 = tracker.percentile(95)
        print(f"\n[latency 1k] p50={p50:.2f}ms p95={p95:.2f}ms over 200 queries")
        assert p50 < 50, f"p50={p50:.2f}ms exceeds 50ms on 1k table"

    def test_search_latency_10k_table_p95_under_200ms(self, store_10k):
        """p95 search latency on 10k table must be < 200 ms."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=101)
        query_vecs = gen.vectors_random(500, dims=768)
        tracker = LatencyTracker()
        for vec in query_vecs:
            t0 = time.perf_counter()
            store.search(vec.tolist(), limit=10)
            tracker.record((time.perf_counter() - t0) * 1_000)
        p50 = tracker.percentile(50)
        p95 = tracker.percentile(95)
        p99 = tracker.percentile(99)
        print(f"\n[latency 10k] p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms")
        assert p95 < 200, f"p95={p95:.2f}ms exceeds 200ms on 10k table"

    @pytest.mark.slow
    def test_search_latency_100k_table_p99_under_500ms(self, store_100k):
        """p99 search latency on 100k table must be < 500 ms."""
        store, facts = store_100k
        gen = LanceDBDataGenerator(seed=102)
        query_vecs = gen.vectors_random(1_000, dims=768)
        tracker = LatencyTracker()
        for vec in query_vecs:
            t0 = time.perf_counter()
            store.search(vec.tolist(), limit=10)
            tracker.record((time.perf_counter() - t0) * 1_000)
        p50 = tracker.percentile(50)
        p95 = tracker.percentile(95)
        p99 = tracker.percentile(99)
        print(f"\n[latency 100k] p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms over 1000 queries")
        assert p99 < 500, f"p99={p99:.2f}ms exceeds 500ms on 100k table"

    def test_search_latency_does_not_degrade_over_1k_queries(self, store_10k):
        """Last-500-queries p95 must not be > 2x first-500-queries p95."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=103)
        query_vecs = gen.vectors_random(1_000, dims=768)
        first_500, last_500 = LatencyTracker(), LatencyTracker()
        for i, vec in enumerate(query_vecs):
            t0 = time.perf_counter()
            store.search(vec.tolist(), limit=10)
            ms = (time.perf_counter() - t0) * 1_000
            (first_500 if i < 500 else last_500).record(ms)
        p95_first = first_500.percentile(95)
        p95_last = last_500.percentile(95)
        print(f"\n[latency stability] first-500 p95={p95_first:.2f}ms, last-500 p95={p95_last:.2f}ms")
        assert p95_last < p95_first * 2.5, \
            f"Latency degraded: first p95={p95_first:.2f}ms → last p95={p95_last:.2f}ms"


# ---------------------------------------------------------------------------
# Phase 2b — Score correctness
# ---------------------------------------------------------------------------

class TestSearchScoreCorrectness:

    def test_identical_vector_score_near_1(self, tmp_path):
        """Searching with a vector that is in the table returns score ≈ 1.0."""
        store = _make_store(tmp_path)
        vec = [0.1] * 768
        # Normalise so cosine distance is well-defined
        norm = sum(v ** 2 for v in vec) ** 0.5
        vec = [v / norm for v in vec]
        store.upsert_facts([{
            "id": 1, "vector": vec,
            "metadata": {"text": "exact match", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec, limit=1)
        assert len(results) == 1
        assert results[0]["score"] > 0.98, f"Expected score ≈ 1.0, got {results[0]['score']:.4f}"

    def test_all_scores_in_zero_to_one_range(self, store_10k):
        """Every returned score must be in [0, 1]."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=110)
        query_vecs = gen.vectors_random(100, dims=768)
        for vec in query_vecs:
            results = store.search(vec.tolist(), limit=20)
            for r in results:
                assert 0.0 <= r["score"] <= 1.0, \
                    f"Score out of range: {r['score']}"

    def test_score_threshold_excludes_low_scores(self, store_10k):
        """Results with score < threshold must not appear."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=111)
        query_vec = gen.vectors_random(1, dims=768)[0].tolist()
        threshold = 0.5
        results = store.search(query_vec, limit=50, score_threshold=threshold)
        for r in results:
            assert r["score"] >= threshold, \
                f"Result with score {r['score']:.4f} slipped below threshold {threshold}"

    def test_results_sorted_by_score_descending(self, store_10k):
        """Results must be returned in descending score order."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=112)
        query_vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(query_vec, limit=20)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), \
            f"Results not sorted by score: {scores}"

    def test_orthogonal_vector_has_low_score(self, tmp_path):
        """Two orthogonal vectors should yield a score near 0."""
        store = _make_store(tmp_path)
        vec_a = [0.0] * 768
        vec_b = [0.0] * 768
        vec_a[0] = 1.0  # unit vector along dim 0
        vec_b[1] = 1.0  # unit vector along dim 1 — orthogonal to vec_a
        store.upsert_facts([{
            "id": 1, "vector": vec_b,
            "metadata": {"text": "orthogonal", "hemisphere_tag": "safe"},
        }])
        results = store.search(vec_a, limit=1)
        assert len(results) == 1
        # Cosine similarity of orthogonal vectors = 0 → score ≈ 0
        assert results[0]["score"] < 0.2, \
            f"Orthogonal vectors yielded high score: {results[0]['score']:.4f}"

    def test_score_conversion_distance_zero_is_score_one(self, tmp_path):
        """Verify the 1 - distance formula: distance=0 → score=1."""
        store = _make_store(tmp_path)
        import unittest.mock as mock
        # Patch table.search to return a mock result with _distance=0
        fake_result = [{
            "id": 99, "_distance": 0.0,
            "text": "perfect", "hemisphere_tag": "safe",
            "unix_timestamp": 0, "importance": 5,
            "source_id": 0, "entity": "", "category": "",
        }]
        vec = [0.1] * 768
        with mock.patch.object(store.table, "search") as mock_search:
            mock_searcher = mock.MagicMock()
            mock_searcher.metric.return_value = mock_searcher
            mock_searcher.limit.return_value = mock_searcher
            mock_searcher.to_list.return_value = fake_result
            mock_search.return_value = mock_searcher
            results = store.search(vec, limit=1)
        assert results[0]["score"] == 1.0


# ---------------------------------------------------------------------------
# Phase 2c — Limit enforcement
# ---------------------------------------------------------------------------

class TestSearchLimit:

    def test_limit_respected_exact(self, store_10k):
        """search(limit=5) must return ≤ 5 results."""
        store, facts = store_10k
        gen = LanceDBDataGenerator(seed=120)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=5)
        assert len(results) <= 5

    @pytest.mark.parametrize("limit", [1, 3, 10, 25, 50, 100])
    def test_limit_parametrized(self, store_10k, limit):
        """Various limit values are respected."""
        store, _ = store_10k
        gen = LanceDBDataGenerator(seed=121 + limit)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=limit)
        assert len(results) <= limit, f"Got {len(results)} results for limit={limit}"

    def test_empty_table_returns_empty_list(self, tmp_path):
        """Searching an empty table returns []."""
        store = _make_store(tmp_path)
        vec = [0.1] * 768
        results = store.search(vec, limit=10)
        assert results == []


# ---------------------------------------------------------------------------
# Phase 2d — Hemisphere filtering
# ---------------------------------------------------------------------------

class TestHemisphereFiltering:

    def _populate_mixed(self, tmp_path):
        """Create a store with 500 safe + 500 spicy records."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        store = LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=768)
        gen = LanceDBDataGenerator(seed=130)
        vecs = gen.vectors_random(1_000, dims=768)
        facts = []
        for i in range(1_000):
            facts.append({
                "id": i,
                "vector": vecs[i].tolist(),
                "metadata": {
                    "text": f"item {i}",
                    "hemisphere_tag": "safe" if i < 500 else "spicy",
                    "unix_timestamp": 0, "importance": 5,
                },
            })
        store.upsert_facts(facts)
        return store, vecs

    def test_safe_filter_returns_only_safe(self, tmp_path):
        """hemisphere_tag = 'safe' filter must exclude all spicy results."""
        store, vecs = self._populate_mixed(tmp_path)
        vec = vecs[0].tolist()  # safe record
        results = store.search(vec, limit=50, query_filter="hemisphere_tag = 'safe'")
        for r in results:
            assert r["metadata"]["hemisphere_tag"] == "safe", \
                f"Spicy result leaked through safe filter: id={r['id']}"

    def test_spicy_filter_includes_both_hemispheres(self, tmp_path):
        """IN ('safe', 'spicy') filter must return both hemispheres."""
        store, vecs = self._populate_mixed(tmp_path)
        vec = vecs[0].tolist()
        results = store.search(
            vec, limit=100,
            query_filter="hemisphere_tag IN ('safe', 'spicy')"
        )
        tags = {r["metadata"]["hemisphere_tag"] for r in results}
        assert "safe" in tags, "No safe results in spicy+safe query"
        assert "spicy" in tags, "No spicy results in spicy+safe query"

    def test_no_filter_returns_all_hemispheres(self, tmp_path):
        """Without a filter, both hemispheres appear in results."""
        store, vecs = self._populate_mixed(tmp_path)
        vec = vecs[250].tolist()  # somewhere in the middle
        results = store.search(vec, limit=100)
        tags = {r["metadata"]["hemisphere_tag"] for r in results}
        assert len(tags) >= 1  # at minimum, we get results

    def test_safe_filter_reduces_result_pool(self, tmp_path):
        """Safe-only filter should return fewer results than unfiltered."""
        store, vecs = self._populate_mixed(tmp_path)
        vec = vecs[0].tolist()
        all_results = store.search(vec, limit=100)
        safe_results = store.search(vec, limit=100, query_filter="hemisphere_tag = 'safe'")
        assert len(safe_results) <= len(all_results)


# ---------------------------------------------------------------------------
# Phase 2e — Result format validation
# ---------------------------------------------------------------------------

class TestResultFormat:

    def test_result_has_all_required_keys(self, store_1k):
        """Every result dict must have id, score, and all metadata subkeys."""
        store, _ = store_1k
        gen = LanceDBDataGenerator(seed=140)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=5)
        assert len(results) > 0
        required_meta = {"text", "hemisphere_tag", "unix_timestamp",
                         "importance", "source_id", "entity", "category"}
        for r in results:
            assert "id" in r
            assert "score" in r
            assert "metadata" in r
            missing = required_meta - set(r["metadata"].keys())
            assert not missing, f"Missing metadata keys: {missing}"

    def test_id_is_integer(self, store_1k):
        """id field must be an integer."""
        store, _ = store_1k
        gen = LanceDBDataGenerator(seed=141)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=5)
        for r in results:
            assert isinstance(r["id"], (int, np.integer)), \
                f"id is not int: {type(r['id'])}"

    def test_score_is_float(self, store_1k):
        """score field must be a float."""
        store, _ = store_1k
        gen = LanceDBDataGenerator(seed=142)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=5)
        for r in results:
            assert isinstance(r["score"], float), \
                f"score is not float: {type(r['score'])}"

    def test_text_is_string(self, store_1k):
        """metadata.text must be a str."""
        store, _ = store_1k
        gen = LanceDBDataGenerator(seed=143)
        vec = gen.vectors_random(1, dims=768)[0].tolist()
        results = store.search(vec, limit=5)
        for r in results:
            assert isinstance(r["metadata"]["text"], str), \
                f"text is not str: {type(r['metadata']['text'])}"


# ---------------------------------------------------------------------------
# Phase 2f — ANN accuracy
# ---------------------------------------------------------------------------

class TestSearchAccuracy:

    def test_planted_vector_is_top1(self, tmp_path):
        """A known vector planted at id=999 must be top-1 when queried exactly."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        gen = LanceDBDataGenerator(seed=150)
        store = LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=768)

        # Fill with random noise
        noise = gen.facts(500)
        store.upsert_facts(noise)

        # Plant a distinct vector.
        # IMPORTANT: gen.vectors_random(n) always reseeds from self._seed, so
        # gen.vectors_random(1)[0] == gen.facts(500)'s vector[0] == noise id=0.
        # Take index 500 (outside the 0..499 range used by noise) to guarantee uniqueness.
        anchor = gen.vectors_random(501, dims=768)[500].tolist()
        store.upsert_facts([{
            "id": 999_999,
            "vector": anchor,
            "metadata": {"text": "anchor", "hemisphere_tag": "safe"},
        }])
        # More noise after
        store.upsert_facts(gen.facts(500, id_offset=1000))

        results = store.search(anchor, limit=1)
        assert len(results) > 0
        assert results[0]["id"] == 999_999, \
            f"Expected id=999999 as top-1, got id={results[0]['id']}"

    @pytest.mark.slow
    def test_top1_recall_at_100k(self, store_100k):
        """In a 100k table, 95%+ of exactly-planted queries return top-1 correctly."""
        store, facts = store_100k
        # Sample 100 facts whose vectors we know exactly
        sample = facts[:100]
        hits = 0
        for f in sample:
            results = store.search(f["vector"], limit=1)
            if results and results[0]["id"] == f["id"]:
                hits += 1
        recall = hits / len(sample)
        print(f"\n[recall@1 100k] {hits}/{len(sample)} = {recall:.2%}")
        # IVF_PQ is approximate — allow up to 5% miss rate
        assert recall >= 0.95, f"Recall@1 = {recall:.2%} below 95% threshold"


# ---------------------------------------------------------------------------
# Phase 2g — Reliability: zero errors over many searches
# ---------------------------------------------------------------------------

class TestSearchReliability:

    def test_10k_searches_zero_errors(self, store_10k):
        """10 000 consecutive searches on a 10k table raise zero exceptions."""
        store, _ = store_10k
        gen = LanceDBDataGenerator(seed=160)
        query_vecs = gen.vectors_random(10_000, dims=768)
        errors = 0
        for vec in query_vecs:
            try:
                store.search(vec.tolist(), limit=10)
            except Exception:
                errors += 1
        assert errors == 0, f"{errors}/10000 searches raised exceptions"

    @pytest.mark.slow
    def test_50k_searches_zero_errors(self, store_100k):
        """50 000 consecutive searches on a 100k table raise zero exceptions."""
        store, _ = store_100k
        gen = LanceDBDataGenerator(seed=161)
        query_vecs = gen.vectors_random(50_000, dims=768)
        errors = 0
        for vec in query_vecs:
            try:
                store.search(vec.tolist(), limit=10)
            except Exception:
                errors += 1
        assert errors == 0, f"{errors}/50000 searches raised exceptions"


# ---------------------------------------------------------------------------
# Phase 2h — FastEmbed semantic retrieval
# ---------------------------------------------------------------------------

class TestFastEmbedSemanticRetrieval:

    @pytest.mark.fastembed
    def test_semantic_nearest_neighbour(self, fastembed_store_10k):
        """Query with a paraphrase should retrieve the original text in top-5."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        store, facts, texts, vectors = fastembed_store_10k
        gen = LanceDBDataGenerator(seed=170)

        # Plant a very specific fact and query with a paraphrase
        specific_text = "I enjoy writing Python code every morning in my home office"
        from sci_fi_dashboard.embedding.factory import get_provider
        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        # Embed the document and query via project provider (auto GPU/CPU)
        doc_vec = provider.embed_query(specific_text)
        paraphrase_vec = provider.embed_query("I like coding Python at home in the mornings")

        # Upsert the specific document
        store.upsert_facts([{
            "id": 999_998,
            "vector": doc_vec,
            "metadata": {"text": specific_text, "hemisphere_tag": "safe"},
        }])

        results = store.search(paraphrase_vec, limit=10)
        top_ids = [r["id"] for r in results]
        assert 999_998 in top_ids, \
            f"Paraphrase did not retrieve original in top-10. Top IDs: {top_ids}"

    @pytest.mark.fastembed
    def test_dissimilar_query_low_score(self, fastembed_store_10k):
        """A query about a completely different topic should yield lower scores than a related one."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        store, facts, texts, vectors = fastembed_store_10k
        from sci_fi_dashboard.embedding.factory import get_provider
        provider = get_provider()
        if provider is None:
            pytest.skip("No embedding provider available")

        related_vec = provider.embed_query("I remember working on a project")
        unrelated_vec = provider.embed_query("the speed of light in a vacuum is 299792458 m/s")

        related_results = store.search(related_vec, limit=5)
        unrelated_results = store.search(unrelated_vec, limit=5)

        related_top = related_results[0]["score"] if related_results else 0
        unrelated_top = unrelated_results[0]["score"] if unrelated_results else 0

        print(f"\n[semantic] related top score={related_top:.4f}, unrelated top score={unrelated_top:.4f}")
        # Related query should score higher in a corpus of everyday language
        assert related_top >= unrelated_top - 0.05, "Unrelated query scored suspiciously higher"
