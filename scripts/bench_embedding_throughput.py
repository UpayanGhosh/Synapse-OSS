"""
Benchmark: embedding provider throughput and vector health.

Measures embed_documents() batch throughput, dimensions, and malformed-vector
coverage. This proves the embedding layer can keep up with memory ingestion.

Usage:
    python scripts/bench_embedding_throughput.py
    python scripts/bench_embedding_throughput.py --n 256 --batch-size 32

Output:
    docs/benchmarks/embedding-throughput-{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT / "workspace"
sys.path.insert(0, str(WORKSPACE))

try:
    from sci_fi_dashboard.embedding import get_provider
except ImportError as e:
    print(f"ERROR: failed to import embedding provider: {e}", file=sys.stderr)
    sys.exit(2)


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=256, help="Number of texts to embed. Default 256.")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size. Default 32.")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path.")
    args = parser.parse_args()

    provider = get_provider()
    if provider is None:
        print("ERROR: no embedding provider configured", file=sys.stderr)
        sys.exit(3)

    info = provider.info()
    expected_dims = int(provider.dimensions)
    texts = [
        (
            f"Benchmark embedding sample {i}: personal memory about work, travel, "
            "relationships, planning, emotion, and follow-up reminders."
        )
        for i in range(args.n)
    ]

    print(f"[bench] Provider: {info.name}; dims={expected_dims}")
    provider.embed_documents(["warmup embedding throughput probe"])

    batch_latencies_ms: list[float] = []
    vectors_seen = 0
    dimension_mismatches = 0
    zero_vectors = 0
    t_all = time.perf_counter()
    for start in range(0, len(texts), args.batch_size):
        batch = texts[start : start + args.batch_size]
        t0 = time.perf_counter()
        vectors = provider.embed_documents(batch)
        batch_latencies_ms.append((time.perf_counter() - t0) * 1000)
        vectors_seen += len(vectors)
        for vec in vectors:
            if len(vec) != expected_dims:
                dimension_mismatches += 1
            if not any(float(v) != 0.0 for v in vec):
                zero_vectors += 1
    total_seconds = time.perf_counter() - t_all

    result = {
        "benchmark": "embedding-throughput",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provider": info.name,
        "model": getattr(info, "model", None),
        "expected_dimensions": expected_dims,
        "texts_requested": args.n,
        "vectors_returned": vectors_seen,
        "dimension_mismatches": dimension_mismatches,
        "zero_vectors": zero_vectors,
        "batch_size": args.batch_size,
        "total_seconds": round(total_seconds, 4),
        "vectors_per_second": round(vectors_seen / total_seconds, 2) if total_seconds else 0,
        "batch_latency_ms": {
            "p50": round(statistics.median(batch_latencies_ms), 2),
            "p95": round(_percentile(batch_latencies_ms, 0.95), 2),
            "max": round(max(batch_latencies_ms), 2),
            "mean": round(statistics.fmean(batch_latencies_ms), 2),
        },
        "notes": (
            "Measures document embedding throughput and checks every returned vector "
            "for expected dimensionality and non-zero content."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"embedding-throughput-{datetime.now().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"[bench] Wrote {out_path}")

    if vectors_seen != args.n or dimension_mismatches or zero_vectors:
        sys.exit(4)


if __name__ == "__main__":
    main()
