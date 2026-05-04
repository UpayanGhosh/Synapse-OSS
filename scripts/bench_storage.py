"""
Benchmark: on-disk storage footprint of the live Synapse data layer.

Walks ~/.synapse/ and reports per-file and per-store sizes:
  - SQLite memory.db  (documents + FTS5)
  - sqlite-vec items  (embeddings, if stored alongside)
  - knowledge_graph.db (nodes + edges)
  - LanceDB tables    (under workspace/db/lancedb/)
  - Pairing/state JSONLs

Writes a JSON artifact that backs the resume claim:
    "Storage footprint for N-message corpus: SQLite X MB, LanceDB Y MB, KG Z MB."

Usage:
    python scripts/bench_storage.py
    python scripts/bench_storage.py --root /custom/path
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def humanize(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.2f} {unit}"
        n_bytes /= 1024  # type: ignore[assignment]
    return f"{n_bytes:.2f} TB"


def walk(root: Path) -> dict:
    total = 0
    by_file: list[dict] = []
    by_top: dict[str, int] = {}

    if not root.exists():
        return {"root": str(root), "exists": False, "total_bytes": 0, "files": []}

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total += size
        rel = p.relative_to(root)
        by_file.append({"path": str(rel), "bytes": size, "human": humanize(size)})
        # Bucket by first path component
        top = rel.parts[0] if rel.parts else "<root>"
        by_top[top] = by_top.get(top, 0) + size

    by_file.sort(key=lambda d: d["bytes"], reverse=True)
    return {
        "root": str(root),
        "exists": True,
        "total_bytes": total,
        "total_human": humanize(total),
        "by_top": [
            {"top": k, "bytes": v, "human": humanize(v)}
            for k, v in sorted(by_top.items(), key=lambda kv: -kv[1])
        ],
        "files": by_file[:50],  # top-50 largest
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".synapse",
        help="Synapse data root (default: ~/.synapse).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: docs/benchmarks/storage-{date}.json).",
    )
    args = parser.parse_args()

    print(f"[bench] Scanning {args.root} ...")
    snap = walk(args.root)

    if not snap["exists"]:
        print(f"ERROR: {args.root} does not exist", file=sys.stderr)
        sys.exit(1)

    result = {
        "benchmark": "storage-footprint",
        "ran_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": snap,
        "notes": (
            "On-disk size of all Synapse-managed state. Reproduce by running "
            "`python scripts/bench_storage.py`. For a like-for-like comparison "
            "across machines, normalize by message count "
            "(`SELECT COUNT(*) FROM documents`)."
        ),
    }

    out_path = args.out
    if out_path is None:
        out_dir = REPO_ROOT / "docs" / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"storage-{datetime.now().strftime('%Y-%m-%d')}.json"
    out_path.write_text(json.dumps(result, indent=2))

    print()
    print(f"Total: {snap['total_human']}")
    print()
    print("By top-level dir:")
    for row in snap["by_top"][:10]:
        print(f"  {row['human']:>12}  {row['top']}")
    print()
    print(f"[bench] Wrote {out_path}")


if __name__ == "__main__":
    main()
