"""
Phase 4 — FastEmbed Provider Reliability Suite
================================================
Validates FastEmbed (ONNX, in-process) embedding provider across every dimension that matters.

Run tests:
    cd workspace && pytest tests/reliability/test_phase4_provider_comparison.py -v --run-slow -s

Metrics covered:
  1.  Cold start latency      — first embed after process start
  2.  Warm latency (p50/p95/p99) — 1k, 5k texts
  3.  Throughput              — texts/sec (single + batch)
  4.  Batch throughput        — batch of 64, 256
  5.  Memory footprint        — RSS before vs after warmup
  6.  Error rate over 10k     — 0% required
  7.  Concurrency             — 4 threads x 1k
  8.  Determinism             — same input → same vector (100 repeats)
  9.  Vector drift under load — vectors don't change between call 1 and call 10k
  10. Edge cases              — empty/unicode/long texts without error
  11. REPORT                  — final formatted table of all metrics
"""

import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.reliability.conftest import (
    SKIP_NO_FASTEMBED,
    LatencyTracker,
    ReliabilityDataGenerator,
    get_memory_mb,
)

pytestmark = [pytest.mark.reliability, SKIP_NO_FASTEMBED]

# ---------------------------------------------------------------------------
# Shared report (module-level accumulator)
# ---------------------------------------------------------------------------


@dataclass
class ProviderMetrics:
    name: str
    cold_start_ms: float | None = None
    p50_1k_ms: float | None = None
    p95_1k_ms: float | None = None
    p99_1k_ms: float | None = None
    p50_5k_ms: float | None = None
    p95_5k_ms: float | None = None
    throughput_single: float | None = None  # texts/sec
    throughput_batch64: float | None = None  # texts/sec (uniform-length texts)
    throughput_batch256: float | None = None
    memory_mb: float | None = None
    error_rate_10k: float | None = None
    concurrency_4t_1k_ms: float | None = None  # total wall time
    is_deterministic: bool = False
    vector_drift: float | None = None  # L2 diff between call 1 and call 10k
    notes: list[str] = field(default_factory=list)


_REPORT: dict[str, ProviderMetrics] = {}


def _get_metrics(name: str) -> ProviderMetrics:
    if name not in _REPORT:
        _REPORT[name] = ProviderMetrics(name=name)
    return _REPORT[name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fastembed():
    from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

    return FastEmbedProvider()


@pytest.fixture(scope="module")
def gen():
    return ReliabilityDataGenerator(seed=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def l2_dist(a: list, b: list) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))


def measure_latencies(provider, texts: list[str]) -> LatencyTracker:
    tracker = LatencyTracker()
    for text in texts:
        t0 = time.perf_counter()
        provider.embed_query(text)
        tracker.record(time.perf_counter() - t0)
    return tracker


# ---------------------------------------------------------------------------
# 1. Cold start latency
# ---------------------------------------------------------------------------


def test_cold_start_fastembed():
    """Measure FastEmbed cold start (first embed after fresh provider creation)."""
    from sci_fi_dashboard.embedding.fastembed_provider import FastEmbedProvider

    p = FastEmbedProvider()
    t0 = time.perf_counter()
    p.embed_query("cold start test")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    m = _get_metrics("FastEmbed")
    m.cold_start_ms = elapsed_ms
    print(f"\n  FastEmbed cold start: {elapsed_ms:.0f} ms")
    # No hard assertion — just measurement


