"""
test_gentle_worker.py — Tests for gentle_worker.py

Covers:
  - GentleWorker construction
  - check_conditions: battery, CPU checks
  - heavy_task_graph_pruning: conditions check, graph prune call
  - heavy_task_db_optimize: conditions check, VACUUM call
  - start method scheduling
"""

import os
import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGentleWorker:
    @pytest.fixture
    def mock_graph(self):
        g = MagicMock()
        g.prune_graph.return_value = None
        conn = MagicMock()
        g._conn.return_value = conn
        return g

    @pytest.fixture
    def worker(self, mock_graph):
        with patch("sci_fi_dashboard.gentle_worker.SQLiteGraph", return_value=mock_graph):
            from sci_fi_dashboard.gentle_worker import GentleWorker
            return GentleWorker(graph=mock_graph)

    def test_construction_default(self):
        with patch("sci_fi_dashboard.gentle_worker.SQLiteGraph") as mock_cls:
            from sci_fi_dashboard.gentle_worker import GentleWorker
            w = GentleWorker()
            assert w.is_running is True

    def test_construction_with_graph(self, mock_graph):
        from sci_fi_dashboard.gentle_worker import GentleWorker
        w = GentleWorker(graph=mock_graph)
        assert w.graph is mock_graph

    def test_check_conditions_plugged_in_idle(self, worker):
        """When plugged in and CPU < 20%, should return True."""
        mock_battery = MagicMock()
        mock_battery.power_plugged = True
        mock_battery.percent = 80

        with patch("psutil.sensors_battery", return_value=mock_battery), \
             patch("psutil.cpu_percent", return_value=5.0):
            can_run, reason = worker.check_conditions()
            assert can_run is True
            assert "OK" in reason

    def test_check_conditions_on_battery(self, worker):
        """When on battery, should return False."""
        mock_battery = MagicMock()
        mock_battery.power_plugged = False
        mock_battery.percent = 50

        with patch("psutil.sensors_battery", return_value=mock_battery):
            can_run, reason = worker.check_conditions()
            assert can_run is False
            assert "Battery" in reason.upper() or "BATTERY" in reason

    def test_check_conditions_cpu_busy(self, worker):
        """When CPU > 20%, should return False."""
        mock_battery = MagicMock()
        mock_battery.power_plugged = True

        with patch("psutil.sensors_battery", return_value=mock_battery), \
             patch("psutil.cpu_percent", return_value=50.0):
            can_run, reason = worker.check_conditions()
            assert can_run is False
            assert "CPU" in reason.upper() or "FIRE" in reason

    def test_check_conditions_no_battery(self, worker):
        """Desktop with no battery should pass battery check."""
        with patch("psutil.sensors_battery", return_value=None), \
             patch("psutil.cpu_percent", return_value=5.0):
            can_run, reason = worker.check_conditions()
            assert can_run is True

    def test_check_conditions_battery_error(self, worker):
        """Battery check error should not crash, falls through to CPU check."""
        with patch("psutil.sensors_battery", side_effect=RuntimeError("no battery")), \
             patch("psutil.cpu_percent", return_value=5.0):
            can_run, reason = worker.check_conditions()
            assert can_run is True

    def test_graph_pruning_runs_when_conditions_met(self, worker, mock_graph):
        with patch.object(worker, "check_conditions", return_value=(True, "OK")):
            worker.heavy_task_graph_pruning()
            mock_graph.prune_graph.assert_called_once()

    def test_graph_pruning_skipped_when_conditions_not_met(self, worker, mock_graph):
        with patch.object(worker, "check_conditions", return_value=(False, "CPU busy")):
            worker.heavy_task_graph_pruning()
            mock_graph.prune_graph.assert_not_called()

    def test_graph_pruning_error_handled(self, worker, mock_graph):
        mock_graph.prune_graph.side_effect = RuntimeError("db error")
        with patch.object(worker, "check_conditions", return_value=(True, "OK")):
            worker.heavy_task_graph_pruning()  # should not raise

    def test_db_optimize_runs_when_conditions_met(self, worker, mock_graph):
        conn = MagicMock()
        mock_graph._conn.return_value = conn

        with patch.object(worker, "check_conditions", return_value=(True, "OK")):
            worker.heavy_task_db_optimize()
            conn.execute.assert_called_once_with("VACUUM")

    def test_db_optimize_skipped_when_conditions_not_met(self, worker, mock_graph):
        with patch.object(worker, "check_conditions", return_value=(False, "Battery")):
            worker.heavy_task_db_optimize()
            mock_graph._conn.assert_not_called()

    def test_db_optimize_error_handled(self, worker, mock_graph):
        mock_graph._conn.side_effect = RuntimeError("db locked")
        with patch.object(worker, "check_conditions", return_value=(True, "OK")):
            worker.heavy_task_db_optimize()  # should not raise
