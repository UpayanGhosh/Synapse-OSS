"""
Benchmark: memory write latency and persistence guarantees.

Writes a small batch of unique memories through MemoryEngine.add_memory(), then
reopens the SQLite DB to verify documents, timestamps, embeddings, and affect
rows exist. This proves capture durability, not only retrieval speed.

Usage:
    python scripts/bench_memory_write_persistence.py
    python scripts/bench_memory_write_persistence.py --n 20

Output:
    docs/benchmarks/memory-write-persistence-{YYYY-MM-DD}.json
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
    print(f"ERROR: failed to import Synapse runtime: {e}", file=sys.stderr)
    sys.exit(2)


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=12, help="Number of writes. Default 12.")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path.")
    args = parser.parse_args()

    marker = f"bench-write-{int(time.time())}"
    engine = MemoryEngine()
    latencies_ms: list[float] = []
    doc_ids: list[int] = []
    errors: list[str] = []
    embedded_results = 0

    print(f"[bench] Writing {args.n} benchmark memories...")
    for i in range(args.n):
        content = (
            f"Benchmark persistence marker {marker}-{i}: user felt anxious but "
            "handled the moment with a calm walk and a practical checklist."
        )
        t0 = time.perf_counter()
        result = engine.add_memory(content, category="benchmark_write_persistence", hemisphere="safe")
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        if result.get("error"):
            errors.append(str(result["error"]))
        else:
            doc_ids.append(int(result["id"]))
            if result.get("embedded"):
                embedded_results += 1

    db_path = SynapseConfig.load().db_dir / "memory.db"
    conn = sqlite3.connect(str(db_path))
    try:
        placeholders = ",".join("?" for _ in doc_ids) or "NULL"
        documents = conn.execute(
            f"""
            SELECT COUNT(*), COUNT(unix_timestamp), MIN(unix_timestamp), MAX(unix_timestamp)
            FROM documents
            WHERE id IN ({placeholders})
            """,
            doc_ids,
        ).fetchone()
        affect_cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_affect)")}
        affect_doc_col = "doc_id" if "doc_id" in affect_cols else "document_id"
        affect_count = conn.execute(
            f"SELECT COUNT(*) FROM memory_affect WHERE {affect_doc_col} IN ({placeholders})",
            doc_ids,
        ).fetchone()[0]
    finally:
        conn.close()

    succeeded = len(doc_ids)
    result = {
        "benchmark": "memory-write-persistence",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db_path": str(db_path),
        "writes_requested": args.n,
        "writes_succeeded": succeeded,
        "writes_failed": len(errors),
        "document_rows_verified": int(documents[0] or 0),
        "timestamp_rows_verified": int(documents[1] or 0),
        "timestamp_min": int(documents[2] or 0),
        "timestamp_max": int(documents[3] or 0),
        "embedded_results_reported": embedded_results,
        "memory_affect_rows_verified": int(affect_count),
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 2),
            "p95": round(_percentile(latencies_ms, 0.95), 2),
            "max": round(max(latencies_ms), 2),
            "mean": round(statistics.fmean(latencies_ms), 2),
        },
        "errors_sample": errors[:3],
        "notes": (
            "Writes through MemoryEngine.add_memory(), then reopens memory.db "
            "to verify durable rows, timestamps, and emotional affect rows. "
            "Embedding success is taken from the write receipt because vec_items may "
            "require the sqlite-vec extension to query directly."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"memory-write-persistence-{datetime.now().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"[bench] Wrote {out_path}")

    if (
        result["writes_failed"]
        or result["document_rows_verified"] != succeeded
        or result["timestamp_rows_verified"] != succeeded
        or result["embedded_results_reported"] < succeeded
        or result["memory_affect_rows_verified"] < succeeded
    ):
        sys.exit(4)


if __name__ == "__main__":
    main()
