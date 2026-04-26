import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.memory_affect import AffectTags


def _make_engine_with_lancedb(results):
    mock_lance = MagicMock()
    mock_lance.search.return_value = results
    mock_provider = MagicMock()
    mock_provider.info.return_value.name = "test-embedder"
    mock_provider.dimensions = 3
    mock_provider.embed_query.return_value = [0.1, 0.2, 0.3]
    with (
        patch("sci_fi_dashboard.memory_engine.LanceDBVectorStore", return_value=mock_lance),
        patch("sci_fi_dashboard.memory_engine.get_provider", return_value=mock_provider),
    ):
        from sci_fi_dashboard.memory_engine import MemoryEngine

        engine = MemoryEngine()
    return engine, mock_lance


def test_add_memory_writes_affect_row(tmp_path):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.lastrowid = 42
    mock_conn.cursor.return_value = mock_cursor

    with (
        patch("sci_fi_dashboard.memory_engine.get_db_connection", return_value=mock_conn),
        patch("sci_fi_dashboard.memory_engine._resolve_backup_path", return_value=str(tmp_path / "backup.jsonl")),
        patch("sci_fi_dashboard.memory_engine.upsert_memory_affect") as mock_upsert,
    ):
        engine, _ = _make_engine_with_lancedb([])

        result = engine.add_memory("I feel unseen and hurt", "test_cat")

    assert result.get("status") == "stored"
    assert result.get("id") == 42
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.args[1] == 42


def test_query_reranks_by_affect_match():
    now = time.time()
    engine, _ = _make_engine_with_lancedb(
        [
            {
                "id": 1,
                "score": 0.70,
                "metadata": {
                    "text": "old neutral work note",
                    "unix_timestamp": now,
                    "importance": 5,
                },
            },
            {
                "id": 2,
                "score": 0.65,
                "metadata": {
                    "text": "felt ignored and hurt before",
                    "unix_timestamp": now,
                    "importance": 5,
                },
            },
        ]
    )
    mock_conn = MagicMock()

    affect_by_doc = {
        1: AffectTags(),
        2: AffectTags(
            sentiment="negative",
            mood="hurt",
            emotional_intensity=0.8,
            tension_type="neglect",
            user_need="validation",
            response_style_hint="soft",
            confidence=0.9,
        ),
    }

    with (
        patch("sci_fi_dashboard.memory_engine.get_db_connection", return_value=mock_conn),
        patch("sci_fi_dashboard.memory_engine.load_affect_for_doc_ids", return_value=affect_by_doc),
    ):
        result = engine.query("I feel ignored", limit=2)

    assert result["results"][0]["content"] == "felt ignored and hurt before"
    assert result["results"][0]["affect"]["mood"] == "hurt"
    assert "EMOTIONAL MEMORY SIGNALS" in result.get("affect_hints", "")
