"""
Cron Scheduler — delivery routing.

Routes job output to the appropriate destination: a channel via the
ChannelRegistry, a webhook URL, or nowhere (``none``).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sci_fi_dashboard.action_receipts import ActionReceipt

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from .types import CronDelivery, DeliveryMode

logger = logging.getLogger(__name__)


def _sanitize_announce_output(output: str) -> str:
    """Keep proactive channel messages free of diagnostics and chat markdown."""
    text = str(output or "")
    for marker in ("\u200b", "\u200c", "\u200d", "\ufeff", "\x00"):
        text = text.replace(marker, "")

    text = re.sub(r"<think\b[^>]*>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?final\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?think\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?im)^\s*thought\s+for\s+\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?)\s*$\n?",
        "",
        text,
    )
    text = re.split(r"\n\s*---\s*\n\*\*Context Usage:\*\*", text, maxsplit=1)[0]
    text = re.sub(r"```(?:\w+)?\n([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = text.strip()
    return cleaned or "Done."


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
            receipt = ActionReceipt(
                action="channel_send",
                status="unavailable",
                evidence=f"channel {channel_id!r} not found",
                confidence=0.0,
            )
            return {
                "status": "error",
                "reason": f"channel {channel_id!r} not found",
                "action_receipts": [receipt],
            }
        sent = await channel.send(delivery.to or channel_id, _sanitize_announce_output(output))
        receipt = ActionReceipt(
            action="channel_send",
            status="verified" if sent is not False else "failed",
            evidence=(
                f"announce delivered to {delivery.to or channel_id} via {channel_id}"
                if sent is not False
                else f"channel.send returned false for {delivery.to or channel_id}"
            ),
            confidence=0.97 if sent is not False else 0.0,
        )
        if sent is False:
            return {
                "status": "error",
                "reason": "channel.send returned false",
                "mode": "announce",
                "channel": channel_id,
                "action_receipts": [receipt],
            }
        return {
            "status": "ok",
            "mode": "announce",
            "channel": channel_id,
            "action_receipts": [receipt],
        }
    except Exception as exc:
        logger.exception("Announce delivery failed for channel %s", channel_id)
        receipt = ActionReceipt(
            action="channel_send",
            status="failed",
            evidence=str(exc)[:240],
            confidence=0.0,
        )
        return {"status": "error", "reason": str(exc), "action_receipts": [receipt]}


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
