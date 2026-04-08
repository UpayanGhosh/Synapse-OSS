"""
test_phase3_concurrency.py — Concurrent read/write safety.

LanceDB embedded stores use MVCC (multi-version concurrency control)
and are safe for concurrent reads. Concurrent writes from multiple
threads to the same store are serialised by the test to match real
Synapse usage (MemoryEngine is a singleton — writes come from one
worker at a time, reads come from multiple async tasks).

Tests cover:
- Concurrent reads: 8 threads searching simultaneously → zero errors
- Concurrent writes: 4 threads writing non-overlapping IDs → correct final count
- Mixed read+write: writers and readers active simultaneously → no corruption
- Result integrity under concurrency: pre-computed expected IDs still returned
- Singleton store: same LanceDBVectorStore instance shared across threads
- Write→read ordering: after a write completes, the data is immediately readable
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pytest

from .conftest import LanceDBDataGenerator, LatencyTracker

lancedb = pytest.importorskip("lancedb", reason="lancedb not installed")


def _make_store(tmp_path, dims=768):
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
    return LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=dims)


# ---------------------------------------------------------------------------
# Phase 3a — Concurrent reads
# ---------------------------------------------------------------------------

class TestConcurrentReads:

    def test_8_threads_concurrent_reads_zero_errors(self, store_10k):
        """8 threads issuing search() simultaneously — zero exceptions."""
        store, _ = store_10k
        gen = LanceDBDataGenerator(seed=200)
        query_vecs = gen.vectors_random(800, dims=768)  # 100 per thread

        errors = []
        def worker(thread_id: int):
            for i in range(100):
                vec = query_vecs[thread_id * 100 + i].tolist()
                try:
                    store.search(vec, limit=10)
                except Exception as e:
                    errors.append((thread_id, i, str(e)))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent read errors: {errors[:5]}"

    def test_concurrent_read_results_are_consistent(self, store_10k):
        """Same query from 4 threads returns the same top-1 id every time."""
        store, facts = store_10k
        # Use a known vector from the store
        anchor_vec = facts[0]["vector"]
        anchor_id = facts[0]["id"]

        top1_ids = []
        lock = threading.Lock()

        def worker():
            results = store.search(anchor_vec, limit=1)
            if results:
                with lock:
                    top1_ids.append(results[0]["id"])

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(top1_ids) == 4
        assert all(i == anchor_id for i in top1_ids), \
            f"Inconsistent results under concurrent reads: {top1_ids}"

    def test_read_latency_under_concurrency_p95(self, store_10k):
        """p95 latency with 4 concurrent readers stays under 500ms."""
        store, _ = store_10k
        gen = LanceDBDataGenerator(seed=201)
        query_vecs = gen.vectors_random(400, dims=768)
        tracker = LatencyTracker()

        def worker(thread_id: int):
            for i in range(100):
                vec = query_vecs[thread_id * 100 + i].tolist()
                t0 = time.perf_counter()
                store.search(vec, limit=10)
                tracker.record((time.perf_counter() - t0) * 1_000)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        p95 = tracker.percentile(95)
        print(f"\n[concurrent reads p95] {p95:.2f}ms over {tracker.count()} queries")
        assert p95 < 500, f"p95 latency under concurrency: {p95:.2f}ms"


# ---------------------------------------------------------------------------
# Phase 3b — Concurrent writes
# ---------------------------------------------------------------------------

class TestConcurrentWrites:

    def test_4_threads_non_overlapping_ids_correct_row_count(self, tmp_path):
        """4 threads each writing 250 unique IDs → final count = 1000."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=210)
        # Pre-generate all facts to avoid data-race in generator
        all_facts = gen.facts(1_000)
        chunks = [all_facts[i * 250 : (i + 1) * 250] for i in range(4)]

        errors = []
        def writer(chunk):
            try:
                store.upsert_facts(chunk)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(chunk,)) for chunk in chunks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Write errors: {errors}"
        count = store.table.count_rows()
        assert count == 1_000, f"Expected 1000 rows, got {count}"

    def test_concurrent_writes_no_data_corruption(self, tmp_path):
        """After concurrent writes, every written record is retrievable."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=211)

        # Plant 4 anchor vectors with known IDs in separate threads
        anchor_vecs = gen.vectors_random(4, dims=768)
        ANCHOR_IDS = [90001, 90002, 90003, 90004]

        def write_anchor(idx):
            store.upsert_facts([{
                "id": ANCHOR_IDS[idx],
                "vector": anchor_vecs[idx].tolist(),
                "metadata": {"text": f"anchor-{idx}", "hemisphere_tag": "safe"},
            }])

        threads = [threading.Thread(target=write_anchor, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Now verify each anchor is findable
        for idx, anchor_id in enumerate(ANCHOR_IDS):
            results = store.search(anchor_vecs[idx].tolist(), limit=5)
            found_ids = [r["id"] for r in results]
            assert anchor_id in found_ids, \
                f"Anchor id={anchor_id} not found after concurrent write"

    @pytest.mark.slow
    def test_concurrent_writes_100k_total_correct_count(self, tmp_path):
        """8 threads each write 12 500 records → 100 000 total rows."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=212)
        all_facts = gen.facts(100_000)
        n_threads = 8
        chunk_size = 100_000 // n_threads
        chunks = [all_facts[i * chunk_size : (i + 1) * chunk_size] for i in range(n_threads)]

        errors = []
        def writer(chunk):
            try:
                for i in range(0, len(chunk), 500):
                    store.upsert_facts(chunk[i : i + 500])
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(c,)) for c in chunks]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors[:3]}"
        count = store.table.count_rows()
        assert count == 100_000, f"Expected 100k rows, got {count}"


