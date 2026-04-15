"""
Test Suite: SBS Vacuum
======================
Tests for the SBS maintenance vacuum utility.

Covers:
- SQLite VACUUM reclaims space
- Profile archive pruning
- Edge cases: missing DB, no archive, fewer versions than limit
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sbs.ingestion.schema import RawMessage  # noqa: F401
from sci_fi_dashboard.sbs.vacuum import vacuum_sbs


class TestVacuumSBS:
    """Tests for the vacuum_sbs maintenance function."""

    @pytest.fixture
    def vacuum_env(self, tmp_path):
        """Create a data directory with a messages DB and profile archive."""
        data_dir = tmp_path / "data"
        indices_dir = data_dir / "indices"
        indices_dir.mkdir(parents=True)
        archive_dir = data_dir / "profiles" / "archive"
        archive_dir.mkdir(parents=True)

        # Create and populate a SQLite DB
        db_path = indices_dir / "messages.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL
                )
            """)
            for i in range(100):
                conn.execute(
                    "INSERT INTO messages VALUES (?, ?)",
                    (f"msg-{i}", f"Content for message {i}" * 10),
                )
            conn.commit()

        # Create some profile versions
        for v in range(15):
            v_dir = archive_dir / f"v_{v:04d}_2025-01-{v+1:02d}T00-00"
            v_dir.mkdir()
            (v_dir / "meta.json").write_text('{"version": ' + str(v) + "}")

        return str(data_dir)

    @pytest.mark.unit
    def test_vacuum_runs_without_error(self, vacuum_env):
        """vacuum_sbs should run without raising exceptions."""
        vacuum_sbs(data_dir=vacuum_env, retain_days=30, keep_versions=10)

    @pytest.mark.unit
    def test_vacuum_prunes_old_versions(self, vacuum_env):
        """vacuum_sbs should prune versions beyond keep_versions."""
        vacuum_sbs(data_dir=vacuum_env, retain_days=30, keep_versions=5)

        archive_dir = Path(vacuum_env) / "profiles" / "archive"
        remaining = list(archive_dir.iterdir())
        assert len(remaining) == 5

    @pytest.mark.unit
    def test_vacuum_keeps_all_when_under_limit(self, vacuum_env):
        """When versions < keep_versions, nothing should be pruned."""
        vacuum_sbs(data_dir=vacuum_env, retain_days=30, keep_versions=20)

        archive_dir = Path(vacuum_env) / "profiles" / "archive"
        remaining = list(archive_dir.iterdir())
        assert len(remaining) == 15

    @pytest.mark.unit
    def test_vacuum_no_db_returns_early(self, tmp_path):
        """When no SQLite database exists, vacuum should return early."""
        data_dir = tmp_path / "empty_data"
        data_dir.mkdir()
        # Should not raise
        vacuum_sbs(data_dir=str(data_dir), retain_days=30, keep_versions=10)

    @pytest.mark.unit
    def test_vacuum_no_archive_dir(self, tmp_path):
        """When no archive directory exists, vacuum should handle gracefully."""
        data_dir = tmp_path / "data"
        indices_dir = data_dir / "indices"
        indices_dir.mkdir(parents=True)

        db_path = indices_dir / "messages.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS messages (msg_id TEXT PRIMARY KEY)")

        # Should not raise
        vacuum_sbs(data_dir=str(data_dir), retain_days=30, keep_versions=10)

    @pytest.mark.unit
    def test_vacuum_reclaims_space(self, vacuum_env):
        """After deleting rows and vacuuming, DB size should decrease or stay same."""
        db_path = Path(vacuum_env) / "indices" / "messages.db"

        # Delete half the rows to create reclaimable space
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM messages WHERE msg_id LIKE 'msg-5%'")
            conn.commit()

        size_before = db_path.stat().st_size
        vacuum_sbs(data_dir=vacuum_env, retain_days=30, keep_versions=15)
        size_after = db_path.stat().st_size

        # After vacuum, size should be <= before (usually smaller)
        assert size_after <= size_before


class TestRawMessageSchema:
    """Tests for the RawMessage Pydantic schema."""

    @pytest.mark.unit
    def test_raw_message_defaults(self):
        """RawMessage should have sensible defaults."""
        from sci_fi_dashboard.sbs.ingestion.schema import RawMessage

        msg = RawMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.char_count == 0
        assert msg.word_count == 0
        assert msg.has_emoji is False
        assert msg.is_question is False
        assert msg.rt_sentiment is None
        assert msg.rt_language is None
        assert msg.msg_id  # should be auto-generated UUID
        assert msg.timestamp  # should be auto-generated

    @pytest.mark.unit
    def test_raw_message_all_roles(self):
        """RawMessage should accept user, assistant, and system roles."""
        for role in ("user", "assistant", "system"):
            msg = RawMessage(role=role, content="test")
            assert msg.role == role

    @pytest.mark.unit
    def test_raw_message_invalid_role_raises(self):
        """RawMessage with invalid role should raise validation error."""
        from pydantic import ValidationError
        from sci_fi_dashboard.sbs.ingestion.schema import RawMessage

        with pytest.raises(ValidationError):
            RawMessage(role="invalid_role", content="test")

    @pytest.mark.unit
    def test_raw_message_serialization(self):
        """RawMessage should serialize to JSON and back."""
        from sci_fi_dashboard.sbs.ingestion.schema import RawMessage

        msg = RawMessage(
            role="user",
            content="hello world",
            char_count=11,
            word_count=2,
            is_question=False,
        )
        json_str = msg.model_dump_json()
        assert "hello world" in json_str
        assert '"role":"user"' in json_str or '"role": "user"' in json_str
