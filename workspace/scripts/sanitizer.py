import sqlite3
import os
import json
import re

# --- CONFIGURATION ---
DB_PATH = "db/memory.db"
OUTPUT_DB = "db/memory_sanitized.db"
SENSITIVE_KEYWORDS = ["User Name", "Personal Name", "Nickname", "Email", "Phone", "Partner", "Secret", "Password", "Key"]

def sanitize_memory():
    print("[PROC] Initializing Soul Sanitizer Protocol...")
    
    if not os.path.exists(DB_PATH):
        print("[ERROR] Error: Original memory.db not found.")
        return

    # Create a copy for sanitization
    import shutil
    shutil.copyfile(DB_PATH, OUTPUT_DB)
    
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()

    # 1. Wipe purely personal tables
    tables_to_wipe = ["relationship_memories", "sentiment_logs", "gift_date_vault", "life_checkin"]
    for table in tables_to_wipe:
        print(f"[CLEAN] Wiping table: {table}...")
        cursor.execute(f"DELETE FROM {table}")

    # 2. Anonymize the Users table (Keep only Tier 0 structure)
    print("[USER] Anonymizing user profiles...")
    cursor.execute("UPDATE users SET phone_number = 'TEMPLATE_USER', name = 'Host', tier = 0, privileges = 'GOD_MODE'")

    # 3. Scrub the Documents table (High-intensity pattern matching)
    print("[LOG] Scrubbing conversation history...")
    cursor.execute("SELECT id, content FROM documents")
    rows = cursor.fetchall()
    
    for doc_id, content in rows:
        # Simple keyword replacement
        sanitized_content = content
        for word in SENSITIVE_KEYWORDS:
            sanitized_content = re.sub(rf"(?i){word}", "[REDACTED]", sanitized_content)
        
        cursor.execute("UPDATE documents SET content = ? WHERE id = ?", (sanitized_content, doc_id))

    # 4. Final Vacuum
    print("[ATOM]  Executing recursive entropy reduction (Vacuum)...")
    conn.execute("VACUUM")
    conn.commit()
    conn.close()

    print(f"\n[OK] Sanitization Complete. Path: {OUTPUT_DB}")
    print("[WARN]  Manual Check Recommended: Verify 'Operating Wisdom' is intact but secrets are gone.")

if __name__ == "__main__":
    sanitize_memory()
