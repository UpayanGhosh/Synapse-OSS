"""
Phase 4 — Head-to-Head Provider Comparison (FastEmbed vs Ollama)
=================================================================
This is the migration validation suite.
Synapse is migrating from Ollama (HTTP, separate process) to FastEmbed (ONNX, in-process).
These tests prove FastEmbed matches or exceeds Ollama across every dimension that matters.

Run setup first:
    python tests/reliability/setup_ollama.py

Run tests:
    cd workspace && pytest tests/reliability/test_phase4_provider_comparison.py -v --run-slow -s

Metrics covered:
  1.  Cold start latency      — first embed after process start
  2.  Warm latency (p50/p95/p99) — 1k, 5k texts
  3.  Throughput              — texts/sec (single + batch)
  4.  Batch throughput        — batch of 64, 256
  5.  Memory footprint        — RSS before vs after warmup
  6.  Error rate over 10k     — 0% required for both
  7.  Concurrency             — 4 threads x 1k (Ollama serializes, FastEmbed doesn't)
  8.  Determinism             — same input → same vector (100 repeats)
  9.  Semantic agreement      — cosine_sim(fastembed_vec, ollama_vec) on same text > 0.90
  10. Vector drift under load — vectors don't change between call 1 and call 10k
  11. Edge case parity        — both handle empty/unicode/long texts without error
  12. REPORT                  — final formatted table comparing all metrics
"""

import math
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.reliability.conftest import (
    SKIP_NO_FASTEMBED,
    ReliabilityDataGenerator,
    LatencyTracker,
    get_memory_mb,
)

pytestmark = [pytest.mark.reliability, SKIP_NO_FASTEMBED]

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL = "nomic-embed-text"

# ---------------------------------------------------------------------------
# Ollama availability guard
# ---------------------------------------------------------------------------


def _ollama_available() -> bool:
    try:
        import urllib.request

        req = urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3)
        return req.status == 200
    except Exception:
        return False


SKIP_NO_OLLAMA = pytest.mark.skipif(
    not _ollama_available(),
    reason=(
        "Ollama server not running. "
        "Run: python tests/reliability/setup_ollama.py"
    ),
)

# ---------------------------------------------------------------------------
# Shared comparison report (module-level accumulator)
# ---------------------------------------------------------------------------


@dataclass
class ProviderMetrics:
    name: str
    cold_start_ms: Optional[float] = None
    p50_1k_ms: Optional[float] = None
    p95_1k_ms: Optional[float] = None
    p99_1k_ms: Optional[float] = None
    p50_5k_ms: Optional[float] = None
    p95_5k_ms: Optional[float] = None
    throughput_single: Optional[float] = None   # texts/sec
    throughput_batch64: Optional[float] = None  # texts/sec (uniform-length texts)
    throughput_batch256: Optional[float] = None
    memory_mb: Optional[float] = None
    error_rate_10k: Optional[float] = None
    concurrency_4t_1k_ms: Optional[float] = None  # total wall time
    is_deterministic: bool = False
    semantic_agreement: Optional[float] = None    # cosine_sim vs other provider
    vector_drift: Optional[float] = None          # L2 diff between call 1 and call 10k
    notes: List[str] = field(default_factory=list)


_REPORT: Dict[str, ProviderMetrics] = {}


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
def ollama_provider():
    from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

    p = OllamaProvider(api_base=OLLAMA_HOST)
    if not p.available:
        pytest.skip("Ollama not available")
    return p


