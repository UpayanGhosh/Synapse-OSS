import sqlite3
import os
import sqlite_vec  # This is the key for Mac

DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/memory.db")
TRASH_PATTERNS = [
    "%Phase 2: The Chameleon%",
    "%multi-modal safety classifiers%",
    "%slip past the sensors%",
    "%Research Context flag%",
    "%Google's Gemini models%"
]

def clean_brain():
    conn = sqlite3.connect(DB_PATH)
    
    # --- MAC M1 EXTENSION LOADING ---
    conn.enable_load_extension(True)
    sqlite_vec.load(conn) # Uses the python package to load the dylib correctly
    # --------------------------------
    
    cursor = conn.cursor()
    all_trash_ids = []

    print("🔍 Scanning for ghost data...")
    for pattern in TRASH_PATTERNS:
        cursor.execute("SELECT id, content FROM documents WHERE content LIKE ?", (pattern,))
        results = cursor.fetchall()
        for row_id, content in results:
            print(f"🚩 FOUND: (ID: {row_id})")
            all_trash_ids.append(row_id)

    if not all_trash_ids:
        print("✅ No trash found.")
        conn.close()
        return

    confirm = input(f"⚠️ Delete {len(all_trash_ids)} items? (y/n): ")
    if confirm.lower() == 'y':
        placeholders = ','.join(['?'] * len(all_trash_ids))
        try:
            # We delete from vec_items first so the foreign keys/linkage stay clean
            cursor.execute(f"DELETE FROM vec_items WHERE document_id IN ({placeholders})", all_trash_ids)
            cursor.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", all_trash_ids)
            conn.commit()
            
            print("🧹 Optimizing DB...")
            conn.execute("VACUUM")
            print("✨ Purge complete. Stheno is now free of Gemini's ghost.")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    conn.close()

if __name__ == "__main__":
    clean_brain()