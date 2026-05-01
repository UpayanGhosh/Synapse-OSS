import sqlite3

from sci_fi_dashboard.chat_pipeline import (
    _fetch_recent_session_recall_context,
    _message_requests_recent_session_recall,
)


def test_message_requests_recent_session_recall():
    assert _message_requests_recent_session_recall(
        "What was I spiralling about before this fresh session?"
    )
    assert _message_requests_recent_session_recall("Do you remember what we just discussed?")
    assert not _message_requests_recent_session_recall("What is the best TVS service route?")


def test_fetch_recent_session_recall_context_prioritizes_latest_session_doc(tmp_path):
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            content TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO documents(id, filename, content, created_at) VALUES (1, 'session', ?, ?)",
        ("[Telegram session]\nUser: old office politics spiral", "2026-04-30 10:00:00"),
    )
    conn.execute(
        "INSERT INTO documents(id, filename, content, created_at) VALUES (2, 'session', ?, ?)",
        (
            "[Telegram session]\nUser: scared the birthday dinner will get awkward\n"
            "Me: that is stomach theatre",
            "2026-04-30 22:39:13",
        ),
    )
    conn.commit()
    conn.close()

    context = _fetch_recent_session_recall_context(
        "What was I spiralling about before this fresh session?",
        db_path,
        limit=1,
        max_chars=500,
    )

    assert "RECENT ARCHIVED SESSION" in context
    assert "birthday dinner" in context
    assert "old office politics" not in context


def test_recent_session_recall_context_preserves_session_tail(tmp_path):
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            content TEXT,
            created_at TEXT
        )
        """
    )
    long_prefix = "User: old setup detail. " * 80
    latest_tail = "User: scared the birthday dinner will get awkward."
    conn.execute(
        "INSERT INTO documents(id, filename, content, created_at) VALUES (9, 'session', ?, ?)",
        (long_prefix + latest_tail, "2026-04-30 22:39:13"),
    )
    conn.commit()
    conn.close()

    context = _fetch_recent_session_recall_context(
        "What was I spiralling about before this fresh session?",
        db_path,
        limit=1,
        max_chars=500,
    )

    assert "old setup detail" in context
    assert "birthday dinner" in context
