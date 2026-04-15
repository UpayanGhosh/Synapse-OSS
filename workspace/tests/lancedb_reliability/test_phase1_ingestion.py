"""
test_phase1_ingestion.py — Ingestion speed, reliability, and correctness.

Tests cover:
- Zero-error ingestion at 1k / 10k / 100k scale
- Throughput benchmarks (rows/sec)
- Memory usage bounds during bulk ingest
- Idempotency: re-upsert same data → row count unchanged
- Batch-size impact on throughput
- IVF_PQ index creation after threshold (256 rows)
- Full end-to-end ingestion via real FastEmbed vectors
- Progressive ingestion: build up from 0 → 100k incrementally
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from .conftest import LanceDBDataGenerator, get_memory_mb

lancedb = pytest.importorskip("lancedb", reason="lancedb not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_count(store) -> int:
    return store.table.count_rows()


def _make_store(tmp_path, dims=768):
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    return LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=dims)


# ---------------------------------------------------------------------------
# Phase 1a — Scale: zero-error ingestion
# ---------------------------------------------------------------------------


class TestIngestionZeroErrors:

    def test_ingest_1k_zero_errors(self, tmp_path):
        """1 000 records ingested without any exception."""
        gen = LanceDBDataGenerator(seed=1)
        store = _make_store(tmp_path)
        facts = gen.facts(1_000)
        # should not raise
        store.upsert_facts(facts)
        assert _row_count(store) == 1_000

    def test_ingest_10k_zero_errors(self, tmp_path):
        """10 000 records ingested in a single call, zero errors."""
        gen = LanceDBDataGenerator(seed=2)
        store = _make_store(tmp_path)
        facts = gen.facts(10_000)
        store.upsert_facts(facts)
        assert _row_count(store) == 10_000

    @pytest.mark.slow
    def test_ingest_100k_zero_errors(self, tmp_path):
        """100 000 records ingested in 1k batches, zero errors."""
        gen = LanceDBDataGenerator(seed=3)
        store = _make_store(tmp_path)
        facts = gen.facts(100_000)
        errors = 0
        for i in range(0, 100_000, 1_000):
            try:
                store.upsert_facts(facts[i : i + 1_000])
            except Exception:
                errors += 1
        assert errors == 0, f"{errors} batches raised exceptions"
        assert _row_count(store) == 100_000

    def test_ingest_returns_correct_row_count_after_two_calls(self, tmp_path):
        """Consecutive upserts accumulate rows correctly."""
        gen = LanceDBDataGenerator(seed=4)
        store = _make_store(tmp_path)
        store.upsert_facts(gen.facts(500, id_offset=0))
        store.upsert_facts(gen.facts(500, id_offset=500))
        assert _row_count(store) == 1_000


# ---------------------------------------------------------------------------
# Phase 1b — Throughput
# ---------------------------------------------------------------------------


class TestIngestionThroughput:

    def test_throughput_1k_exceeds_1k_rows_per_sec(self, tmp_path):
        """Ingest 1k rows in one call and verify throughput > 1 000 rows/s."""
        gen = LanceDBDataGenerator(seed=10)
        store = _make_store(tmp_path)
        facts = gen.facts(1_000)
        t0 = time.perf_counter()
        store.upsert_facts(facts)
        elapsed = time.perf_counter() - t0
        rows_per_sec = 1_000 / elapsed
        print(f"\n[throughput] 1k rows: {rows_per_sec:.0f} rows/s ({elapsed*1000:.1f}ms)")
        assert rows_per_sec > 1_000, f"Too slow: {rows_per_sec:.0f} rows/s"

    def test_throughput_10k_exceeds_2k_rows_per_sec(self, tmp_path):
        """Ingest 10k rows and verify throughput > 2 000 rows/s."""
        gen = LanceDBDataGenerator(seed=11)
        store = _make_store(tmp_path)
        facts = gen.facts(10_000)
        t0 = time.perf_counter()
        store.upsert_facts(facts)
        elapsed = time.perf_counter() - t0
        rows_per_sec = 10_000 / elapsed
        print(f"\n[throughput] 10k rows: {rows_per_sec:.0f} rows/s ({elapsed*1000:.1f}ms)")
        assert rows_per_sec > 2_000, f"Too slow: {rows_per_sec:.0f} rows/s"

    @pytest.mark.slow
    def test_throughput_100k_report(self, tmp_path):
        """Measure and report throughput over 100k rows (no hard floor — just report)."""
        gen = LanceDBDataGenerator(seed=12)
        store = _make_store(tmp_path)
        facts = gen.facts(100_000)
        batch_times = []
        for i in range(0, 100_000, 1_000):
            t0 = time.perf_counter()
            store.upsert_facts(facts[i : i + 1_000])
            batch_times.append(time.perf_counter() - t0)

        avg_ms = sum(batch_times) / len(batch_times) * 1_000
        total_s = sum(batch_times)
        rows_per_s = 100_000 / total_s
        print(
            f"\n[throughput] 100k rows: {rows_per_s:.0f} rows/s total, "
            f"avg batch={avg_ms:.1f}ms, total={total_s:.2f}s"
        )
        # Sanity: must finish in under 5 minutes
        assert total_s < 300, f"100k ingest took {total_s:.1f}s — too slow"

    @pytest.mark.parametrize("batch_size", [100, 500, 1_000, 5_000])
    def test_batch_size_comparison(self, tmp_path, batch_size):
        """Measure throughput at each batch size (informational, not gated)."""
        gen = LanceDBDataGenerator(seed=20 + batch_size)
        store = _make_store(tmp_path)
        n = 10_000
        facts = gen.facts(n)
        t0 = time.perf_counter()
        for i in range(0, n, batch_size):
            store.upsert_facts(facts[i : i + batch_size])
        elapsed = time.perf_counter() - t0
        rows_per_s = n / elapsed
        print(f"\n[batch_size={batch_size}] {rows_per_s:.0f} rows/s ({elapsed*1000:.1f}ms)")
        assert _row_count(store) == n


# ---------------------------------------------------------------------------
# Phase 1c — Memory
# ---------------------------------------------------------------------------


class TestIngestionMemory:

    def test_memory_growth_bounded_10k(self, tmp_path):
        """RSS growth during 10k ingest stays under 200 MB."""
        mem_before = get_memory_mb()
        if mem_before == 0:
            pytest.skip("psutil not available")
        gen = LanceDBDataGenerator(seed=30)
        store = _make_store(tmp_path)
        facts = gen.facts(10_000)
        store.upsert_facts(facts)
        mem_after = get_memory_mb()
        delta = mem_after - mem_before
        print(
            f"\n[memory] 10k ingest: +{delta:.1f} MB (before={mem_before:.1f}, after={mem_after:.1f})"
        )
        assert delta < 200, f"Memory grew {delta:.1f} MB — possible leak"

    @pytest.mark.slow
    def test_memory_growth_bounded_100k(self, tmp_path):
        """RSS growth during 100k ingest stays under 500 MB."""
        mem_before = get_memory_mb()
        if mem_before == 0:
            pytest.skip("psutil not available")
        gen = LanceDBDataGenerator(seed=31)
        store = _make_store(tmp_path)
        facts = gen.facts(100_000)
        for i in range(0, 100_000, 1_000):
            store.upsert_facts(facts[i : i + 1_000])
        mem_after = get_memory_mb()
        delta = mem_after - mem_before
        print(f"\n[memory] 100k ingest: +{delta:.1f} MB")
        assert delta < 500, f"Memory grew {delta:.1f} MB — possible leak"


# ---------------------------------------------------------------------------
# Phase 1d — Idempotency
# ---------------------------------------------------------------------------


class TestIngestionIdempotency:

    def test_double_upsert_same_ids_no_duplicate_rows(self, tmp_path):
        """Upserting the same 1k rows twice yields exactly 1k rows."""
        gen = LanceDBDataGenerator(seed=40)
        store = _make_store(tmp_path)
        facts = gen.facts(1_000)
        store.upsert_facts(facts)
        store.upsert_facts(facts)  # exact same data
        assert _row_count(store) == 1_000

    def test_update_existing_record_changes_text(self, tmp_path):
        """Re-upsert with same id but different text updates in place."""
        store = _make_store(tmp_path)
        vec = [0.1] * 768
        store.upsert_facts(
            [
                {
                    "id": 1,
                    "vector": vec,
                    "metadata": {"text": "original text", "hemisphere_tag": "safe"},
                }
            ]
        )
        store.upsert_facts(
            [
                {
                    "id": 1,
                    "vector": vec,
                    "metadata": {"text": "updated text", "hemisphere_tag": "safe"},
                }
            ]
        )
        assert _row_count(store) == 1
        results = store.search(vec, limit=1)
        assert results[0]["metadata"]["text"] == "updated text"

    @pytest.mark.slow
    def test_idempotent_100k_double_upsert(self, tmp_path):
        """100k rows upserted twice → still exactly 100k rows."""
        gen = LanceDBDataGenerator(seed=41)
        store = _make_store(tmp_path)
        facts = gen.facts(100_000)
        for i in range(0, 100_000, 2_000):
            store.upsert_facts(facts[i : i + 2_000])
        count_after_first = _row_count(store)
        # Second pass — same IDs
        for i in range(0, 100_000, 2_000):
            store.upsert_facts(facts[i : i + 2_000])
        count_after_second = _row_count(store)
        assert count_after_first == 100_000
        assert count_after_second == 100_000, "Duplicate rows inserted on second upsert"

    def test_partial_overlap_upsert(self, tmp_path):
        """Batch with 500 new + 500 existing IDs → 1500 total rows."""
        gen = LanceDBDataGenerator(seed=42)
        store = _make_store(tmp_path)
        facts_a = gen.facts(1_000, id_offset=0)
        facts_b = gen.facts(1_000, id_offset=500)  # IDs 500-1499 (overlap with 500-999)
        store.upsert_facts(facts_a)  # 0-999
        store.upsert_facts(facts_b)  # 500-1499
        assert _row_count(store) == 1_500


# ---------------------------------------------------------------------------
# Phase 1e — Index creation
# ---------------------------------------------------------------------------


class TestIndexCreation:

    def test_no_index_below_threshold(self, tmp_path):
        """With < 256 rows, _ensure_index() skips index creation silently."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=50)
        store.upsert_facts(gen.facts(100))
        # If we get here without exception, the skip-below-threshold logic works
        assert _row_count(store) == 100

    def test_index_created_above_threshold(self, tmp_path):
        """After 256+ rows, create_index() is called without error."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=51)
        # Ingest in one shot past threshold
        store.upsert_facts(gen.facts(300))
        # Manually call to confirm it doesn't raise
        store._ensure_index()
        assert _row_count(store) == 300

    def test_index_rebuild_is_idempotent(self, tmp_path):
        """Calling _ensure_index() multiple times does not raise."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=52)
        store.upsert_facts(gen.facts(500))
        for _ in range(3):
            store._ensure_index()  # should not raise


