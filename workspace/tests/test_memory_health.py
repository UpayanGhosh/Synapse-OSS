"""test_memory_health.py — Tests for ingest failure persistence and /memory_health endpoint.

Covers:
1. test_ingest_failure_persisted_to_db — _ingest_session_background writes a
   phase='vector' row when add_memory raises.
2. test_memory_health_endpoint_shape — /memory_health returns all 6 expected keys.
3. test_memory_health_endpoint_requires_auth — /memory_health returns 401 without token.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_TEST_TOKEN = "test-gateway-token-phase1"


def _patched_auth():
    """Patch SynapseConfig.load so _require_gateway_auth uses our test token."""
    mock_cfg = MagicMock()
    mock_cfg.gateway = {"token": _TEST_TOKEN}
    return patch("synapse_config.SynapseConfig.load", return_value=mock_cfg)


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_TEST_TOKEN}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Fresh memory.db in a temp dir with ingest_failures table created."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content TEXT NOT NULL,
            hemisphere_tag TEXT DEFAULT 'safe',
            content_hash TEXT,
            processed INTEGER DEFAULT 0,
            unix_timestamp INTEGER,
            importance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS entity_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            predicate TEXT,
            object TEXT,
            confidence REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE INDEX IF NOT EXISTS idx_ingest_failures_created_at
            ON ingest_failures(created_at);
        CREATE INDEX IF NOT EXISTS idx_ingest_failures_phase
            ON ingest_failures(phase);
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def tmp_transcript(tmp_path: Path) -> Path:
    """A minimal archived JSONL transcript with one turn."""
    session_dir = tmp_path / "agents" / "the_creator" / "sessions"
    session_dir.mkdir(parents=True)
    archived = session_dir / "sess-abc123.jsonl.deleted.1000000000"
    lines = [
        json.dumps({"role": "user", "content": "hello there"}),
        json.dumps({"role": "assistant", "content": "hi back"}),
    ]
    archived.write_text("\n".join(lines), encoding="utf-8")
    return archived


# ---------------------------------------------------------------------------
# Test 1: failure persisted to DB
# ---------------------------------------------------------------------------


class TestIngestFailurePersistedToDb:
    """_ingest_session_background writes a phase='vector' row when add_memory raises."""

    def test_ingest_failure_persisted_to_db(self, tmp_db: Path, tmp_transcript: Path) -> None:
        import sys  # noqa: PLC0415

        from sci_fi_dashboard.session_ingest import _ingest_session_background

        db_path_str = str(tmp_db)

        # Minimal SynapseConfig mock
        mock_cfg = MagicMock()
        mock_cfg.db_dir = tmp_db.parent
        mock_cfg.kg_extraction.enabled = False  # disable KG so only vector path runs

        # memory_engine.add_memory raises RuntimeError — this is what Phase 1 surfaces
        mock_memory_engine = MagicMock()
        mock_memory_engine.add_memory = MagicMock(side_effect=RuntimeError("boom"))

        # Stub load_messages to return our two messages
        async def _fake_load(path):
            return [
                {"role": "user", "content": "hello there"},
                {"role": "assistant", "content": "hi back"},
            ]

        # _deps is a submodule (sci_fi_dashboard/_deps.py); the late import inside
        # _ingest_session_background resolves through sys.modules at call time.
        # Inject a mock module so the `from sci_fi_dashboard import _deps as deps` sees it.
        mock_deps_module = MagicMock()
        mock_deps_module.memory_engine = mock_memory_engine
        mock_deps_module.brain = MagicMock()
        mock_deps_module.synapse_llm_router = MagicMock()

        real_deps = sys.modules.get("sci_fi_dashboard._deps")
        sys.modules["sci_fi_dashboard._deps"] = mock_deps_module  # type: ignore[assignment]
        try:
            with (
                patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
                patch(
                    "sci_fi_dashboard.multiuser.transcript.load_messages",
                    new=_fake_load,
                ),
            ):
                asyncio.run(
                    _ingest_session_background(
                        archived_path=tmp_transcript,
                        agent_id="the_creator",
                        session_key="sess-abc123",
                        hemisphere="safe",
                    )
                )
        finally:
            if real_deps is None:
                sys.modules.pop("sci_fi_dashboard._deps", None)
            else:
                sys.modules["sci_fi_dashboard._deps"] = real_deps

        conn = sqlite3.connect(db_path_str)
        rows = conn.execute(
            "SELECT phase, exception_type FROM ingest_failures WHERE phase != 'completed'"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, "Expected at least one failure row"
        phases = [r[0] for r in rows]
        exc_types = [r[1] for r in rows]
        assert "vector" in phases, f"Expected phase='vector' row, got: {phases}"
        assert (
            "RuntimeError" in exc_types
        ), f"Expected exception_type='RuntimeError', got: {exc_types}"


# ---------------------------------------------------------------------------
# Test 2: endpoint shape
# ---------------------------------------------------------------------------


class TestMemoryHealthEndpointShape:
    """/memory_health returns all 6 expected keys when rows exist."""

    def _make_app(self, db_path: str, data_root: Path):
        from fastapi import FastAPI
        from sci_fi_dashboard.routes.health import router

        app = FastAPI()
        app.include_router(router)

        # Patch get_db_connection to use our tmp db (no sqlite-vec extension needed)
        def _fake_get_db_connection(journal_mode="WAL"):
            conn = sqlite3.connect(db_path)
            return conn

        mock_cfg = MagicMock()
        mock_cfg.gateway = {"token": _TEST_TOKEN}
        mock_cfg.data_root = data_root

        app.state._test_cfg = mock_cfg
        app.state._fake_conn = _fake_get_db_connection

        return app, mock_cfg, _fake_get_db_connection

    def test_memory_health_endpoint_shape(self, tmp_db: Path, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        db_path_str = str(tmp_db)

        # Seed one row in each relevant table
        conn = sqlite3.connect(db_path_str)
        conn.execute("INSERT INTO documents (content, hemisphere_tag) VALUES ('hello', 'safe')")
        conn.execute(
            "INSERT INTO entity_links (subject, predicate, object, confidence)"
            " VALUES ('A', 'knows', 'B', 0.9)"
        )
        conn.execute(
            "INSERT INTO ingest_failures (phase, session_key) VALUES ('completed', 'sess-1')"
        )
        conn.execute(
            "INSERT INTO ingest_failures (phase, session_key, exception_type, exception_msg)"
            " VALUES ('vector', 'sess-1', 'RuntimeError', 'boom')"
        )
        conn.commit()
        conn.close()

        from fastapi import FastAPI
        from sci_fi_dashboard.routes.health import router

        app = FastAPI()
        app.include_router(router)

        mock_cfg = MagicMock()
        mock_cfg.gateway = {"token": _TEST_TOKEN}
        mock_cfg.data_root = tmp_path  # no agents dir → pending_count = 0

        def _fake_get_db_connection(journal_mode="WAL"):
            return sqlite3.connect(db_path_str)

        with (
            patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
            patch("sci_fi_dashboard.routes.health.get_db_connection", _fake_get_db_connection),
            TestClient(app) as client,
        ):
            resp = client.get("/memory_health", headers=_auth_headers())

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        expected_keys = {
            "last_doc_added_at",
            "last_kg_extraction_at",
            "last_ingest_completed_at",
            "last_ingest_failure_at",
            "pending_session_message_count",
            "recent_failures",
        }
        assert expected_keys <= set(
            data.keys()
        ), f"Missing keys: {expected_keys - set(data.keys())}"
        assert data["last_doc_added_at"] is not None
        assert data["last_kg_extraction_at"] is not None
        assert data["last_ingest_completed_at"] is not None
        assert data["last_ingest_failure_at"] is not None
        assert isinstance(data["pending_session_message_count"], int)
        assert isinstance(data["recent_failures"], list)
        assert len(data["recent_failures"]) >= 1


# ---------------------------------------------------------------------------
# Test 3: auth enforcement
# ---------------------------------------------------------------------------


class TestMemoryHealthEndpointRequiresAuth:
    """/memory_health returns 401 without Authorization header."""

    def test_memory_health_endpoint_requires_auth(self, tmp_db: Path, tmp_path: Path) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sci_fi_dashboard.routes.health import router

        app = FastAPI()
        app.include_router(router)

        mock_cfg = MagicMock()
        mock_cfg.gateway = {"token": _TEST_TOKEN}

        with (
            patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
            TestClient(app) as client,
        ):
            resp = client.get("/memory_health")  # no auth header

        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
