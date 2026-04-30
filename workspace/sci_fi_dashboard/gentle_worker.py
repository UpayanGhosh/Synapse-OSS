import asyncio
import concurrent.futures
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

try:
    import schedule
except ImportError:  # pragma: no cover - production installs the dependency
    schedule = None

from .sqlite_graph import SQLiteGraph

logger = logging.getLogger(__name__)

_DEFAULT_PROACTIVE_USERS = ("the_creator", "the_partner")
_PROACTIVE_COOLDOWN_SECONDS = 6 * 3600
_MEMORY_SUMMARY_LIMIT = 5
_EMOTIONAL_TERMS = (
    "anxious",
    "anxiety",
    "worried",
    "stress",
    "stressed",
    "scared",
    "fear",
    "panic",
    "sad",
    "lonely",
)
_COMMITMENT_TERMS = (
    "deadline",
    "demo",
    "meeting",
    "interview",
    "reminder",
    "remind",
    "check-in",
    "check in",
    "follow up",
)


@dataclass(frozen=True)
class ProactiveTarget:
    agent_id: str
    channel_id: str
    recipient_id: str
    session_key: str | None = None
    last_message_time: float | None = None
    recent_memory_summaries: tuple[str, ...] = ()
    emotional_need: float = 0.0

    @property
    def cooldown_key(self) -> str:
        return self.session_key or f"{self.agent_id}:{self.channel_id}:{self.recipient_id}"


def _path_or_none(value) -> Path | None:
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    return None


def _memory_db_path_from_config(cfg) -> Path | None:
    db_dir = _path_or_none(getattr(cfg, "db_dir", None))
    if db_dir is not None:
        return db_dir / "memory.db"
    data_root = _path_or_none(getattr(cfg, "data_root", None))
    if data_root is not None:
        return data_root / "workspace" / "db" / "memory.db"
    return None


def _parse_direct_session_target(
    session_key: str,
    last_message_time: float | None,
) -> ProactiveTarget | None:
    parts = str(session_key or "").lower().split(":")
    if len(parts) < 5 or parts[0] != "agent" or parts[3] != "dm":
        return None
    agent_id = parts[1].strip()
    channel_id = parts[2].strip()
    recipient_id = parts[-1].strip()
    if not agent_id or not channel_id or not recipient_id or recipient_id == "unknown":
        return None
    return ProactiveTarget(
        agent_id=agent_id,
        channel_id=channel_id,
        recipient_id=recipient_id,
        session_key=":".join(parts),
        last_message_time=last_message_time,
    )


def _load_recent_memory_summaries(
    db_path: Path | None,
    session_key: str,
    *,
    limit: int,
) -> list[str]:
    if db_path is None or not db_path.exists():
        return []

    user_ids = tuple(dict.fromkeys([session_key, session_key.lower()]))
    placeholders = ",".join("?" for _ in user_ids)
    query = f"""
        SELECT summary
        FROM user_memory_facts
        WHERE user_id IN ({placeholders})
          AND status = 'active'
        ORDER BY last_seen DESC, id DESC
        LIMIT ?
    """
    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(query, (*user_ids, int(limit))).fetchall()
    except sqlite3.Error:
        return []

    summaries: list[str] = []
    for (summary,) in rows:
        text = " ".join(str(summary or "").split())
        if text:
            summaries.append(text)
    return summaries


