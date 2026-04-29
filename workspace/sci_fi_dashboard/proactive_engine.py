"""
ProactiveAwarenessEngine - background polling of personal MCP servers.

Runs as an asyncio task. Reach-outs are gated by ProactivePolicyScorer so
Synapse only speaks when local context makes it useful.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer

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
            for event in self.calendar_events:
                lines.append(f"  - {event.get('summary', 'Event')} at {event.get('start', '?')}")
                if event.get("attendees"):
                    attendees = ", ".join(str(a) for a in event["attendees"][:3])
                    lines.append(f"    Attendees: {attendees}")
        if self.unread_emails:
            lines.append(f"[UNREAD EMAILS: {len(self.unread_emails)}]")
            for email in self.unread_emails[:3]:
                lines.append(
                    f"  - From: {email.get('from', '?')} | Subject: {email.get('subject', '?')}"
                )
        if self.slack_mentions:
            lines.append(f"[SLACK MENTIONS: {len(self.slack_mentions)}]")
            for mention in self.slack_mentions[:3]:
                lines.append(
                    f"  - #{mention.get('channel', '?')} from {mention.get('user', '?')}: "
                    f"{mention.get('text', '')[:80]}"
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
        self.config = proactive_config
        self._context = ProactiveContext()
        self._running = False
        self._task = None
        self.policy_scorer = ProactivePolicyScorer()

    @property
    def context(self) -> ProactiveContext:
        return self._context

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[PROACTIVE] Started (interval: %ss)", self.config.poll_interval_seconds)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[PROACTIVE] Poll error: %s", exc)
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _poll_all(self):
        ctx = ProactiveContext(generated_at=datetime.now().isoformat())
        sources = self.config.sources

        cal_src = sources.get("calendar")
        if cal_src and cal_src.proactive:
            try:
                result = await self.mcp_client.call_tool(
                    "get_upcoming", {"minutes": cal_src.lookahead_minutes}
                )
                parsed = json.loads(result) if result else []
                ctx.calendar_events = parsed if isinstance(parsed, list) else []
            except Exception as exc:
                logger.warning("[PROACTIVE] Calendar poll failed: %s", exc)

        gmail_src = sources.get("gmail")
        if gmail_src and gmail_src.proactive:
            try:
                result = await self.mcp_client.call_tool(
                    "get_unread", {"limit": gmail_src.max_unread}
                )
                parsed = json.loads(result) if result else []
                ctx.unread_emails = parsed if isinstance(parsed, list) else []
            except Exception as exc:
                logger.warning("[PROACTIVE] Gmail poll failed: %s", exc)

        slack_src = sources.get("slack")
        if slack_src and slack_src.proactive:
            try:
                result = await self.mcp_client.call_tool("get_mentions", {"since_hours": 1})
                parsed = json.loads(result) if result else []
                ctx.slack_mentions = parsed if isinstance(parsed, list) else []
            except Exception as exc:
                logger.warning("[PROACTIVE] Slack poll failed: %s", exc)

        self._context = ctx
        if ctx.has_urgent_items():
            logger.info(
                "[PROACTIVE] %d events, %d emails, %d mentions",
                len(ctx.calendar_events),
                len(ctx.unread_emails),
                len(ctx.slack_mentions),
            )

    def get_prompt_injection(self) -> str:
        return self._context.compile_prompt_block()

    async def maybe_reach_out(
        self,
        user_id: str,
        channel_id: str,
        last_message_time: float = None,
    ) -> str | None:
        """Return a proactive message if policy allows speaking."""
        from datetime import datetime, timedelta, timezone

        IST = timezone(timedelta(hours=5, minutes=30))  # noqa: N806
        now = datetime.now(IST)
        decision = self.policy_scorer.score(
            ProactivePolicyInput(
                user_id=user_id,
                channel_id=channel_id,
                now_hour=now.hour,
                last_message_time=last_message_time,
                calendar_events=self._context.calendar_events,
                unread_emails=self._context.unread_emails,
                slack_mentions=self._context.slack_mentions,
                recent_memory_summaries=[],
            )
        )
        if not decision.should_reach_out:
            logger.debug(
                "[PROACTIVE] skipped for %s/%s: %s %.3f",
                user_id,
                channel_id,
                decision.reason,
                decision.score,
            )
            return None

        try:
            from sci_fi_dashboard.chat_pipeline import persona_chat
            from sci_fi_dashboard.schemas import ChatRequest

            payload = (
                "Check in naturally with the user. "
                "Don't say you're doing an automated check-in. "
                "Reference something from recent memory if you remember it: "
                "a topic they mentioned, something they were working on. "
                f"Reach-out reason: {decision.reason}; evidence: {', '.join(decision.evidence)}. "
                "Keep it brief and warm."
            )
            request = ChatRequest(message=payload, user_id=user_id, history=[])
            result = await persona_chat(request, target=user_id)
            reply = result.get("reply", "")
            if "---\n**Context Usage:**" in reply:
                reply = reply.split("---\n**Context Usage:**")[0].strip()
            return reply if reply else None
        except Exception as exc:
            logger.warning("[PROACTIVE] maybe_reach_out failed: %s", exc)
            return None