# ---------------------------------------------------------------------------
# 2. Warm latency — 1k and 5k texts
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_warm_latency_fastembed(fastembed, gen):
    texts_1k = gen.generate(1_000)
    texts_5k = gen.generate(5_000)

    # Warmup
    for t in texts_1k[:50]:
        fastembed.embed_query(t)

    tracker_1k = measure_latencies(fastembed, texts_1k)
    tracker_5k = measure_latencies(fastembed, texts_5k)

    m = _get_metrics("FastEmbed")
    m.p50_1k_ms = tracker_1k.percentile(50) * 1000
    m.p95_1k_ms = tracker_1k.percentile(95) * 1000
    m.p99_1k_ms = tracker_1k.percentile(99) * 1000
    m.p50_5k_ms = tracker_5k.percentile(50) * 1000
    m.p95_5k_ms = tracker_5k.percentile(95) * 1000

    print(
        f"\n  FastEmbed 1k: p50={m.p50_1k_ms:.2f}ms  p95={m.p95_1k_ms:.2f}ms  p99={m.p99_1k_ms:.2f}ms"
    )
    print(f"  FastEmbed 5k: p50={m.p50_5k_ms:.2f}ms  p95={m.p95_5k_ms:.2f}ms")


# ---------------------------------------------------------------------------
# 3. Throughput — single + batch
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_throughput_fastembed(fastembed):
    # Use uniform-length texts to avoid ONNX padding distortion.
    # (Mixed-length batches are padded to max token length, which skews batch numbers.)
    short_texts = ["this is a short chat message number " + str(i) for i in range(512)]

    # Warmup
    for t in short_texts[:20]:
        fastembed.embed_query(t)

    # Single throughput
    t0 = time.perf_counter()
    for t in short_texts[:500]:
        fastembed.embed_query(t)
    single_tps = 500 / (time.perf_counter() - t0)

    # Batch-64 throughput
    t0 = time.perf_counter()
    for i in range(0, 512, 64):
        fastembed.embed_documents(short_texts[i : i + 64])
    batch64_tps = 512 / (time.perf_counter() - t0)

    # Batch-256 throughput
    t0 = time.perf_counter()
    for i in range(0, 512, 256):
        fastembed.embed_documents(short_texts[i : i + 256])
    batch256_tps = 512 / (time.perf_counter() - t0)

    m = _get_metrics("FastEmbed")
    m.throughput_single = single_tps
    m.throughput_batch64 = batch64_tps
    m.throughput_batch256 = batch256_tps

    print("\n  FastEmbed throughput (uniform-length texts):")
    print(f"    Single:    {single_tps:.0f} texts/sec")
    print(f"    Batch-64:  {batch64_tps:.0f} texts/sec")
    print(f"    Batch-256: {batch256_tps:.0f} texts/sec")


# ---------------------------------------------------------------------------
# 4. Memory footprint
# ---------------------------------------------------------------------------


def test_memory_fastembed(fastembed):
    baseline = get_memory_mb()
    for _ in range(100):
        fastembed.embed_query("memory test text")
    after = get_memory_mb()

    m = _get_metrics("FastEmbed")
    m.memory_mb = after - baseline
    print(
        f"\n  FastEmbed memory delta after 100 embeds: {m.memory_mb:.1f} MB  (total RSS: {after:.0f} MB)"
    )


# ---------------------------------------------------------------------------
# 5. Error rate over 10k
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_error_rate_fastembed(fastembed, gen):
    texts = gen.generate(10_000)
    errors = []
    for i, t in enumerate(texts):
        try:
            fastembed.embed_query(t)
        except Exception as e:
            errors.append(f"[{i}] {e}")

    rate = len(errors) / 10_000
    m = _get_metrics("FastEmbed")
    m.error_rate_10k = rate
    print(f"\n  FastEmbed error rate (10k): {rate*100:.4f}%  ({len(errors)} errors)")
    assert rate == 0.0, f"FastEmbed had errors: {errors[:3]}"


