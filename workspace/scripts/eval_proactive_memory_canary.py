from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer
from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
from sci_fi_dashboard.sbs.profile.manager import ProfileManager
from sci_fi_dashboard.sbs.profile.sync import sync_user_memory_profile
from sci_fi_dashboard.user_memory_distiller_v2 import UserMemoryDistillerV2

USER_ID = "agent:the_creator:whatsapp:dm:+919999999999"


def run_canary(root: Path, *, seconds_since_last_message: float = 10 * 3600) -> dict:
    """Run a deterministic fresh-DB canary for proactive memory personality."""
    root = Path(root)
    canary_root = root / ".proactive_memory_canary"
    shutil.rmtree(canary_root, ignore_errors=True)
    canary_root.mkdir(parents=True, exist_ok=True)

    try:
        db_path = canary_root / "workspace" / "db" / "memory.db"
        profile_dir = canary_root / "workspace" / "sbs" / "profiles" / "the_creator"
        _create_canary_db(db_path)
        messages = _scripted_messages()

        conn = sqlite3.connect(str(db_path))
        try:
            for index, text in enumerate(messages, start=1):
                doc_id = _insert_document(conn, text, index)
                _insert_affect(conn, doc_id)
            full_transcript = "\n".join(f"User: {message}" for message in messages)
            distiller = UserMemoryDistillerV2(conn)
            distiller.enqueue(user_id=USER_ID, text=full_transcript, source_doc_id=1)
            asyncio.run(distiller.process_pending())
            conn.commit()

            stored = {
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "memory_affect": conn.execute("SELECT COUNT(*) FROM memory_affect").fetchone()[0],
                "user_memory_facts": conn.execute(
                    "SELECT COUNT(*) FROM user_memory_facts WHERE user_id = ?",
                    (USER_ID,),
                ).fetchone()[0],
            }
            retrieval_text = "\n".join(
                row[0]
                for row in conn.execute(
                    """
                    SELECT content
                    FROM documents
                    WHERE content LIKE '%PipelinePilot%' OR content LIKE '%Synapse-OSS%'
                    """
                ).fetchall()
            )
            summaries = [
                row[0]
                for row in conn.execute(
                    "SELECT summary FROM user_memory_facts WHERE user_id = ? ORDER BY kind, key",
                    (USER_ID,),
                ).fetchall()
            ]
        finally:
            conn.close()

        # Simulated restart: new ProfileManager instance, same persisted DB/profile path.
        profile_mgr = ProfileManager(profile_dir)
        sync_user_memory_profile(profile_mgr, user_id=USER_ID, db_path=db_path)
        prompt_after_restart = PromptCompiler(profile_mgr).compile()

        if seconds_since_last_message >= 8 * 3600:
            policy_input = ProactivePolicyInput(
                user_id="the_creator",
                channel_id="whatsapp",
                now_hour=14,
                calendar_events=[{"summary": "Synapse launch review", "start": "15:00"}],
                unread_emails=[{"subject": "urgent Synapse launch"} for _ in range(4)],
                slack_mentions=[{"text": "prod is blocked"}],
                recent_memory_summaries=summaries,
                seconds_since_last_message=seconds_since_last_message,
                emotional_need=0.7,
            )
        else:
            policy_input = ProactivePolicyInput(
                user_id="the_creator",
                channel_id="whatsapp",
                now_hour=14,
                unread_emails=[{"subject": "FYI"}],
                recent_memory_summaries=summaries,
                seconds_since_last_message=seconds_since_last_message,
            )

        decision = ProactivePolicyScorer().score(policy_input)

        return {
            "stored": stored,
            "retrieval": {
                "has_codename": "PipelinePilot" in retrieval_text,
                "has_project": "Synapse-OSS" in retrieval_text,
            },
            "prompt_after_restart": {
                "has_style": "Preferred response style: direct." in prompt_after_restart,
                "has_routine": "standup at 10am every day" in prompt_after_restart,
            },
            "proactive": {
                "should_reach_out": decision.should_reach_out,
                "reason": decision.reason,
                "score": decision.score,
                "has_memory_evidence": "memory" in decision.evidence,
            },
        }
    finally:
        shutil.rmtree(canary_root, ignore_errors=True)


def _scripted_messages() -> list[str]:
    base = [
        "Keep it short and direct. Call me PipelinePilot.",
        "My routine is standup at 10am every day.",
        "Priya is my design partner.",
        "Synapse-OSS is my main project.",
        "Don't call me bro.",
    ]
    fillers = [
        "I am working on proactive memory today.",
        "I care about fast feedback loops.",
        "Please remember stable preferences, not random noise.",
        "I want canary tests after every memory change.",
        "The bot should speak only when useful.",
        "I like senior developer style planning.",
        "Keep implementation phased.",
        "Do not over-explain obvious commands.",
        "I prefer concrete verification evidence.",
        "Track repeated workflows before suggesting skills.",
        "Ask approval before self-modifying.",
        "Preserve privacy boundaries.",
        "Use memory to adapt tone.",
        "Restart should not erase personality.",
        "Same prompt should feel different per user.",
    ]
    return base + fillers


def _create_canary_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                content TEXT NOT NULL,
                hemisphere_tag TEXT DEFAULT 'safe',
                processed INTEGER DEFAULT 0,
                unix_timestamp INTEGER,
                importance INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memory_affect (
                doc_id INTEGER PRIMARY KEY,
                mood TEXT,
                tension_type TEXT,
                user_need TEXT,
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS entity_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                relation TEXT,
                object TEXT,
                source_doc_id INTEGER,
                confidence REAL DEFAULT 1.0,
                archived INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_document(conn: sqlite3.Connection, text: str, index: int) -> int:
    cursor = conn.execute(
        """
        INSERT INTO documents
            (filename, content, hemisphere_tag, processed, unix_timestamp, importance)
        VALUES (?, ?, 'safe', 1, ?, 5)
        """,
        ("canary", f"User: {text}", index),
    )
    return int(cursor.lastrowid)


def _insert_affect(conn: sqlite3.Connection, doc_id: int) -> None:
    conn.execute(
        """
        INSERT INTO memory_affect (doc_id, mood, tension_type, user_need, raw_json)
        VALUES (?, 'focused', 'none', 'clarity', ?)
        """,
        (doc_id, json.dumps({"mood": "focused"})),
    )


if __name__ == "__main__":
    print(json.dumps(run_canary(WORKSPACE_ROOT), indent=2, sort_keys=True))
