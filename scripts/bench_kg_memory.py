"""
Benchmark: NetworkX in-memory KG vs SQLite SPO triples — memory footprint.

Reads the live knowledge_graph.db, builds the same edge set in:
  (a) a NetworkX DiGraph (in-memory, the pre-migration representation)
  (b) a SQLite :memory: database with subject/predicate/object schema and
      indexes on subject and object columns
... and reports peak Python-process memory (via tracemalloc) for each.

Writes a JSON artifact that backs the resume claim:
    "Reduced KG RAM footprint by N% (NetworkX X MB -> SQLite Y MB)
     over Z edges, measured via tracemalloc."

Usage:
    python scripts/bench_kg_memory.py
    python scripts/bench_kg_memory.py --db /custom/path/knowledge_graph.db

Prerequisites:
    1. `pip install networkx`  (the only extra dep — Synapse no longer
       ships it as a runtime dep after the migration).
    2. ~/.synapse/workspace/db/knowledge_graph.db must exist with edges.
       Verify with: sqlite3 ~/.synapse/workspace/db/knowledge_graph.db
                     "SELECT COUNT(*) FROM edges"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_KG_PATHS = [
    Path.home() / ".synapse" / "workspace" / "db" / "knowledge_graph.db",
    Path.home() / ".synapse" / "knowledge_graph.db",
    REPO_ROOT / "workspace" / "db" / "knowledge_graph.db",
]


def find_kg_db(explicit: Path | None) -> Path:
    if explicit:
        if not explicit.exists():
            print(f"ERROR: --db not found: {explicit}", file=sys.stderr)
            sys.exit(1)
        return explicit
    for p in DEFAULT_KG_PATHS:
        if p.exists():
            return p
    print(
        "ERROR: knowledge_graph.db not found. Searched:\n  - "
        + "\n  - ".join(str(p) for p in DEFAULT_KG_PATHS),
        file=sys.stderr,
    )
    sys.exit(1)


def load_edges(db_path: Path) -> list[tuple[str, str, str]]:
    """Return [(subject, predicate, object), ...] from the live KG."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT source, relation, target FROM edges"
        ).fetchall()
    finally:
        conn.close()
    return [(s, p, o) for s, p, o in rows if s and o]


def measure_networkx(edges: list[tuple[str, str, str]]) -> dict:
    try:
        import networkx as nx
    except ImportError:
        print(
            "ERROR: networkx not installed. Run: pip install networkx",
            file=sys.stderr,
        )
        sys.exit(2)

    tracemalloc.start()
    g = nx.DiGraph()
    for s, p, o in edges:
        g.add_edge(s, o, relation=p)
    current, peak = tracemalloc.get_traced_memory()
    n_nodes = g.number_of_nodes()
    n_edges = g.number_of_edges()
    tracemalloc.stop()
    del g
    return {
        "current_bytes": current,
        "peak_bytes": peak,
        "current_mb": round(current / 1024 / 1024, 2),
        "peak_mb": round(peak / 1024 / 1024, 2),
        "nodes": n_nodes,
        "edges": n_edges,
    }


def measure_sqlite(edges: list[tuple[str, str, str]]) -> dict:
    tracemalloc.start()
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE triples (subject TEXT, predicate TEXT, object TEXT)"
    )
    conn.execute("CREATE INDEX idx_subject ON triples(subject)")
    conn.execute("CREATE INDEX idx_object ON triples(object)")
    conn.executemany(
        "INSERT INTO triples (subject, predicate, object) VALUES (?, ?, ?)",
        edges,
    )
    conn.commit()
    current, peak = tracemalloc.get_traced_memory()
    n_rows = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
    tracemalloc.stop()
    conn.close()
    return {
        "current_bytes": current,
        "peak_bytes": peak,
        "current_mb": round(current / 1024 / 1024, 2),
        "peak_mb": round(peak / 1024 / 1024, 2),
        "rows": n_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to knowledge_graph.db (defaults to ~/.synapse/workspace/db/).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: docs/benchmarks/kg-memory-{date}.json).",
    )
    args = parser.parse_args()

    db_path = find_kg_db(args.db)
    print(f"[bench] Loading edges from {db_path}...")
    edges = load_edges(db_path)
    if not edges:
        print(
            "ERROR: no edges found in KG. Ingest some data before benchmarking.",
            file=sys.stderr,
        )
        sys.exit(3)
    print(f"[bench] Loaded {len(edges)} edges")

    print(f"[bench] Measuring NetworkX representation...")
    nx_result = measure_networkx(edges)
    print(
        f"  NetworkX: {nx_result['peak_mb']} MB peak "
        f"({nx_result['nodes']} nodes, {nx_result['edges']} edges)"
    )

    print(f"[bench] Measuring SQLite representation...")
    sq_result = measure_sqlite(edges)
    print(f"  SQLite:   {sq_result['peak_mb']} MB peak ({sq_result['rows']} rows)")

    # Compute reduction percentage on peak memory.
    if nx_result["peak_bytes"] > 0:
        reduction_pct = round(
            (1 - sq_result["peak_bytes"] / nx_result["peak_bytes"]) * 100, 1
        )
    else:
        reduction_pct = None

    result = {
        "benchmark": "kg-memory",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kg_source": str(db_path),
        "edge_count": len(edges),
        "networkx": nx_result,
        "sqlite": sq_result,
        "reduction_pct_peak": reduction_pct,
        "notes": (
            "Measured via tracemalloc on the live edge set. NetworkX "
            "DiGraph builds a Python object graph; SQLite stores as rows "
            "with subject/object indexes. Reproduce by running "
            "`python scripts/bench_kg_memory.py`."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"kg-memory-{datetime.now().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print()
    print(json.dumps(result, indent=2))
    print()
    print(f"[bench] Wrote {out_path}")


if __name__ == "__main__":
    main()
