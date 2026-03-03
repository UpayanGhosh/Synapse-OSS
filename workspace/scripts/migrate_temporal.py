import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
import sqlite3
from datetime import datetime

from qdrant_client import QdrantClient
from synapse_config import SynapseConfig

# Paths
DB_PATH = str(SynapseConfig.load().db_dir / "memory.db")
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
        except Exception:
            # print(f"Error for ID {doc_id}: {e}")
            pass

    conn.commit()
    conn.close()
    print(f"[OK] Migration Complete. Updated {count} records with unix_timestamp payload.")


if __name__ == "__main__":
    migrate()
