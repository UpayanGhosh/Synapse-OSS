"""
Emotional Trajectory Engine — tracks emotional arc over time.

Records tension, tone, and topics after every DualCognition merge.
Injected into merge prompt as 72h peak-end weighted trajectory.

Stored in a dedicated SQLite DB (~/.synapse/workspace/db/emotional_trajectory.db)
so it is independent of memory.db and easily resettable.
"""

import logging
import os
import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.dual_cognition import CognitiveMerge

logger = logging.getLogger("synapse.trajectory")

_DEFAULT_DB_PATH = os.path.expanduser("~/.synapse/workspace/db/emotional_trajectory.db")


class EmotionalTrajectory:
    """Tracks emotional tension arc across conversations.

    Records every DualCognition merge and provides a 72h peak-end
    weighted summary for injection into the merge prompt.

    DB schema (trajectory table):
        id, timestamp, tension_level, tension_type, emotional_state,
        topics, response_strategy, is_peak
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: Path to the SQLite DB. Defaults to
                     ~/.synapse/workspace/db/emotional_trajectory.db.
                     Override in tests to use a temp path.
        """
        if db_path is None:
            db_path = _DEFAULT_DB_PATH
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create the trajectory table if it does not exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trajectory (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         REAL NOT NULL,
                tension_level     REAL DEFAULT 0.0,
                tension_type      TEXT DEFAULT 'none',
                emotional_state   TEXT,
                topics            TEXT,
                response_strategy TEXT,
                is_peak           INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_traj_ts ON trajectory(timestamp)")
        conn.commit()
        conn.close()

    def record(self, merge: "CognitiveMerge", topics: list = None) -> None:
        """Record a cognition merge to the trajectory.

        Args:
            merge: CognitiveMerge from DualCognitionEngine.think().
                   Reads tension_level, tension_type, suggested_tone,
                   and response_strategy.
            topics: Optional topic list from PresentStream.
        """
        try:
            is_peak = 1 if merge.tension_level > 0.6 else 0
            topics_str = ",".join(str(t) for t in (topics or [])[:3])
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT INTO trajectory
                   (timestamp, tension_level, tension_type,
                    emotional_state, topics, response_strategy, is_peak)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    merge.tension_level,
                    merge.tension_type,
                    merge.suggested_tone,
                    topics_str,
                    getattr(merge, "response_strategy", ""),
                    is_peak,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("Trajectory record failed: %s", e)

    def get_trajectory(self, hours: int = 72, limit: int = 10) -> list:
        """Return raw trajectory rows for the given time window.

        Returns list of (emotional_state, tension_level, tension_type,
                         topics, timestamp) tuples.
        Ordered by is_peak DESC, timestamp DESC (peak-end weighted).
        """
        try:
            cutoff = time.time() - (hours * 3600)
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT emotional_state, tension_level, tension_type, topics, timestamp
                   FROM trajectory
                   WHERE timestamp > ?
                   ORDER BY is_peak DESC, timestamp DESC LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.debug("Trajectory get_trajectory failed: %s", e)
            return []

    def get_summary(self, hours: int = 72, limit: int = 10) -> str:
        """Get human-readable trajectory summary for prompt injection.

        Called by DualCognitionEngine._merge_streams() to inject emotional
        context into the merge prompt.

        Returns:
            Formatted string with peak-end weighted trajectory, or "" if empty.
        """
        rows = self.get_trajectory(hours=hours, limit=limit)
        if not rows:
            return ""

        lines = []
        for r in rows:
            age_hrs = (time.time() - r[4]) / 3600
            lines.append(
                f"- {age_hrs:.0f}h ago: {r[0]} " f"(tension={r[1]:.1f}, type={r[2]}, topic={r[3]})"
            )

        return "EMOTIONAL TRAJECTORY (last 72h, peaks highlighted):\n" + "\n".join(lines)
