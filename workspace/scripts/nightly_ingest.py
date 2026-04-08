import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
import json
import os
import sqlite3
import time
from datetime import datetime

from synapse_config import SynapseConfig
from sci_fi_dashboard.embedding import get_provider
from sci_fi_dashboard.vector_store import LanceDBVectorStore

# --- CONFIGURATION ---
DB_PATH = str(SynapseConfig.load().db_dir / "memory.db")


def get_embedding(text):
    return get_provider().embed_documents([text])[0]


def extract_structured_data(content):
    """Uses Local LLM to extract facts and graph triples."""
    prompt = f"""
    Analyze the following text and extract:
    1. A list of 'atomic_facts' (short, independent statements).
    2. A list of 'relations' as triples [subject, relation, object].
    
    Format as JSON: {{"atomic_facts": [], "relations": [["sub", "rel", "obj"]]}}
    Text: {content}
    """
    try:
        from skills.llm_router import llm

        response_text = llm.generate(prompt)
        return json.loads(response_text)
    except Exception as e:
        print(f"Extraction failed: {e}")
        return {"atomic_facts": [], "relations": []}


def ingest_nightly():
    print(f"[MOON] Starting Nightly Ingestion [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")

    if not os.path.exists(DB_PATH):
        print("Error: DB not found.")
        return

    # ... existing logic ...
    # (I need to be careful with the context here, I'll rewrite the function below to ensure it's correct)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure tables exist
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS atomic_facts (id INTEGER PRIMARY KEY, entity TEXT, content TEXT, category TEXT, source_doc_id INTEGER)"
    )

    # Fetch pending logs (unprocessed documents)
    cursor.execute("SELECT id, content, unix_timestamp FROM documents WHERE processed = 0 LIMIT 50")
    rows = cursor.fetchall()

    if not rows:
        print("No pending logs to ingest.")
        return

    lance_store = LanceDBVectorStore()

    for doc_id, content, ts in rows:
        print(f"  -> Processing document {doc_id}...")
        data = extract_structured_data(content)

        # 1. Update LanceDB (Atomic Facts)
        facts_batch = []
        for fact in data.get("atomic_facts", []):
            vec = get_embedding(fact)
            cursor.execute(
                "INSERT INTO atomic_facts (content, source_doc_id) VALUES (?, ?)", (fact, doc_id)
            )
            fact_id = cursor.lastrowid

            facts_batch.append({
                "id": fact_id,
                "vector": list(vec),
                "metadata": {
                    "text": fact,
                    "source_id": doc_id,
                    "unix_timestamp": ts or int(time.time()),
                },
            })

        if facts_batch:
            lance_store.upsert_facts(facts_batch)

        # 2. Update Knowledge Graph (with Archival Logic)
        for rel_data in data.get("relations", []):
            if not isinstance(rel_data, list) or len(rel_data) < 3:
                continue
            subj, rel, obj = str(rel_data[0]), str(rel_data[1]), str(rel_data[2])

            # SANITY CHECK: Ensure no empty strings to prevent IntegrityError
            if not subj.strip() or not rel.strip() or not obj.strip():
                print(f"  [Warn] Skipping malformed triple: {rel_data}")
                continue
            # ARCHIVAL LOGIC: If (subj, rel) exists, archive the old one
            cursor.execute(
                "UPDATE entity_links SET archived = 1 WHERE subject = ? AND relation = ? AND archived = 0",
                (subj, rel),
            )
            # Insert new edge
            cursor.execute(
                "INSERT INTO entity_links (subject, relation, object, archived) VALUES (?, ?, ?, 0)",
                (subj, rel, obj),
            )

        # Mark processed
        cursor.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
        conn.commit()
        time.sleep(0.5)

    conn.close()
    print("[OK] Nightly Ingestion & Archival Complete.")


if __name__ == "__main__":
    ingest_nightly()
