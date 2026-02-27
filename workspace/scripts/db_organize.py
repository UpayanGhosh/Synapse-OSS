import sqlite3
import sqlite_vec
import os

OPENCLAW_HOME = os.path.expanduser("~/.openclaw")
DB_PATH = os.path.join(OPENCLAW_HOME, "workspace", "db", "memory.db")


def organize():
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    cursor = conn.cursor()

    print("Checking for exact duplicates...")
    cursor.execute("""
        DELETE FROM vec_items 
        WHERE document_id IN (
            SELECT id FROM documents 
            WHERE id NOT IN (SELECT MIN(id) FROM documents GROUP BY content)
        )
    """)
    cursor.execute("""
        DELETE FROM documents 
        WHERE id NOT IN (SELECT MIN(id) FROM documents GROUP BY content)
    """)
    conn.commit()
    print("Duplicates removed.")

    print("Cleaning binary/Base64 noise...")
    # Find items with very long strings and no spaces
    cursor.execute(
        "SELECT id FROM documents WHERE length(content) > 100 AND instr(content, ' ') = 0"
    )
    bad_ids = [row[0] for row in cursor.fetchall()]
    if bad_ids:
        print(f"Found {len(bad_ids)} binary garbage items. Deleting...")
        cursor.execute(
            f"DELETE FROM vec_items WHERE document_id IN ({','.join(['?']*len(bad_ids))})", bad_ids
        )
        cursor.execute(
            f"DELETE FROM documents WHERE id IN ({','.join(['?']*len(bad_ids))})", bad_ids
        )
        conn.commit()

    print("Optimizing tables...")
    cursor.execute("ANALYZE")
    cursor.execute("VACUUM")

    print("Rebuilding FTS index...")
    cursor.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")

    conn.commit()
    conn.close()
    print("[OK] Database optimization complete.")


if __name__ == "__main__":
    organize()
