import sqlite3
import time
import os
import sqlite_vec

db_path = os.path.expanduser("~/.openclaw/workspace/db/memory.db")
conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)

start = time.perf_counter()

# This tests the JOIN efficiency between the Vector table and Document table
# Test the "Spicy Filter" / Air-Gap speed
try:
    print("[INFO] Testing Air-Gap Query Speed...")
    # This query mimics the real-world Air-Gap logic:
    # Filter by Safe Tag AND Valid Vector ID
    res = conn.execute("""
        SELECT d.content 
        FROM documents d 
        WHERE d.hemisphere_tag = 'safe' 
        AND d.id IN (SELECT document_id FROM vec_items LIMIT 10)
    """).fetchall()
    end = time.perf_counter()
    print(f"[TIME] Air-Gap Filter Speed: {(end - start) * 1000:.2f}ms")
    print(f"[OK] Retrieved {len(res)} safe documents instantly.")
except Exception as e:
    print(f"[ERROR] Error: {e}")
