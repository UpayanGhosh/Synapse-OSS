import sqlite3
import os
import struct
import json
import urllib.request
from tqdm import tqdm

DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/memory.db")


def finish_facts():
    conn = sqlite3.connect(DB_PATH)
    # On Mac, the extension might be vec0.dylib or loaded via the python package
    conn.enable_load_extension(True)
    try:
        import sqlite_vec

        conn.load_extension(sqlite_vec.loadable_path())
    except:
        conn.load_extension("vec0")  # Fallback to local dylib

    cur = conn.cursor()
    cur.execute("SELECT id, content FROM atomic_facts")
    facts = cur.fetchall()

    print(f"[PROC] Finalizing {len(facts)} Atomic Facts on Mac...")
    for f_id, content in tqdm(facts):
        try:
            payload = json.dumps({"model": "nomic-embed-text", "input": [content[:1024]]}).encode(
                "utf-8"
            )
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                if "embeddings" in data and len(data["embeddings"]) > 0:
                    emb = data["embeddings"][0]
                    # Ensure embedding is 768 dimensions
                    if len(emb) == 768:
                        cur.execute(
                            "INSERT OR REPLACE INTO atomic_facts_vec(fact_id, embedding) VALUES (?, ?)",
                            (f_id, struct.pack("768f", *emb)),
                        )
                    else:
                        print(f"[WARN] Fact {f_id}: dimension mismatch {len(emb)}")
                else:
                    print(f"[WARN] Fact {f_id}: no embedding returned")
        except Exception as e:
            print(f"[ERROR] Error processing fact {f_id}: {e}")

    conn.commit()
    cur.execute("VACUUM")
    conn.close()
    print("[OK] Memory Fully Synchronized.")


if __name__ == "__main__":
    finish_facts()