# ---------------------------------------------------------------------------
# Phase 1f — FastEmbed end-to-end ingestion
# ---------------------------------------------------------------------------


class TestFastEmbedIngestion:

    @pytest.mark.fastembed
    def test_fastembed_1k_ingestion_zero_errors(self, tmp_path):
        """Embed 1k texts with FastEmbed, ingest all, verify row count."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        gen = LanceDBDataGenerator(seed=60)
        texts = gen.texts(1_000)
        vectors = gen.vectors_fastembed(texts, batch_size=256)
        assert vectors.shape == (1_000, 768)

        store = _make_store(tmp_path)
        facts = gen.facts(1_000, vectors=vectors, texts=texts)
        store.upsert_facts(facts)
        assert _row_count(store) == 1_000

    @pytest.mark.fastembed
    def test_fastembed_vectors_are_unit_normalized(self, tmp_path):
        """FastEmbed output vectors should be near unit-length (L2 ≈ 1.0)."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        gen = LanceDBDataGenerator(seed=61)
        texts = gen.texts(100)
        vectors = gen.vectors_fastembed(texts, batch_size=100)
        norms = np.linalg.norm(vectors, axis=1)
        assert np.allclose(
            norms, 1.0, atol=0.05
        ), f"Vectors not unit-normalized: min={norms.min():.4f} max={norms.max():.4f}"

    @pytest.mark.fastembed
    def test_fastembed_dimension_is_768(self, tmp_path):
        """FastEmbed nomic-embed-text-v1.5 must produce 768-dim vectors."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        gen = LanceDBDataGenerator(seed=62)
        texts = gen.texts(10)
        vectors = gen.vectors_fastembed(texts, batch_size=10)
        assert vectors.shape[1] == 768

    @pytest.mark.slow
    @pytest.mark.fastembed
    def test_fastembed_10k_ingestion_throughput(self, tmp_path):
        """Embed + ingest 10k texts, report throughput for both stages."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        gen = LanceDBDataGenerator(seed=63)
        texts = gen.texts(10_000)

        t_embed0 = time.perf_counter()
        vectors = gen.vectors_fastembed(texts, batch_size=256)
        t_embed = time.perf_counter() - t_embed0
        embed_tps = 10_000 / t_embed

        store = _make_store(tmp_path)
        facts = gen.facts(10_000, vectors=vectors, texts=texts)

        t_ingest0 = time.perf_counter()
        store.upsert_facts(facts)
        t_ingest = time.perf_counter() - t_ingest0
        ingest_rps = 10_000 / t_ingest

        print(
            f"\n[fastembed+lance] embed={embed_tps:.0f} text/s "
            f"({t_embed:.2f}s), ingest={ingest_rps:.0f} rows/s ({t_ingest:.2f}s)"
        )
        assert _row_count(store) == 10_000

    @pytest.mark.slow
    @pytest.mark.fastembed
    def test_fastembed_100k_full_pipeline(self, tmp_path):
        """Full pipeline: generate → embed (FastEmbed) → ingest (LanceDB) at 100k scale."""
        pytest.importorskip("fastembed", reason="fastembed not installed")
        gen = LanceDBDataGenerator(seed=64)
        texts = gen.texts(100_000)

        t0 = time.perf_counter()
        vectors = gen.vectors_fastembed(texts, batch_size=256)
        embed_time = time.perf_counter() - t0
        print(f"\n[fastembed 100k] embed: {embed_time:.1f}s ({100_000/embed_time:.0f} text/s)")

        store = _make_store(tmp_path)
        facts = gen.facts(100_000, vectors=vectors, texts=texts)

        t1 = time.perf_counter()
        for i in range(0, 100_000, 1_000):
            store.upsert_facts(facts[i : i + 1_000])
        ingest_time = time.perf_counter() - t1
        print(f"[lancedb 100k] ingest: {ingest_time:.1f}s ({100_000/ingest_time:.0f} rows/s)")

        assert _row_count(store) == 100_000


