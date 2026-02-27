import sqlite3
import sqlite_vec
import subprocess
import json
import requests
import os

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")
OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text:latest"

def get_embedding(text):
    response = requests.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text})
    return response.json()["embedding"]

def extract_facts_with_gemini(content):
    prompt = f"""
    Extract key atomic facts, decisions, plans, and entities from the following text.
    Return the result as a JSON array of objects.
    Each object must have:
    - entity: The main subject (e.g., 'primary_user', 'primary_partner', 'Friend Name', 'YourWorkplace')
    - content: The fact itself (concise, atomic)
    - category: (e.g., 'Work', 'Relationship', 'Plan', 'Preference')
    - links: A list of triples [subject, relation, object] for a knowledge graph. (Optional)

    Text:
    {content}

    Only return valid JSON.
    """
    
    # Use gemini-cli for one-shot extraction
    # We use --output-format json if supported by the CLI version
    try:
        result = subprocess.run(
            ["gemini", prompt], 
            capture_output=True, text=True, check=True
        )
        # Clean up possible markdown code blocks
        raw_output = result.stdout.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output[7:-3].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output[3:-3].strip()
            
        return json.loads(raw_output)
    except Exception as e:
        print(f"Error extracting facts: {e}")
        return []

def process_memory():
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    cursor = conn.cursor()

    # Get unprocessed documents
    # Increased limit to 50 for faster progress
    cursor.execute("SELECT id, content FROM documents WHERE processed = 0 LIMIT 50")
    rows = cursor.fetchall()

    if not rows:
        print("No new documents to process.")
        return

    for doc_id, content in rows:
        print(f"Processing doc {doc_id}...")
        facts = extract_facts_with_gemini(content)
        
        for fact in facts:
            entity = fact.get("entity")
            fact_content = fact.get("content")
            category = fact.get("category")
            links = fact.get("links", [])

            # 1. Insert into atomic_facts
            cursor.execute(
                "INSERT INTO atomic_facts (entity, content, category, source_doc_id) VALUES (?, ?, ?, ?)",
                (entity, fact_content, category, doc_id)
            )
            fact_id = cursor.lastrowid

            # 2. Generate embedding and insert into atomic_facts_vec
            embedding = get_embedding(fact_content)
            cursor.execute(
                "INSERT INTO atomic_facts_vec (fact_id, embedding) VALUES (?, ?)",
                (fact_id, sqlite_vec.serialize_float32(embedding))
            )

            # 3. Insert into entity_links
            for link in links:
                if len(link) == 3:
                    cursor.execute(
                        "INSERT INTO entity_links (subject, relation, object, source_fact_id) VALUES (?, ?, ?, ?)",
                        (link[0], link[1], link[2], fact_id)
                    )

        # Mark as processed
        cursor.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
        conn.commit()

    conn.close()
    print("[OK] Batch processing complete.")

if __name__ == "__main__":
    process_memory()
