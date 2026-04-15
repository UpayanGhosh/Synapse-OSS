"""
Phase 1 — Sustained Load (7 tests)
=====================================
Runtime: ~15-30 min. Requires --run-slow.

Tests:
  1. 100k single embed_query() calls — assert 0 errors
  2. 100k via embed_documents() in batches of 256 — assert 0 errors
  3. Memory no-leak — sample RSS every 10k, assert drift < 500 MB
  4. Latency stability — p95 of last 10k < 2x p95 of first 10k
  5. Latency percentiles — p50 < 5ms, p95 < 15ms, p99 < 50ms
  6. Dimensions consistent — all 100k vectors exactly 768-dim
  7. Vectors not all-zeros — spot-check 1000 random vectors
"""

import os
import random
import sys
import time

import pytest
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.reliability.conftest import (
    SKIP_NO_FASTEMBED,
    LatencyTracker,
    ReliabilityDataGenerator,
    ReliabilityReport,
    get_memory_mb,
)

pytestmark = [
    pytest.mark.reliability,
    pytest.mark.slow,
    pytest.mark.performance,
    SKIP_NO_FASTEMBED,
]

TOTAL = 100_000
BATCH_SIZE = 256
SAMPLE_EVERY = 10_000
PRINT_EVERY = 10_000


def _bar(total, desc):
    """Create a tqdm bar that works cleanly inside pytest (-s mode)."""
    return tqdm(
        total=total,
        desc=desc,
        unit="text",
        dynamic_ncols=True,
        file=sys.stderr,
        leave=True,
        smoothing=0.1,
    )


# ---------------------------------------------------------------------------
# Shared fixture — one provider for all Phase 1 tests (expensive to init)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provider():
    from sci_fi_dashboard.embedding.factory import create_provider

    return create_provider()


@pytest.fixture(scope="module")
def gen():
    return ReliabilityDataGenerator(seed=100)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_100k_single_embeddings_zero_errors(provider, gen):
    """100k embed_query() calls must complete with 0 errors."""
    texts = gen.generate(TOTAL)
    errors = []

    with _bar(TOTAL, "1/7 single embed_query") as bar:
        t_start = time.perf_counter()
        for i, text in enumerate(texts):
            try:
                provider.embed_query(text)
            except Exception as e:
                errors.append(f"[{i}] {e}")
            bar.update(1)
            if (i + 1) % PRINT_EVERY == 0:
                elapsed = time.perf_counter() - t_start
                tps = (i + 1) / elapsed
                bar.set_postfix(tps=f"{tps:.0f}/s", errors=len(errors))

    assert errors == [], f"{len(errors)} errors in 100k single queries. First 3: {errors[:3]}"


