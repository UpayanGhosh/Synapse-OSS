"""
Benchmark: retrieval quality over a tiny labeled sentinel set.

Seeds a small set of benchmark memories into the live Synapse memory store,
then runs paraphrased queries and reports Hit@K, MRR, and Recall@K. This
complements latency benchmarks by proving the right memories are actually
retrieved, not merely retrieved quickly.

Usage:
    python scripts/bench_retrieval_quality.py
    python scripts/bench_retrieval_quality.py --k 10 --out docs/benchmarks/retrieval-quality.json

Output:
    docs/benchmarks/retrieval-quality-{YYYY-MM-DD}.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = REPO_ROOT / "workspace"
sys.path.insert(0, str(WORKSPACE))

try:
    from sci_fi_dashboard.memory_engine import MemoryEngine
    from synapse_config import SynapseConfig
except ImportError as e:
    print(f"ERROR: failed to import MemoryEngine: {e}", file=sys.stderr)
    sys.exit(2)


SENTINELS = [
    {
        "id": "bench-kite",
        "content": "Benchmark memory: Mira chose a crimson kite for the monsoon rooftop plan.",
        "query": "what color kite did Mira pick for the rainy rooftop plan",
        "must_contain": ["crimson", "kite"],
    },
    {
        "id": "bench-cafe",
        "content": "Benchmark memory: Aarav prefers quiet corner tables at Blue Fern Cafe.",
        "query": "where does Aarav like to sit at Blue Fern",
        "must_contain": ["corner", "blue fern"],
    },
    {
        "id": "bench-battery",
        "content": "Benchmark memory: The scooter battery issue should be checked before Sunday travel.",
        "query": "what scooter problem needs attention before the weekend trip",
        "must_contain": ["battery", "scooter"],
    },
    {
        "id": "bench-budget",
        "content": "Benchmark memory: Riya is saving 12000 rupees monthly for a Goa photography trip.",
        "query": "how much is Riya saving every month for the camera trip",
        "must_contain": ["12000", "goa"],
    },
    {
        "id": "bench-anxiety",
        "content": "Benchmark memory: When Dev feels anxious, he calms down with a ten minute walk.",
        "query": "what helps Dev settle when he gets nervous",
        "must_contain": ["ten minute walk", "anxious"],
    },
    {
        "id": "bench-launch",
        "content": "Benchmark memory: The product launch checklist must be reviewed every Friday morning.",
        "query": "when should the launch checklist be reviewed",
        "must_contain": ["friday", "launch checklist"],
    },
]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def _contains_all(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return all(term.lower() in lower for term in terms)


def _existing_doc_id(marker: str) -> int | None:
    db_path = SynapseConfig.load().db_dir / "memory.db"
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT id FROM documents WHERE content LIKE ? ORDER BY id ASC LIMIT 1",
            (f"%retrieval_quality_id={marker}%",),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=10, help="Top-K retrieval cutoff. Default 10.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: docs/benchmarks/retrieval-quality-{date}.json).",
    )
    args = parser.parse_args()

    engine = MemoryEngine()
    seeded_ids: list[int] = []
    print(f"[bench] Seeding {len(SENTINELS)} labeled benchmark memories...")
    for item in SENTINELS:
        existing_id = _existing_doc_id(item["id"])
        if existing_id is not None:
            seeded_ids.append(existing_id)
            continue
        result = engine.add_memory(
            f"{item['content']} [retrieval_quality_id={item['id']}]",
            category="benchmark_retrieval_quality",
            hemisphere="safe",
        )
        if result.get("error"):
            print(f"ERROR: seed failed for {item['id']}: {result}", file=sys.stderr)
            sys.exit(3)
        seeded_ids.append(int(result["id"]))

    # LanceDB upserts are synchronous in the current engine, but a tiny settle
    # window avoids measuring filesystem visibility races on Windows.
    time.sleep(0.25)

    per_query: list[dict] = []
    latencies_ms: list[float] = []
    hits = 0
    reciprocal_ranks: list[float] = []

    print(f"[bench] Running {len(SENTINELS)} labeled queries (k={args.k})...")
    for item in SENTINELS:
        t0 = time.perf_counter()
        result = engine.query(item["query"], limit=args.k, hemisphere="safe")
        latency_ms = (time.perf_counter() - t0) * 1000
        latencies_ms.append(latency_ms)

        rank = 0
        top_preview = []
        for idx, row in enumerate(result.get("results", []), start=1):
            content = str(row.get("content", ""))
            if idx <= 3:
                top_preview.append(content[:120])
            if rank == 0 and _contains_all(content, item["must_contain"]):
                rank = idx

        hit = rank > 0
        hits += 1 if hit else 0
        reciprocal_ranks.append(1 / rank if rank else 0)
        per_query.append(
            {
                "id": item["id"],
                "query": item["query"],
                "expected_terms": item["must_contain"],
                "hit": hit,
                "rank": rank,
                "latency_ms": round(latency_ms, 2),
                "tier": result.get("tier"),
                "top_preview": top_preview,
            }
        )

    result = {
        "benchmark": "retrieval-quality",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seeded_document_ids": seeded_ids,
        "queries": len(SENTINELS),
        "k": args.k,
        "hit_at_k": round(hits / len(SENTINELS), 4),
        "recall_at_k": round(hits / len(SENTINELS), 4),
        "mrr": round(statistics.fmean(reciprocal_ranks), 4),
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 2),
            "p95": round(_percentile(latencies_ms, 0.95), 2),
            "max": round(max(latencies_ms), 2),
        },
        "per_query": per_query,
        "notes": (
            "Seeds labeled benchmark memories, then checks whether paraphrased "
            "queries retrieve the expected memory inside top-k. Metrics mirror "
            "standard RAG retrieval quality reporting: Hit@K, Recall@K, and MRR."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"retrieval-quality-{datetime.now().strftime('%Y-%m-%d')}.json"

    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"[bench] Wrote {out_path}")

    if result["hit_at_k"] < 1.0:
        sys.exit(4)


if __name__ == "__main__":
    main()
