import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
import sqlite3

import sqlite_vec
from synapse_config import SynapseConfig

DB_PATH = str(SynapseConfig.load().db_dir / "memory.db")


def update_schema():
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    cursor = conn.cursor()

    print("Updating 'documents' table...")
    try:
        cursor.execute("ALTER TABLE documents ADD COLUMN processed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        print("Column 'processed' already exists.")

    print("Creating 'atomic_facts' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS atomic_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT,
            content TEXT NOT NULL,
            category TEXT,
            source_doc_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_doc_id) REFERENCES documents(id)
        )
    """)

    print("Creating 'atomic_facts_vec' virtual table...")
    # document_id in vec_items maps to atomic_facts.id here
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS atomic_facts_vec USING vec0(
            fact_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        )
    """)

    print("Creating 'entity_links' table (Knowledge Graph)...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            relation TEXT NOT NULL,
            object TEXT NOT NULL,
            source_fact_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_fact_id) REFERENCES atomic_facts(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[OK] Schema update complete.")


if __name__ == "__main__":
    update_schema()
