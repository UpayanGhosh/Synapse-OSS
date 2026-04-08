"""
CronService — asyncio job scheduler for proactive Synapse messages.

Reads job definitions from <data_root>/cron/jobs.json.
Each job fires a persona_chat() call at a scheduled interval and delivers
the response to the specified channel.

Job schema (jobs.json):
[
  {
    "job_id": "morning_checkin",
    "schedule": "every_day_at_08:00",
    "user_id": "the_creator",
    "channel_id": "default",
    "payload": "Do a natural morning check-in. Don't mention it's automated.",
    "delivery_mode": "send",
    "enabled": true
  }
]

Schedule format:
  "every_Nh"              — every N hours (e.g., "every_8h")
  "every_day_at_HH:MM"   — daily at specific local time
  "once_at_HH:MM"        — once per day at local time

Timezone: uses system local time by default. Override via
  synapse.json -> session.timezone_offset_hours (e.g. 5.5 for IST).
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("synapse.cron")


def _get_local_tz() -> timezone:
    """Return the user's configured timezone or system local timezone."""
    try:
        from synapse_config import SynapseConfig
        cfg = SynapseConfig.load()
        tz_offset = cfg.session.get("timezone_offset_hours")
        if tz_offset is not None:
            return timezone(timedelta(hours=float(tz_offset)))
    except Exception:
        pass
    # Fallback: system local timezone
    local_offset = datetime.now(timezone.utc).astimezone().utcoffset()
    return timezone(local_offset) if local_offset else timezone.utc


def _get_cron_dir() -> Path:
    """Resolve cron directory from SynapseConfig.data_root."""
    try:
        from synapse_config import SynapseConfig
        return SynapseConfig.load().data_root / "cron"
    except Exception:
        return Path(os.path.expanduser("~/.synapse/cron"))


CRON_DIR = _get_cron_dir()
JOBS_FILE = CRON_DIR / "jobs.json"


def _load_jobs() -> list[dict]:
    """Load job definitions from ~/.synapse/cron/jobs.json."""
    if not JOBS_FILE.exists():
        return []
    try:
        with open(JOBS_FILE, encoding="utf-8") as f:
            jobs = json.load(f)
        return [j for j in jobs if j.get("enabled", True)]
    except Exception as e:
        logger.warning("Failed to load cron jobs: %s", e)
        return []


def _parse_schedule(schedule: str) -> float:
    """
    Parse schedule string into seconds-until-next-fire.
    Returns seconds until the next scheduled time.
    """
    now_local = datetime.now(_get_local_tz())

    if schedule.startswith("every_") and schedule.endswith("h"):
        # "every_8h" -> fire every 8 hours
        try:
            hours = float(schedule.split("_")[1].rstrip("h"))
            return hours * 3600
        except (ValueError, IndexError):
            return 3600  # fallback: every hour

    if "at_" in schedule:
        # "every_day_at_08:00" or "once_at_08:00" (legacy _IST suffix also accepted)
        try:
            after_at = schedule.split("at_")[1]
            # Strip optional timezone suffix (e.g. "_IST", "_UTC") for backward compat
            time_part = after_at.split("_")[0]
            h, m = (int(x) for x in time_part.split(":"))
            target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now_local:
                target = target + timedelta(days=1)
            return (target - now_local).total_seconds()
        except Exception:
            return 86400  # fallback: 24h

    # Unknown format — fire every 4 hours
    logger.warning("Unknown schedule format: %s. Defaulting to 4h.", schedule)
    return 14400


class CronService:
    """
    Asyncio-based job scheduler for proactive Synapse messages.
    Wired into GentleWorker — only fires when CPU < 20% and plugged in.
    """

    def __init__(self, channel_registry=None):
        """
        Args:
            channel_registry: ChannelRegistry for sending messages.
                              Injected from _deps at startup.
        """
        self.channel_registry = channel_registry
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        CRON_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_default_jobs()

    def _ensure_default_jobs(self):
        """Create a minimal jobs.json if none exists (OSS onboarding)."""
        if not JOBS_FILE.exists():
            default = [
                {
                    "job_id": "example_checkin",
                    "schedule": "every_8h",
                    "user_id": "the_creator",
                    "channel_id": "default",
                    "payload": (
                        "Do a natural check-in. Ask how they're doing. "
                        "Reference something from recent conversation if you remember it. "
                        "Don't mention this is automated."
                    ),
                    "delivery_mode": "send",
                    "enabled": False,  # disabled by default — user opts in
                }
            ]
            try:
                with open(JOBS_FILE, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2)
            except Exception:
                pass

    async def start(self):
        """Start scheduling all enabled jobs."""
        self._running = True
        jobs = _load_jobs()
        logger.info("[Cron] Loaded %d enabled jobs", len(jobs))
        for job in jobs:
            task = asyncio.create_task(self._job_loop(job))
            self._tasks[job["job_id"]] = task

    async def stop(self):
        """Cancel all running job tasks."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    def reload(self):
        """Hot-reload jobs from disk (cancel old tasks, start new ones)."""
        asyncio.create_task(self._reload_async())

    async def _reload_async(self):
        await self.stop()
        await self.start()

    async def _job_loop(self, job: dict):
        """Per-job execution loop."""
        job_id = job.get("job_id", "unknown")
        schedule = job.get("schedule", "every_8h")

        while self._running:
            delay = _parse_schedule(schedule)
            logger.debug("[Cron] Job %s fires in %.1fh", job_id, delay / 3600)
            await asyncio.sleep(delay)

            if not self._running:
                break

            try:
                await self._fire_job(job)
            except Exception as e:
                logger.warning("[Cron] Job %s failed: %s", job_id, e)

    async def _fire_job(self, job: dict):
        """Execute a single job — call persona_chat and deliver result."""
        job_id = job.get("job_id", "unknown")
        user_id = job.get("user_id", "the_creator")
        channel_id = job.get("channel_id", "whatsapp")
        payload = job.get("payload", "")

        logger.info("[Cron] Firing job: %s -> %s on %s", job_id, user_id, channel_id)

        try:
            from sci_fi_dashboard.chat_pipeline import persona_chat
            from sci_fi_dashboard.schemas import ChatRequest

            request = ChatRequest(
                message=payload,
                user_id=user_id,
                history=[],
            )
            result = await persona_chat(request, target=user_id)
            reply = result.get("reply", "")

            # Strip stats footer if present
            if "---\n**Context Usage:**" in reply:
                reply = reply.split("---\n**Context Usage:**")[0].strip()

            if reply and self.channel_registry:
                channel = self.channel_registry.get(channel_id)
                if channel:
                    await channel.send(user_id, reply)
                    logger.info("[Cron] Delivered job %s reply (%d chars)", job_id, len(reply))
                else:
                    logger.warning("[Cron] Channel %s not found", channel_id)
        except Exception as e:
            logger.error("[Cron] Job execution failed %s: %s", job_id, e)
