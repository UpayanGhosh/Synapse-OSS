"""
Benchmark: MemoryEngine.query() retrieval latency.

Measures P50 / P95 / P99 over N queries against the live Synapse memory
DBs at ~/.synapse/. Writes a JSON artifact under docs/benchmarks/ that the
resume can cite with provenance.

Usage:
    python scripts/bench_retrieval_latency.py
    python scripts/bench_retrieval_latency.py --queries my_queries.txt --n 200

Prerequisites:
    1. Synapse Python deps installed (`pip install -e .` from repo root).
    2. ~/.synapse/workspace/db/ populated by at least one ingest run.
       Verify with: synapse memory memory-health  (or GET /memory_health).
    3. An embedding provider configured (FastEmbed by default — no setup
       needed beyond `pip install fastembed`).

Output:
    docs/benchmarks/retrieval-latency-{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# --- Locate the workspace package ---------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT / "workspace"
if not WORKSPACE.exists():
    print(f"ERROR: workspace not found at {WORKSPACE}", file=sys.stderr)
    sys.exit(1)
sys.path.insert(0, str(WORKSPACE))

try:
    from sci_fi_dashboard.memory_engine import MemoryEngine
except ImportError as e:
    print(
        "ERROR: failed to import MemoryEngine.\n"
        "  Run from a checkout where Synapse deps are installed.\n"
        f"  Underlying error: {e}",
        file=sys.stderr,
    )
    sys.exit(2)


# Generic seed queries. Replace / extend with your own corpus-relevant
# questions in a text file (one per line) and pass via --queries.
DEFAULT_QUERIES = [
    "what did I say about my deadline last week",
    "remind me what we discussed about the project",
    "what was the bug I fixed in the auth module",
    "summarize my last conversation about training",
    "what did the partner say about plans this weekend",
    "what's the latest on the marathon training plan",
    "what did I share about my work stress",
    "what does she usually say when she's tired",
    "what was the last book I mentioned reading",
    "what did I say about switching jobs",
    "what was my goal for the quarter",
    "what topic comes up most often in our chats",
    "what did I say about my health last month",
    "what was the recipe she liked",
    "what did I think of the meeting yesterday",
    "what's the next milestone I'm working on",
    "what did I say about feeling overwhelmed",
    "what was the trip we were planning",
    "what did I say about my manager last week",
    "what's the recurring problem I keep mentioning",
    "what does the user prefer for replies — short or long",
    "what was the side project I started",
    "what did I say about my parents last call",
    "what's the financial goal I mentioned",
    "what did I say about the new tool I'm trying",
    "summarize my recent emotional state",
    "what was the conflict we resolved",
    "what's the upcoming event I need to remember",
    "what did I say about the codebase architecture",
    "what's the topic I avoid talking about",
]


def load_queries(path: Path | None) -> list[str]:
    if path is None:
        return list(DEFAULT_QUERIES)
    if not path.exists():
        print(f"ERROR: queries file not found: {path}", file=sys.stderr)
        sys.exit(1)
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help="Path to a text file with one query per line (default: built-in seed list).",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=200,
        help="Total number of timed queries (cycles through the query list). Default 200.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Top-K limit per query. Default 10.",
    )
    parser.add_argument(
        "--hemisphere",
        type=str,
        default="safe",
        help="Hemisphere to query (safe/spicy). Default safe.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: docs/benchmarks/retrieval-latency-{date}.json).",
    )
    args = parser.parse_args()

    queries = load_queries(args.queries)
    if not queries:
        print("ERROR: no queries to run", file=sys.stderr)
        sys.exit(1)

    print(f"[bench] Initializing MemoryEngine...")
    engine = MemoryEngine()

    # Warmup — first call pays embedding-provider load, model warmup, etc.
    print(f"[bench] Warmup: running 3 throwaway queries...")
    for q in queries[:3]:
        try:
            engine.query(q, limit=args.limit, hemisphere=args.hemisphere)
        except Exception as e:
            print(f"[bench] WARN: warmup query failed: {e}")

    print(f"[bench] Running {args.n} timed queries (limit={args.limit}, hemisphere={args.hemisphere})...")
    durations_ms: list[float] = []
    failures = 0
    for i in range(args.n):
        q = queries[i % len(queries)]
        try:
            t0 = time.perf_counter()
            _ = engine.query(q, limit=args.limit, hemisphere=args.hemisphere)
            durations_ms.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            failures += 1
            if failures <= 3:
                print(f"[bench] query failed: {e}")

        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{args.n}]")

    if not durations_ms:
        print("ERROR: every query failed. Check ~/.synapse/ DBs and embedding provider.", file=sys.stderr)
        sys.exit(3)

    durations_sorted = sorted(durations_ms)
    n = len(durations_sorted)
    p50 = statistics.median(durations_sorted)
    # Linear interpolation percentiles, robust for small N.
    def percentile(p: float) -> float:
        idx = (n - 1) * p
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return durations_sorted[lo] + (durations_sorted[hi] - durations_sorted[lo]) * (idx - lo)

    p95 = percentile(0.95)
    p99 = percentile(0.99)
    mean = statistics.fmean(durations_sorted)
    stdev = statistics.pstdev(durations_sorted)

    result = {
        "benchmark": "retrieval-latency",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "queries_total": args.n,
        "queries_succeeded": n,
        "queries_failed": failures,
        "limit_k": args.limit,
        "hemisphere": args.hemisphere,
        "latency_ms": {
            "min": round(min(durations_sorted), 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max(durations_sorted), 2),
            "mean": round(mean, 2),
            "stdev": round(stdev, 2),
        },
        "notes": (
            "Measured against the live ~/.synapse/ DBs. Reproduce by running "
            "`python scripts/bench_retrieval_latency.py`."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"retrieval-latency-{datetime.now().strftime('%Y-%m-%d')}.json"

    out_path.write_text(json.dumps(result, indent=2))
    print()
    print(json.dumps(result, indent=2))
    print()
    print(f"[bench] Wrote {out_path}")


if __name__ == "__main__":
    main()
