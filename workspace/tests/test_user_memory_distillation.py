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


def _entity_links_columns(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(entity_links)").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def _entity_links_indexes(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA index_list(entity_links)").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def test_entity_links_schema_created_on_first_boot() -> None:
    from sci_fi_dashboard.db import DatabaseManager

    db_path = _make_local_db_path("kg-schema")
    try:
        with patch("sci_fi_dashboard.db.DB_PATH", str(db_path)):
            DatabaseManager._initialized = False
            DatabaseManager._ensure_db()
            DatabaseManager._initialized = False

        cols = _entity_links_columns(db_path)
        assert {
            "subject",
            "relation",
            "object",
            "archived",
            "confidence",
            "source_doc_id",
        }.issubset(cols)

        indexes = _entity_links_indexes(db_path)
        assert "idx_entity_links_subject_relation_active" in indexes
        assert "idx_entity_links_source_doc_id" in indexes
    finally:
        if db_path.exists():
            db_path.unlink()


def test_entity_links_schema_migrates_existing_db() -> None:
    from sci_fi_dashboard.db import DatabaseManager

    db_path = _make_local_db_path("kg-migrate")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    content TEXT NOT NULL
                );
                CREATE TABLE entity_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        with patch("sci_fi_dashboard.db.DB_PATH", str(db_path)):
            DatabaseManager._initialized = False
            DatabaseManager._ensure_db()
            DatabaseManager._initialized = False

        cols = _entity_links_columns(db_path)
        assert {"relation", "archived", "confidence", "source_doc_id"}.issubset(cols)

        indexes = _entity_links_indexes(db_path)
        assert "idx_entity_links_subject_relation_active" in indexes
        assert "idx_entity_links_source_doc_id" in indexes
    finally:
        if db_path.exists():
            db_path.unlink()
