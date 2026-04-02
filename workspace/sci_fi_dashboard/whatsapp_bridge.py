"""WhatsApp bridge SQLite store for inbound message tracking."""
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bridge DB path — same as in api_gateway.py
BRIDGE_DB_PATH = Path(__file__).resolve().with_name("whatsapp_bridge.db")


def normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(ch for ch in str(raw) if ch.isdigit())


def ensure_bridge_db() -> None:
    BRIDGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbound_messages (
                message_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                from_phone TEXT NOT NULL,
                to_phone TEXT,
                conversation_id TEXT,
                text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_id TEXT,
                reply TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.commit()


def get_inbound_message(message_id: str) -> dict[str, Any] | None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM inbound_messages WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    return dict(row) if row else None


def insert_inbound_message(
    *,
    message_id: str,
    channel: str,
    from_phone: str,
    to_phone: str | None,
    conversation_id: str | None,
    text: str,
    status: str,
) -> None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO inbound_messages
            (message_id, channel, from_phone, to_phone, conversation_id, text, status,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (message_id, channel, from_phone, to_phone, conversation_id, text, status),
        )
        conn.commit()


def update_inbound_message(
    message_id: str,
    *,
    status: str | None = None,
    task_id: str | None = None,
    reply: str | None = None,
    error: str | None = None,
) -> None:
    ensure_bridge_db()
    with sqlite3.connect(BRIDGE_DB_PATH) as conn:
        conn.execute(
            """
            UPDATE inbound_messages
            SET status = COALESCE(?, status),
                task_id = COALESCE(?, task_id),
                reply = COALESCE(?, reply),
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE message_id = ?
            """,
            (status, task_id, reply, error, message_id),
        )
        conn.commit()
