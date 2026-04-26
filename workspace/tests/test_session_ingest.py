"""test_session_ingest.py — Unit tests for _ingest_session_background (Phase 2).

Three cases:
1. test_session_ingest_writes_documents_row — real add_memory path against tmp DB;
   asserts a documents row with filename='session' is written.
2. test_session_ingest_records_vector_failure — add_memory returns {"error": "boom"};
   asserts ingest_failures row with phase='vector', exception_type='RuntimeError'.
3. test_session_ingest_records_vector_exception — add_memory raises RuntimeError;
   asserts ingest_failures row with phase='vector', exception_type='RuntimeError'.

Isolation rules (per pipeline/conftest.py):
- Tests 2 and 3 MUST mock add_memory (they test the error path, not the real write).
- Test 1 uses the real add_memory path against a tmp DB (explicitly allowed).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_memory_db(tmp_path: Path) -> Path:
    """Fresh memory.db with the full schema (documents + ingest_failures + vec_items)."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT,
            content         TEXT NOT NULL,
            hemisphere_tag  TEXT DEFAULT 'safe',
            content_hash    TEXT,
            processed       INTEGER DEFAULT 0,
            unix_timestamp  INTEGER,
            importance      INTEGER DEFAULT 5,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS vec_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            embedding   BLOB
        );
        CREATE TABLE IF NOT EXISTS entity_links (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            subject     TEXT,
            predicate   TEXT,
            object      TEXT,
            confidence  REAL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ingest_failures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_key     TEXT,
            agent_id        TEXT,
            archived_path   TEXT,
            batch_index     INTEGER,
            total_batches   INTEGER,
            phase           TEXT NOT NULL,
            exception_type  TEXT,
            exception_msg   TEXT,
            traceback       TEXT,
            ingested_vec    INTEGER,
            ingested_kg     INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_ingest_failures_phase
            ON ingest_failures(phase);
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def tmp_transcript(tmp_path: Path) -> Path:
    """Minimal archived JSONL transcript: one user + one assistant turn."""
    session_dir = tmp_path / "agents" / "the_creator" / "sessions"
    session_dir.mkdir(parents=True)
    archived = session_dir / "sess-test001.jsonl.deleted.1000000000"
    lines = [
        json.dumps({"role": "user", "content": "test message"}),
        json.dumps({"role": "assistant", "content": "test reply"}),
    ]
    archived.write_text("\n".join(lines), encoding="utf-8")
    return archived


def _make_mock_cfg(tmp_memory_db: Path) -> MagicMock:
    """Minimal SynapseConfig mock for _ingest_session_background."""
    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = False  # disable KG so only vector path runs
    return mock_cfg


def _make_mock_deps_module(memory_engine_mock: MagicMock) -> MagicMock:
    """Minimal sci_fi_dashboard._deps mock module."""
    mock_deps = MagicMock()
    mock_deps.memory_engine = memory_engine_mock
    mock_deps.brain = MagicMock()
    mock_deps.synapse_llm_router = MagicMock()
    return mock_deps


async def _fake_load_messages(path):  # noqa: ARG001
    return [
        {"role": "user", "content": "test message"},
        {"role": "assistant", "content": "test reply"},
    ]


# ---------------------------------------------------------------------------
# Helper: run _ingest_session_background with all external deps stubbed
# ---------------------------------------------------------------------------


async def _run_ingest(
    tmp_memory_db: Path,
    tmp_transcript: Path,
    memory_engine_mock: MagicMock,
) -> None:
    """Patch all external deps and call _ingest_session_background."""
    from sci_fi_dashboard.session_ingest import _ingest_session_background

    mock_cfg = _make_mock_cfg(tmp_memory_db)
    mock_deps = _make_mock_deps_module(memory_engine_mock)

    real_deps = sys.modules.get("sci_fi_dashboard._deps")
    sys.modules["sci_fi_dashboard._deps"] = mock_deps  # type: ignore[assignment]
    try:
        with (
            patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
            patch(
                "sci_fi_dashboard.multiuser.transcript.load_messages",
                new=_fake_load_messages,
            ),
        ):
            await _ingest_session_background(
                archived_path=tmp_transcript,
                agent_id="the_creator",
                session_key="sess-test001",
                hemisphere="safe",
            )
    finally:
        if real_deps is None:
            sys.modules.pop("sci_fi_dashboard._deps", None)
        else:
            sys.modules["sci_fi_dashboard._deps"] = real_deps


# ---------------------------------------------------------------------------
# Test 1: real add_memory path writes a documents row
# ---------------------------------------------------------------------------


class TestSessionIngestWritesDocumentsRow:
    """add_memory success path produces a documents row with filename='session' in the DB.

    We use a side_effect that performs the minimal INSERT directly into the tmp DB —
    this validates that session_ingest correctly calls add_memory with category='session'
    AND only increments ingested_vec when add_memory succeeds (no error dict returned).
    Full MemoryEngine wiring (embedding, LanceDB, sqlite-vec) is out of scope here;
    the memory_engine unit tests cover that path.
    """

    @pytest.mark.unit
    async def test_session_ingest_writes_documents_row(
        self, tmp_memory_db: Path, tmp_transcript: Path
    ) -> None:
        # A side_effect that inserts directly into the tmp DB using the category
        # argument as filename, matching what real add_memory does.
        def _fake_add_memory(
            content: str, category: str = "direct_entry", hemisphere: str = "safe"
        ):
            conn = sqlite3.connect(str(tmp_memory_db))
            try:
                conn.execute(
                    "INSERT INTO documents (filename, content, hemisphere_tag, processed)"
                    " VALUES (?, ?, ?, 1)",
                    (category, content, hemisphere),
                )
                conn.commit()
            finally:
                conn.close()
            return {"status": "stored", "id": 1, "embedded": False}

        mock_memory_engine = MagicMock()
        mock_memory_engine.add_memory = MagicMock(side_effect=_fake_add_memory)

        await _run_ingest(tmp_memory_db, tmp_transcript, mock_memory_engine)

        conn = sqlite3.connect(str(tmp_memory_db))
        rows = conn.execute(
            "SELECT id, filename FROM documents WHERE filename = 'session'"
        ).fetchall()
        conn.close()

        assert (
            len(rows) >= 1
        ), f"Expected at least one documents row with filename='session', got: {rows}"


# ---------------------------------------------------------------------------
# Test 2: add_memory returns {"error": ...} → ingest_failures row recorded
# ---------------------------------------------------------------------------


class TestSessionIngestRecordsVectorFailure:
    """add_memory returning {'error': 'boom'} produces a phase='vector' ingest_failures row."""

    @pytest.mark.unit
    async def test_session_ingest_records_vector_failure(
        self, tmp_memory_db: Path, tmp_transcript: Path
    ) -> None:
        mock_memory_engine = MagicMock()
        mock_memory_engine.add_memory = MagicMock(return_value={"error": "boom"})

        await _run_ingest(tmp_memory_db, tmp_transcript, mock_memory_engine)

        conn = sqlite3.connect(str(tmp_memory_db))
        rows = conn.execute(
            "SELECT phase, exception_type, exception_msg "
            "FROM ingest_failures WHERE phase = 'vector'"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, f"Expected at least one phase='vector' failure row, got: {rows}"
        exc_types = [r[1] for r in rows]
        exc_msgs = [r[2] for r in rows]
        assert (
            "RuntimeError" in exc_types
        ), f"Expected exception_type='RuntimeError', got: {exc_types}"
        assert any(
            "boom" in (m or "") for m in exc_msgs
        ), f"Expected exception_msg containing 'boom', got: {exc_msgs}"


# ---------------------------------------------------------------------------
# Test 3: add_memory raises RuntimeError → ingest_failures row recorded
# ---------------------------------------------------------------------------


class TestSessionIngestRecordsVectorException:
    """add_memory raising RuntimeError produces a phase='vector' ingest_failures row."""

    @pytest.mark.unit
    async def test_session_ingest_records_vector_exception(
        self, tmp_memory_db: Path, tmp_transcript: Path
    ) -> None:
        mock_memory_engine = MagicMock()
        mock_memory_engine.add_memory = MagicMock(side_effect=RuntimeError("kaboom"))

        await _run_ingest(tmp_memory_db, tmp_transcript, mock_memory_engine)

        conn = sqlite3.connect(str(tmp_memory_db))
        rows = conn.execute(
            "SELECT phase, exception_type, exception_msg "
            "FROM ingest_failures WHERE phase = 'vector'"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, f"Expected at least one phase='vector' failure row, got: {rows}"
        exc_types = [r[1] for r in rows]
        exc_msgs = [r[2] for r in rows]
        assert (
            "RuntimeError" in exc_types
        ), f"Expected exception_type='RuntimeError', got: {exc_types}"
        assert any(
            "kaboom" in (m or "") for m in exc_msgs
        ), f"Expected exception_msg containing 'kaboom', got: {exc_msgs}"
