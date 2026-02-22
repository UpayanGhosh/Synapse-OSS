import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from filelock import FileLock
from .schema import RawMessage

class ConversationLogger:
    """
    Dual-write logger: JSONL for raw archival, SQLite for indexed queries.
    
    Why both?
    - JSONL: Append-only, human-readable, easy backup, no corruption risk
    - SQLite: Indexed queries for batch processor (by date, sentiment, topic)
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.jsonl_path = data_dir / "raw" / "persistent_log.jsonl"
        self.db_path = data_dir / "indices" / "messages.db"
        self.lock = FileLock(str(self.jsonl_path) + ".lock")
        
        self._init_dirs()
        self._init_db()
    
    def _init_dirs(self):
        (self.data_dir / "raw").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "indices").mkdir(parents=True, exist_ok=True)
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    session_id TEXT,
                    response_to TEXT,
                    char_count INTEGER,
                    word_count INTEGER,
                    has_emoji BOOLEAN,
                    is_question BOOLEAN,
                    rt_sentiment REAL,
                    rt_language TEXT,
                    rt_mood_signal TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON messages(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session 
                ON messages(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_role 
                ON messages(role)
            """)
    
    def log(self, message: RawMessage):
        """Atomic dual-write: JSONL + SQLite."""
        
        # 1. Append to JSONL (with file lock for safety)
        with self.lock:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(message.model_dump_json() + "\\n")
        
        # 2. Insert into SQLite index
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO messages 
                (msg_id, timestamp, role, content, session_id, response_to,
                 char_count, word_count, has_emoji, is_question,
                 rt_sentiment, rt_language, rt_mood_signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.msg_id, message.timestamp.isoformat(), message.role,
                message.content, message.session_id, message.response_to,
                message.char_count, message.word_count, message.has_emoji,
                message.is_question, message.rt_sentiment, message.rt_language,
                message.rt_mood_signal
            ))
    
    def update_realtime_fields(self, msg_id: str, sentiment: float, 
                                language: str, mood: str):
        """Called by realtime processor after initial analysis."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE messages 
                SET rt_sentiment = ?, rt_language = ?, rt_mood_signal = ?
                WHERE msg_id = ?
            """, (sentiment, language, mood, msg_id))
    
    def query_recent(self, hours: int = 24, role: str = None) -> list[dict]:
        """Fetch recent messages for batch processing."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        query = "SELECT * FROM messages WHERE timestamp > ?"
        params = [cutoff]
        if role:
            query += " AND role = ?"
            params.append(role)
        query += " ORDER BY timestamp ASC"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]
    
    def get_message_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
