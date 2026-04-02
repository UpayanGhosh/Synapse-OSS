"""
test_state.py — Tests for state management (DashboardState, Process, LogEntry, Activity).

Covers:
  - DashboardState initialization defaults
  - Uptime string formatting
  - Activity list management (add, overflow cap)
  - Log list management (add, overflow cap)
  - update_stats with and without psutil
  - Process dataclass
  - LogEntry dataclass
  - Activity dataclass
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

from sci_fi_dashboard.state import DashboardState, Process, LogEntry, Activity


class TestProcess:
    """Tests for the Process dataclass."""

    def test_defaults(self):
        """Process should have expected defaults."""
        p = Process(name="test", progress=50.0)
        assert p.name == "test"
        assert p.progress == 50.0
        assert p.status == "ACTIVE"

    def test_custom_status(self):
        """Process should accept a custom status."""
        p = Process(name="idle_proc", progress=0.0, status="IDLE")
        assert p.status == "IDLE"


class TestLogEntry:
    """Tests for the LogEntry dataclass."""

    def test_fields(self):
        """LogEntry should store all fields."""
        entry = LogEntry(timestamp="12:00:00", level="ERROR", message="fail")
        assert entry.timestamp == "12:00:00"
        assert entry.level == "ERROR"
        assert entry.message == "fail"


class TestActivity:
    """Tests for the Activity dataclass."""

    def test_defaults(self):
        """Activity should have empty sub_text by default."""
        a = Activity(time_str="14:00", narrative="Something happened")
        assert a.sub_text == ""

    def test_custom_sub_text(self):
        """Activity should accept sub_text."""
        a = Activity(time_str="14:00", narrative="Event", sub_text="Details")
        assert a.sub_text == "Details"


class TestDashboardState:
    """Tests for DashboardState class."""

    def test_initial_defaults(self):
        """DashboardState should initialize with sensible defaults."""
        state = DashboardState()
        assert state.system_name == "Synapse v2.4"
        assert state.status == "OPERATIONAL"
        assert state.active_tasks_count == 0
        assert state.network_health == 82
        assert state.cpu_load == 34
        assert state.memory_usage == "2.1GB"
        assert state.total_tokens_in == 0
        assert state.total_tokens_out == 0
        assert state.context_limit == 1048576
        assert state.active_sessions == 0

    def test_initial_processes(self):
        """Default processes should be present."""
        state = DashboardState()
        assert "Memory Indexing" in state.processes
        assert "Sentiment Monitor" in state.processes
        assert "Shadow Pushing" in state.processes
        assert isinstance(state.processes["Memory Indexing"], Process)

    def test_empty_activities_and_logs(self):
        """Activities and logs should start empty."""
        state = DashboardState()
        assert state.activities == []
        assert state.logs == []

    def test_uptime_str_format(self):
        """Uptime string should be formatted as 'Xh Ym Zs'."""
        state = DashboardState()
        # Force known uptime
        state.uptime_start = time.time() - 3661  # 1h 1m 1s
        result = state.get_uptime_str()
        assert "1h" in result
        assert "1m" in result
        assert "1s" in result

    def test_uptime_str_zero(self):
        """Uptime should be near zero immediately after creation."""
        state = DashboardState()
        result = state.get_uptime_str()
        assert "0h" in result
        assert "0m" in result

    def test_add_activity(self):
        """Adding an activity should insert at index 0."""
        state = DashboardState()
        state.add_activity("Test event", "sub text")
        assert len(state.activities) == 1
        assert state.activities[0].narrative == "Test event"
        assert state.activities[0].sub_text == "sub text"

    def test_add_activity_overflow(self):
        """Activities should be capped at 10."""
        state = DashboardState()
        for i in range(15):
            state.add_activity(f"Event {i}")
        assert len(state.activities) == 10
        # Most recent should be first
        assert state.activities[0].narrative == "Event 14"

    def test_add_log(self):
        """Adding a log should insert at index 0."""
        state = DashboardState()
        state.add_log("INFO", "test message")
        assert len(state.logs) == 1
        assert state.logs[0].level == "INFO"
        assert state.logs[0].message == "test message"

    def test_add_log_overflow(self):
        """Logs should be capped at 20."""
        state = DashboardState()
        for i in range(25):
            state.add_log("INFO", f"log {i}")
        assert len(state.logs) == 20
        assert state.logs[0].message == "log 24"

    def test_activity_has_time_str(self):
        """Activity should have a time_str populated."""
        state = DashboardState()
        state.add_activity("Test")
        assert state.activities[0].time_str  # non-empty

    def test_log_has_timestamp(self):
        """LogEntry should have a timestamp populated."""
        state = DashboardState()
        state.add_log("ERROR", "oops")
        assert state.logs[0].timestamp  # non-empty

    @patch("sci_fi_dashboard.state.psutil")
    def test_update_stats_with_psutil(self, mock_psutil):
        """update_stats should use psutil when available."""
        mock_psutil.cpu_percent.return_value = 55.0
        mock_vm = MagicMock()
        mock_vm.used = 4 * (1024 ** 3)  # 4 GB
        mock_psutil.virtual_memory.return_value = mock_vm
        mock_psutil.ImportError = ImportError  # ensure the except block works

        state = DashboardState()
        # Patch sqlite3 to avoid DB access
        with patch("sci_fi_dashboard.state.sqlite3") as mock_sql:
            mock_conn = MagicMock()
            mock_sql.connect.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            state.update_stats()

        assert state.cpu_load == 55.0
        assert "4.0GB" in state.memory_usage

    def test_update_stats_no_crash(self):
        """update_stats should not raise even if psutil or DB is unavailable."""
        state = DashboardState()
        # Should not raise
        with patch("sci_fi_dashboard.state.sqlite3") as mock_sql:
            mock_conn = MagicMock()
            mock_sql.connect.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            state.update_stats()
