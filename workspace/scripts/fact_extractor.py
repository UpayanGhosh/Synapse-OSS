"""
Offline Knowledge Graph extractor — replaces the old Gemini CLI path.

Uses TripleExtractor (local Qwen2.5) to extract facts + triples from
documents and dual-writes to BOTH graph stores:
  - entity_links   (memory.db)       — with archival logic
  - SQLiteGraph    (knowledge_graph.db) — via add_edge() upserts

Also updates entities.json (FlashText/EntityGate feed) at the end of each run.

Usage
-----
    python scripts/fact_extractor.py                 # process kg_processed=0 docs
    python scripts/fact_extractor.py --force         # re-process ALL docs
    python scripts/fact_extractor.py --limit 100     # cap at 100 docs
    python scripts/fact_extractor.py --dry-run       # extract but don't write
"""

import argparse
import json
import os
import sqlite3
import sys
import time

from tqdm import tqdm

_sys_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

import sqlite_vec  # noqa: E402
from synapse_config import SynapseConfig  # noqa: E402
from sci_fi_dashboard.embedding import get_provider  # noqa: E402
from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402
from sci_fi_dashboard.triple_extractor import TripleExtractor  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_cfg = SynapseConfig.load()
DB_PATH = str(_cfg.db_dir / "memory.db")
ENTITIES_JSON = os.path.join(os.path.dirname(__file__), "..", "sci_fi_dashboard", "entities.json")
ENTITIES_JSON = os.path.normpath(ENTITIES_JSON)

COMMIT_EVERY = 10  # docs per commit + progress print


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------


def _get_embedding(text: str) -> list[float]:
    return get_provider().embed_documents([text])[0]


# ---------------------------------------------------------------------------
# entity_links helpers (memory.db)
# ---------------------------------------------------------------------------


