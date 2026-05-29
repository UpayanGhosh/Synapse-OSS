"""Backfill memory_affect rows from existing documents.

Safe defaults:
- dry-run writes no affect rows
- real writes create memory.db.bak_affect_<timestamp> first
- no atomic_facts or other tables are touched
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_WORKSPACE = Path(__file__).resolve().parents[2]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from sci_fi_dashboard.memory_affect import (  # noqa: E402
    ensure_memory_affect_table,
    extract_affect,
    upsert_memory_affect,
)


def resolve_memory_db() -> Path:
    """Resolve runtime memory.db via SynapseConfig."""
    from synapse_config import SynapseConfig

    return SynapseConfig.load().db_dir / "memory.db"


def _memory_affect_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_affect'"
    ).fetchone()
    return row is not None


def select_documents_without_affect(
    conn: sqlite3.Connection,
    limit: int,
    since_id: int = 0,
    force: bool = False,
) -> list[dict]:
    """Return candidate documents for affect extraction."""
    conn.row_factory = sqlite3.Row
    limit = max(0, int(limit))
    since_id = max(0, int(since_id))
    if limit == 0:
        return []

    if force:
        rows = conn.execute(
            """
            SELECT id, content
            FROM documents
            WHERE id > ? AND content IS NOT NULL AND TRIM(content) != ''
            ORDER BY id ASC
            LIMIT ?
            """,
            (since_id, limit),
        ).fetchall()
    elif _memory_affect_exists(conn):
        rows = conn.execute(
            """
            SELECT d.id, d.content
            FROM documents d
            LEFT JOIN memory_affect ma ON ma.doc_id = d.id
            WHERE d.id > ?
              AND ma.doc_id IS NULL
              AND d.content IS NOT NULL
              AND TRIM(d.content) != ''
            ORDER BY d.id ASC
            LIMIT ?
            """,
            (since_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, content
            FROM documents
            WHERE id > ? AND content IS NOT NULL AND TRIM(content) != ''
            ORDER BY id ASC
            LIMIT ?
            """,
            (since_id, limit),
        ).fetchall()

    return [{"id": int(row["id"]), "content": str(row["content"])} for row in rows]


def backfill(
    db_path: Path,
    limit: int = 100,
    dry_run: bool = False,
    force: bool = False,
    since_id: int = 0,
) -> dict:
    """Backfill memory_affect rows and return a summary dict."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"memory.db not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    backup_path: Path | None = None
    written = 0
    try:
        if not dry_run:
            ensure_memory_affect_table(conn)
        candidates = select_documents_without_affect(
            conn,
            limit=limit,
            since_id=since_id,
            force=force,
        )

        if dry_run or not candidates:
            return {
                "dry_run": dry_run,
                "candidates": len(candidates),
                "written": 0,
                "backup": None,
            }

        backup_path = db_path.with_name(f"{db_path.name}.bak_affect_{int(time.time())}")
        shutil.copy2(db_path, backup_path)

        for row in candidates:
            upsert_memory_affect(conn, row["id"], extract_affect(row["content"]))
            written += 1
        conn.commit()
        return {
            "dry_run": False,
            "candidates": len(candidates),
            "written": written,
            "backup": str(backup_path),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill memory_affect from documents")
    parser.add_argument("--db", type=Path, default=None, help="Path to memory.db")
    parser.add_argument("--limit", type=int, default=100, help="Max docs to process")
    parser.add_argument("--since-id", type=int, default=0, help="Only docs with id greater than this")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates without writing rows")
    parser.add_argument("--force", action="store_true", help="Recompute affect rows even when present")
    args = parser.parse_args()

    db_path = args.db or resolve_memory_db()
    result = backfill(
        db_path=db_path,
        limit=args.limit,
        dry_run=args.dry_run,
        force=args.force,
        since_id=args.since_id,
    )
    print(
        "[memory_affect] "
        f"dry_run={result['dry_run']} candidates={result['candidates']} "
        f"written={result['written']} backup={result['backup']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
