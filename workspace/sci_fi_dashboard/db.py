import sqlite3
import os
import sqlite_vec
import time
from typing import Literal, Tuple, Optional

# Constants
DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/memory.db")
MAX_DB_SIZE_MB = 100

class DatabaseManager:
    """
    The Single Source of Truth for Database Integriy.
    Handles connection lifecycle, extension loading, and invariant checking.
    """
    
    @staticmethod
    def get_connection(journal_mode: str = "WAL") -> sqlite3.Connection:
        """
        Get a configured SQLite connection with extensions loaded.
        """
        if not os.path.exists(DB_PATH):
             raise FileNotFoundError(f"CRITICAL: memory.db not found at {DB_PATH}")

        # Check invariant on every connect (lightweight stat)
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        if size_mb > MAX_DB_SIZE_MB:
            print(f"⚠️ WARNING: Database size ({size_mb:.1f}MB) exceeds target ({MAX_DB_SIZE_MB}MB). Running VACUUM recommended.")

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
            cursor = conn.execute("SELECT hemisphere_tag, count(*) FROM documents GROUP BY hemisphere_tag")
            counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            safe_count = counts.get('safe', 0)
            spicy_count = counts.get('spicy', 0)
            
            print(f"🛡️ Air-Gap Status: Safe={safe_count} | Spicy={spicy_count}")
            
            if safe_count == 0 or spicy_count == 0:
                 return False
            return True
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