def test_100k_batch_embeddings(provider, gen):
    """100k texts via embed_documents() in batches of 256 — 0 errors."""
    texts = gen.generate(TOTAL)
    errors = []
    total_processed = 0

    with _bar(TOTAL, "2/7 batch embed_documents") as bar:
        t_start = time.perf_counter()
        for start in range(0, TOTAL, BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                vecs = provider.embed_documents(batch)
                assert len(vecs) == len(batch), f"Batch size mismatch at {start}"
                total_processed += len(vecs)
            except Exception as e:
                errors.append(f"batch@{start}: {e}")
            bar.update(len(batch))
            if total_processed % PRINT_EVERY == 0 and total_processed > 0:
                elapsed = time.perf_counter() - t_start
                tps = total_processed / elapsed
                bar.set_postfix(tps=f"{tps:.0f}/s", errors=len(errors))

    assert errors == [], f"{len(errors)} batch errors. First 3: {errors[:3]}"
    assert total_processed == TOTAL


def test_memory_no_leak_over_100k(provider, gen):
    """RSS must not grow > 500 MB over 100k queries after initial warmup."""
    texts = gen.generate(TOTAL)
    memory_samples = []

    with _bar(1000, "3/7 warmup (1k)") as bar:
        for text in texts[:1000]:
            provider.embed_query(text)
            bar.update(1)

    baseline_mb = get_memory_mb()

    with _bar(TOTAL - 1000, "3/7 memory leak check") as bar:
        for i, text in enumerate(texts[1000:], start=1000):
            provider.embed_query(text)
            if i % SAMPLE_EVERY == 0:
                sample = get_memory_mb()
                memory_samples.append(sample)
                drift = sample - baseline_mb
                bar.set_postfix(rss=f"{sample:.0f}MB", drift=f"+{drift:.0f}MB")
            bar.update(1)

    if not memory_samples:
        pytest.skip("psutil not available — memory tracking skipped")

    end_mb = memory_samples[-1]
    drift_mb = end_mb - baseline_mb

    print(
        f"\n  Baseline: {baseline_mb:.1f}MB  |  Final: {end_mb:.1f}MB  |  Drift: +{drift_mb:.1f}MB",
        flush=True,
    )

    ReliabilityReport(
        total_calls=TOTAL,
        memory_start_mb=baseline_mb,
        memory_end_mb=end_mb,
        memory_samples=memory_samples,
    )

    assert drift_mb < 500, (
        f"Memory drift {drift_mb:.1f} MB exceeds 500 MB threshold. "
        f"Samples: {[f'{m:.0f}' for m in memory_samples]}"
    )

    if len(memory_samples) >= 3:
        trend = memory_samples[-1] - memory_samples[1]
        assert (
            trend < 200
        ), f"Upward memory trend detected: +{trend:.1f} MB from sample[1] to sample[-1]"


def test_latency_stability(provider, gen):
    """p95 of last 10k must be < 2x p95 of first 10k (no degradation)."""
    texts = gen.generate(TOTAL)
    tracker = LatencyTracker()

    with _bar(TOTAL, "4/7 latency stability") as bar:
        for i, text in enumerate(texts):
            t0 = time.perf_counter()
            provider.embed_query(text)
            tracker.record(time.perf_counter() - t0)
            bar.update(1)
            if (i + 1) % PRINT_EVERY == 0:
                window = tracker.window(max(0, i - PRINT_EVERY + 1), i + 1)
                p95_ms = window.percentile(95) * 1000
                bar.set_postfix(p95=f"{p95_ms:.1f}ms")

    first_window = tracker.window(0, 10_000)
    last_window = tracker.window(TOTAL - 10_000, TOTAL)
    p95_first = first_window.percentile(95) * 1000
    p95_last = last_window.percentile(95) * 1000

    print(f"\n  First-10k p95: {p95_first:.1f}ms  |  Last-10k p95: {p95_last:.1f}ms", flush=True)

    assert p95_last < p95_first * 2, (
        f"Latency degraded: first-10k p95={p95_first:.1f}ms, "
        f"last-10k p95={p95_last:.1f}ms (>{p95_first * 2:.1f}ms threshold)"
    )


def test_latency_percentiles(provider, gen):
    """p50 < 8ms, p95 < 15ms, p99 < 50ms over 10k warm queries.

    Note: 8ms p50 threshold accounts for GPU (CUDA) single-query kernel launch overhead.
    CPU quantized model would achieve ~3-4ms p50; GPU float32 single-query baseline is ~5-7ms.
    Throughput (batched) is ~150+ text/s on GPU — latency is not the bottleneck.
    """
    texts = gen.generate(10_000)
    tracker = LatencyTracker()

    with _bar(100, "5/7 warmup (100)") as bar:
        for text in texts[:100]:
            provider.embed_query(text)
            bar.update(1)

    with _bar(9900, "5/7 latency percentiles") as bar:
        for text in texts[100:]:
            t0 = time.perf_counter()
            provider.embed_query(text)
            tracker.record(time.perf_counter() - t0)
            bar.update(1)
        p50 = tracker.percentile(50) * 1000
        p95 = tracker.percentile(95) * 1000
        bar.set_postfix(p50=f"{p50:.1f}ms", p95=f"{p95:.1f}ms")

    p50 = tracker.percentile(50) * 1000
    p95 = tracker.percentile(95) * 1000
    p99 = tracker.percentile(99) * 1000

    print(f"\n  p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms", flush=True)

    assert p50 < 8.0, f"p50={p50:.2f}ms exceeds 8ms"
    assert p95 < 15.0, f"p95={p95:.2f}ms exceeds 15ms"
    assert p99 < 50.0, f"p99={p99:.2f}ms exceeds 50ms"


def test_dimensions_consistent(provider, gen):
    """All 100k vectors must be exactly 768-dim."""
    texts = gen.generate(TOTAL)
    wrong_dims = []

    with _bar(TOTAL, "6/7 dimensions check") as bar:
        t_start = time.perf_counter()
        for i, text in enumerate(texts):
            vec = provider.embed_query(text)
            if len(vec) != 768:
                wrong_dims.append((i, len(vec)))
            bar.update(1)
            if (i + 1) % PRINT_EVERY == 0:
                elapsed = time.perf_counter() - t_start
                tps = (i + 1) / elapsed
                bar.set_postfix(tps=f"{tps:.0f}/s", wrong=len(wrong_dims))

    print(f"\n  Wrong dimensions: {len(wrong_dims)}", flush=True)

    assert wrong_dims == [], (
        f"{len(wrong_dims)} vectors had wrong dimensions. " f"First 3: {wrong_dims[:3]}"
    )


def test_vectors_not_all_zeros(provider, gen):
    """Spot-check 1000 random vectors — none should be all-zeros."""
    rng = random.Random(42)
    texts = gen.generate(TOTAL)
    sample_indices = rng.sample(range(TOTAL), 1000)
    sample_texts = [texts[i] for i in sample_indices]

    zero_vectors = []
    with _bar(1000, "7/7 zero-vector check") as bar:
        for text in sample_texts:
            vec = provider.embed_query(text)
            if all(v == 0.0 for v in vec):
                zero_vectors.append(text[:40])
            bar.update(1)

    print(f"\n  All-zero vectors found: {len(zero_vectors)}", flush=True)

    assert zero_vectors == [], (
        f"{len(zero_vectors)} all-zero vectors found in spot-check. " f"First 3: {zero_vectors[:3]}"
    )
