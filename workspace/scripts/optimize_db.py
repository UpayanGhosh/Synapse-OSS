import sqlite3
import os
import sqlite_vec

db_path = os.path.expanduser("~/.openclaw/workspace/db/memory.db")
conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)

print("Running ANALYZE...")
conn.execute("ANALYZE;")
print("ANALYZE complete.")

print("\nQuery Plan:")
try:
    cursor = conn.execute("EXPLAIN QUERY PLAN SELECT d.content FROM documents d JOIN vec_items v ON d.id = v.document_id LIMIT 100 OFFSET 5000")
    for row in cursor:
        print(row)
except Exception as e:
    print(e)

conn.close()
