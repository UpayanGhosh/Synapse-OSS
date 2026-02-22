import sqlite3
import argparse
import sys
import os

DB_PATH = "./db/memory.db"

def log_dsa_problem(name, logic, code, complexity):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Ensure table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dsa_logic_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_name TEXT NOT NULL,
            logic_description TEXT,
            code_snippet TEXT,
            complexity TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        INSERT INTO dsa_logic_journal (problem_name, logic_description, code_snippet, complexity)
        VALUES (?, ?, ?, ?)
    """, (name, logic, code, complexity))
    
    conn.commit()
    conn.close()
    print(f"✅ Success: '{name}' logged to DSA Journal.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis DSA Logger")
    parser.add_argument("--name", required=True, help="Problem Name")
    parser.add_argument("--logic", required=True, help="Logical Description")
    parser.add_argument("--code", required=True, help="Solution Code Snippet")
    parser.add_argument("--complexity", required=True, help="Time/Space Complexity")
    
    args = parser.parse_args()
    log_dsa_problem(args.name, args.logic, args.code, args.complexity)
