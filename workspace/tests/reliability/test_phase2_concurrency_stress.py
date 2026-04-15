"""
Phase 2 — Concurrency Stress (8 tests)
=======================================
Runtime: ~2-5 min. Requires --run-slow.

Tests:
  1. 2 workers x 10k queries (mirrors real gateway)
  2. 2 query threads + 1 batch ingest thread (mixed workload)
  3. 10 threads x 1k queries (exceeds production concurrency)
  4. Lazy init race — 10 threads hit embed_query() simultaneously via Barrier
  5. Factory singleton race — reset_provider() then 10 threads call get_provider()
  6. Mixed query + embed_documents from multiple threads
  7. No result corruption — compare against pre-computed expected vectors
  8. Recovery after failure — mock first call to fail, verify subsequent calls succeed
"""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.reliability.conftest import (
    SKIP_NO_FASTEMBED,
    LatencyTracker,
    ReliabilityDataGenerator,
)

pytestmark = [pytest.mark.reliability, pytest.mark.slow, SKIP_NO_FASTEMBED]

QUERIES_PER_WORKER = 10_000
HIGH_CONTENTION_QUERIES = 1_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_provider():
    """Always create a fresh provider (not the singleton) for isolation."""
    from sci_fi_dashboard.embedding.factory import create_provider

    return create_provider()


