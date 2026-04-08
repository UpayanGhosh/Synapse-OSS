import os
import sqlite3
import threading

import sqlite_vec

# Embedding dimension constant — single source of truth for all tables and virtual tables.
# Change this when switching to a different embedding model (e.g. 1536 for text-embedding-3-small).
EMBEDDING_DIMENSIONS = 768


# Constants
def _get_db_path() -> str:
    # Import here (not at module top) to allow test monkeypatching of SYNAPSE_HOME
    from synapse_config import SynapseConfig  # noqa: PLC0415

    return str(SynapseConfig.load().db_dir / "memory.db")


DB_PATH = _get_db_path()
MAX_DB_SIZE_MB = 100


def _ensure_sessions_table(conn: sqlite3.Connection) -> None:
    """
    Idempotent migration helper: create the sessions table and its index
    if they do not yet exist. Safe to call on both fresh and existing DBs.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL,
            role          TEXT NOT NULL,
            model         TEXT NOT NULL,
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens  INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
    """)
    conn.commit()


def _ensure_jarvis_tables(conn: sqlite3.Connection) -> None:
    """Create Jarvis-migration and new feature tables (idempotent).

    Called on both first boot and existing DB migrations so all tables
    are guaranteed to exist regardless of install order.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS relationship_memories (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            category        TEXT,
            content         TEXT NOT NULL,
            source_event    TEXT,
            hemisphere_tag  TEXT DEFAULT 'safe',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS roast_vault (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT NOT NULL,
            context     TEXT,
            used_count  INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS gift_date_vault (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name   TEXT NOT NULL,
            category    TEXT,
            context     TEXT,
            source_date TEXT,
            priority    INTEGER DEFAULT 5,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS memory_diary (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            session_id      TEXT,
            user_id         TEXT,
            entry_text      TEXT NOT NULL,
            message_count   INTEGER DEFAULT 0,
            dominant_mood   TEXT,
            peak_tension    REAL DEFAULT 0.0,
            key_topics      TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_diary_user_date
            ON memory_diary(user_id, date);

        CREATE TABLE IF NOT EXISTS structured_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table    TEXT NOT NULL,
            content         TEXT NOT NULL,
            metadata        TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS atomic_facts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entity          TEXT,
            content         TEXT NOT NULL,
            category        TEXT,
            source_doc_id   INTEGER,
            unix_timestamp  INTEGER,
            embedding_model TEXT DEFAULT 'nomic-embed-text',
            embedding_version TEXT DEFAULT 'ollama-v1',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


def _ensure_kg_processed_column(conn: sqlite3.Connection) -> None:
    """Add kg_processed column to documents table if missing (idempotent).

    Separate from processed= (which tracks the old Gemini extraction pipeline).
    All existing documents start at 0 so the new local-LLM extractor picks them up.
    """
    cursor = conn.execute("PRAGMA table_info(documents)")
    columns = {row[1] for row in cursor.fetchall()}
    if "kg_processed" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN kg_processed INTEGER DEFAULT 0")
    conn.commit()


def _ensure_embedding_metadata(conn: sqlite3.Connection) -> None:
    """Add embedding provenance columns if they don't exist yet (idempotent).

    Migrates both `documents` and `atomic_facts` tables to record which model
    produced each embedding and what version of the pipeline was used.
    Safe to call on both fresh and existing databases.
    """
    cursor = conn.execute("PRAGMA table_info(documents)")
    columns = {row[1] for row in cursor.fetchall()}
    if "embedding_model" not in columns:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN embedding_model TEXT DEFAULT 'nomic-embed-text'"
        )
        conn.execute(
            "ALTER TABLE documents ADD COLUMN embedding_version TEXT DEFAULT 'ollama-v1'"
        )
    # Same migration for atomic_facts table (may not exist on all deployments)
    cursor = conn.execute("PRAGMA table_info(atomic_facts)")
    columns = {row[1] for row in cursor.fetchall()}
    if columns and "embedding_model" not in columns:
        conn.execute(
            "ALTER TABLE atomic_facts ADD COLUMN embedding_model TEXT DEFAULT 'nomic-embed-text'"
        )
        conn.execute(
            "ALTER TABLE atomic_facts ADD COLUMN embedding_version TEXT DEFAULT 'ollama-v1'"
        )
    conn.commit()


def validate_embedding_dimension(
    vector: list[float], expected: int = EMBEDDING_DIMENSIONS
) -> None:
    """Raise ValueError if vector has wrong dimension.

    Prevents silent data corruption when the embedding model changes but
    existing rows still have the old dimension schema.
    """
    if len(vector) != expected:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(vector)}, expected {expected}. "
            f"Run 'synapse re-embed' to re-embed all documents with the current provider."
        )


_ALLOWED_JOURNAL_MODES = frozenset({"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY", "OFF"})


class DatabaseManager:
    """
    The Single Source of Truth for Database Integrity.
    Handles connection lifecycle, extension loading, and invariant checking.
    Auto-creates the database and schema on first boot.
    """

    _initialized = False
    _init_lock = threading.Lock()

    @staticmethod
    def _ensure_db():
        """Create the database directory and schema if they don't exist."""
        if DatabaseManager._initialized:
            return

        with DatabaseManager._init_lock:
            # Double-check inside the lock to prevent race
            if DatabaseManager._initialized:
                return

            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

            if not os.path.exists(DB_PATH):
                print(f"[PKG] First boot: Creating memory database at {DB_PATH}")
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
                        print(f"[WARN] sqlite-vec not available during DB init: {e2}")
                        print(
                            "   Vector search will not work until sqlite-vec is installed."
                        )
                conn.enable_load_extension(False)

                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT,
                        content TEXT NOT NULL,
                        hemisphere_tag TEXT DEFAULT 'safe',
                        content_hash TEXT,
                        processed INTEGER DEFAULT 0,
                        unix_timestamp INTEGER,
                        importance INTEGER DEFAULT 5,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_documents_hemisphere
                        ON documents(hemisphere_tag);
                """)

                # Create vector virtual table (requires sqlite-vec extension)
                try:
                    conn.execute(f"""
                        CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                            document_id INTEGER,
                            embedding float[{EMBEDDING_DIMENSIONS}]
                        );
                    """)
                except Exception as e:
                    print(f"[WARN] Could not create vec_items table: {e}")
                    print("   Vector search disabled. Install sqlite-vec to enable.")

                # Create FTS5 virtual table for full-text search
                try:
                    conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                            USING fts5(content, content=documents, content_rowid=id);
                    """)
                except Exception as e:
                    print(f"[WARN] Could not create FTS5 table: {e}")

                _ensure_sessions_table(conn)
                _ensure_embedding_metadata(conn)
                _ensure_jarvis_tables(conn)
                _ensure_kg_processed_column(conn)
                conn.commit()
                conn.close()
                print("[OK] Memory database initialized successfully.")
            else:
                # Existing DB: apply idempotent migrations
                with sqlite3.connect(DB_PATH) as _mig:
                    _ensure_sessions_table(_mig)
                    _ensure_embedding_metadata(_mig)
                    _ensure_jarvis_tables(_mig)
                    _ensure_kg_processed_column(_mig)

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
                    f"[WARN] WARNING: Database size ({size_mb:.1f}MB) exceeds target ({MAX_DB_SIZE_MB}MB). Running VACUUM recommended."
                )

        conn = sqlite3.connect(DB_PATH)

        # Performance Tuning (WAL Mode as requested)
        # Validate journal_mode against allowlist to prevent SQL injection
        jm_upper = journal_mode.upper()
        if jm_upper not in _ALLOWED_JOURNAL_MODES:
            raise ValueError(
                f"Invalid journal_mode '{journal_mode}'. "
                f"Allowed: {sorted(_ALLOWED_JOURNAL_MODES)}"
            )
        conn.execute(f"PRAGMA journal_mode={jm_upper};")
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
                print(f"[ERROR] CRITICAL: Failed to load sqlite-vec extension: {e} | {e2}")
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

            print(f"[GUARD] Air-Gap Status: Safe={safe_count} | Spicy={spicy_count}")

            return not (safe_count == 0 or spicy_count == 0)
        finally:
            conn.close()


def get_db_connection(journal_mode: str = "WAL") -> sqlite3.Connection:
    """Helper wrapper for external scripts"""
    return DatabaseManager.get_connection(journal_mode)


if __name__ == "__main__":
    print("[LAB] db.py Self-Test...")
    try:
        conn = get_db_connection()
        print("[OK] Connection Successful")

        # Test 1: Extension Check
        vec_version = conn.execute("SELECT vec_version()").fetchone()[0]
        print(f"[OK] sqlite-vec loaded (version: {vec_version})")

        # Test 2: Invariant Check
        DatabaseManager.verify_air_gap()

        conn.close()
    except Exception as e:
        print(f"[ERROR] Self-Test Failed: {e}")