# ---------------------------------------------------------------------------
# Phase 1g — Progressive ingestion
# ---------------------------------------------------------------------------


class TestProgressiveIngestion:

    def test_progressive_build_row_counts_are_cumulative(self, tmp_path):
        """Row count grows correctly as we add batches progressively."""
        gen = LanceDBDataGenerator(seed=70)
        store = _make_store(tmp_path)
        expected = 0
        for step, size in enumerate([100, 200, 300, 400]):
            store.upsert_facts(gen.facts(size, id_offset=expected))
            expected += size
            assert _row_count(store) == expected, f"After step {step}: expected {expected}"

    @pytest.mark.slow
    def test_progressive_100k_search_remains_accurate(self, tmp_path):
        """As the store grows 0→100k, known vectors stay retrievable."""
        gen = LanceDBDataGenerator(seed=71)
        store = _make_store(tmp_path)

        # Plant a known vector at id=0
        known_vec = gen.vectors_random(1, dims=768)[0].tolist()
        store.upsert_facts(
            [
                {
                    "id": 0,
                    "vector": known_vec,
                    "metadata": {"text": "known anchor", "hemisphere_tag": "safe"},
                }
            ]
        )

        # Grow the store with unrelated vectors
        facts = gen.facts(99_999, id_offset=1)
        for i in range(0, 99_999, 1_000):
            store.upsert_facts(facts[i : i + 1_000])

        # The known vector should still be top-1
        results = store.search(known_vec, limit=1)
        assert len(results) > 0
        assert results[0]["id"] == 0, "Known anchor vector not returned as top-1"
        assert results[0]["score"] > 0.99, f"Score degraded: {results[0]['score']:.4f}"
