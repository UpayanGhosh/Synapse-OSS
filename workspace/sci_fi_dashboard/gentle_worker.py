import time

import psutil
import schedule


class GentleWorker:
    def __init__(self):
        self.is_running = True

    def check_conditions(self):
        """
        Checks if the worker should run active tasks.
        Returns Tuple (bool, reason)
        """
        # 1. Check Power
        try:
            battery = psutil.sensors_battery()
            # On macOS, battery can be None if permissions issue or desktop
            if battery is not None and not battery.power_plugged:
                return False, f"🔋 On Battery ({battery.percent}%)"
            elif battery is None:
                # Assume true if we can't detect, or maybe log a warning.
                # For a Gentle Worker, err on side of caution?
                # Let's assume plugged in but print once.
                pass
        except Exception as e:
            print(f"⚠️ Battery check error: {e}")

        # 2. Check CPU Load (Gentle Mode)
        # Interval=1 blocks for 1 second to measure CPU
        cpu_load = psutil.cpu_percent(interval=1)
        if cpu_load > 20:
            return False, f"🔥 CPU Busy ({cpu_load}%)"

        return True, "✅ System Idle & Plugged In"

    def heavy_task_ingestion(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping Ingestion: {reason}")
            return

        print("🚜 Starting Heavy Ingestion Task...")
        # Simulate work
        time.sleep(2)
        print("✅ Ingestion Complete")

    def heavy_task_graph_optimization(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping Graph Opt: {reason}")
            return

        print("🧠 Optimizing Knowledge Graph...")
        # Simulate work
        time.sleep(1)
        print("✅ Graph Optimized")

    def start(self):
        print(f"👷 Gentle Worker Started (PID: {psutil.Process().pid})")

        # Schedule tasks
        schedule.every(10).seconds.do(self.heavy_task_ingestion)  # Run often for testing
        schedule.every(30).seconds.do(self.heavy_task_graph_optimization)

        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("🛑 Worker Stopped")


if __name__ == "__main__":
    worker = GentleWorker()
    worker.start()
