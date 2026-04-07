"""
DiaryEngine — generates and stores structured diary entries per session.

After each session ends (or every N messages), generate a diary entry
summarizing what happened, emotional state, key topics.
Stored in the memory_diary table in memory.db.
File copies stored in ~/.synapse/diary/YYYY-MM-DD.md.
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("synapse.diary")

DIARY_DIR = Path(os.path.expanduser("~/.synapse/diary"))


class DiaryEngine:
    """Generates and stores structured diary entries after each session."""

    def __init__(self, llm_fn=None):
        """
        Args:
            llm_fn: async function (messages, temperature, max_tokens) -> str
                    Injected from api_gateway at startup. Used for AI-generated summaries.
                    If None, entries are generated from structured data only.
        """
        self.llm_fn = llm_fn
        DIARY_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self):
        """Create memory_diary table if missing (idempotent)."""
        try:
            from sci_fi_dashboard.db import DatabaseManager
            conn = DatabaseManager.get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_diary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    entry_text TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    dominant_mood TEXT,
                    peak_tension REAL DEFAULT 0.0,
                    key_topics TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("diary table init: %s", e)

    async def generate_entry(
        self,
        session_id: str,
        user_id: str,
        messages: list[dict],
        cognitive_states: list = None,
    ) -> Optional[str]:
        """
        Generate a diary entry for a completed session.

        Args:
            session_id: Unique session identifier
            user_id: User identifier (e.g., "the_creator")
            messages: List of {role, content} dicts from the conversation
            cognitive_states: Optional list of CognitiveMerge objects for mood tracking

        Returns:
            The generated diary text, or None on failure.
        """
        if not messages:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        asst_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]

        # Extract mood/tension stats from cognitive states
        dominant_mood = "neutral"
        peak_tension = 0.0
        key_topics: list[str] = []
        if cognitive_states:
            tensions = [c.tension_level for c in cognitive_states if hasattr(c, "tension_level")]
            peak_tension = max(tensions) if tensions else 0.0
            tones = [c.suggested_tone for c in cognitive_states if hasattr(c, "suggested_tone") and c.suggested_tone]
            if tones:
                dominant_mood = max(set(tones), key=tones.count)

        # Build entry text
        if self.llm_fn and len(user_msgs) >= 2:
            entry_text = await self._ai_summary(user_id, user_msgs, asst_msgs, today)
        else:
            entry_text = self._structured_entry(
                today, user_id, user_msgs, peak_tension, dominant_mood
            )

        if not entry_text:
            return None

        # Store in DB
        topics_json = json.dumps(key_topics)
        try:
            from sci_fi_dashboard.db import DatabaseManager
            conn = DatabaseManager.get_connection()
            conn.execute(
                """INSERT INTO memory_diary
                   (date, session_id, user_id, entry_text, message_count,
                    dominant_mood, peak_tension, key_topics)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (today, session_id, user_id, entry_text, len(user_msgs),
                 dominant_mood, peak_tension, topics_json),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to store diary entry: %s", e)

        # Write file copy
        try:
            diary_file = DIARY_DIR / f"{today}.md"
            with open(diary_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n## Session {session_id} ({user_id})\n\n{entry_text}\n")
        except Exception as e:
            logger.debug("Diary file write failed: %s", e)

        return entry_text

    async def _ai_summary(
        self, user_id: str, user_msgs: list, asst_msgs: list, date: str
    ) -> str:
        """Generate AI summary of the session."""
        sample_msgs = user_msgs[:5]
        prompt = (
            f"Summarize this conversation from {date} between {user_id} and Synapse (AI). "
            f"Write as a first-person diary entry for Synapse. "
            f"3-4 sentences. Include: main topics, emotional tone, anything notable. "
            f"Don't start with 'Today' or 'I'. Be direct.\n\n"
            f"User messages:\n" + "\n".join(f"- {m[:100]}" for m in sample_msgs)
        )
        try:
            result = await self.llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            return result.strip()
        except Exception as e:
            logger.debug("AI diary generation failed: %s", e)
            return self._structured_entry(date, user_id, user_msgs, 0.0, "neutral")

    def _structured_entry(
        self,
        date: str,
        user_id: str,
        user_msgs: list,
        peak_tension: float,
        dominant_mood: str,
    ) -> str:
        """Fallback: structured entry without AI."""
        msg_count = len(user_msgs)
        sample = user_msgs[0][:80] if user_msgs else "(no messages)"
        return (
            f"Session with {user_id} — {msg_count} messages. "
            f"Peak tension: {peak_tension:.1f}. Dominant mood: {dominant_mood}. "
            f"First message: \"{sample}...\""
        )

    def get_recent_entries(self, user_id: str, days: int = 7) -> list[dict]:
        """Retrieve recent diary entries for context injection."""
        try:
            from sci_fi_dashboard.db import DatabaseManager
            conn = DatabaseManager.get_connection()
            cutoff = datetime.now().strftime("%Y-%m-%d")
            rows = conn.execute(
                """SELECT date, entry_text, dominant_mood, peak_tension
                   FROM memory_diary
                   WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, days),
            ).fetchall()
            conn.close()
            return [{"date": r[0], "text": r[1], "mood": r[2], "tension": r[3]} for r in rows]
        except Exception:
            return []
