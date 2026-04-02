"""
test_emotional_trajectory.py — Tests for the EmotionalTrajectory module.

Covers:
  - Database initialization (table creation)
  - Recording emotional snapshots
  - Retrieving trajectory (with Peak-End weighting)
  - Getting summary text
  - Edge cases (empty DB, no peaks)
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock

from sci_fi_dashboard.emotional_trajectory import EmotionalTrajectory


@pytest.fixture
def trajectory(tmp_path):
    """EmotionalTrajectory with a temp DB."""
    db_path = str(tmp_path / "emotional_trajectory.db")
    return EmotionalTrajectory(db_path=db_path)


@pytest.fixture
def mock_merge():
    """Create a mock CognitiveMerge object."""
    merge = MagicMock()
    merge.tension_level = 0.3
    merge.tension_type = "curiosity"
    merge.suggested_tone = "engaged"
    merge.response_strategy = "acknowledge"
    return merge


@pytest.fixture
def high_tension_merge():
    """Create a high-tension mock merge (peak)."""
    merge = MagicMock()
    merge.tension_level = 0.8
    merge.tension_type = "conflict"
    merge.suggested_tone = "cautious"
    merge.response_strategy = "support"
    return merge


class TestEmotionalTrajectoryInit:
    """Tests for initialization and DB setup."""

    def test_creates_db_file(self, tmp_path):
        """Should create the database file."""
        db_path = str(tmp_path / "test_emo.db")
        et = EmotionalTrajectory(db_path=db_path)
        assert os.path.exists(db_path)

    def test_creates_table(self, trajectory):
        """Should create the trajectory table."""
        import sqlite3
        conn = sqlite3.connect(trajectory.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trajectory'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent_init(self, tmp_path):
        """Calling init twice should not fail."""
        db_path = str(tmp_path / "test_emo.db")
        et1 = EmotionalTrajectory(db_path=db_path)
        et2 = EmotionalTrajectory(db_path=db_path)
        # Should not raise

    def test_creates_parent_directory(self, tmp_path):
        """Should create parent directories if they don't exist."""
        db_path = str(tmp_path / "deep" / "nested" / "emo.db")
        et = EmotionalTrajectory(db_path=db_path)
        assert os.path.exists(db_path)


class TestRecord:
    """Tests for the record method."""

    def test_basic_record(self, trajectory, mock_merge):
        """Should record an emotional snapshot."""
        trajectory.record(mock_merge, topics=["tech", "career"])
        rows = trajectory.get_trajectory(hours=1)
        assert len(rows) == 1

    def test_record_captures_fields(self, trajectory, mock_merge):
        """Should store the correct field values."""
        trajectory.record(mock_merge, topics=["tech"])
        import sqlite3
        conn = sqlite3.connect(trajectory.db_path)
        row = conn.execute("SELECT * FROM trajectory ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        # row: id, timestamp, tension_level, tension_type, emotional_state, topics, response_strategy, is_peak
        assert row[2] == pytest.approx(0.3)  # tension_level
        assert row[3] == "curiosity"  # tension_type
        assert row[4] == "engaged"  # emotional_state (suggested_tone)
        assert "tech" in row[5]  # topics
        assert row[6] == "acknowledge"  # response_strategy
        assert row[7] == 0  # is_peak (tension < 0.6)

    def test_record_high_tension_is_peak(self, trajectory, high_tension_merge):
        """High tension (>0.6) should be flagged as peak."""
        trajectory.record(high_tension_merge)
        import sqlite3
        conn = sqlite3.connect(trajectory.db_path)
        row = conn.execute("SELECT is_peak FROM trajectory ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row[0] == 1

    def test_record_none_topics(self, trajectory, mock_merge):
        """None topics should default to empty."""
        trajectory.record(mock_merge, topics=None)
        rows = trajectory.get_trajectory(hours=1)
        assert len(rows) == 1

    def test_record_topics_truncated(self, trajectory, mock_merge):
        """Topics should be truncated to first 3."""
        trajectory.record(mock_merge, topics=["a", "b", "c", "d", "e"])
        import sqlite3
        conn = sqlite3.connect(trajectory.db_path)
        row = conn.execute("SELECT topics FROM trajectory ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        parts = row[0].split(",")
        assert len(parts) == 3

    def test_multiple_records(self, trajectory, mock_merge, high_tension_merge):
        """Multiple records should all be stored."""
        trajectory.record(mock_merge, topics=["tech"])
        trajectory.record(high_tension_merge, topics=["relationship"])
        trajectory.record(mock_merge, topics=["gaming"])
        rows = trajectory.get_trajectory(hours=1)
        assert len(rows) == 3


class TestGetTrajectory:
    """Tests for get_trajectory method."""

    def test_empty_db(self, trajectory):
        """Empty DB should return empty list."""
        rows = trajectory.get_trajectory(hours=72)
        assert rows == []

    def test_time_window_filtering(self, trajectory, mock_merge):
        """Should only return records within the time window."""
        trajectory.record(mock_merge, topics=["recent"])
        # Manually insert an old record
        import sqlite3
        conn = sqlite3.connect(trajectory.db_path)
        old_ts = time.time() - (100 * 3600)  # 100 hours ago
        conn.execute(
            "INSERT INTO trajectory (timestamp, tension_level, tension_type, emotional_state, topics, response_strategy, is_peak)"
            " VALUES (?, 0.5, 'old', 'calm', 'old', 'acknowledge', 0)",
            (old_ts,),
        )
        conn.commit()
        conn.close()

        rows = trajectory.get_trajectory(hours=72)
        # Should only get the recent one
        assert len(rows) == 1

    def test_limit_applied(self, trajectory, mock_merge):
        """Should respect the limit parameter."""
        for _ in range(15):
            trajectory.record(mock_merge)
        rows = trajectory.get_trajectory(hours=1, limit=5)
        assert len(rows) == 5

    def test_peaks_first(self, trajectory, mock_merge, high_tension_merge):
        """Peaks should appear first (ORDER BY is_peak DESC)."""
        trajectory.record(mock_merge)
        trajectory.record(high_tension_merge)
        trajectory.record(mock_merge)
        rows = trajectory.get_trajectory(hours=1, limit=10)
        # First row should be the peak
        tensions = [r[1] for r in rows]
        assert tensions[0] > 0.6


class TestGetSummary:
    """Tests for get_summary method."""

    def test_empty_db_returns_empty(self, trajectory):
        """Empty DB should return empty string."""
        assert trajectory.get_summary() == ""

    def test_summary_format(self, trajectory, mock_merge):
        """Summary should contain the header and structured lines."""
        trajectory.record(mock_merge, topics=["tech"])
        summary = trajectory.get_summary(hours=1)
        assert "EMOTIONAL TRAJECTORY" in summary
        assert "tension=" in summary
        assert "type=" in summary

    def test_summary_contains_data(self, trajectory, mock_merge, high_tension_merge):
        """Summary should reflect recorded data."""
        trajectory.record(mock_merge, topics=["career"])
        trajectory.record(high_tension_merge, topics=["conflict"])
        summary = trajectory.get_summary(hours=1)
        assert "h ago" in summary
        # Should have at least 2 lines (after header)
        lines = summary.strip().split("\n")
        assert len(lines) >= 2
