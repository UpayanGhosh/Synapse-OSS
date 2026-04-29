import asyncio
import concurrent.futures
import logging
import time

import psutil
import schedule

from .sqlite_graph import SQLiteGraph

logger = logging.getLogger(__name__)


class GentleWorker:
    """
    Thermal-aware background worker.
    Only runs heavy maintenance tasks when the system is idle and plugged in.
    """

    def __init__(
        self,
        graph: SQLiteGraph = None,
        cron_service=None,
        proactive_engine=None,
        channel_registry=None,
    ):
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
        """Maybe reach out to users who haven't messaged in 8h+.

        PROA-02 thread-safety: we run on a non-event-loop thread (schedule's
        while-loop), so we MUST use asyncio.run_coroutine_threadsafe to submit
        the coroutine onto the main event loop captured at init time. Using
        loop.create_task from here raises RuntimeError.
        """
        can_run, reason = self.check_conditions()
        if not can_run:
            return

        if not self.proactive_engine or not self.channel_registry:
            return

        loop = getattr(self, "_event_loop", None)
        if loop is None or not loop.is_running():
            return

        coro = self._async_proactive_checkin()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            if not isinstance(future, concurrent.futures.Future):
                coro.close()
        except Exception as e:
            coro.close()
            print(f"[WARN] Proactive check-in scheduling failed: {e}")

    async def _async_proactive_checkin(self):
        """Async proactive check-in for default users.

        PROA-02 + OQ-4: resolves user_id ("the_creator"/"the_partner") to a
        real WhatsApp JID via synapse.json session.identityLinks. If the user
        has no paired JID, skip silently (logger.debug) — the user hasn't
        onboarded any contacts yet.

        PROA-04 + OQ-2: on successful send, emits 'proactive.sent' SSE event
        with metadata + 80-char ASCII-safe preview (Gotcha #5).
        """
        from synapse_config import SynapseConfig

        from sci_fi_dashboard.pipeline_emitter import get_emitter

        cfg = SynapseConfig.load()
        session_cfg = getattr(cfg, "session", {}) or {}
        identity_links = session_cfg.get("identityLinks", {}) or {}

        for user_id, channel_id in [("the_creator", "whatsapp"), ("the_partner", "whatsapp")]:
            try:
                reply = await self.proactive_engine.maybe_reach_out(user_id, channel_id)
                if not reply:
                    continue

                # OQ-4: resolve user_id -> JID via identityLinks
                linked = identity_links.get(user_id, [])
                if isinstance(linked, str):
                    linked = [linked]
                if not linked:
                    logger.debug(
                        "No JID for %s in identityLinks — skipping proactive send", user_id
                    )
                    continue
                jid = linked[0]

                channel = self.channel_registry.get(channel_id)
                if channel is None:
                    continue

                ok = await channel.send(jid, reply)
                if not ok:
                    print(f"[WARN] Proactive send to {user_id} returned False")
                    continue

                # PROA-04 + OQ-2: emit metadata-only SSE event with ASCII-safe preview
                preview = reply[:80].encode("ascii", errors="replace").decode("ascii")
                get_emitter().emit(
                    "proactive.sent",
                    {
                        "channel_id": channel_id,
                        "user_id": user_id,
                        "reason": "silence_gap_8h",
                        "preview": preview,
                    },
                )
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
