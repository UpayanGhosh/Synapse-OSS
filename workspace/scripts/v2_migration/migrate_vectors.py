import sqlite3
import sqlite_vec
import os
import sys
import json
from qdrant_handler import QdrantVectorStore

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")

def migrate():
    print("Starting Migration: SQLite -> Qdrant")
    
    # 1. Connect to SQLite
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    cursor = conn.cursor()

    # 2. Connect to Qdrant
    try:
        qdrant = QdrantVectorStore()
    except Exception as e:
        print(f"Failed to connect to Qdrant. Is it running? {e}")
        return

    # 3. Fetch Atomic Facts + Vectors
    print("Fetching atomic facts from SQLite...")
    cursor.execute("""
        SELECT f.id, f.entity, f.content, f.category, f.created_at, vec_to_json(v.embedding)
        FROM atomic_facts f
        JOIN atomic_facts_vec v ON f.id = v.fact_id
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("No atomic facts found in SQLite.")
        return

    print(f"Found {len(rows)} facts. Preparing batches...")

    batch_size = 50
    facts_to_upload = []

    for row in rows:
        fid, entity, content, category, created_at, embedding_json = row
        
        # Parse JSON vector
        embedding = json.loads(embedding_json)
        
        facts_to_upload.append({
            "id": fid,
            "vector": embedding,
            "metadata": {
                "entity": entity,
                "text": content,
                "category": category,
                "created_at": created_at
            }
        })

        if len(facts_to_upload) >= batch_size:
            qdrant.upsert_facts(facts_to_upload)
            print(f"Uploaded batch ({len(facts_to_upload)} points)...")
            facts_to_upload = []

    if facts_to_upload:
        qdrant.upsert_facts(facts_to_upload)
        print(f"Uploaded final batch ({len(facts_to_upload)} points)...")

    conn.close()
    print("✅ Migration Complete!")

if __name__ == "__main__":
    migrate()