def _estimate_emotional_need(summaries: list[str]) -> float:
    text = " ".join(summaries).lower()
    if any(term in text for term in _EMOTIONAL_TERMS):
        return 0.8
    if any(term in text for term in _COMMITMENT_TERMS):
        return 0.55
    return 0.0


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
        self._proactive_last_sent: dict[str, float] = {}

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
        """Async proactive check-in for active direct sessions and linked users."""
        from synapse_config import SynapseConfig

        from sci_fi_dashboard.pipeline_emitter import get_emitter

        cfg = SynapseConfig.load()
        targets = await self._discover_proactive_targets(cfg)

        for target in targets:
            try:
                if self._is_proactive_cooling_down(target.cooldown_key):
                    continue

                reply = await self.proactive_engine.maybe_reach_out(
                    target.agent_id,
                    target.channel_id,
                    last_message_time=target.last_message_time,
                    recent_memory_summaries=list(target.recent_memory_summaries),
                    emotional_need=target.emotional_need,
                )
                if not reply:
                    continue

                channel = self.channel_registry.get(target.channel_id)
                if channel is None:
                    continue

                ok = await channel.send(target.recipient_id, reply)
                if not ok:
                    print(f"[WARN] Proactive send to {target.agent_id} returned False")
                    continue

                self._mark_proactive_sent(target.cooldown_key)
                preview = reply[:80].encode("ascii", errors="replace").decode("ascii")
                get_emitter().emit(
                    "proactive.sent",
                    {
                        "channel_id": target.channel_id,
                        "user_id": target.agent_id,
                        "recipient_id": target.recipient_id,
                        "reason": "policy_score",
                        "preview": preview,
                    },
                )
                print(f"[PROACTIVE] Sent check-in to {target.agent_id}/{target.channel_id}")
            except Exception as e:
                print(f"[WARN] Proactive {target.agent_id} failed: {e}")

    async def _discover_proactive_targets(self, cfg) -> list[ProactiveTarget]:
        targets: list[ProactiveTarget] = []
        targets.extend(self._identity_link_targets(cfg))
        targets.extend(await self._session_store_targets(cfg))

        deduped: dict[tuple[str, str], ProactiveTarget] = {}
        for target in targets:
            key = (target.channel_id, target.recipient_id)
            existing = deduped.get(key)
            if existing is None or (not existing.session_key and target.session_key):
                deduped[key] = target
        return list(deduped.values())

    def _identity_link_targets(self, cfg) -> list[ProactiveTarget]:
        session_cfg = getattr(cfg, "session", {}) or {}
        identity_links = (
            session_cfg.get("identityLinks", {}) if isinstance(session_cfg, dict) else {}
        )
        if not isinstance(identity_links, dict):
            return []

        targets: list[ProactiveTarget] = []
        for agent_id in [*_DEFAULT_PROACTIVE_USERS, *identity_links.keys()]:
            linked = identity_links.get(agent_id, [])
            if isinstance(linked, str):
                linked = [linked]
            if not isinstance(linked, list):
                continue
            for recipient_id in linked:
                recipient = str(recipient_id or "").strip()
                if not recipient:
                    continue
                targets.append(
                    ProactiveTarget(
                        agent_id=str(agent_id),
                        channel_id="whatsapp",
                        recipient_id=recipient,
                    )
                )
        return targets

    async def _session_store_targets(self, cfg) -> list[ProactiveTarget]:
        data_root = _path_or_none(getattr(cfg, "data_root", None))
        if data_root is None:
            return []

        from sci_fi_dashboard.multiuser.session_store import SessionStore

        db_path = _memory_db_path_from_config(cfg)
        session_cfg = getattr(cfg, "session", {}) or {}
        identity_links = (
            session_cfg.get("identityLinks", {}) if isinstance(session_cfg, dict) else {}
        )
        agent_ids = set(_DEFAULT_PROACTIVE_USERS)
        if isinstance(identity_links, dict):
            agent_ids.update(str(key) for key in identity_links)

        targets: list[ProactiveTarget] = []
        for agent_id in sorted(agent_ids):
            try:
                store = SessionStore(agent_id, data_root=data_root)
                entries = await store.load()
            except Exception as exc:
                logger.debug("Proactive session discovery failed for %s: %s", agent_id, exc)
                continue

            for session_key, entry in entries.items():
                parsed = _parse_direct_session_target(session_key, entry.updated_at)
                if parsed is None:
                    continue
                summaries = _load_recent_memory_summaries(
                    db_path,
                    parsed.session_key or session_key,
                    limit=_MEMORY_SUMMARY_LIMIT,
                )
                targets.append(
                    ProactiveTarget(
                        agent_id=parsed.agent_id,
                        channel_id=parsed.channel_id,
                        recipient_id=parsed.recipient_id,
                        session_key=parsed.session_key,
                        last_message_time=parsed.last_message_time,
                        recent_memory_summaries=tuple(summaries),
                        emotional_need=_estimate_emotional_need(summaries),
                    )
                )
        return targets

    def _is_proactive_cooling_down(self, key: str) -> bool:
        last_sent = self._proactive_last_sent.get(key)
        if last_sent is None:
            return False
        return time.time() - last_sent < _PROACTIVE_COOLDOWN_SECONDS

    def _mark_proactive_sent(self, key: str) -> None:
        self._proactive_last_sent[key] = time.time()

    async def _async_proactive_checkin_legacy(self):
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

        if schedule is None:
            print("[WARN] Gentle Worker scheduling disabled: missing 'schedule' package")
            return

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