def _ensure_entity_links(conn: sqlite3.Connection) -> None:
    """Idempotent: create entity_links + archived column."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_links (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            subject   TEXT NOT NULL,
            relation  TEXT NOT NULL,
            object    TEXT NOT NULL,
            archived  INTEGER DEFAULT 0,
            source_fact_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add archived column if missing (older schemas)
    cursor = conn.execute("PRAGMA table_info(entity_links)")
    cols = {row[1] for row in cursor.fetchall()}
    if "archived" not in cols:
        conn.execute("ALTER TABLE entity_links ADD COLUMN archived INTEGER DEFAULT 0")
    conn.commit()


def _write_triple_to_entity_links(
    conn: sqlite3.Connection,
    subj: str,
    rel: str,
    obj: str,
    fact_id: int,
) -> None:
    """Archival-write: mark old (subj, rel) as archived, insert new row."""
    conn.execute(
        "UPDATE entity_links SET archived = 1 WHERE subject = ? AND relation = ? AND archived = 0",
        (subj, rel),
    )
    conn.execute(
        "INSERT INTO entity_links (subject, relation, object, archived, source_fact_id) VALUES (?, ?, ?, 0, ?)",
        (subj, rel, obj, fact_id),
    )


# ---------------------------------------------------------------------------
# atomic_facts_vec helper
# ---------------------------------------------------------------------------


def _ensure_atomic_facts_vec(conn: sqlite3.Connection) -> None:
    """Create atomic_facts_vec virtual table if missing."""
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS atomic_facts_vec USING vec0(
                fact_id INTEGER,
                embedding float[768]
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"[WARN] Could not create atomic_facts_vec: {e}")


# ---------------------------------------------------------------------------
# entities.json update
# ---------------------------------------------------------------------------


def _update_entities_json(new_entities: set[str]) -> None:
    """Merge new entity names into entities.json (dict of name -> 1)."""
    try:
        with open(ENTITIES_JSON) as f:
            current: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        current = {}

    before = len(current)
    for name in new_entities:
        name = name.strip()
        if name:
            current[name] = 1

    with open(ENTITIES_JSON, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    added = len(current) - before
    if added:
        print(f"[KG] entities.json updated (+{added} new entities, {len(current)} total)")


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------


def process_documents(force: bool = False, limit: int = 0, dry_run: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    except Exception as e:
        print(f"[WARN] sqlite-vec load failed: {e} — atomic_facts_vec writes may fail")
    conn.enable_load_extension(False)

    _ensure_entity_links(conn)
    _ensure_atomic_facts_vec(conn)

    # Add kg_processed column to documents if missing (older schemas)
    _cur = conn.execute("PRAGMA table_info(documents)")
    if "kg_processed" not in {row[1] for row in _cur.fetchall()}:
        conn.execute("ALTER TABLE documents ADD COLUMN kg_processed INTEGER DEFAULT 0")
        conn.commit()

    cursor = conn.cursor()

    where_clause = "1=1" if force else "kg_processed = 0"
    limit_clause = f"LIMIT {limit}" if limit > 0 else ""
    cursor.execute(
        f"SELECT id, content FROM documents WHERE {where_clause} {limit_clause}"
    )
    rows = cursor.fetchall()

    if not rows:
        print("[KG] No documents to process.")
        conn.close()
        return

    total = len(rows)
    print(
        f"[KG] Processing {total} document(s)"
        f"{' (force)' if force else ''}"
        f"{' (dry-run)' if dry_run else ''} ..."
    )

    extractor = TripleExtractor()
    kg_graph = SQLiteGraph()
    collected_entities: set[str] = set()
    total_facts = 0
    total_triples = 0
    run_start = time.time()

    bar = tqdm(
        total=total,
        unit="doc",
        dynamic_ncols=True,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
    )

    for batch_start in range(0, total, COMMIT_EVERY):
        batch = rows[batch_start : batch_start + COMMIT_EVERY]

        for doc_id, content in batch:
            result = extractor.extract(content)
            facts = result.get("facts", [])
            triples = result.get("triples", [])

            if dry_run:
                bar.write(f"  [dry] doc={doc_id}: {len(facts)} fact(s), {len(triples)} triple(s)")
                for f in facts[:3]:
                    bar.write(f"    fact: [{f['entity']}] {f['content']}")
                for t in triples[:3]:
                    bar.write(f"    triple: {t}")
            else:
                # --- Write atomic facts ---
                for fact in facts:
                    entity = fact.get("entity", "")
                    fact_content = fact.get("content", "")
                    category = fact.get("category", "")
                    if not fact_content:
                        continue

                    cursor.execute(
                        "INSERT INTO atomic_facts (entity, content, category, source_doc_id)"
                        " VALUES (?, ?, ?, ?)",
                        (entity, fact_content, category, doc_id),
                    )
                    fact_id = cursor.lastrowid

                    try:
                        embedding = _get_embedding(fact_content)
                        cursor.execute(
                            "INSERT INTO atomic_facts_vec (fact_id, embedding) VALUES (?, ?)",
                            (fact_id, sqlite_vec.serialize_float32(embedding)),
                        )
                    except Exception as e:
                        bar.write(f"  [WARN] Embedding failed for fact {fact_id}: {e}")

                    if entity:
                        collected_entities.add(entity)

                # --- Dual-write triples ---
                for triple in triples:
                    if len(triple) < 3:
                        continue
                    subj, rel, obj = str(triple[0]), str(triple[1]), str(triple[2])
                    if not subj.strip() or not rel.strip() or not obj.strip():
                        continue

                    _write_triple_to_entity_links(conn, subj, rel, obj, fact_id=0)
                    kg_graph.add_edge(subj, obj, relation=rel)

                    collected_entities.add(subj)
                    collected_entities.add(obj)

                # Mark kg_processed
                cursor.execute(
                    "UPDATE documents SET kg_processed = 1 WHERE id = ?", (doc_id,)
                )

            total_facts += len(facts)
            total_triples += len(triples)
            bar.set_postfix(facts=total_facts, triples=total_triples, refresh=False)
            bar.update(1)

        if not dry_run:
            conn.commit()

    bar.close()

    conn.close()
    kg_graph.close()

    elapsed = time.time() - run_start
    if not dry_run:
        _update_entities_json(collected_entities)
        print(
            f"[KG] Done. {total} doc(s) in {elapsed:.1f}s — "
            f"{total_facts} facts, {total_triples} triples, "
            f"{len(collected_entities)} entities."
        )
    else:
        print(
            f"[KG] Dry run complete. {total} docs — "
            f"{total_facts} facts, {total_triples} triples (nothing written)."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline KG extractor — replaces Gemini CLI pipeline"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process ALL documents (default: only kg_processed=0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Cap at N documents (0 = no limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract but do not write to any DB or JSON",
    )
    args = parser.parse_args()
    process_documents(force=args.force, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
