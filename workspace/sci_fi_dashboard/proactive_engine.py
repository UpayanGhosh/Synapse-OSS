"""
ProactiveAwarenessEngine — Background polling of personal MCP servers.
Runs as asyncio task. Thermal-aware like GentleWorker.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("synapse.proactive")


@dataclass
class ProactiveContext:
    calendar_events: list[dict] = field(default_factory=list)
    unread_emails: list[dict] = field(default_factory=list)
    slack_mentions: list[dict] = field(default_factory=list)
    generated_at: str = ""

    def compile_prompt_block(self) -> str:
        lines = []
        if self.calendar_events:
            lines.append("[UPCOMING EVENTS]")
            for e in self.calendar_events:
                lines.append(f"  - {e.get('summary', 'Event')} at {e.get('start', '?')}")
                if e.get("attendees"):
                    lines.append(f"    Attendees: {', '.join(str(a) for a in e['attendees'][:3])}")
        if self.unread_emails:
            lines.append(f"[UNREAD EMAILS: {len(self.unread_emails)}]")
            for e in self.unread_emails[:3]:
                lines.append(f"  - From: {e.get('from', '?')} | Subject: {e.get('subject', '?')}")
        if self.slack_mentions:
            lines.append(f"[SLACK MENTIONS: {len(self.slack_mentions)}]")
            for m in self.slack_mentions[:3]:
                lines.append(
                    f"  - #{m.get('channel', '?')} from {m.get('user', '?')}: "
                    f"{m.get('text', '')[:80]}"
                )
        if not lines:
            return ""
        return (
            "\n--- PROACTIVE AWARENESS (auto-gathered) ---\n"
            + "\n".join(lines)
            + "\n--- END PROACTIVE ---\n"
        )

    def has_urgent_items(self) -> bool:
        return bool(self.calendar_events) or len(self.unread_emails) > 3


class ProactiveAwarenessEngine:
    def __init__(self, mcp_client, proactive_config):
        self.mcp_client = mcp_client
        self.config = proactive_config  # ProactiveConfig from mcp_config.py
        self._context = ProactiveContext()
        self._running = False
        self._task = None

    @property
    def context(self) -> ProactiveContext:
        return self._context

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"[PROACTIVE] Started (interval: {self.config.poll_interval_seconds}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PROACTIVE] Poll error: {e}")
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _poll_all(self):
        ctx = ProactiveContext(generated_at=datetime.now().isoformat())
        sources = self.config.sources

        # Calendar
        cal_src = sources.get("calendar")
        if cal_src and cal_src.proactive:
            try:
                result = await self.mcp_client.call_tool(
                    "get_upcoming", {"minutes": cal_src.lookahead_minutes}
                )
                parsed = json.loads(result) if result else []
                ctx.calendar_events = parsed if isinstance(parsed, list) else []
            except Exception as e:
                logger.warning(f"[PROACTIVE] Calendar poll failed: {e}")

        # Gmail
        gmail_src = sources.get("gmail")
        if gmail_src and gmail_src.proactive:
            try:
                result = await self.mcp_client.call_tool(
                    "get_unread", {"limit": gmail_src.max_unread}
                )
                parsed = json.loads(result) if result else []
                ctx.unread_emails = parsed if isinstance(parsed, list) else []
            except Exception as e:
                logger.warning(f"[PROACTIVE] Gmail poll failed: {e}")

        # Slack
        slack_src = sources.get("slack")
        if slack_src and slack_src.proactive:
            try:
                result = await self.mcp_client.call_tool("get_mentions", {"since_hours": 1})
                parsed = json.loads(result) if result else []
                ctx.slack_mentions = parsed if isinstance(parsed, list) else []
            except Exception as e:
                logger.warning(f"[PROACTIVE] Slack poll failed: {e}")

        self._context = ctx
        if ctx.has_urgent_items():
            logger.info(
                f"[PROACTIVE] {len(ctx.calendar_events)} events, "
                f"{len(ctx.unread_emails)} emails, {len(ctx.slack_mentions)} mentions"
            )

    def get_prompt_injection(self) -> str:
        return self._context.compile_prompt_block()

    async def maybe_reach_out(
        self,
        user_id: str,
        channel_id: str,
        last_message_time: float = None,
    ) -> str | None:
        """
        Check if Synapse should proactively reach out to the user.

        Conditions:
        - last_message_time > 8h ago (or unknown)
        - Not 23:00-08:00 IST (sleep window)
        - Returns a generated message string, or None if conditions aren't met.

        Caller (GentleWorker) is responsible for sending the message.
        """
        from datetime import datetime, timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))  # noqa: N806
        now = datetime.now(IST)

        # Sleep window: 23:00 - 08:00 IST
        hour = now.hour
        if hour >= 23 or hour < 8:
            return None

        # Check last message gap
        if last_message_time is not None:
            import time as _time

            gap_seconds = _time.time() - last_message_time
            if gap_seconds < 8 * 3600:
                return None  # Less than 8h — don't interrupt

        # Generate check-in message
        try:
            from sci_fi_dashboard.chat_pipeline import persona_chat
            from sci_fi_dashboard.schemas import ChatRequest

            payload = (
                "Check in naturally with the user. "
                "Don't say you're doing an automated check-in. "
                "Reference something from recent memory if you remember it — "
                "a topic they mentioned, something they were working on. "
                "Keep it brief and warm."
            )
            request = ChatRequest(message=payload, user_id=user_id, history=[])
            result = await persona_chat(request, target=user_id)
            reply = result.get("reply", "")
            # Strip stats footer
            if "---\n**Context Usage:**" in reply:
                reply = reply.split("---\n**Context Usage:**")[0].strip()
            return reply if reply else None
        except Exception as e:
            logger.warning("[PROACTIVE] maybe_reach_out failed: %s", e)
            return None
