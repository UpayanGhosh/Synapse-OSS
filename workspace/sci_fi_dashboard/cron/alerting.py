"""
Cron Scheduler — failure alerting.

Sends an alert when a job's consecutive error count meets the threshold,
respecting a cooldown window to avoid spamming.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .types import CronFailureAlert, CronJob, DeliveryMode

logger = logging.getLogger(__name__)


async def check_and_send_failure_alert(
    job: CronJob,
    alert: CronFailureAlert,
    channel_registry: Optional[Any] = None,
) -> bool:
    """Send a failure alert if conditions are met.

    Conditions:
        1. ``job.state.consecutive_errors >= alert.after``
        2. Cooldown has elapsed since last alert

    Returns True if an alert was actually sent.
    """
    state = job.state
    now_ms = int(time.time() * 1000)

    # Threshold not reached
    if state.consecutive_errors < alert.after:
        return False

    # Cooldown not elapsed
    if state.last_failure_alert_at_ms > 0:
        elapsed = now_ms - state.last_failure_alert_at_ms
        if elapsed < alert.cooldown_ms:
            logger.debug(
                "Failure alert for job %s suppressed by cooldown (%d ms remaining)",
                job.id,
                alert.cooldown_ms - elapsed,
            )
            return False

    # Build alert message
    message = (
        f"[Cron Alert] Job {job.name!r} (id={job.id}) has failed "
        f"{state.consecutive_errors} consecutive times.\n"
        f"Last error: {state.last_error or 'unknown'}"
    )

    sent = await _send_alert(message, alert, channel_registry)
    if sent:
        state.last_failure_alert_at_ms = now_ms
    return sent


async def _send_alert(
    message: str,
    alert: CronFailureAlert,
    channel_registry: Optional[Any],
) -> bool:
    """Dispatch the alert through the configured channel."""
    mode = DeliveryMode(alert.mode)

    if mode == DeliveryMode.NONE:
        logger.info("Failure alert (mode=none): %s", message)
        return True  # logged but not delivered externally

    if mode == DeliveryMode.ANNOUNCE:
        if channel_registry is None:
            logger.warning("Cannot send failure alert — no channel_registry")
            return False
        try:
            channel = channel_registry.get(alert.channel)
            if channel is None:
                logger.warning("Alert channel %r not found", alert.channel)
                return False
            await channel.send(alert.to or alert.channel, message)
            return True
        except Exception:
            logger.exception("Failed to send failure alert via channel %s", alert.channel)
            return False

    if mode == DeliveryMode.WEBHOOK:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    alert.to or "",
                    json={"alert": message, "job_id": alert.account_id},
                )
                resp.raise_for_status()
                return True
        except Exception:
            logger.exception("Failed to send failure alert via webhook")
            return False

    return False
