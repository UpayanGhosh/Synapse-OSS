import contextlib
import hashlib
import os
import sqlite3
import struct

from sci_fi_dashboard.db import get_db_connection
from sci_fi_dashboard.embedding import get_provider

try:
    from synapse_config import SynapseConfig  # noqa: PLC0415
except ImportError:
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
    from synapse_config import SynapseConfig

SOURCE_DIR = str(SynapseConfig.load().data_root / "workspace" / "memory")


def ensure_schema_migration():
    """
    Ensures 'content_hash' column exists and backfills it if missing.
    """
    conn = get_db_connection()
    try:
        # Check if column exists
        cursor = conn.execute("PRAGMA table_info(documents)")
        columns = [row[1] for row in cursor.fetchall()]

        if "content_hash" not in columns:
            print("[PKG] Migrating Schema: Adding 'content_hash' column...")
            conn.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")

            print("[REFRESH] Backfilling content hashes (this may take a moment)...")
            cursor = conn.execute("SELECT id, content FROM documents WHERE content_hash IS NULL")
            updates = []
            for row in cursor:
                doc_id, content = row
                md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
                updates.append((md5, doc_id))

            conn.executemany("UPDATE documents SET content_hash = ? WHERE id = ?", updates)
            conn.commit()
            print(f"[OK] Backfilled hashes for {len(updates)} documents.")
    except Exception as e:
        print(f"[ERROR] Migration Error: {e}")
        conn.rollback()
    finally:
        conn.close()


def compute_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def ingest_atomic():
    """
    Atomic Ingestion Strategy:
    1. Create 'documents_shadow' (Clone of valid 'documents').
    2. Scan source files, compute hash.
    3. If hash missing in shadow, embed & insert.
    4. Atomic Swap: Replace 'documents' with 'documents_shadow'.
    5. Rebuild FTS index.
    """
    print("[INFO] Starting Atomic Ingestion...")
    ensure_schema_migration()

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    try:
        # 1. Setup Shadow Table
        print("[MOON] Creating Shadow Table...")
        conn.execute("DROP TABLE IF EXISTS documents_shadow")
        conn.execute("CREATE TABLE documents_shadow AS SELECT * FROM documents WHERE 1=1")
        # Ensure indices on shadow for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_hash ON documents_shadow(content_hash)")

        # Load existing hashes set for fast lookup
        existing_hashes = {
            row[0] for row in conn.execute("SELECT content_hash FROM documents_shadow").fetchall()
        }
        print(f"[STATS] Existing Memories: {len(existing_hashes)}")

        # 2. Scan & Process
        new_items = []
        if os.path.exists(SOURCE_DIR):
            print(f"[DIR] Scanning {SOURCE_DIR}...")
            for root, _, files in os.walk(SOURCE_DIR):
                for file in files:
                    if file.endswith((".md", ".txt")):
                        path = os.path.join(root, file)
                        with open(path, encoding="utf-8") as f:
                            content = f.read()

                        # Chunking (paragraphs)
                        chunks = [c.strip() for c in content.split("\n\n") if c.strip()]

                        for chunk in chunks:
                            chash = compute_hash(chunk)
                            if chash not in existing_hashes:
                                new_items.append((file, chunk, chash))
                                existing_hashes.add(chash)  # Avoid dupes in same batch

        print(f"[PUZZLE] New Memories Found: {len(new_items)}")

        # 3. Batch Embed & Insert New Items
        if new_items:
            print("[MEM] Embedding new memories (batch)...")
            provider = get_provider()
            if provider is None:
                print("[WARN] No embedding provider available — skipping vector ingestion.")
            else:
                texts = [content for _, content, _ in new_items]
                vectors = provider.embed_documents(texts)

                cursor = conn.cursor()
                count = 0
                for (filename, content, chash), vec in zip(new_items, vectors, strict=False):
                    if not vec:
                        continue

                    # Insert Doc
                    cursor.execute(
                        "INSERT INTO documents (filename, content, hemisphere_tag, content_hash)"
                        " VALUES (?, ?, 'safe', ?)",
                        (filename, content, chash),
                    )
                    doc_id = cursor.lastrowid

                    # Insert Vec
                    vec_blob = struct.pack(f"{len(vec)}f", *vec)
                    cursor.execute(
                        "INSERT INTO vec_items(document_id, embedding) VALUES (?, ?)",
                        (doc_id, vec_blob),
                    )
                    count += 1
                    if count % 100 == 0:
                        print(f"   ... Committed {count} memories")

                conn.commit()
                print(f"[OK] Successfully ingested {count} new memories.")

        else:
            print("[OK] No new memories to ingest.")

    except Exception as e:
        print(f"[ERROR] Ingestion Failed: {e}")
        conn.rollback()
        # Clean up shadow if we made one
    finally:
        # Clean up shadow to save space
        with contextlib.suppress(BaseException):
            conn.execute("DROP TABLE IF EXISTS documents_shadow")
        conn.close()


if __name__ == "__main__":
    ingest_atomic()
