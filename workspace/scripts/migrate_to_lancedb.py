"""
migrate_to_lancedb.py — One-time migration of SQLite vector data to LanceDB.

Usage:
    cd workspace
    python scripts/migrate_to_lancedb.py [--dry-run]

What it does:
1. Connects to memory.db (sqlite-vec extension loaded).
2. Reads vec_items (document embeddings) joined to documents.
3. Reads atomic_facts_vec (fact embeddings) joined to atomic_facts.
4. Batch-upserts everything to LanceDB (1000 rows/batch).
5. Triggers _ensure_index() after migration.
6. Verifies row counts SQLite vs LanceDB.

Safe to re-run: merge_insert on "id" is idempotent.
"""

import argparse
import os
import struct
import sys
import time
from pathlib import Path

# Ensure workspace/ is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from synapse_config import SynapseConfig
from sci_fi_dashboard.vector_store import LanceDBVectorStore

BATCH_SIZE = 1000


def _load_sqlite_vec(db_path: str):
    """Return a sqlite3 connection with sqlite-vec loaded."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.enable_load_extension(True)
        try:
            conn.load_extension("vec0")
        except Exception:
            # Try alternate paths (Windows DLL, macOS dylib)
            import sqlite_vec

            conn.load_extension(sqlite_vec.loadable_path())
    except Exception as e:
        print(f"[WARN] Could not load sqlite-vec extension: {e}")
        print("       Vector blobs will still be read as raw bytes.")
    return conn


def _unpack_vector(blob: bytes, dimensions: int = 768) -> list[float]:
    """Unpack a float32 blob to a Python list."""
    return list(struct.unpack(f"{dimensions}f", blob[:dimensions * 4]))


def migrate_documents(conn, store: LanceDBVectorStore, dry_run: bool) -> int:
    """Migrate vec_items (document embeddings) to LanceDB."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, d.content, d.hemisphere_tag, d.unix_timestamp, d.importance,
               v.embedding
        FROM vec_items v
        JOIN documents d ON v.document_id = d.id
    """)
    rows = cursor.fetchall()

    if not rows:
        print("  [documents] No rows found in vec_items.")
        return 0

    print(f"  [documents] Found {len(rows)} rows to migrate...")
    facts = []
    migrated = 0

    for doc_id, content, hemisphere_tag, unix_ts, importance, blob in rows:
        if blob is None:
            continue
        try:
            vector = _unpack_vector(blob, store._embedding_dimensions)
        except Exception as e:
            print(f"  [WARN] Could not unpack vector for doc_id={doc_id}: {e}")
            continue

        facts.append({
            "id": int(doc_id),
            "vector": vector,
            "metadata": {
                "text": content or "",
                "hemisphere_tag": hemisphere_tag or "safe",
                "unix_timestamp": int(unix_ts or 0),
                "importance": int(importance or 5),
                "source_id": 0,
                "entity": "",
                "category": "document",
            },
        })

        if len(facts) >= BATCH_SIZE:
            if not dry_run:
                store.upsert_facts(facts)
            migrated += len(facts)
            print(f"    ... upserted {migrated} rows")
            facts = []

    if facts:
        if not dry_run:
            store.upsert_facts(facts)
        migrated += len(facts)

    print(f"  [documents] Migrated {migrated} rows {'(dry-run)' if dry_run else ''}")
    return migrated


def migrate_atomic_facts(conn, store: LanceDBVectorStore, dry_run: bool) -> int:
    """Migrate atomic_facts_vec (fact embeddings) to LanceDB."""
    cursor = conn.cursor()

    # Check if atomic_facts_vec table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='atomic_facts_vec'"
    )
    if not cursor.fetchone():
        print("  [atomic_facts] Table atomic_facts_vec not found — skipping.")
        return 0

    # Check if atomic_facts table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='atomic_facts'"
    )
    has_atomic = cursor.fetchone() is not None

    if has_atomic:
        cursor.execute("""
            SELECT f.id, f.content, f.source_doc_id, f.entity, f.category,
                   v.embedding
            FROM atomic_facts_vec v
            JOIN atomic_facts f ON v.fact_id = f.id
        """)
    else:
        # Fallback: just the vec table itself
        cursor.execute("SELECT id, embedding FROM atomic_facts_vec")

    rows = cursor.fetchall()
    if not rows:
        print("  [atomic_facts] No rows found.")
        return 0

    print(f"  [atomic_facts] Found {len(rows)} rows to migrate...")
    facts = []
    migrated = 0
    # Offset IDs to avoid colliding with document IDs
    ID_OFFSET = 10_000_000

    for row in rows:
        if has_atomic:
            fact_id, content, source_doc_id, entity, category, blob = row
        else:
            fact_id, blob = row
            content, source_doc_id, entity, category = "", 0, "", ""

        if blob is None:
            continue
        try:
            vector = _unpack_vector(blob, store._embedding_dimensions)
        except Exception as e:
            print(f"  [WARN] Could not unpack atomic_fact vector id={fact_id}: {e}")
            continue

        facts.append({
            "id": int(fact_id) + ID_OFFSET,
            "vector": vector,
            "metadata": {
                "text": content or "",
                "hemisphere_tag": "safe",  # atomic_facts default to safe
                "unix_timestamp": int(time.time()),
                "importance": 5,
                "source_id": int(source_doc_id or 0),
                "entity": entity or "",
                "category": category or "atomic_fact",
            },
        })

        if len(facts) >= BATCH_SIZE:
            if not dry_run:
                store.upsert_facts(facts)
            migrated += len(facts)
            print(f"    ... upserted {migrated} rows")
            facts = []

    if facts:
        if not dry_run:
            store.upsert_facts(facts)
        migrated += len(facts)

    print(f"  [atomic_facts] Migrated {migrated} rows {'(dry-run)' if dry_run else ''}")
    return migrated


def verify(conn, store: LanceDBVectorStore) -> None:
    """Compare row counts between SQLite and LanceDB."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM vec_items")
    sqlite_docs = cursor.fetchone()[0]

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='atomic_facts_vec'"
    )
    if cursor.fetchone():
        cursor.execute("SELECT COUNT(*) FROM atomic_facts_vec")
        sqlite_facts = cursor.fetchone()[0]
    else:
        sqlite_facts = 0

    sqlite_total = sqlite_docs + sqlite_facts
    lance_total = store.table.count_rows()

    print(f"\n  SQLite rows  : {sqlite_total} (docs={sqlite_docs}, facts={sqlite_facts})")
    print(f"  LanceDB rows : {lance_total}")
    delta = abs(lance_total - sqlite_total)
    if delta == 0:
        print("  [OK] Row counts match.")
    else:
        print(f"  [WARN] Delta = {delta} rows. May include pre-existing rows or nulls.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite vector data to LanceDB")
    parser.add_argument("--dry-run", action="store_true", help="Read only — no writes to LanceDB")
    args = parser.parse_args()

    cfg = SynapseConfig.load()
    db_path = str(cfg.db_dir / "memory.db")

    if not Path(db_path).exists():
        print(f"[ERROR] memory.db not found at {db_path}")
        print("        Run Synapse at least once to create the database first.")
        sys.exit(1)

    print(f"[START] Migrating vectors from {db_path}")
    if args.dry_run:
        print("[DRY-RUN] No writes will be performed.")

    conn = _load_sqlite_vec(db_path)
    store = LanceDBVectorStore()

    total = 0
    total += migrate_documents(conn, store, dry_run=args.dry_run)
    total += migrate_atomic_facts(conn, store, dry_run=args.dry_run)

    if not args.dry_run:
        print("\n[INDEX] Building LanceDB indexes...")
        store._ensure_index()

    verify(conn, store)
    conn.close()

    print(f"\n[DONE] Migration complete. Total rows processed: {total}")
    if args.dry_run:
        print("       Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
