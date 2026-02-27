import os
import json
import sqlite3
import requests
import subprocess
import time
from datetime import datetime
import ollama
from qdrant_client import QdrantClient
from qdrant_client.http import models

# --- CONFIGURATION ---
OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")
EMBEDDING_MODEL = 'nomic-embed-text'
THINK_MODEL = 'llama3.2:3b'

def get_embedding(text):
    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text)
    return response['embedding']

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
        response = ollama.chat(model=THINK_MODEL, messages=[{"role": "user", "content": prompt}], format="json")
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"Extraction failed: {e}")
        return {"atomic_facts": [], "relations": []}

def ingest_nightly():
    print(f"🌙 Starting Nightly Ingestion [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    
    if not os.path.exists(DB_PATH):
        print("Error: DB not found.")
        return

    # ... existing logic ...
    # (I need to be careful with the context here, I'll rewrite the function below to ensure it's correct)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Ensure tables exist
    cursor.execute("CREATE TABLE IF NOT EXISTS atomic_facts (id INTEGER PRIMARY KEY, entity TEXT, content TEXT, category TEXT, source_doc_id INTEGER)")
    
    # Fetch pending logs (unprocessed documents)
    cursor.execute("SELECT id, content, unix_timestamp FROM documents WHERE processed = 0 LIMIT 50")
    rows = cursor.fetchall()
    
    if not rows:
        print("No pending logs to ingest.")
        return

    qdrant = QdrantClient(host="localhost", port=6333)
    
    for doc_id, content, ts in rows:
        print(f"  -> Processing document {doc_id}...")
        data = extract_structured_data(content)
        
        # 1. Update Qdrant (Atomic Facts)
        points = []
        for fact in data.get('atomic_facts', []):
            vec = get_embedding(fact)
            cursor.execute(
                "INSERT INTO atomic_facts (content, source_doc_id) VALUES (?, ?)",
                (fact, doc_id)
            )
            fact_id = cursor.lastrowid
            
            points.append(models.PointStruct(
                id=fact_id,
                vector=vec,
                payload={
                    "text": fact, 
                    "source_id": doc_id, 
                    "unix_timestamp": ts or int(time.time())
                }
            ))
        
        if points:
            qdrant.upsert(collection_name="atomic_facts", points=points)

        # 2. Update Knowledge Graph (with Archival Logic)
        for rel_data in data.get('relations', []):
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
                (subj, rel)
            )
            # Insert new edge
            cursor.execute(
                "INSERT INTO entity_links (subject, relation, object, archived) VALUES (?, ?, ?, 0)",
                (subj, rel, obj)
            )

        # Mark processed
        cursor.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
        conn.commit()
        time.sleep(0.5)

    conn.close()
    print("✅ Nightly Ingestion & Archival Complete.")

if __name__ == "__main__":
    ingest_nightly()
