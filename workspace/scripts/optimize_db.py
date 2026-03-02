import os as _os, sys as _sys
_sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
from synapse_config import SynapseConfig

import sqlite3
import os
import sqlite_vec

db_path = str(SynapseConfig.load().db_dir / "memory.db")
conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)

print("Running ANALYZE...")
conn.execute("ANALYZE;")
print("ANALYZE complete.")

print("\nQuery Plan:")
try:
    cursor = conn.execute(
        "EXPLAIN QUERY PLAN SELECT d.content FROM documents d JOIN vec_items v ON d.id = v.document_id LIMIT 100 OFFSET 5000"
    )
    for row in cursor:
        print(row)
except Exception as e:
    print(e)

conn.close()
