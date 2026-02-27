import sqlite3
import os
import json
from datetime import datetime
from qdrant_client import QdrantClient

# Paths
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
COLLECTION_NAME = "atomic_facts"


def migrate():
    print("[INFO] Starting Temporal Migration v2 (Using DB created_at)...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE documents ADD COLUMN unix_timestamp INTEGER;")
    except:
        pass

    q_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Fetch all documents with their DB creation time
    cursor.execute("SELECT id, created_at FROM documents")
    rows = cursor.fetchall()

    count = 0
    for doc_id, created_at in rows:
        try:
            # Parse '2026-02-11 07:35:05'
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            ts = int(dt.timestamp())

            # Update SQLite
            cursor.execute("UPDATE documents SET unix_timestamp = ? WHERE id = ?", (ts, doc_id))

            # Update Qdrant Payload
            # We use 'overwrite' mode for payload update
            q_client.set_payload(
                collection_name=COLLECTION_NAME, payload={"unix_timestamp": ts}, points=[doc_id]
            )

            count += 1
            if count % 200 == 0:
                print(f"  Synced {count} records...")
                conn.commit()
        except Exception as e:
            # print(f"Error for ID {doc_id}: {e}")
            pass

    conn.commit()
    conn.close()
    print(f"[OK] Migration Complete. Updated {count} records with unix_timestamp payload.")


if __name__ == "__main__":
    migrate()
