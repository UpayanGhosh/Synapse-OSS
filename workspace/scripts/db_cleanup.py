import sqlite3
import sqlite_vec
import os

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")

def cleanup():
    print(f"Opening database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    
    cursor = conn.cursor()
    
    # 1. Identify Junk
    junk_patterns = [
        '%end-to-end encrypted%',
        '%This message was deleted%',
        '%Messages and calls are end-to-end encrypted%',
        '%omit media%',
        '%attached file%'
    ]
    
    total_deleted = 0
    for pattern in junk_patterns:
        # Get IDs first
        cursor.execute("SELECT id FROM documents WHERE content LIKE ?", (pattern,))
        ids = [row[0] for row in cursor.fetchall()]
        
        if not ids:
            continue
            
        print(f"Pattern '{pattern}': Found {len(ids)} junk items. Deleting...")
        
        # Delete from Vector Table
        cursor.execute(f"DELETE FROM vec_items WHERE document_id IN ({','.join(['?']*len(ids))})", ids)
        
        # Delete from Documents Table
        cursor.execute(f"DELETE FROM documents WHERE id IN ({','.join(['?']*len(ids))})", ids)
        
        total_deleted += len(ids)
    
    print(f"Cleaning up FTS index...")
    cursor.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
    
    conn.commit()
    
    print("Running VACUUM to reclaim space...")
    cursor.execute("VACUUM")
    
    conn.close()
    print(f"✅ Cleanup complete. Total items removed: {total_deleted}")

if __name__ == "__main__":
    cleanup()
