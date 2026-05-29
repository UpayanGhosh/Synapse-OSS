"""dedupe_today_session.py — Remove duplicate session-doc copies from memory.db.

Today's session was ingested twice (different format-string between runs)
producing 12 docs / 113 atomic_facts / 86 entity_links instead of 6/56/45.
This script keeps only the newer copies (23979-23984) and cascade-deletes
the older copies (23973-23978) and their dependent atomic_facts +
entity_links.

Idempotent: re-running after a successful pass is a no-op.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path.home() / ".synapse" / "workspace" / "db" / "memory.db"
OLD_DOC_IDS = [23973, 23974, 23975, 23976, 23977, 23978]


def main() -> None:
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    ph = ",".join("?" * len(OLD_DOC_IDS))
    old_fact_ids = [
        r[0]
        for r in cur.execute(
            f"SELECT id FROM atomic_facts WHERE source_doc_id IN ({ph})",
            OLD_DOC_IDS,
        ).fetchall()
    ]
    print(f"atomic_facts to delete: {len(old_fact_ids)}")

    if old_fact_ids:
        fact_ph = ",".join("?" * len(old_fact_ids))
        cur.execute(
            f"DELETE FROM entity_links WHERE source_fact_id IN ({fact_ph})",
            old_fact_ids,
        )
        print(f"entity_links deleted: {cur.rowcount}")

    cur.execute(
        f"DELETE FROM atomic_facts WHERE source_doc_id IN ({ph})",
        OLD_DOC_IDS,
    )
    print(f"atomic_facts deleted: {cur.rowcount}")

    cur.execute(
        f"DELETE FROM documents WHERE id IN ({ph})",
        OLD_DOC_IDS,
    )
    print(f"documents deleted: {cur.rowcount}")

    conn.commit()

    print()
    print("--- FINAL STATE ---")

    n_docs_total = cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_docs_today = cur.execute(
        "SELECT COUNT(*) FROM documents "
        "WHERE filename = 'session' AND created_at > datetime('now', '-1 day')"
    ).fetchone()[0]
    n_facts = cur.execute("SELECT COUNT(*) FROM atomic_facts").fetchone()[0]
    n_facts_today = cur.execute(
        "SELECT COUNT(*) FROM atomic_facts WHERE created_at > datetime('now', '-1 day')"
    ).fetchone()[0]
    n_links = cur.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]
    n_links_today = cur.execute(
        "SELECT COUNT(*) FROM entity_links WHERE created_at > datetime('now', '-1 day')"
    ).fetchone()[0]
    n_links_linked = cur.execute(
        "SELECT COUNT(*) FROM entity_links "
        "WHERE source_fact_id IN (SELECT id FROM atomic_facts)"
    ).fetchone()[0]
    n_kg_processed = cur.execute(
        "SELECT COUNT(*) FROM documents WHERE kg_processed = 1"
    ).fetchone()[0]

    print(f"  documents total: {n_docs_total}")
    print(f"  documents (session, today): {n_docs_today}")
    print(f"  atomic_facts total: {n_facts}")
    print(f"  atomic_facts new today: {n_facts_today}")
    print(f"  entity_links total: {n_links}")
    print(f"  entity_links new today: {n_links_today}")
    print(f"  entity_links linked to valid atomic_facts: {n_links_linked}")
    print(f"  documents kg_processed=1: {n_kg_processed}")

    conn.close()


if __name__ == "__main__":
    main()