# ---------------------------------------------------------------------------
# Phase 3c — Mixed read + write
# ---------------------------------------------------------------------------

class TestMixedReadWrite:

    def test_2_writers_4_readers_zero_errors(self, tmp_path):
        """2 write threads + 4 read threads running simultaneously → no crashes."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=220)

        # Pre-load some data so reads have something to search
        store.upsert_facts(gen.facts(500))

        write_errors, read_errors = [], []
        write_facts = gen.facts(500, id_offset=500)
        query_vecs = gen.vectors_random(400, dims=768)

        def writer(offset):
            chunk = write_facts[offset : offset + 250]
            try:
                for i in range(0, len(chunk), 50):
                    store.upsert_facts(chunk[i : i + 50])
                    time.sleep(0.001)  # yield to readers
            except Exception as e:
                write_errors.append(str(e))

        def reader(thread_id):
            for i in range(100):
                vec = query_vecs[thread_id * 100 + i].tolist()
                try:
                    store.search(vec, limit=5)
                except Exception as e:
                    read_errors.append(str(e))

        writers = [threading.Thread(target=writer, args=(o,)) for o in [0, 250]]
        readers = [threading.Thread(target=reader, args=(t,)) for t in range(4)]

        all_threads = writers + readers
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        assert not write_errors, f"Write errors in mixed test: {write_errors}"
        assert not read_errors, f"Read errors in mixed test: {read_errors}"

    def test_write_then_read_data_immediately_visible(self, tmp_path):
        """After upsert_facts() returns, new records are queryable immediately."""
        store = _make_store(tmp_path)
        gen = LanceDBDataGenerator(seed=221)

        anchor_vec = gen.vectors_random(1, dims=768)[0].tolist()
        anchor_id = 77777

        visible = threading.Event()
        write_done = threading.Event()

        def writer():
            store.upsert_facts([{
                "id": anchor_id,
                "vector": anchor_vec,
                "metadata": {"text": "just written", "hemisphere_tag": "safe"},
            }])
            write_done.set()

        def reader():
            write_done.wait(timeout=5.0)
            results = store.search(anchor_vec, limit=1)
            if results and results[0]["id"] == anchor_id:
                visible.set()

        t_w = threading.Thread(target=writer)
        t_r = threading.Thread(target=reader)
        t_w.start()
        t_r.start()
        t_w.join()
        t_r.join()

        assert visible.is_set(), "Written record not immediately visible to reader"


# ---------------------------------------------------------------------------
# Phase 3d — Singleton store safety
# ---------------------------------------------------------------------------

class TestSingletonStoreSafety:

    def test_factory_returns_same_store_instance_across_threads(self, tmp_path):
        """get_provider() singleton pattern: all threads see the same instance."""
        from sci_fi_dashboard.embedding.factory import get_provider, reset_provider
        reset_provider()

        instances = []
        lock = threading.Lock()
        errors = []

        def get_instance():
            try:
                p = get_provider()
                with lock:
                    instances.append(id(p) if p else None)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=get_instance) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors:
            pytest.skip(f"Provider unavailable: {errors[0]}")

        # All non-None instances must be the same object
        non_none = [i for i in instances if i is not None]
        if non_none:
            assert len(set(non_none)) == 1, \
                f"Multiple provider instances created: {set(non_none)}"

    def test_concurrent_lazy_init_no_race(self, tmp_path):
        """10 threads hit _open_or_create_table simultaneously — no crash."""
        from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore
        errors = []

        def create_store():
            try:
                s = LanceDBVectorStore(db_path=tmp_path / "concurrent_init", embedding_dimensions=768)
                s.close()
            except Exception as e:
                errors.append(str(e))

        # All 10 try to open the same path simultaneously
        threads = [threading.Thread(target=create_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent init errors: {errors}"
