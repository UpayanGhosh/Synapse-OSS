"""
Emotional Trajectory -- Tracks emotional state across sessions.
Uses Peak-End Rule weighting: peaks and most recent entries matter most.
"""

import os
import sqlite3
import time

DB_PATH = os.path.expanduser("~/.openclaw/workspace/db/emotional_trajectory.db")


class EmotionalTrajectory:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS trajectory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            tension_level REAL DEFAULT 0.0,
            tension_type TEXT DEFAULT 'none',
            emotional_state TEXT DEFAULT 'calm',
            topics TEXT DEFAULT '',
            response_strategy TEXT DEFAULT 'acknowledge',
            is_peak INTEGER DEFAULT 0
        )""")
        conn.commit()
        conn.close()

    def record(self, merge, topics: list = None):
        """Record an emotional snapshot after a cognitive merge."""
        conn = sqlite3.connect(self.db_path)
        try:
            is_peak = 1 if merge.tension_level > 0.6 else 0
            topic_str = ",".join((topics or [])[:3])
            conn.execute(
                "INSERT INTO trajectory"
                " (timestamp, tension_level, tension_type, emotional_state,"
                " topics, response_strategy, is_peak)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    merge.tension_level,
                    merge.tension_type,
                    merge.suggested_tone,
                    topic_str,
                    merge.response_strategy,
                    is_peak,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_trajectory(self, hours: int = 72, limit: int = 10) -> list:
        """Get recent emotional trajectory points, Peak-End weighted."""
        conn = sqlite3.connect(self.db_path)
        try:
            cutoff = time.time() - (hours * 3600)
            rows = conn.execute(
                """
                SELECT emotional_state, tension_level, tension_type, topics, timestamp
                FROM trajectory WHERE timestamp > ?
                ORDER BY is_peak DESC, timestamp DESC LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
            return rows
        finally:
            conn.close()

    def get_summary(self, hours: int = 72) -> str:
        """Compact trajectory summary for injection into merge prompt."""
        rows = self.get_trajectory(hours=hours, limit=10)
        if not rows:
            return ""

        lines = []
        for r in rows:
            age_hrs = (time.time() - r[4]) / 3600
            lines.append(
                f"- {age_hrs:.0f}h ago: {r[0]} " f"(tension={r[1]:.1f}, type={r[2]}, topic={r[3]})"
            )

        return "EMOTIONAL TRAJECTORY (last 72h, peaks highlighted):\n" + "\n".join(lines)