# ---------------------------------------------------------------------------
# 6. Concurrency — 4 threads x 1k
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_concurrency_fastembed(fastembed, gen):
    texts = gen.generate(4_000)
    slices = [texts[i * 1000 : (i + 1) * 1000] for i in range(4)]
    errors = []

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = []
        for sl in slices:

            def worker(s=sl):
                for t in s:
                    try:
                        fastembed.embed_query(t)
                    except Exception as e:
                        errors.append(str(e))

            futures.append(ex.submit(worker))
        for f in futures:
            f.result()
    wall_ms = (time.perf_counter() - t0) * 1000

    m = _get_metrics("FastEmbed")
    m.concurrency_4t_1k_ms = wall_ms
    print(f"\n  FastEmbed 4-thread x 1k wall time: {wall_ms:.0f} ms")
    assert errors == [], f"Concurrency errors: {errors[:3]}"


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


def test_determinism_fastembed(fastembed):
    text = "determinism check — the quick brown fox"
    ref = fastembed.embed_query(text)
    all_match = True
    for _ in range(99):
        v = fastembed.embed_query(text)
        if any(abs(a - b) > 1e-7 for a, b in zip(ref, v, strict=False)):
            all_match = False
            break
    m = _get_metrics("FastEmbed")
    m.is_deterministic = all_match
    print(f"\n  FastEmbed deterministic: {all_match}")
    assert all_match


# ---------------------------------------------------------------------------
# 8. Vector drift under load
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_vector_drift_fastembed(fastembed, gen):
    """Vector for the same text must be identical at call 1 vs call 10k."""
    anchor_text = "anchor text for drift detection"
    texts = gen.generate(10_000)

    vec_before = fastembed.embed_query(anchor_text)
    for t in texts:
        fastembed.embed_query(t)
    vec_after = fastembed.embed_query(anchor_text)

    drift = l2_dist(vec_before, vec_after)
    m = _get_metrics("FastEmbed")
    m.vector_drift = drift
    print(f"\n  FastEmbed vector drift after 10k calls: {drift:.8f}")
    assert drift < 1e-6, f"FastEmbed vector drifted after 10k calls: L2={drift}"


# ---------------------------------------------------------------------------
# 9. Edge cases — must handle tricky inputs without error
# ---------------------------------------------------------------------------


EDGE_CASES = [
    ("empty", ""),
    ("whitespace", "   \t\n  "),
    ("unicode_bengali", "\u0986\u09ae\u09be\u09b0 \u09b8\u09cb\u09a8\u09be\u09b0"),
    ("unicode_emoji", "\U0001f600\U0001f4a5\U0001f916"),
    ("sql_injection", "SELECT * FROM users; DROP TABLE messages;--"),
    ("long_text", "word " * 1000),
    ("null_like", "None"),
    ("json", '{"key": "value", "nested": [1, 2, 3]}'),
]


@pytest.mark.parametrize("name,text", EDGE_CASES)
def test_edge_case_fastembed(name, text, fastembed):
    vec = fastembed.embed_query(text)
    assert len(vec) == 768, f"FastEmbed edge case {name!r}: bad dims {len(vec)}"


# ---------------------------------------------------------------------------
# 10. Batch throughput deep-dive — mixed vs uniform text length
# ---------------------------------------------------------------------------


