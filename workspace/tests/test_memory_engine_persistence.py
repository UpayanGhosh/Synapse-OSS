import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapse_cli import app


def _mock_embedder():
    provider = MagicMock()
    provider.info.return_value.name = "test-embedder"
    provider.dimensions = 3
    provider.embed_query.return_value = [0.1, 0.2, 0.3]
    return provider


def test_add_memory_stores_document_when_backup_log_denied(tmp_path):
    from sci_fi_dashboard.memory_engine import MemoryEngine

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.lastrowid = 77
    mock_conn.cursor.return_value = mock_cursor
    mock_lance = MagicMock()

    with (
        patch(
            "sci_fi_dashboard.memory_engine._resolve_backup_path",
            return_value=str(tmp_path / "backup.jsonl"),
        ),
        patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore", return_value=mock_lance),
        patch("sci_fi_dashboard.memory_engine.get_provider", return_value=_mock_embedder()),
        patch("sci_fi_dashboard.memory_engine.get_db_connection", return_value=mock_conn),
        patch("sci_fi_dashboard.memory_engine.upsert_memory_affect"),
    ):
        engine = MemoryEngine()
        with patch("builtins.open", side_effect=OSError("backup write denied")):
            result = engine.add_memory("keep this memory durable", category="test_cat")

    assert result["status"] == "stored"
    assert result["id"] == 77
    assert result["embedded"] is True
    assert "backup write denied" in (result["backup_error"] or "")
    assert mock_conn.commit.called
    assert any(
        "INSERT INTO documents" in (call.args[0] if call.args else "")
        for call in mock_cursor.execute.call_args_list
    )
    mock_lance.upsert_facts.assert_called_once()


def test_memory_save_probe_returns_counts(tmp_path, monkeypatch):
    db_dir = tmp_path / "workspace" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE memory_affect (document_id INTEGER)")
        conn.execute("INSERT INTO documents (id) VALUES (1), (2)")
        conn.execute("INSERT INTO memory_affect (document_id) VALUES (1), (2), (2)")
        conn.commit()

    class _FakeMemoryEngine:
        def add_memory(self, content: str, category: str = "direct_entry", hemisphere: str = "safe"):
            return {
                "status": "stored",
                "id": 123,
                "embedded": True,
                "backup_error": None,
            }

    fake_cfg = SimpleNamespace(db_dir=db_dir)
    monkeypatch.setattr("sci_fi_dashboard.memory_engine.MemoryEngine", _FakeMemoryEngine)
    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: fake_cfg))

    result = CliRunner().invoke(app, ["memory", "save-probe", "--content", "probe content"])

    assert result.exit_code == 0, result.output
    assert "save_result:" in result.output
    assert "documents_count: 2" in result.output
    assert "memory_affect_count: 3" in result.output


def test_memory_save_probe_exits_nonzero_on_add_memory_error(tmp_path, monkeypatch):
    db_dir = tmp_path / "workspace" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "memory.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE memory_affect (document_id INTEGER)")
        conn.commit()

    class _FailingMemoryEngine:
        def add_memory(self, content: str, category: str = "direct_entry", hemisphere: str = "safe"):
            return {"error": "vector write failed"}

    fake_cfg = SimpleNamespace(db_dir=db_dir)
    monkeypatch.setattr("sci_fi_dashboard.memory_engine.MemoryEngine", _FailingMemoryEngine)
    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: fake_cfg))

    result = CliRunner().invoke(app, ["memory", "save-probe", "--content", "probe content"])

    assert result.exit_code == 1, result.output
    assert "save_result:" in result.output
    assert "save_error: vector write failed" in result.output


def test_memory_save_probe_handles_missing_tables(tmp_path, monkeypatch):
    db_dir = tmp_path / "workspace" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "memory.db"
    sqlite3.connect(db_path).close()

    class _OkMemoryEngine:
        def add_memory(self, content: str, category: str = "direct_entry", hemisphere: str = "safe"):
            return {"status": "stored", "id": 9, "embedded": True, "backup_error": None}

    fake_cfg = SimpleNamespace(db_dir=db_dir)
    monkeypatch.setattr("sci_fi_dashboard.memory_engine.MemoryEngine", _OkMemoryEngine)
    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: fake_cfg))

    result = CliRunner().invoke(app, ["memory", "save-probe", "--content", "probe content"])

    assert result.exit_code == 0, result.output
    assert "documents_count: 0 (unavailable:" in result.output
    assert "memory_affect_count: 0 (unavailable:" in result.output
