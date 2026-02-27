import os
import sqlite3

import sqlite_vec

# Constants
DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/memory.db")
MAX_DB_SIZE_MB = 100


class DatabaseManager:
    """
    The Single Source of Truth for Database Integrity.
    Handles connection lifecycle, extension loading, and invariant checking.
    Auto-creates the database and schema on first boot.
    """

    _initialized = False

    @staticmethod
    def _ensure_db():
        """Create the database directory and schema if they don't exist."""
        if DatabaseManager._initialized:
            return

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

        if not os.path.exists(DB_PATH):
            print(f"📦 First boot: Creating memory database at {DB_PATH}")
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")

            # Load sqlite-vec extension for virtual table creation
            conn.enable_load_extension(True)
            try:
                sqlite_vec.load(conn)
            except Exception:
                try:
                    conn.load_extension("vec0")
                except Exception as e2:
                    print(f"⚠️ sqlite-vec not available during DB init: {e2}")
                    print("   Vector search will not work until sqlite-vec is installed.")
            conn.enable_load_extension(False)

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    content TEXT NOT NULL,
                    hemisphere_tag TEXT DEFAULT 'safe',
                    content_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_documents_hemisphere
                    ON documents(hemisphere_tag);
            """)

            # Create vector virtual table (requires sqlite-vec extension)
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                        document_id INTEGER,
                        embedding float[768]
                    );
                """)
            except Exception as e:
                print(f"⚠️ Could not create vec_items table: {e}")
                print("   Vector search disabled. Install sqlite-vec to enable.")

            # Create FTS5 virtual table for full-text search
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                        USING fts5(content, content=documents, content_rowid=id);
                """)
            except Exception as e:
                print(f"⚠️ Could not create FTS5 table: {e}")

            conn.commit()
            conn.close()
            print("✅ Memory database initialized successfully.")

        DatabaseManager._initialized = True

    @staticmethod
    def get_connection(journal_mode: str = "WAL") -> sqlite3.Connection:
        """
        Get a configured SQLite connection with extensions loaded.
        Auto-creates the database on first call if it doesn't exist.
        """
        DatabaseManager._ensure_db()

        # Check invariant on every connect (lightweight stat)
        if os.path.exists(DB_PATH):
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            if size_mb > MAX_DB_SIZE_MB:
                print(
                    f"⚠️ WARNING: Database size ({size_mb:.1f}MB) exceeds target ({MAX_DB_SIZE_MB}MB). Running VACUUM recommended."
                )

        conn = sqlite3.connect(DB_PATH)

        # Performance Tuning (WAL Mode as requested)
        conn.execute(f"PRAGMA journal_mode={journal_mode};")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        # Canonical Extension Loading for Mac/Linux
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        except Exception as e:
            # Fallback for manual dylib if package fails (rare but possible in dev envs)
            try:
                conn.load_extension("vec0")
            except Exception as e2:
                print(f"❌ CRITICAL: Failed to load sqlite-vec extension: {e} | {e2}")
                raise

        conn.enable_load_extension(False)
        return conn

    @staticmethod
    def verify_air_gap() -> bool:
        """
        Verifies the Air-Gap integrity by checking tag counts.
        Returns True if both hemispheres exist and are populated.
        """
        conn = DatabaseManager.get_connection()
        try:
            cursor = conn.execute(
                "SELECT hemisphere_tag, count(*) FROM documents GROUP BY hemisphere_tag"
            )
            counts = {row[0]: row[1] for row in cursor.fetchall()}

            safe_count = counts.get("safe", 0)
            spicy_count = counts.get("spicy", 0)

            print(f"🛡️ Air-Gap Status: Safe={safe_count} | Spicy={spicy_count}")

            return not (safe_count == 0 or spicy_count == 0)
        finally:
            conn.close()


def get_db_connection(journal_mode: str = "WAL") -> sqlite3.Connection:
    """Helper wrapper for external scripts"""
    return DatabaseManager.get_connection(journal_mode)


if __name__ == "__main__":
    print("🔬 db.py Self-Test...")
    try:
        conn = get_db_connection()
        print("✅ Connection Successful")

        # Test 1: Extension Check
        vec_version = conn.execute("SELECT vec_version()").fetchone()[0]
        print(f"✅ sqlite-vec loaded (version: {vec_version})")

        # Test 2: Invariant Check
        DatabaseManager.verify_air_gap()

        conn.close()
    except Exception as e:
        print(f"❌ Self-Test Failed: {e}")