def test_batch_deep_dive_fastembed(fastembed):
    """Investigate ONNX padding effect on batch throughput.

    Key insight: ONNX pads all texts in a batch to the LONGEST token length.
    A single long document in a batch of 64 forces the entire batch to run
    at 'long doc' speed — making batch appear slower than single for mixed inputs.

    This test measures batch throughput across three realistic scenarios:
    - Uniform short (chat messages)   — batch should be fastest
    - Uniform long (documents)        — batch at max throughput for long texts
    - Mixed (realistic production)    — worst case for batch (padding waste)
    """
    import random as _rng

    _rng.seed(42)

    short = ["this is a chat message " + str(i) for i in range(256)]
    long = ["word " * 200 + str(i) for i in range(128)]  # ~200 word docs
    mixed = short[:192] + long[:64]
    _rng.shuffle(mixed)

    # Warmup
    fastembed.embed_query("warmup")
    fastembed.embed_documents(["warmup"])

    results = {}
    for label, texts, batch_size in [
        ("uniform_short_single", short, 1),
        ("uniform_short_batch64", short, 64),
        ("uniform_long_single", long, 1),
        ("uniform_long_batch64", long, 64),
        ("mixed_single", mixed, 1),
        ("mixed_batch64", mixed, 64),
    ]:
        t0 = time.perf_counter()
        if batch_size == 1:
            for t in texts:
                fastembed.embed_query(t)
        else:
            for i in range(0, len(texts), batch_size):
                fastembed.embed_documents(texts[i : i + batch_size])
        tps = len(texts) / (time.perf_counter() - t0)
        results[label] = tps

    print("\n  FastEmbed batch deep-dive:")
    print(f"    Uniform short — single:   {results['uniform_short_single']:.0f} texts/sec")
    print(f"    Uniform short — batch-64: {results['uniform_short_batch64']:.0f} texts/sec")
    print(f"    Uniform long  — single:   {results['uniform_long_single']:.0f} texts/sec")
    print(f"    Uniform long  — batch-64: {results['uniform_long_batch64']:.0f} texts/sec")
    print(f"    Mixed         — single:   {results['mixed_single']:.0f} texts/sec")
    print(f"    Mixed         — batch-64: {results['mixed_batch64']:.0f} texts/sec")
    print("\n  NOTE: batch > single for uniform texts = ONNX batch vectorization working.")
    print("  NOTE: mixed batch < mixed single = padding overhead (expected for ONNX).")


# ---------------------------------------------------------------------------
# 11. Final report — printed after all tests
# ---------------------------------------------------------------------------


def test_zz_print_report():
    """Always runs last (zz_ prefix). Prints the FastEmbed metrics table."""
    if not _REPORT:
        pytest.skip("No metrics collected yet — run with --run-slow")

    fe = _REPORT.get("FastEmbed")
    if not fe:
        pytest.skip("No FastEmbed metrics collected")

    DIVIDER = "=" * 60  # noqa: N806
    print(f"\n\n{DIVIDER}")
    print("  FASTEMBED PROVIDER RELIABILITY REPORT")
    print(DIVIDER)

    def row(label, val, fmt=".2f", unit="ms"):
        val_s = "N/A" if val is None else f"{val:{fmt}}{unit}"
        print(f"  {label:<36} {val_s:>14}")

    print("\n  --- LATENCY ---")
    row("Cold start", fe.cold_start_ms)
    row("1k texts  p50", fe.p50_1k_ms)
    row("1k texts  p95", fe.p95_1k_ms)
    row("1k texts  p99", fe.p99_1k_ms)
    row("5k texts  p50", fe.p50_5k_ms)
    row("5k texts  p95", fe.p95_5k_ms)

    print("\n  --- THROUGHPUT ---")
    row("Single (texts/sec)", fe.throughput_single, fmt=".0f", unit="")
    row("Batch-64 (texts/sec)", fe.throughput_batch64, fmt=".0f", unit="")
    row("Batch-256 (texts/sec)", fe.throughput_batch256, fmt=".0f", unit="")

    print("\n  --- RELIABILITY ---")
    fe_err = fe.error_rate_10k * 100 if fe.error_rate_10k is not None else None
    row("Error rate", fe_err, fmt=".4f", unit="%")
    row("Concurrency wall time", fe.concurrency_4t_1k_ms)

    print("\n  --- CORRECTNESS ---")
    row("Vector drift (L2)", fe.vector_drift, fmt=".2e", unit="")

    print("\n  --- SYSTEM ---")
    row("Memory delta (MB)", fe.memory_mb)
    det = "yes" if fe.is_deterministic else "no"
    print(f"  {'Deterministic':<36} {det:>14}")

    if fe.notes:
        print("\n  --- NOTES ---")
        for n in fe.notes:
            print(f"  {n}")

    print(f"\n{DIVIDER}\n")
