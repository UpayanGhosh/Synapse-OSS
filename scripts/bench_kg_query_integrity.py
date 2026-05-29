"""
Benchmark: knowledge-graph query latency and integrity.

Measures indexed SQLite KG lookup latency and basic graph hygiene:
missing endpoints, duplicate edges, index presence, and source_doc_id coverage
when available.

Usage:
    python scripts/bench_kg_query_integrity.py
    python scripts/bench_kg_query_integrity.py --n 500

Output:
    docs/benchmarks/kg-query-integrity-{YYYY-MM-DD}.json
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
DEFAULT_DB = Path.home() / ".synapse" / "workspace" / "db" / "knowledge_graph.db"


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to knowledge_graph.db.")
    parser.add_argument("--n", type=int, default=500, help="Timed lookup count. Default 500.")
    parser.add_argument("--out", type=Path, default=None, help="Output JSON path.")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: KG DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(args.db))
    try:
        edge_cols = _columns(conn, "edges")
        required = {"source", "relation", "target"}
        if not required <= edge_cols:
            print(f"ERROR: edges table missing columns: {sorted(required - edge_cols)}", file=sys.stderr)
            sys.exit(2)

        total_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        if total_edges == 0:
            print("ERROR: no KG edges found", file=sys.stderr)
            sys.exit(3)

        missing_endpoint_edges = conn.execute(
            """
            SELECT COUNT(*) FROM edges
            WHERE source IS NULL OR trim(source) = ''
               OR relation IS NULL OR trim(relation) = ''
               OR target IS NULL OR trim(target) = ''
            """
        ).fetchone()[0]
        duplicate_edge_groups = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT source, relation, target, COUNT(*) c
              FROM edges
              GROUP BY source, relation, target
              HAVING c > 1
            )
            """
        ).fetchone()[0]
        source_doc_coverage = None
        if "source_doc_id" in edge_cols:
            with_source_doc = conn.execute(
                "SELECT COUNT(*) FROM edges WHERE source_doc_id IS NOT NULL"
            ).fetchone()[0]
            source_doc_coverage = round(with_source_doc / total_edges, 4)

        indexes = [r[1] for r in conn.execute("PRAGMA index_list(edges)")]
        seeds = conn.execute(
            """
            SELECT source FROM edges
            WHERE source IS NOT NULL AND trim(source) != ''
            GROUP BY source
            ORDER BY COUNT(*) DESC
            LIMIT 50
            """
        ).fetchall()
        subjects = [r[0] for r in seeds] or ["__missing__"]

        latencies_ms: list[float] = []
        rows_returned = 0
        for i in range(args.n):
            subject = subjects[i % len(subjects)]
            t0 = time.perf_counter()
            rows = conn.execute(
                "SELECT relation, target FROM edges WHERE source = ? LIMIT 20",
                (subject,),
            ).fetchall()
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            rows_returned += len(rows)
    finally:
        conn.close()

    result = {
        "benchmark": "kg-query-integrity",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kg_source": str(args.db),
        "edge_count": int(total_edges),
        "missing_endpoint_edges": int(missing_endpoint_edges),
        "duplicate_edge_groups": int(duplicate_edge_groups),
        "source_doc_coverage": source_doc_coverage,
        "edge_indexes": indexes,
        "lookups": args.n,
        "rows_returned": rows_returned,
        "latency_ms": {
            "p50": round(statistics.median(latencies_ms), 4),
            "p95": round(_percentile(latencies_ms, 0.95), 4),
            "p99": round(_percentile(latencies_ms, 0.99), 4),
            "max": round(max(latencies_ms), 4),
            "mean": round(statistics.fmean(latencies_ms), 4),
        },
        "notes": (
            "Measures hot SQLite source-neighborhood lookups and graph hygiene. "
            "Integrity counts should trend toward zero missing endpoints and zero duplicate groups."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"kg-query-integrity-{datetime.now().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"[bench] Wrote {out_path}")


if __name__ == "__main__":
    main()
