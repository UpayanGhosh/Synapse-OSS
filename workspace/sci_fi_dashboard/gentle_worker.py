import time

import psutil
import schedule

from .sqlite_graph import SQLiteGraph


class GentleWorker:
    """
    Thermal-aware background worker.
    Only runs heavy maintenance tasks when the system is idle and plugged in.
    """

    def __init__(self, graph: SQLiteGraph = None):
        self.is_running = True
        self.graph = graph or SQLiteGraph()

    def check_conditions(self):
        """
        Checks if the worker should run active tasks.
        Returns Tuple (bool, reason)
        """
        # 1. Check Power
        try:
            battery = psutil.sensors_battery()
            if battery is not None and not battery.power_plugged:
                return False, f"🔋 On Battery ({battery.percent}%)"
        except Exception as e:
            print(f"⚠️ Battery check error: {e}")

        # 2. Check CPU Load (Gentle Mode)
        cpu_load = psutil.cpu_percent(interval=1)
        if cpu_load > 20:
            return False, f"🔥 CPU Busy ({cpu_load}%)"

        return True, "✅ System Idle & Plugged In"

    def heavy_task_graph_pruning(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping Graph Pruning: {reason}")
            return

        print("🧠 Pruning Knowledge Graph (low-confidence triples)...")
        try:
            pruned = self.graph.prune_graph()
            print(f"✅ Graph Pruned ({pruned} triples removed)")
        except Exception as e:
            print(f"⚠️ Graph pruning failed: {e}")

    def heavy_task_db_optimize(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping DB Optimize: {reason}")
            return

        print("📦 Optimizing databases (VACUUM)...")
        try:
            conn = self.graph._conn()
            conn.execute("VACUUM")
            conn.close()
            print("✅ Database optimized")
        except Exception as e:
            print(f"⚠️ DB optimization failed: {e}")

    def start(self):
        print(f"👷 Gentle Worker Started (PID: {psutil.Process().pid})")

        # Schedule tasks at production-appropriate intervals
        schedule.every(10).minutes.do(self.heavy_task_graph_pruning)
        schedule.every(30).minutes.do(self.heavy_task_db_optimize)

        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("🛑 Worker Stopped")


if __name__ == "__main__":
    worker = GentleWorker()
    worker.start()