@pytest.fixture(scope="module")
def gen():
    return ReliabilityDataGenerator(seed=200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def l2_dist(a: list, b: list) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def measure_latencies(provider, texts: List[str]) -> LatencyTracker:
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


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_cold_start_ollama():
    """Measure Ollama cold start (first embed including HTTP round-trip + model load)."""
    from sci_fi_dashboard.embedding.ollama_provider import OllamaProvider

    p = OllamaProvider(api_base=OLLAMA_HOST)
    t0 = time.perf_counter()
    p.embed_query("cold start test")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    m = _get_metrics("Ollama")
    m.cold_start_ms = elapsed_ms
    print(f"\n  Ollama cold start: {elapsed_ms:.0f} ms")


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


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_warm_latency_ollama(ollama_provider, gen):
    texts_1k = gen.generate(1_000)
    texts_5k = gen.generate(5_000)

    # Warmup
    for t in texts_1k[:10]:
        ollama_provider.embed_query(t)

    tracker_1k = measure_latencies(ollama_provider, texts_1k)
    tracker_5k = measure_latencies(ollama_provider, texts_5k)

    m = _get_metrics("Ollama")
    m.p50_1k_ms = tracker_1k.percentile(50) * 1000
    m.p95_1k_ms = tracker_1k.percentile(95) * 1000
    m.p99_1k_ms = tracker_1k.percentile(99) * 1000
    m.p50_5k_ms = tracker_5k.percentile(50) * 1000
    m.p95_5k_ms = tracker_5k.percentile(95) * 1000

    print(
        f"\n  Ollama 1k: p50={m.p50_1k_ms:.2f}ms  p95={m.p95_1k_ms:.2f}ms  p99={m.p99_1k_ms:.2f}ms"
    )
    print(f"  Ollama 5k: p50={m.p50_5k_ms:.2f}ms  p95={m.p95_5k_ms:.2f}ms")


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

    print(f"\n  FastEmbed throughput (uniform-length texts):")
    print(f"    Single:    {single_tps:.0f} texts/sec")
    print(f"    Batch-64:  {batch64_tps:.0f} texts/sec")
    print(f"    Batch-256: {batch256_tps:.0f} texts/sec")


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_throughput_ollama(ollama_provider):
    short_texts = ["this is a short chat message number " + str(i) for i in range(256)]

    # Warmup
    for t in short_texts[:5]:
        ollama_provider.embed_query(t)

    # Single throughput
    t0 = time.perf_counter()
    for t in short_texts[:200]:
        ollama_provider.embed_query(t)
    single_tps = 200 / (time.perf_counter() - t0)

    # Batch-64 throughput (Ollama iterates internally — still serial HTTP per item)
    t0 = time.perf_counter()
    for i in range(0, 256, 64):
        ollama_provider.embed_documents(short_texts[i : i + 64])
    batch64_tps = 256 / (time.perf_counter() - t0)

    m = _get_metrics("Ollama")
    m.throughput_single = single_tps
    m.throughput_batch64 = batch64_tps
    m.throughput_batch256 = batch64_tps  # Same for Ollama — no native batching

    print(f"\n  Ollama throughput (uniform-length texts):")
    print(f"    Single:    {single_tps:.0f} texts/sec")
    print(f"    Batch-64:  {batch64_tps:.0f} texts/sec (serial HTTP — no native batching)")


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
    print(f"\n  FastEmbed memory delta after 100 embeds: {m.memory_mb:.1f} MB  (total RSS: {after:.0f} MB)")


@SKIP_NO_OLLAMA
def test_memory_ollama(ollama_provider):
    baseline = get_memory_mb()
    for _ in range(100):
        ollama_provider.embed_query("memory test text")
    after = get_memory_mb()

    m = _get_metrics("Ollama")
    m.memory_mb = after - baseline
    print(f"\n  Ollama memory delta after 100 embeds: {m.memory_mb:.1f} MB  (total RSS: {after:.0f} MB)")


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


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_error_rate_ollama(ollama_provider, gen):
    texts = gen.generate(1_000)  # 1k for Ollama — 10k would take too long at ~50ms/call
    errors = []
    for i, t in enumerate(texts):
        try:
            ollama_provider.embed_query(t)
        except Exception as e:
            errors.append(f"[{i}] {e}")

    rate = len(errors) / 1_000
    m = _get_metrics("Ollama")
    m.error_rate_10k = rate
    m.notes.append("Error rate measured over 1k (not 10k) — Ollama is serial HTTP")
    print(f"\n  Ollama error rate (1k): {rate*100:.4f}%  ({len(errors)} errors)")
    assert rate == 0.0, f"Ollama had errors: {errors[:3]}"


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


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_concurrency_ollama(ollama_provider, gen):
    """Ollama serializes requests — 4 threads will queue. This shows the difference."""
    texts = gen.generate(400)  # 100 per thread — Ollama is slow
    slices = [texts[i * 100 : (i + 1) * 100] for i in range(4)]
    errors = []

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = []
        for sl in slices:
            def worker(s=sl):
                for t in s:
                    try:
                        ollama_provider.embed_query(t)
                    except Exception as e:
                        errors.append(str(e))
            futures.append(ex.submit(worker))
        for f in futures:
            f.result()
    wall_ms = (time.perf_counter() - t0) * 1000

    m = _get_metrics("Ollama")
    m.concurrency_4t_1k_ms = wall_ms
    m.notes.append("Concurrency measured over 4x100 (not 4x1k) — Ollama is serial HTTP")
    print(f"\n  Ollama 4-thread x 100 wall time: {wall_ms:.0f} ms")
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
        if any(abs(a - b) > 1e-7 for a, b in zip(ref, v)):
            all_match = False
            break
    m = _get_metrics("FastEmbed")
    m.is_deterministic = all_match
    print(f"\n  FastEmbed deterministic: {all_match}")
    assert all_match


@SKIP_NO_OLLAMA
def test_determinism_ollama(ollama_provider):
    text = "determinism check — the quick brown fox"
    ref = ollama_provider.embed_query(text)
    all_match = True
    for _ in range(9):  # Fewer repeats — HTTP overhead
        v = ollama_provider.embed_query(text)
        if any(abs(a - b) > 1e-6 for a, b in zip(ref, v)):
            all_match = False
            break
    m = _get_metrics("Ollama")
    m.is_deterministic = all_match
    print(f"\n  Ollama deterministic: {all_match}")
    assert all_match


# ---------------------------------------------------------------------------
# 8. Semantic agreement — cosine sim between providers on same texts
# ---------------------------------------------------------------------------


@SKIP_NO_OLLAMA
def test_semantic_agreement(fastembed, ollama_provider):
    """FastEmbed and Ollama use the SAME underlying model (nomic-embed-text).
    Their vectors should be very close (cosine_sim > 0.98).

    Minor differences are expected because:
    - FastEmbed uses ONNX (quantized) vs Ollama uses GGUF
    - Different prefix formats (tested separately)
    """
    # Use raw text without prefix to compare apples-to-apples
    test_texts = [
        "hello world this is a test",
        "machine learning embeddings for semantic search",
        "the weather is sunny and warm today",
        "Python function that sorts a list of integers",
        "deep neural network architecture for NLP tasks",
    ]

    similarities = []
    for text in test_texts:
        # embed_query adds "search_query: " prefix to both — so both use same prefix
        fe_vec = fastembed.embed_query(text)
        ol_vec = ollama_provider.embed_query(text)
        sim = cosine_sim(fe_vec, ol_vec)
        similarities.append(sim)
        print(f"    sim({text[:30]!r}): {sim:.4f}")

    avg_sim = sum(similarities) / len(similarities)
    min_sim = min(similarities)

    m_fe = _get_metrics("FastEmbed")
    m_ol = _get_metrics("Ollama")
    m_fe.semantic_agreement = avg_sim
    m_ol.semantic_agreement = avg_sim

    print(f"\n  Semantic agreement (avg cosine sim): {avg_sim:.4f}")
    print(f"  Min: {min_sim:.4f}")

    # > 0.90 is the migration safety threshold
    assert avg_sim > 0.90, (
        f"Semantic agreement {avg_sim:.4f} below 0.90 threshold. "
        "Vectors are too different — migration may affect search quality."
    )
    assert min_sim > 0.85, (
        f"Some texts had very low agreement: min={min_sim:.4f}"
    )


# ---------------------------------------------------------------------------
# 9. Vector drift under load
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


@pytest.mark.slow
@SKIP_NO_OLLAMA
def test_vector_drift_ollama(ollama_provider, gen):
    texts = gen.generate(500)  # Fewer for Ollama

    anchor_text = "anchor text for drift detection"
    vec_before = ollama_provider.embed_query(anchor_text)
    for t in texts:
        ollama_provider.embed_query(t)
    vec_after = ollama_provider.embed_query(anchor_text)

    drift = l2_dist(vec_before, vec_after)
    m = _get_metrics("Ollama")
    m.vector_drift = drift
    print(f"\n  Ollama vector drift after 500 calls: {drift:.8f}")
    assert drift < 1e-6, f"Ollama vector drifted: L2={drift}"


# ---------------------------------------------------------------------------
# 10. Edge case parity — both must handle the same tricky inputs
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


@pytest.mark.parametrize("name,text", EDGE_CASES)
@SKIP_NO_OLLAMA
def test_edge_case_ollama(name, text, ollama_provider):
    vec = ollama_provider.embed_query(text)
    assert len(vec) == 768, f"Ollama edge case {name!r}: bad dims {len(vec)}"


# ---------------------------------------------------------------------------
# 11. Batch throughput deep-dive (FastEmbed) — mixed vs uniform text length
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
        ("uniform_short_single",  short, 1),
        ("uniform_short_batch64", short, 64),
        ("uniform_long_single",   long,  1),
        ("uniform_long_batch64",  long,  64),
        ("mixed_single",          mixed, 1),
        ("mixed_batch64",         mixed, 64),
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

    print(f"\n  FastEmbed batch deep-dive:")
    print(f"    Uniform short — single:   {results['uniform_short_single']:.0f} texts/sec")
    print(f"    Uniform short — batch-64: {results['uniform_short_batch64']:.0f} texts/sec")
    print(f"    Uniform long  — single:   {results['uniform_long_single']:.0f} texts/sec")
    print(f"    Uniform long  — batch-64: {results['uniform_long_batch64']:.0f} texts/sec")
    print(f"    Mixed         — single:   {results['mixed_single']:.0f} texts/sec")
    print(f"    Mixed         — batch-64: {results['mixed_batch64']:.0f} texts/sec")
    print(f"\n  NOTE: batch > single for uniform texts = ONNX batch vectorization working.")
    print(f"  NOTE: mixed batch < mixed single = padding overhead (expected for ONNX).")


# ---------------------------------------------------------------------------
# 12. Final report — printed after all tests
# ---------------------------------------------------------------------------


def test_zz_print_comparison_report():
    """Always runs last (zz_ prefix). Prints the full comparison table."""
    if not _REPORT:
        pytest.skip("No metrics collected yet — run with --run-slow")

    providers = list(_REPORT.values())

    def col(val, width=14):
        if isinstance(val, float):
            s = f"{val:.2f}"
        elif isinstance(val, bool):
            s = "yes" if val else "no"
        else:
            s = str(val)
        return s.rjust(width)

    DIVIDER = "=" * 80
    print(f"\n\n{DIVIDER}")
    print("  EMBEDDING PROVIDER COMPARISON REPORT")
    print(f"  FastEmbed (ONNX in-process) vs Ollama (HTTP subprocess)")
    print(DIVIDER)

    headers = ["Metric", "FastEmbed", "Ollama", "Winner"]
    print(f"\n  {'Metric':<36} {'FastEmbed':>12} {'Ollama':>12} {'Winner':>10}")
    print(f"  {'-'*36} {'-'*12} {'-'*12} {'-'*10}")

    fe = _REPORT.get("FastEmbed")
    ol = _REPORT.get("Ollama")

    def row(label, fe_val, ol_val, lower_is_better=True, fmt=".2f", unit="ms"):
        # Use None as sentinel for "not measured", not 0.0 (0.0 is a valid result)
        fe_not_measured = fe_val is None
        ol_not_measured = ol_val is None
        if fe_not_measured and ol_not_measured:
            winner = "N/A"
        elif ol_not_measured:
            winner = "FastEmbed"
        elif fe_not_measured:
            winner = "Ollama"
        elif lower_is_better:
            winner = "FastEmbed" if fe_val <= ol_val else "Ollama"
        else:
            winner = "FastEmbed" if fe_val >= ol_val else "Ollama"

        fe_s = "N/A" if fe_val is None else f"{fe_val:{fmt}}{unit}"
        ol_s = "N/A" if ol_val is None else f"{ol_val:{fmt}}{unit}"
        print(f"  {label:<36} {fe_s:>12} {ol_s:>12} {winner:>10}")

    if fe and ol:
        print(f"\n  --- LATENCY ---")
        row("Cold start", fe.cold_start_ms, ol.cold_start_ms)
        row("1k texts  p50", fe.p50_1k_ms, ol.p50_1k_ms)
        row("1k texts  p95", fe.p95_1k_ms, ol.p95_1k_ms)
        row("1k texts  p99", fe.p99_1k_ms, ol.p99_1k_ms)
        row("5k texts  p50", fe.p50_5k_ms, ol.p50_5k_ms)
        row("5k texts  p95", fe.p95_5k_ms, ol.p95_5k_ms)

        print(f"\n  --- THROUGHPUT ---")
        row("Single (texts/sec)", fe.throughput_single, ol.throughput_single,
            lower_is_better=False, fmt=".0f", unit="")
        row("Batch-64 (texts/sec)", fe.throughput_batch64, ol.throughput_batch64,
            lower_is_better=False, fmt=".0f", unit="")
        row("Batch-256 (texts/sec)", fe.throughput_batch256, ol.throughput_batch256,
            lower_is_better=False, fmt=".0f", unit="")

        print(f"\n  --- RELIABILITY ---")
        fe_err = fe.error_rate_10k * 100 if fe.error_rate_10k is not None else None
        ol_err = ol.error_rate_10k * 100 if ol.error_rate_10k is not None else None
        row("Error rate", fe_err, ol_err, lower_is_better=True, fmt=".4f", unit="%")
        row("Concurrency wall time", fe.concurrency_4t_1k_ms, ol.concurrency_4t_1k_ms)

        print(f"\n  --- CORRECTNESS ---")
        row("Semantic agreement", fe.semantic_agreement, ol.semantic_agreement,
            lower_is_better=False, fmt=".4f", unit="")
        row("Vector drift (L2)", fe.vector_drift, ol.vector_drift,
            lower_is_better=True, fmt=".2e", unit="")

        print(f"\n  --- SYSTEM ---")
        row("Memory delta (MB)", fe.memory_mb, ol.memory_mb)
        det_fe = "yes" if fe.is_deterministic else "no"
        det_ol = "yes" if ol.is_deterministic else "no"
        print(f"  {'Deterministic':<36} {det_fe:>12} {det_ol:>12}")

        if fe.notes or ol.notes:
            print(f"\n  --- NOTES ---")
            for n in fe.notes:
                print(f"  FastEmbed: {n}")
            for n in ol.notes:
                print(f"  Ollama:    {n}")

    elif fe:
        print("\n  FastEmbed metrics only (Ollama not available):")
        print(f"    Cold start:        {fe.cold_start_ms:.0f} ms")
        print(f"    p50 (1k):          {fe.p50_1k_ms:.2f} ms")
        print(f"    p95 (1k):          {fe.p95_1k_ms:.2f} ms")
        print(f"    p99 (1k):          {fe.p99_1k_ms:.2f} ms")
        print(f"    Throughput single: {fe.throughput_single:.0f} texts/sec")
        print(f"    Error rate:        {fe.error_rate_10k*100:.4f}%")
        print(f"    Deterministic:     {'yes' if fe.is_deterministic else 'no'}")

    print(f"\n{DIVIDER}\n")
