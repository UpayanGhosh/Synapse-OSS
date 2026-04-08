import asyncio
import time

import psutil
import schedule

from .sqlite_graph import SQLiteGraph


class GentleWorker:
    """
    Thermal-aware background worker.
    Only runs heavy maintenance tasks when the system is idle and plugged in.
    """

    def __init__(self, graph: SQLiteGraph = None, cron_service=None, proactive_engine=None,
                 channel_registry=None):
        self.is_running = True
        self.graph = graph or SQLiteGraph()
        self.cron_service = cron_service
        self.proactive_engine = proactive_engine
        self.channel_registry = channel_registry

    def check_conditions(self):
        """
        Checks if the worker should run active tasks.
        Returns Tuple (bool, reason)
        """
        # 1. Check Power
        try:
            battery = psutil.sensors_battery()
            if battery is not None and not battery.power_plugged:
                return False, f"[BATTERY] On Battery ({battery.percent}%)"
        except Exception as e:
            print(f"[WARN] Battery check error: {e}")

        # 2. Check CPU Load (Gentle Mode)
        cpu_load = psutil.cpu_percent(interval=1)
        if cpu_load > 20:
            return False, f"[FIRE] CPU Busy ({cpu_load}%)"

        return True, "[OK] System Idle & Plugged In"

    def heavy_task_graph_pruning(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping Graph Pruning: {reason}")
            return

        print("[MEM] Pruning Knowledge Graph (low-confidence triples)...")
        try:
            pruned = self.graph.prune_graph()
            print(f"[OK] Graph Pruned ({pruned} triples removed)")
        except Exception as e:
            print(f"[WARN] Graph pruning failed: {e}")

    def heavy_task_db_optimize(self):
        can_run, reason = self.check_conditions()
        if not can_run:
            print(f"Skipping DB Optimize: {reason}")
            return

        print("[PKG] Optimizing databases (VACUUM)...")
        try:
            conn = self.graph._conn()
            conn.execute("VACUUM")
            conn.close()
            print("[OK] Database optimized")
        except Exception as e:
            print(f"[WARN] DB optimization failed: {e}")

    def heavy_task_proactive_checkin(self):
        """Maybe reach out to users who haven't messaged in 8h+."""
        can_run, reason = self.check_conditions()
        if not can_run:
            return

        if not self.proactive_engine or not self.channel_registry:
            return

        try:
            # Fire-and-forget: schedule on the event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._async_proactive_checkin())
        except Exception as e:
            print(f"[WARN] Proactive check-in scheduling failed: {e}")

    async def _async_proactive_checkin(self):
        """Async proactive check-in for default users."""
        for user_id, channel_id in [("the_creator", "whatsapp"), ("the_partner", "whatsapp")]:
            try:
                reply = await self.proactive_engine.maybe_reach_out(user_id, channel_id)
                if reply:
                    channel = self.channel_registry.get(channel_id)
                    if channel:
                        await channel.send(user_id, reply)
                        print(f"[PROACTIVE] Sent check-in to {user_id}")
            except Exception as e:
                print(f"[WARN] Proactive {user_id} failed: {e}")

    def start(self):
        print(f"[WORKER] Gentle Worker Started (PID: {psutil.Process().pid})")

        # Schedule tasks at production-appropriate intervals
        # KG extraction now lives in async gentle_worker_loop() (pipeline_helpers.py)
        schedule.every(10).minutes.do(self.heavy_task_graph_pruning)
        schedule.every(30).minutes.do(self.heavy_task_db_optimize)
        schedule.every(15).minutes.do(self.heavy_task_proactive_checkin)

        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("[STOP] Worker Stopped")


if __name__ == "__main__":
    worker = GentleWorker()
    worker.start()
