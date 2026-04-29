from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_local_db_path(tag: str) -> Path:
    return Path(__file__).parent / f".{tag}-{uuid.uuid4().hex}.db"


def _table_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def _table_indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def test_user_memory_schema_created_on_first_boot() -> None:
    from sci_fi_dashboard.db import DatabaseManager

    db_path = _make_local_db_path("user-memory-schema")
    try:
        with patch("sci_fi_dashboard.db.DB_PATH", str(db_path)):
            DatabaseManager._initialized = False
            DatabaseManager._ensure_db()
            DatabaseManager._initialized = False

        cols = _table_columns(db_path, "user_memory_facts")
        assert {
            "id",
            "user_id",
            "kind",
            "key",
            "value",
            "summary",
            "confidence",
            "source_doc_id",
            "evidence",
            "status",
            "first_seen",
            "last_seen",
        }.issubset(cols)

        indexes = _table_indexes(db_path, "user_memory_facts")
        assert "idx_user_memory_facts_user_kind_status" in indexes
        assert "idx_user_memory_facts_last_seen" in indexes
        assert "idx_user_memory_facts_source_doc_id" in indexes
    finally:
        if db_path.exists():
            db_path.unlink()


def test_distill_and_upsert_response_style_and_codename() -> None:
    from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

    conn = sqlite3.connect(":memory:")
    try:
        text = (
            "[WhatsApp session - 2026-04-29]\n"
            "User: Keep it short and direct.\n"
            "Me: Noted.\n"
            "User: Call me Nova."
        )
        facts = distill_and_upsert_user_memory_facts(
            conn,
            text=text,
            user_id="agent:creator:whatsapp:dm:+15551230000",
            source_doc_id=101,
        )
        conn.commit()

        assert {(fact.key, fact.value) for fact in facts} == {
            ("response_style", "direct"),
            ("codename", "Nova"),
        }

        rows = conn.execute(
            """
            SELECT kind, key, value, source_doc_id, status
            FROM user_memory_facts
            ORDER BY key
            """
        ).fetchall()
        assert rows == [
            ("identity", "codename", "Nova", 101, "active"),
            ("preference", "response_style", "direct", 101, "active"),
        ]
    finally:
        conn.close()