def _embed_n(provider, texts, tracker: LatencyTracker, errors: list):
    """Embed texts one-by-one, record latency, collect errors."""
    for text in texts:
        t0 = time.perf_counter()
        try:
            vec = provider.embed_query(text)
            assert len(vec) == 768
        except Exception as e:
            errors.append(str(e))
        finally:
            tracker.record(time.perf_counter() - t0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_2_workers_parallel():
    """2 threads x 10k queries — mirrors the real gateway (2 MessageWorkers)."""
    gen = ReliabilityDataGenerator(seed=1)
    all_texts = gen.generate(QUERIES_PER_WORKER * 2)
    provider = fresh_provider()
    tracker = LatencyTracker()
    errors = []

    def worker(texts):
        _embed_n(provider, texts, tracker, errors)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(worker, all_texts[:QUERIES_PER_WORKER])
        f2 = ex.submit(worker, all_texts[QUERIES_PER_WORKER:])
        f1.result()
        f2.result()

    assert errors == [], f"Errors from 2-worker parallel: {errors[:5]}"
    assert tracker.count == QUERIES_PER_WORKER * 2


def test_2_workers_plus_ingest():
    """2 query threads + 1 batch ingest thread — mixed workload."""
    gen = ReliabilityDataGenerator(seed=2)
    query_texts = gen.generate(QUERIES_PER_WORKER)
    batch_texts = gen.generate(500)  # 500 docs for ingest
    provider = fresh_provider()
    tracker = LatencyTracker()
    errors = []

    def query_worker(texts):
        _embed_n(provider, texts, tracker, errors)

    def ingest_worker():
        for i in range(0, len(batch_texts), 32):
            chunk = batch_texts[i : i + 32]
            t0 = time.perf_counter()
            try:
                vecs = provider.embed_documents(chunk)
                assert len(vecs) == len(chunk)
            except Exception as e:
                errors.append(f"ingest: {e}")
            finally:
                tracker.record(time.perf_counter() - t0)

    with ThreadPoolExecutor(max_workers=3) as ex:
        f1 = ex.submit(query_worker, query_texts[: QUERIES_PER_WORKER // 2])
        f2 = ex.submit(query_worker, query_texts[QUERIES_PER_WORKER // 2 :])
        f3 = ex.submit(ingest_worker)
        for f in [f1, f2, f3]:
            f.result()

    assert errors == [], f"Errors from mixed workload: {errors[:5]}"


def test_10_threads_high_contention():
    """10 threads x 1k queries — exceeds production concurrency."""
    gen = ReliabilityDataGenerator(seed=3)
    all_texts = gen.generate(HIGH_CONTENTION_QUERIES * 10)
    provider = fresh_provider()
    tracker = LatencyTracker()
    errors = []

    slices = [
        all_texts[i * HIGH_CONTENTION_QUERIES : (i + 1) * HIGH_CONTENTION_QUERIES]
        for i in range(10)
    ]

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_embed_n, provider, sl, tracker, errors) for sl in slices]
        for f in as_completed(futures):
            f.result()

    assert errors == [], f"Errors from 10-thread contention: {errors[:5]}"
    assert tracker.count == HIGH_CONTENTION_QUERIES * 10


def test_concurrent_lazy_init_race():
    """10 threads hit embed_query() simultaneously on a brand-new provider.

    This is a regression test for Fix 2 (_embedder_lock in fastembed_provider.py).
    Without the lock, _embedder could be initialized multiple times, causing either
    duplicate work or a corrupt reference.
    """
    from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

    # Fresh provider — _embedder is None
    provider = FastEmbedProvider()

    errors = []
    results = {}
    barrier = threading.Barrier(10)

    def worker(idx):
        barrier.wait()  # all threads start simultaneously
        try:
            vec = provider.embed_query("hello world init race")
            results[idx] = vec
        except Exception as e:
            errors.append(f"thread {idx}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Lazy init race errors: {errors}"
    assert len(results) == 10
    # All threads must get the same result (deterministic)
    vecs = list(results.values())
    for v in vecs[1:]:
        for j, (a, b) in enumerate(zip(vecs[0], v, strict=False)):
            assert abs(a - b) < 1e-7, f"Dim {j} differs across concurrent init threads"


def test_factory_singleton_race():
    """reset_provider() then 10 threads simultaneously call get_provider().

    Regression test for Fix 1 (threading.Lock in factory.py).
    Without the lock, multiple providers could be created and the last writer wins,
    causing inconsistency.
    """
    from sci_fi_dashboard.embedding import factory

    factory.reset_provider()

    errors = []
    provider_ids = {}
    barrier = threading.Barrier(10)

    def worker(idx):
        barrier.wait()
        try:
            p = factory.get_provider()
            provider_ids[idx] = id(p)
        except Exception as e:
            errors.append(f"thread {idx}: {e}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Singleton race errors: {errors}"
    # All threads must see the exact same object
    ids = set(provider_ids.values())
    assert len(ids) == 1, f"Multiple providers created: {len(ids)} distinct objects"


def test_mixed_query_and_document():
    """Interleave embed_query + embed_documents from multiple threads."""
    gen = ReliabilityDataGenerator(seed=4)
    texts = gen.generate(2000)
    provider = fresh_provider()
    errors = []
    results = []
    lock = threading.Lock()

    def query_thread():
        for t in texts[:1000]:
            try:
                vec = provider.embed_query(t)
                with lock:
                    results.append(len(vec))
            except Exception as e:
                errors.append(f"query: {e}")

    def doc_thread():
        for i in range(0, 1000, 50):
            try:
                vecs = provider.embed_documents(texts[1000 + i : 1050 + i])
                with lock:
                    results.extend(len(v) for v in vecs)
            except Exception as e:
                errors.append(f"doc: {e}")

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [
            ex.submit(query_thread),
            ex.submit(doc_thread),
            ex.submit(query_thread),
            ex.submit(doc_thread),
        ]
        for f in futures:
            f.result()

    assert errors == [], f"Mixed query/doc errors: {errors[:5]}"
    assert all(r == 768 for r in results), "Some vectors had wrong dimensions"


def test_no_result_corruption():
    """Pre-compute expected vectors; verify exact match under concurrency."""
    gen = ReliabilityDataGenerator(seed=5)
    texts = gen.generate(100)
    provider = fresh_provider()

    # Pre-compute ground truth (single-threaded)
    expected = {t: provider.embed_query(t) for t in texts}

    errors = []
    mismatches = []

    def verify_worker(subset):
        for text in subset:
            vec = provider.embed_query(text)
            exp = expected[text]
            for j, (a, b) in enumerate(zip(vec, exp, strict=False)):
                if abs(a - b) > 1e-7:
                    mismatches.append(f"text={text[:20]!r} dim={j} got={a} exp={b}")
                    return

    # 5 threads all verifying the same 100 texts
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(verify_worker, texts) for _ in range(5)]
        for f in futures:
            f.result()

    assert errors == [], f"Errors: {errors[:3]}"
    assert mismatches == [], f"Result corruptions: {mismatches[:3]}"


def test_recovery_after_failure():
    """Mock first call to fail; verify subsequent calls succeed."""
    from unittest.mock import patch

    provider = fresh_provider()
    call_count = {"n": 0}
    original_embed_query = provider.embed_query

    def flaky_embed_query(text):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("simulated transient failure")
        return original_embed_query(text)

    with patch.object(provider, "embed_query", side_effect=flaky_embed_query):
        with pytest.raises(ConnectionError):
            provider.embed_query("first call fails")

        # Remaining calls must work
        errors = []
        for i in range(50):
            try:
                vec = provider.embed_query(f"recovery call {i}")
                assert len(vec) == 768
            except Exception as e:
                errors.append(str(e))

    assert errors == [], f"Recovery failed after transient error: {errors[:3]}"
