import sqlite3
import struct

from synapse_config import SynapseConfig
from tqdm import tqdm

DB_PATH = str(SynapseConfig.load().db_dir / "memory.db")


def finish_facts():
    conn = sqlite3.connect(DB_PATH)
    # On Mac, the extension might be vec0.dylib or loaded via the python package
    conn.enable_load_extension(True)
    try:
        import sqlite_vec

        conn.load_extension(sqlite_vec.loadable_path())
    except:
        conn.load_extension("vec0")  # Fallback to local dylib

    from sci_fi_dashboard.embedding import get_provider

    provider = get_provider()

    cur = conn.cursor()
    cur.execute("SELECT id, content FROM atomic_facts")
    facts = cur.fetchall()

    print(f"[PROC] Finalizing {len(facts)} Atomic Facts on Mac...")
    for f_id, content in tqdm(facts):
        try:
            emb = provider.embed_documents([content[:1024]])[0]
            cur.execute(
                "INSERT OR REPLACE INTO atomic_facts_vec(fact_id, embedding) VALUES (?, ?)",
                (f_id, struct.pack(f"{len(emb)}f", *emb)),
            )
        except Exception as e:
            print(f"[ERROR] Error processing fact {f_id}: {e}")

    conn.commit()
    cur.execute("VACUUM")
    conn.close()
    print("[OK] Memory Fully Synchronized.")


if __name__ == "__main__":
    finish_facts()
