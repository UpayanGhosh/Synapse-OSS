"""
Cron Scheduler — delivery routing.

Routes job output to the appropriate destination: a channel via the
ChannelRegistry, a webhook URL, or nowhere (``none``).
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from .types import CronDelivery, DeliveryMode

logger = logging.getLogger(__name__)


async def deliver_output(
    output: str,
    delivery: CronDelivery,
    channel_registry: Any | None = None,
) -> dict[str, Any]:
    """Send *output* according to the delivery configuration.

    Returns a dict with ``{"status": "ok"|"error"|"skipped", ...}``.
    """
    mode = DeliveryMode(delivery.mode)

    if mode == DeliveryMode.NONE:
        return {"status": "skipped", "reason": "delivery mode is none"}

    if mode == DeliveryMode.ANNOUNCE:
        return await _deliver_announce(output, delivery, channel_registry)

    if mode == DeliveryMode.WEBHOOK:
        return await _deliver_webhook(output, delivery)

    return {"status": "error", "reason": f"unknown delivery mode: {mode}"}


async def _deliver_announce(
    output: str,
    delivery: CronDelivery,
    channel_registry: Any | None,
) -> dict[str, Any]:
    """Announce via a registered channel."""
    if channel_registry is None:
        msg = "channel_registry not provided — cannot deliver announce"
        logger.warning(msg)
        return {"status": "error", "reason": msg}

    channel_id = delivery.channel
    if not channel_id:
        return {"status": "error", "reason": "no channel specified for announce delivery"}

    try:
        channel = channel_registry.get(channel_id)
        if channel is None:
            return {"status": "error", "reason": f"channel {channel_id!r} not found"}
        await channel.send(delivery.to or channel_id, output)
        return {"status": "ok", "mode": "announce", "channel": channel_id}
    except Exception as exc:
        logger.exception("Announce delivery failed for channel %s", channel_id)
        return {"status": "error", "reason": str(exc)}


async def _deliver_webhook(
    output: str,
    delivery: CronDelivery,
) -> dict[str, Any]:
    """POST output to a webhook URL."""
    url = delivery.to
    if not url:
        return {"status": "error", "reason": "no webhook URL specified"}

    try:
        if httpx is None:
            return {"status": "error", "reason": "httpx is not installed"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"output": output})
            resp.raise_for_status()
            return {"status": "ok", "mode": "webhook", "status_code": resp.status_code}
    except Exception as exc:
        logger.exception("Webhook delivery failed for %s", url)
        return {"status": "error", "reason": str(exc)}
