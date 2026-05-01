"""Gateway processing pipeline, background workers, and utility functions."""

import asyncio
import contextlib
import json
import logging
import os
import re
import sqlite3
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import psutil
from synapse_config import SynapseConfig

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.action_receipts import (
    ActionReceipt,
    guard_reply_against_unreceipted_claims,
)
from sci_fi_dashboard.conv_kg_extractor import run_batch_extraction
from sci_fi_dashboard.multiuser.session_key import build_session_key
from sci_fi_dashboard.schemas import ChatRequest
from sci_fi_dashboard.session_ingest import _ingest_session_background

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


class ReceiptReply(str):
    """String reply that carries verified action receipts for downstream guards."""

    action_receipts: list[ActionReceipt]

    def __new__(cls, value: str, receipts: list[ActionReceipt]):
        obj = str.__new__(cls, value)
        obj.action_receipts = list(receipts)
        return obj


def _receipts_from_value(value) -> list[ActionReceipt]:
    raw = getattr(value, "action_receipts", None)
    if raw is None and isinstance(value, dict):
        raw = value.get("action_receipts")
    receipts: list[ActionReceipt] = []
    for item in raw or []:
        receipt = ActionReceipt.from_mapping(item)
        if receipt is not None:
            receipts.append(receipt)
    return receipts


def _serialize_receipts(receipts: list[ActionReceipt]) -> list[dict]:
    return [receipt.to_dict() for receipt in receipts]


def _prepare_history_for_llm(messages: list[dict]) -> list[dict]:
    """Strip transcript-only metadata and inject recent action proof as context."""

    prepared: list[dict] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = message.get("content")
        if content is None:
            continue
        prepared.append({"role": role, "content": str(content)})

    receipt_context = _format_recent_action_receipt_context(messages)
    if receipt_context:
        prepared.append({"role": "system", "content": receipt_context})
    return prepared


def _format_recent_action_receipt_context(messages: list[dict], limit: int = 6) -> str:
    receipts: list[ActionReceipt] = []
    for message in reversed(messages or []):
        for receipt in _receipts_from_value(message):
            receipts.append(receipt)
            if len(receipts) >= limit:
                break
        if len(receipts) >= limit:
            break
    receipts.reverse()
    if not receipts:
        return ""

    lines = [
        "RECENT ACTION RECEIPTS:",
        "Use these to answer follow-up questions about what Synapse actually did in prior turns.",
        "Do not contradict verified receipts.",
    ]
    lines.extend(receipt.to_prompt_line() for receipt in receipts)
    return "\n".join(lines)


def _ensure_user_visible_reply(reply: str) -> str:
    """Prevent empty or diagnostics-only replies from reaching chat channels."""
    text = _strip_reasoning_wrappers(str(reply or ""))
    for marker in ("\u200b", "\u200c", "\u200d", "\ufeff", "\x00"):
        text = text.replace(marker, "")
    sep = text.find("\n\n---\n**Context Usage:**")
    if sep == -1:
        sep = text.find("\n---\n**Context Usage:**")
    if sep != -1:
        text = text[:sep]
    visible = _strip_channel_markdown(text).strip()
    if not visible or visible.startswith("---\n**Context Usage:**"):
        return "I heard you. I hit an empty response there, so please try that once more."
    return visible


def _strip_reasoning_wrappers(text: str) -> str:
    """Remove model-internal reasoning/meta wrappers before channel delivery."""
    cleaned = str(text or "")
    cleaned = re.sub(r"<think\b[^>]*>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?final\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?think\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(?im)^\s*thought\s+for\s+\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?)\s*$\n?",
        "",
        cleaned,
    )
    return cleaned


def _strip_channel_markdown(text: str) -> str:
    """Make LLM markdown feel like normal chat text in WhatsApp/Telegram."""
    cleaned = str(text or "")
    cleaned = re.sub(r"```(?:\w+)?\n([\s\S]*?)```", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "- ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _memory_db_path_from_config(cfg) -> Path:
    db_dir = getattr(cfg, "db_dir", None)
    if db_dir is None:
        db_dir = Path(getattr(cfg, "data_root", Path.home() / ".synapse" / "workspace")) / "db"
    return Path(db_dir) / "memory.db"


def _sync_user_turn_memory(
    *,
    user_msg: str,
    session_key: str,
    target: str,
    cfg,
) -> int:
    """Immediately persist lightweight structured user facts for this turn.

    Full vector/KG ingestion still runs on /new, but identity, people, projects,
    preferences, routines, corrections, and commitments should not wait for a
    session archive. This keeps Jarvis-like continuity alive during long chats.
    """
    try:
        from sci_fi_dashboard.user_memory import distill_and_upsert_user_memory_facts

        db_path = _memory_db_path_from_config(cfg)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            facts = distill_and_upsert_user_memory_facts(
                conn,
                text=f"User: {user_msg}",
                user_id=session_key,
                source_doc_id=None,
            )
            conn.commit()
        finally:
            conn.close()

        if facts:
            with contextlib.suppress(Exception):
                sbs = deps.get_sbs_for_target(target)
                if hasattr(sbs, "sync_user_memory"):
                    sbs.sync_user_memory(session_key, str(db_path))
            logger.info(
                "immediate_user_memory_synced",
                extra={
                    "session_key": session_key,
                    "target": target,
                    "facts": len(facts),
                },
            )
        return len(facts)
    except Exception:
        logger.exception("immediate user-memory sync failed for %s", session_key)
        return 0


@dataclass(frozen=True)
class ParsedReminder:
    task: str
    when: datetime


_REMINDER_TRIGGERS = (
    "can you remind",
    "can you nudge",
    "can you ping",
    "can you notify",
    "remind me",
    "set a reminder",
    "reminder for",
    "don't forget",
    "dont forget",
    "nudge me",
    "ping me",
    "notify me",
    "call me out",
)

_DURATION_RE = re.compile(
    r"\b(?:in|after)\s+(?P<amount>\d{1,3})\s*"
    r"(?P<unit>minutes?|mins?|min|hours?|hrs?|hr|days?|day)\b",
    re.IGNORECASE,
)
_RELATIVE_BEFORE_RE = re.compile(
    r"\b(?P<amount>\d{1,3})\s*"
    r"(?P<unit>minutes?|mins?|min|hours?|hrs?|hr|days?|day)\s+before\b(?:\s+it)?",
    re.IGNORECASE,
)
_PASSIVE_COMMITMENT_TERMS = (
    "appointment",
    "call",
    "class",
    "date",
    "deadline",
    "demo",
    "dinner",
    "doctor",
    "exam",
    "flight",
    "interview",
    "meeting",
    "presentation",
    "review",
    "standup",
    "train",
)
_TIME_HINT_RE = re.compile(
    r"\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
    re.IGNORECASE,
)
_NO_ARTICLE_EVENTS = {"breakfast", "brunch", "dinner", "lunch"}


def _duration_from_match(match: re.Match[str]) -> timedelta:
    amount = int(match.group("amount"))
    unit = match.group("unit").lower()
    if unit.startswith(("hour", "hr")):
        return timedelta(hours=amount)
    if unit.startswith("day"):
        return timedelta(days=amount)
    return timedelta(minutes=amount)


def _get_local_reminder_tz() -> timezone:
    """Use configured user timezone for natural-language reminders."""
    try:
        cfg = SynapseConfig.load()
        tz_offset = cfg.session.get("timezone_offset_hours")
        if tz_offset is not None:
            return timezone(timedelta(hours=float(tz_offset)))
    except Exception:
        pass

    local_offset = datetime.now(UTC).astimezone().utcoffset()
    return timezone(local_offset) if local_offset else UTC


def _event_article(event: str) -> str:
    lowered = event.strip().lower()
    if lowered.startswith(("the ", "my ", "a ", "an ")):
        return ""
    if lowered in _NO_ARTICLE_EVENTS:
        return ""
    return "the "


def _is_reminder_request(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in _REMINDER_TRIGGERS)


def _extract_event_name(text: str) -> str | None:
    event_match = re.search(
        r"\b(?:today|tomorrow)?\s*(?:the\s+|my\s+)?"
        r"(?P<event>[a-z0-9][a-z0-9 '\-]{2,90}?)\s+"
        r"(?:is|starts|happens)\s+at\b",
        text,
        re.IGNORECASE,
    )
    if not event_match:
        return None
    event = event_match.group("event").strip(" .,!?:;")
    event = re.sub(r"\s+", " ", event)
    return event or None


def _extract_reminder_task(text: str) -> str:
    task = text.strip()
    lowered = task.lower()
    for prefix in (
        "remind me to ",
        "set a reminder to ",
        "don't forget to ",
        "dont forget to ",
        "nudge me to ",
        "ping me to ",
        "notify me to ",
    ):
        if lowered.startswith(prefix):
            task = task[len(prefix) :]
            break
    else:
        event = _extract_event_name(text)
        action_match = re.search(
            r"\bneed\s+(?:at\s+least\s+)?"
            r"(?:\d{1,3}\s*(?:minutes?|mins?|min|hours?|hrs?|hr)\s+before\s+it\s+)?"
            r"to\s+(?P<action>[^.!?]+)",
            text,
            re.IGNORECASE,
        )
        if event and action_match:
            action = action_match.group("action").strip(" .,!?:;")
            if event.lower() not in action.lower():
                return f"{action} for {_event_article(event)}{event}".strip()
            return action or event
        if event:
            return event

        ask_match = re.search(
            r"\b(?:remind|nudge|ping|notify)\s+me\b[^.!?]{0,80}?\b(?:to|about)\s+"
            r"(?P<task>[^.!?]+)",
            text,
            re.IGNORECASE,
        )
        if ask_match:
            task = ask_match.group("task")

    task = _RELATIVE_BEFORE_RE.sub(" ", task)
    task = _DURATION_RE.sub(" ", task)

    for marker in (" by ", " at ", " on ", " tomorrow", " today", " before "):
        idx = task.lower().find(marker)
        if idx > 0:
            task = task[:idx]
            break

    return task.strip(" .,!") or "your reminder"


def _parse_reminder_request(text: str, now: datetime | None = None) -> ParsedReminder | None:
    """Parse common reminder phrasing into a one-shot datetime + task."""
    if not _is_reminder_request(text):
        return None

    try:
        from dateutil import parser as date_parser
    except Exception:
        return None

    base = now or datetime.now(_get_local_reminder_tz())
    if base.tzinfo is None:
        base = base.replace(tzinfo=_get_local_reminder_tz())

    duration_match = _DURATION_RE.search(text)
    relative_before_matches = list(_RELATIVE_BEFORE_RE.finditer(text))
    if duration_match and not relative_before_matches:
        return ParsedReminder(
            task=_extract_reminder_task(text),
            when=base.replace(microsecond=0) + _duration_from_match(duration_match),
        )

    parse_text = _RELATIVE_BEFORE_RE.sub(" ", text)
    parse_text = _DURATION_RE.sub(" ", parse_text)
    lowered = text.lower()
    date_explicit = bool(
        re.search(
            r"\b(today|tomorrow|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
            lowered,
        )
    )
    if "tomorrow" in lowered:
        parse_text = re.sub(
            r"\btomorrow\b",
            (base + timedelta(days=1)).strftime("%B %d %Y"),
            parse_text,
            flags=re.IGNORECASE,
        )
    elif "today" in lowered:
        parse_text = re.sub(
            r"\btoday\b",
            base.strftime("%B %d %Y"),
            parse_text,
            flags=re.IGNORECASE,
        )

    try:
        when = date_parser.parse(
            parse_text,
            fuzzy=True,
            default=base.replace(second=0, microsecond=0),
            ignoretz=True,
        )
    except (ValueError, OverflowError, TypeError):
        return None

    if when.tzinfo is None:
        when = when.replace(tzinfo=base.tzinfo)

    if relative_before_matches:
        # If the user says both "need 20 minutes before" and "nudge me
        # 30 minutes before", the last lead-time phrase is the requested nudge.
        when = when - _duration_from_match(relative_before_matches[-1])

    if when <= base:
        # If user supplied a month/day without a year and it resolved to past,
        # carry it to next year instead of silently creating a dead cron job.
        try:
            candidate = when.replace(year=when.year + 1)
        except ValueError:
            candidate = when + timedelta(days=365)
        when = candidate

    return ParsedReminder(task=_extract_reminder_task(text), when=when)


def _is_passive_commitment_candidate(text: str) -> bool:
    """Detect natural commitments worth nudging without explicit reminder words."""
    lowered = str(text or "").lower()
    if _is_reminder_request(lowered):
        return False
    if not _TIME_HINT_RE.search(lowered):
        return False
    return any(term in lowered for term in _PASSIVE_COMMITMENT_TERMS)


def _extract_passive_event_name(text: str) -> str | None:
    patterns = (
        r"\b(?:i\s+have|i've\s+got|ive\s+got|got|there(?:'s| is))\s+"
        r"(?:a\s+|an\s+|my\s+|the\s+)?"
        r"(?P<event>[a-z0-9][a-z0-9 '\-]{2,80}?)\s+"
        r"(?:today\s+|tomorrow\s+)?(?:at|by)\b",
        r"\b(?:today\s+|tomorrow\s+)?(?:a\s+|an\s+|my\s+|the\s+)?"
        r"(?P<event>[a-z0-9][a-z0-9 '\-]{2,80}?)\s+"
        r"(?:is|starts|happens)\s+at\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        event = re.sub(r"\s+", " ", match.group("event")).strip(" .,!?:;")
        if event and any(term in event.lower() for term in _PASSIVE_COMMITMENT_TERMS):
            return event
    return _extract_event_name(text)


def _extract_passive_commitment_task(text: str) -> str:
    event = _extract_passive_event_name(text) or "that thing"
    action_match = re.search(
        r"\bneed\s+(?:at\s+least\s+)?"
        r"(?:\d{1,3}\s*(?:minutes?|mins?|min|hours?|hrs?|hr)\s+before\s+it\s+)?"
        r"to\s+(?P<action>[^.!?]+)",
        text,
        re.IGNORECASE,
    )
    if action_match:
        action = action_match.group("action").strip(" .,!?:;")
        if action:
            return f"{action} for {_event_article(event)}{event}".strip()
    return f"get ready for {_event_article(event)}{event}".strip()


def _parse_passive_commitment_nudge(
    text: str,
    now: datetime | None = None,
    *,
    default_lead: timedelta = timedelta(minutes=15),
) -> ParsedReminder | None:
    """Create a proactive nudge from natural event timing, without hijacking chat."""
    if not _is_passive_commitment_candidate(text):
        return None

    try:
        from dateutil import parser as date_parser
    except Exception:
        return None

    base = now or datetime.now(_get_local_reminder_tz())
    if base.tzinfo is None:
        base = base.replace(tzinfo=_get_local_reminder_tz())

    parse_text = _RELATIVE_BEFORE_RE.sub(" ", text)
    parse_text = _DURATION_RE.sub(" ", parse_text)
    lowered = text.lower()
    date_explicit = bool(
        re.search(
            r"\b(today|tomorrow|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
            lowered,
        )
    )
    if "tomorrow" in lowered:
        parse_text = re.sub(
            r"\btomorrow\b",
            (base + timedelta(days=1)).strftime("%B %d %Y"),
            parse_text,
            flags=re.IGNORECASE,
        )
    elif "today" in lowered:
        parse_text = re.sub(
            r"\btoday\b",
            base.strftime("%B %d %Y"),
            parse_text,
            flags=re.IGNORECASE,
        )

    try:
        event_at = date_parser.parse(
            parse_text,
            fuzzy=True,
            default=base.replace(second=0, microsecond=0),
            ignoretz=True,
        )
    except (ValueError, OverflowError, TypeError):
        return None

    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=base.tzinfo)
    if event_at <= base:
        if "today" in lowered:
            return None
        if not date_explicit:
            event_at = event_at + timedelta(days=1)
        else:
            try:
                event_at = event_at.replace(year=event_at.year + 1)
            except ValueError:
                event_at = event_at + timedelta(days=365)

    before_matches = list(_RELATIVE_BEFORE_RE.finditer(text))
    lead = _duration_from_match(before_matches[-1]) if before_matches else default_lead
    nudge_at = event_at - lead
    if nudge_at <= base and event_at > base:
        nudge_at = min(event_at - timedelta(minutes=1), base + timedelta(minutes=1))
    if nudge_at <= base:
        return None

    return ParsedReminder(task=_extract_passive_commitment_task(text), when=nudge_at)


def _format_tools_command(channel_id: str, chat_id: str) -> str:
    registry = deps.tool_registry
    if registry is None:
        return "No tools are loaded right now."

    from sci_fi_dashboard.chat_pipeline import _is_owner_sender
    from sci_fi_dashboard.tool_registry import ToolContext

    tools = registry.resolve(
        ToolContext(
            chat_id=chat_id,
            sender_id=chat_id,
            sender_is_owner=_is_owner_sender(chat_id),
            workspace_dir=str(deps.WORKSPACE_ROOT),
            config=getattr(deps._synapse_cfg, "session", {}),
            channel_id=channel_id,
        )
    )
    if not tools:
        return "No tools are available for this chat."

    lines = ["Available tools:"]
    for tool in sorted(tools, key=lambda t: t.name):
        owner = " owner-only" if getattr(tool, "owner_only", False) else ""
        lines.append(f"- {tool.name}{owner}: {tool.description}")
    return "\n".join(lines)


async def _maybe_handle_reminder_command(
    user_msg: str,
    chat_id: str,
    channel_id: str,
    *,
    now: datetime | None = None,
) -> str | None:
    parsed = _parse_reminder_request(user_msg, now=now)
    if parsed is None:
        return None

    cron_service = getattr(deps, "cron_service", None)
    if cron_service is None:
        return "I understood the reminder, but the cron scheduler is not running yet."

    delivery_prompt = (
        "CRON DELIVERY MODE: Output only the Telegram reminder text. No headers, "
        "labels, or meta-commentary. Your reply is delivered directly to the user.\n\n"
        f"Reminder due now: {parsed.task}.\n"
        f"Original request: {user_msg}\n"
        "Write one short, warm, close-friend nudge. If the user asked to be called "
        "out, do it lightly."
    )
    job = cron_service.add(
        {
            "name": f"Reminder: {parsed.task[:80]}",
            "schedule": {"kind": "at", "at": parsed.when.isoformat()},
            "payload": {
                "kind": "systemEvent",
                "message": delivery_prompt,
                "timeout_seconds": 60,
            },
            "delivery": {
                "mode": "announce",
                "channel": channel_id,
                "to": chat_id,
            },
            "session_target": "main",
            "wake_mode": "now",
            "enabled": True,
        }
    )
    receipts = [
        ActionReceipt(
            action="reminder_schedule",
            status="verified",
            evidence=f"Cron job {getattr(job, 'id', 'unknown')} scheduled for {parsed.when.isoformat()}",
            confidence=0.96,
        )
    ]
    return guard_reply_against_unreceipted_claims(
        f"Done - I'll nudge you at {parsed.when.strftime('%Y-%m-%d %H:%M %Z')}: "
        f"{parsed.task}.",
        receipts,
    )


def _cron_has_matching_nudge(
    cron_service,
    *,
    name: str,
    at_iso: str,
    channel_id: str,
    chat_id: str,
) -> bool:
    list_jobs = getattr(cron_service, "list", None)
    if not callable(list_jobs):
        return False
    try:
        jobs = list_jobs(enabled_only=True)
    except TypeError:
        jobs = list_jobs()
    except Exception:
        return False

    for job in jobs or []:
        schedule = getattr(job, "schedule", None)
        delivery = getattr(job, "delivery", None)
        if not schedule or not delivery:
            continue
        if str(getattr(job, "name", "")) != name:
            continue
        if str(getattr(schedule, "at", "")) != at_iso:
            continue
        if str(getattr(delivery, "channel", "")) != str(channel_id):
            continue
        if str(getattr(delivery, "to", "")) != str(chat_id):
            continue
        return True
    return False


async def _maybe_schedule_passive_commitment_nudge(
    user_msg: str,
    chat_id: str,
    channel_id: str,
    *,
    now: datetime | None = None,
) -> str | None:
    parsed = _parse_passive_commitment_nudge(user_msg, now=now)
    if parsed is None:
        return None

    cron_service = getattr(deps, "cron_service", None)
    if cron_service is None:
        logger.info("passive commitment nudge skipped: cron scheduler unavailable")
        return None

    at_iso = parsed.when.isoformat()
    job_name = f"Passive nudge: {parsed.task[:80]}"
    if _cron_has_matching_nudge(
        cron_service,
        name=job_name,
        at_iso=at_iso,
        channel_id=channel_id,
        chat_id=chat_id,
    ):
        return None

    delivery_prompt = (
        "CRON DELIVERY MODE: Output only the Telegram reminder text. No headers, "
        "labels, or meta-commentary. Your reply is delivered directly to the user.\n\n"
        f"Reminder due now: {parsed.task}.\n"
        f"Original message: {user_msg}\n"
        "Write one short, warm, close-friend nudge. Sound natural, not like a task bot."
    )
    job = cron_service.add(
        {
            "name": job_name,
            "schedule": {"kind": "at", "at": at_iso},
            "payload": {
                "kind": "systemEvent",
                "message": delivery_prompt,
                "timeout_seconds": 60,
            },
            "delivery": {
                "mode": "announce",
                "channel": channel_id,
                "to": chat_id,
            },
            "session_target": "main",
            "wake_mode": "now",
            "enabled": True,
        }
    )
    receipts = [
        ActionReceipt(
            action="reminder_schedule",
            status="verified",
            evidence=f"Cron job {getattr(job, 'id', 'unknown')} scheduled for {at_iso}",
            confidence=0.94,
        )
    ]
    return ReceiptReply(
        guard_reply_against_unreceipted_claims(
            f"I'll nudge you at {parsed.when.strftime('%Y-%m-%d %H:%M %Z')}: "
            f"{parsed.task}.",
            receipts,
        ),
        receipts,
    )


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_databases() -> dict:
    """HLTH-01: Check existence of each SQLite database file."""
    from sci_fi_dashboard.db import DB_PATH as MEMORY_DB
    from sci_fi_dashboard.sqlite_graph import DB_PATH as GRAPH_DB

    result = {
        "memory_db": {
            "status": "ok" if os.path.exists(MEMORY_DB) else "missing",
            "path": MEMORY_DB,
        },
        "knowledge_graph_db": {
            "status": "ok" if os.path.exists(GRAPH_DB) else "missing",
            "path": GRAPH_DB,
        },
    }
    try:
        from sci_fi_dashboard.emotional_trajectory import DB_PATH as TRAJ_DB

        result["emotional_trajectory_db"] = {
            "status": "ok" if os.path.exists(TRAJ_DB) else "missing",
            "path": TRAJ_DB,
        }
    except ImportError:
        result["emotional_trajectory_db"] = {"status": "not_installed"}
    return result


def _check_llm_provider() -> dict:
    """HLTH-01: Report LLM provider configuration status."""
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    casual_model = cfg.model_mappings.get("casual", {}).get("model", "")
    if not casual_model:
        return {"status": "unconfigured", "model": None}
    if "ollama" in casual_model:
        reachable = _port_open("localhost", 11434)
        return {
            "status": "ok" if reachable else "down",
            "provider": "ollama",
            "model": casual_model,
        }
    has_providers = bool(cfg.providers)
    return {
        "status": "configured" if has_providers else "unconfigured",
        "provider": "cloud",
        "model": casual_model,
    }


def validate_env() -> None:
    """Validate required and optional env keys."""
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    print(f"[INFO] Synapse data root: {cfg.data_root}")

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        print(
            "[WARN] GEMINI_API_KEY not set -- direct Gemini routing disabled "
            "(configure in synapse.json for Phase 2)"
        )

    if not os.environ.get("GROQ_API_KEY", "").strip():
        print("[WARN] GROQ_API_KEY not set -- voice transcription disabled")
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("[WARN] OPENROUTER_API_KEY not set -- fallback model routing disabled")
    if not os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip():
        print("[WARN] WHATSAPP_BRIDGE_TOKEN not set -- WhatsApp bridge unauthenticated")

    from synapse_config import SynapseConfig as _SC  # noqa: N814

    ollama_on = _port_open("localhost", 11434)
    lance_dir = _SC.load().db_dir / "lancedb"
    lance_on = lance_dir.exists()
    groq_on = bool(os.environ.get("GROQ_API_KEY", "").strip())
    openrouter_on = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    whatsapp_on = bool(os.environ.get("WHATSAPP_BRIDGE_TOKEN", "").strip())

    print("[INFO] Feature availability:")
    print(f"   Ollama         {'[ON]' if ollama_on else '[--]'}  local embedding + The Vault")
    print(f"   LanceDB        {'[ON]' if lance_on else '[--]'}  vector search (embedded)")
    print(f"   Groq           {'[ON]' if groq_on else '[--]'}  voice transcription")
    print(f"   OpenRouter     {'[ON]' if openrouter_on else '[--]'}  fallback model routing")
    print(f"   WhatsApp       {'[ON]' if whatsapp_on else '[--]'}  bridge authentication")


def _extract_cli_send_route(raw_stdout: str) -> str:
    raw = (raw_stdout or "").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return (
        payload.get("via") or payload.get("delivery") or payload.get("payload", {}).get("via") or ""
    )


# ---------------------------------------------------------------------------
# Auto-Continue Background Task
# ---------------------------------------------------------------------------


async def continue_conversation(
    target: str,
    messages: list[dict],
    last_reply: str,
    channel_id: str = "whatsapp",
):
    """H-10: Background task to generate continuation and send it via the channel."""
    print(f"[REFRESH] [AUTO-CONTINUE] Handling cut-off response for {target}...")

    new_history = [m.copy() for m in messages]
    new_history.append({"role": "assistant", "content": last_reply})
    new_history.append(
        {
            "role": "user",
            "content": (
                "You were cut off. Continue exactly from where you stopped. "
                "Do not repeat what you already said. Just write the rest."
            ),
        }
    )

    try:
        from sci_fi_dashboard.llm_wrappers import call_gemini_flash

        continuation = await call_gemini_flash(new_history, temperature=0.7, max_tokens=2000)

        if not continuation.strip():
            print("[WARN] Continuation was empty.")
            return

        channel = deps.channel_registry.get(channel_id)
        if channel is not None:
            try:
                await channel.send(target, continuation)
                print(
                    f"[AUTO-CONTINUE] Sent continuation ({len(continuation)} chars) "
                    f"via {channel_id}"
                )
            except Exception as send_err:
                print(f"[WARN] [AUTO-CONTINUE] Channel send failed: {send_err}")
        else:
            print(
                f"[AUTO-CONTINUE] Continuation ready ({len(continuation)} chars) "
                f"but channel '{channel_id}' not available."
            )

    except Exception as e:
        print(f"[ERROR] [AUTO-CONTINUE] Failed: {e}")


# ---------------------------------------------------------------------------
# LLM Adapter for Compaction (bridges SynapseLLMRouter → compaction contract)
# ---------------------------------------------------------------------------


class _LLMClientAdapter:
    """Adapter: exposes acompletion(messages=[...]) using SynapseLLMRouter._do_call().

    compaction.py requires: await llm_client.acompletion(messages=[...])
    returning an object with .choices[0].message.content (plain string).

    SynapseLLMRouter._do_call(role, messages) returns the raw litellm response
    which already has that shape. We use the "casual" role for compaction summaries.
    """

    def __init__(self, router) -> None:
        self._router = router

    async def acompletion(self, messages: list[dict], **kwargs):
        """Forward to SynapseLLMRouter._do_call with role='casual'.

        Passes max_tokens=2000 (not the _do_call default of 1000) so that
        compaction summaries of large conversations are not truncated.
        """
        max_tokens = kwargs.get("max_tokens", 2000)
        return await self._router._do_call("casual", messages, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Async Gateway Processing Pipeline
# ---------------------------------------------------------------------------

# Module-level set prevents GC of fire-and-forget background tasks (Research Pitfall 6).
_background_tasks: set[asyncio.Task] = set()

# GC anchor for session ingestion background tasks (/new command)
_session_ingest_tasks: set[asyncio.Task] = set()

# GC anchor for diary generation background tasks (/new command)
_diary_tasks: set[asyncio.Task] = set()

PERIODIC_MEMORY_FLUSH_MESSAGES = 50
PERIODIC_MEMORY_FLUSH_SECONDS = 6 * 60 * 60


async def _send_voice_note(reply: str, chat_id: str) -> None:
    """Background task: synthesize TTS, save to media store, deliver via WhatsApp."""
    try:
        from sci_fi_dashboard.media.store import save_media_buffer
        from sci_fi_dashboard.tts import TTSEngine

        engine = TTSEngine()
        ogg_bytes = await engine.synthesize(reply)
        if not ogg_bytes:
            return  # TTS disabled, text too long, ffmpeg missing, or synthesis failed

        # Save OGG to media store for bridge to fetch
        saved = save_media_buffer(
            ogg_bytes,
            content_type="audio/ogg",
            subdir="tts_outbound",
        )

        # Build local URL for bridge to fetch
        audio_url = f"http://127.0.0.1:8000/media/tts_outbound/{saved.path.name}"

        # Deliver via WhatsApp channel
        wa_channel = deps.channel_registry.get("whatsapp")
        if wa_channel and hasattr(wa_channel, "send_voice_note"):
            await wa_channel.send_voice_note(chat_id, audio_url)
        else:
            logger.warning("TTS: WhatsApp channel not available for voice note delivery")
    except Exception:
        logger.exception("TTS background task failed for chat_id=%s", chat_id)


async def _generate_diary_background(
    archived_path: Path,
    agent_id: str,
    session_key: str,
) -> None:
    """Background coroutine: generate a diary entry from an archived session transcript."""
    try:
        from sci_fi_dashboard.multiuser.transcript import load_messages

        messages = await load_messages(archived_path)
        if not messages:
            return
        await deps.diary_engine.generate_entry(
            session_id=session_key,
            user_id=agent_id,
            messages=messages,
        )
        logger.info("[Diary] Entry generated for session %s", session_key)
    except Exception:
        logger.warning(
            "[Diary] Background diary generation failed for %s", session_key, exc_info=True
        )


async def _write_memory_flush_snapshot(snapshot_path: Path, messages: list[dict]) -> None:
    def _write() -> None:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            for msg in messages:
                fh.write(json.dumps(msg, separators=(",", ":")) + "\n")

    await asyncio.to_thread(_write)


async def _maybe_schedule_periodic_memory_flush(
    *,
    session_key: str,
    agent_id: str,
    data_root: Path,
    transcript_file: Path,
    session_store,
    hemisphere: str = "safe",
) -> None:
    """Flush active transcript tail to long-term memory every 50 msgs or 6h.

    Unlike /new, this does not rotate the session. It snapshots only messages
    not previously flushed so long-running Telegram chats keep durable memory
    without duplicate whole-transcript ingestion.
    """
    from sci_fi_dashboard.multiuser.transcript import load_messages

    try:
        entry = await session_store.get(session_key)
        if entry is None or not transcript_file.exists():
            return

        messages = await load_messages(transcript_file)
        total_count = len(messages)
        last_count = max(0, int(getattr(entry, "memory_flush_message_count", 0) or 0))
        new_count = total_count - last_count
        if new_count <= 0:
            return

        now = time.time()
        last_flush_at = getattr(entry, "memory_flush_at", None)
        flush_baseline = float(last_flush_at) if last_flush_at is not None else float(entry.updated_at)
        count_due = new_count >= PERIODIC_MEMORY_FLUSH_MESSAGES
        time_due = (now - flush_baseline) >= PERIODIC_MEMORY_FLUSH_SECONDS
        if not (count_due or time_due):
            return

        batch = messages[last_count:]
        if not batch:
            return

        snapshot_path = Path(
            f"{transcript_file}.memoryflush.{int(now * 1000)}.{last_count}-{total_count}"
        )
        await _write_memory_flush_snapshot(snapshot_path, batch)
        await session_store.update(
            session_key,
            {
                "memory_flush_at": now,
                "memory_flush_message_count": total_count,
            },
        )

        task = asyncio.create_task(
            _ingest_session_background(
                archived_path=snapshot_path,
                agent_id=agent_id,
                session_key=session_key,
                hemisphere=hemisphere,
            )
        )
        _session_ingest_tasks.add(task)
        task.add_done_callback(_session_ingest_tasks.discard)
        logger.info(
            "periodic_memory_flush_scheduled",
            extra={
                "session_key": session_key,
                "agent_id": agent_id,
                "messages": new_count,
                "reason": "count" if count_due else "time",
            },
        )
    except Exception:
        logger.exception("periodic memory flush scheduling failed for %s", session_key)


async def _handle_new_command(
    session_key: str,
    agent_id: str,
    data_root: "Path",
    session_store,
    hemisphere: str = "safe",
) -> str:
    """Archive current transcript, fire full memory-loop ingestion, rotate session ID.

    The old JSONL is renamed (not deleted).
    Background task runs vector + KG ingestion on the archived transcript.
    Returns confirmation immediately — callers must NOT call the LLM.
    """
    from sci_fi_dashboard.multiuser.transcript import archive_transcript, transcript_path

    entry = await session_store.get(session_key)
    archived_path = None

    if entry is not None:
        old_path = transcript_path(entry, data_root, agent_id)
        archived_path = await archive_transcript(old_path) if old_path.exists() else None

    # Clear in-memory cache
    deps.conversation_cache.invalidate(session_key)
    with contextlib.suppress(Exception):
        from sci_fi_dashboard.chat_pipeline import clear_agent_workspace_session_prefix

        clear_agent_workspace_session_prefix(session_key)

    # Rotate session ID → new JSONL on next message
    # CRITICAL: delete() first — _merge_entry() never overwrites session_id via update()
    await session_store.delete(session_key)
    await session_store.update(session_key, {"compaction_count": 0})

    # Fire-and-forget: full memory loop (vector + KG) in background
    if archived_path is not None:
        task = asyncio.create_task(
            _ingest_session_background(
                archived_path=archived_path,
                agent_id=agent_id,
                session_key=session_key,
                hemisphere=hemisphere,
            )
        )
        _session_ingest_tasks.add(task)
        task.add_done_callback(_session_ingest_tasks.discard)

        # Fire-and-forget: diary entry generation (independent of ingest)
        if deps.diary_engine is not None:
            diary_task = asyncio.create_task(
                _generate_diary_background(
                    archived_path=archived_path,
                    agent_id=agent_id,
                    session_key=session_key,
                )
            )
            _diary_tasks.add(diary_task)
            diary_task.add_done_callback(_diary_tasks.discard)

    return "Session archived! I'll remember everything. Starting fresh now."


def _direct_persona_session_key(request: ChatRequest, target: str) -> str:
    explicit = (request.session_key or "").strip()
    if explicit:
        return explicit
    user_id = (request.user_id or "default").strip() or "default"
    return f"cli:{target}:{user_id}"


async def process_direct_persona_chat(
    request: ChatRequest,
    target: str,
    background_tasks=None,
    mcp_context: str = "",
) -> dict:
    """Run /chat/{persona} through the durable session transcript path.

    Direct persona chat is used by the CLI and OpenAI-compatible local clients.
    Unlike channel workers, it does not enter process_message_pipeline(), so it
    must capture turns here before calling the LLM and let /new ingest them.
    """
    from sci_fi_dashboard.chat_pipeline import persona_chat
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import (
        append_message,
        load_messages,
        transcript_path,
    )

    cfg = SynapseConfig.load()
    data_root = cfg.data_root
    session_cfg = getattr(cfg, "session", {}) or {}
    session_key = _direct_persona_session_key(request, target)
    session_type = (request.session_type or "safe").strip().lower() or "safe"
    hemisphere = "spicy" if session_type == "spicy" else "safe"

    store = SessionStore(agent_id=target, data_root=data_root)
    entry = await store.get(session_key)
    if entry is None:
        entry = await store.update(session_key, {})
    t_path = transcript_path(entry, data_root, target)

    if request.message.strip().lower() == "/new":
        reply = await _handle_new_command(
            session_key=session_key,
            agent_id=target,
            data_root=data_root,
            session_store=store,
            hemisphere=hemisphere,
        )
        return {
            "reply": reply,
            "persona": f"synapse_{target}",
            "memory_method": "session_archive",
            "model": "session-command",
        }

    raw_history_limit = session_cfg.get("cli_history_limit", session_cfg.get("historyLimit", 50))
    try:
        history_limit = int(raw_history_limit)
    except (TypeError, ValueError):
        history_limit = 50

    messages = deps.conversation_cache.get(session_key)
    if messages is None:
        messages = await load_messages(t_path, limit=history_limit)
        deps.conversation_cache.put(session_key, messages)

    history_for_llm = (
        _prepare_history_for_llm(list(messages))
        if messages
        else _prepare_history_for_llm(list(request.history or []))
    )
    action_receipts: list[ActionReceipt] = []
    user_dict = {"role": "user", "content": request.message}
    await append_message(t_path, user_dict)
    action_receipts.append(
        ActionReceipt(
            action="message_capture",
            status="verified",
            evidence=f"User turn appended to transcript for {session_key}.",
            confidence=0.99,
        )
    )
    deps.conversation_cache.append(session_key, user_dict)
    fact_count = _sync_user_turn_memory(
        user_msg=request.message,
        session_key=session_key,
        target=target,
        cfg=cfg,
    )
    if fact_count:
        action_receipts.append(
            ActionReceipt(
                action="memory_save",
                status="verified",
                evidence=f"{fact_count} user memory fact(s) persisted.",
                confidence=0.92,
            )
        )
    passive_nudge_reply = await _maybe_schedule_passive_commitment_nudge(
        request.message,
        chat_id=request.user_id or session_key,
        channel_id=request.channel_id or "cli",
    )

    raw_timeout = session_cfg.get("chat_timeout_seconds", 90.0)
    try:
        chat_timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        chat_timeout_seconds = 90.0

    chat_req = ChatRequest(
        message=request.message,
        history=history_for_llm,
        user_id=request.user_id,
        session_type=session_type,
        session_key=session_key,
    )

    try:
        result = await asyncio.wait_for(
            persona_chat(chat_req, target, background_tasks, mcp_context=mcp_context),
            timeout=chat_timeout_seconds,
        )
        if not isinstance(result, dict):
            result = {"reply": str(result or "")}
        action_receipts.extend(_receipts_from_value(result))
        if passive_nudge_reply:
            action_receipts.extend(_receipts_from_value(passive_nudge_reply))
        reply = _ensure_user_visible_reply(str(result.get("reply", "")))
        if passive_nudge_reply:
            reply = f"{reply.rstrip()}\n\n{passive_nudge_reply}"
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)
    except TimeoutError:
        logger.warning(
            "direct persona_chat timed out after %.2fs for %s",
            chat_timeout_seconds,
            session_key,
        )
        reply = (
            "I saved your message, but I timed out while generating a reply. "
            "Please try again."
        )
        result = {
            "reply": reply,
            "persona": f"synapse_{target}",
            "memory_method": "saved_before_timeout",
            "model": "timeout",
        }
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)
    except Exception:
        logger.exception("direct persona_chat failed for %s", session_key)
        reply = (
            "I saved your message, but hit an error while generating a reply. "
            "Please try again."
        )
        result = {
            "reply": reply,
            "persona": f"synapse_{target}",
            "memory_method": "saved_before_error",
            "model": "error",
        }
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)

    asst_dict = {
        "role": "assistant",
        "content": reply,
        "action_receipts": _serialize_receipts(action_receipts),
    }
    await append_message(t_path, asst_dict)
    deps.conversation_cache.append(session_key, asst_dict)
    await _maybe_schedule_periodic_memory_flush(
        session_key=session_key,
        agent_id=target,
        data_root=data_root,
        transcript_file=t_path,
        session_store=store,
        hemisphere=hemisphere,
    )

    result.setdefault("reply", reply)
    result["reply"] = reply
    result["action_receipts"] = _serialize_receipts(action_receipts)
    result.setdefault("persona", f"synapse_{target}")
    result.setdefault("memory_method", "direct_session")
    return result


async def process_message_pipeline(
    user_msg: str,
    chat_id: str,
    mcp_context: str = "",
    *,
    channel_id: str = "whatsapp",
    is_group: bool = False,
) -> str:
    """Process one inbound message through the full session-aware pipeline.

    Channel metadata defaults to the legacy WhatsApp direct path so older
    callers keep working, while Telegram/Slack/Discord get isolated sessions.
    """
    # Deferred imports to avoid circular dependencies at module load time.
    from sci_fi_dashboard.chat_pipeline import persona_chat
    from sci_fi_dashboard.multiuser.compaction import compact_session, estimate_tokens
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import (
        append_message,
        load_messages,
        transcript_path,
    )

    # ------------------------------------------------------------------
    # Step 1: Resolve target persona and load config
    # ------------------------------------------------------------------
    target = deps._resolve_target(chat_id)
    channel_id = (channel_id or "whatsapp").strip().lower() or "whatsapp"
    cfg = SynapseConfig.load()
    data_root = cfg.data_root  # ~/.synapse/ — NOT cfg.db_dir.parent (Research Pitfall 1)
    session_cfg = getattr(cfg, "session", {}) or {}
    dm_scope = session_cfg.get("dmScope", "per-channel-peer")
    identity_links = session_cfg.get("identityLinks", {})

    # ------------------------------------------------------------------
    # Step 2: Build session key (per D-04, D-05, D-06, D-07)
    # ------------------------------------------------------------------
    session_key = build_session_key(
        agent_id=target,
        channel=channel_id,
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id=channel_id,
        dm_scope=dm_scope,
        main_key=f"{channel_id}:dm",
        identity_links=identity_links,
    )
    logger.debug("session_key_built")

    # ------------------------------------------------------------------
    # Step 2b: Sub-agent spawn detection (Phase 3)
    # ------------------------------------------------------------------
    from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

    spawn_reply = await maybe_spawn_agent(
        user_msg=user_msg,
        chat_id=chat_id,
        channel_id=channel_id,
        session_key=session_key,
    )
    if spawn_reply is not None:
        return spawn_reply  # Short-circuit: agent spawned, return acknowledgment as str

    normalized_msg = user_msg.strip().lower()
    if normalized_msg in {"/tools", "tools"}:
        return _format_tools_command(channel_id, chat_id)

    # ------------------------------------------------------------------
    # Step 3: Get or create session entry (per D-18 corrected, D-19)
    # ------------------------------------------------------------------
    store = SessionStore(agent_id=target, data_root=data_root)
    entry = await store.get(session_key)
    if entry is None:
        entry = await store.update(session_key, {})

    t_path = transcript_path(entry, data_root, target)

    # ------------------------------------------------------------------
    # /new command: archive session + full memory loop + rotate session
    # ------------------------------------------------------------------
    if user_msg.strip().lower() == "/new":
        return await _handle_new_command(
            session_key=session_key,
            agent_id=target,
            data_root=data_root,
            session_store=store,
        )

    reminder_reply = await _maybe_handle_reminder_command(
        user_msg,
        chat_id=chat_id,
        channel_id=channel_id,
    )
    if reminder_reply is not None:
        user_dict = {"role": "user", "content": user_msg}
        asst_dict = {"role": "assistant", "content": reminder_reply}
        await append_message(t_path, user_dict)
        await append_message(t_path, asst_dict)
        deps.conversation_cache.append(session_key, user_dict)
        deps.conversation_cache.append(session_key, asst_dict)
        _sync_user_turn_memory(
            user_msg=user_msg,
            session_key=session_key,
            target=target,
            cfg=cfg,
        )
        await _maybe_schedule_periodic_memory_flush(
            session_key=session_key,
            agent_id=target,
            data_root=data_root,
            transcript_file=t_path,
            session_store=store,
            hemisphere="safe",
        )
        return reminder_reply

    # ------------------------------------------------------------------
    # Step 4: Load history with cache (per D-10, D-13, Research Pitfall 7)
    # ------------------------------------------------------------------
    channels_cfg = (
        cfg.channels if hasattr(cfg, "channels") and isinstance(cfg.channels, dict) else {}
    )
    history_limit = int(channels_cfg.get(channel_id, {}).get("dmHistoryLimit", 50))

    messages = deps.conversation_cache.get(session_key)
    if messages is None:
        messages = await load_messages(t_path, limit=history_limit)
        deps.conversation_cache.put(session_key, messages)  # put() BEFORE append() calls

    # ------------------------------------------------------------------
    # Step 5: Capture user turn first, then call persona_chat with timeout
    # ------------------------------------------------------------------
    history_for_llm = _prepare_history_for_llm(list(messages))
    action_receipts: list[ActionReceipt] = []
    user_dict = {"role": "user", "content": user_msg}
    await append_message(t_path, user_dict)
    action_receipts.append(
        ActionReceipt(
            action="message_capture",
            status="verified",
            evidence=f"User turn appended to transcript for {session_key}.",
            confidence=0.99,
        )
    )
    deps.conversation_cache.append(session_key, user_dict)
    fact_count = _sync_user_turn_memory(
        user_msg=user_msg,
        session_key=session_key,
        target=target,
        cfg=cfg,
    )
    if fact_count:
        action_receipts.append(
            ActionReceipt(
                action="memory_save",
                status="verified",
                evidence=f"{fact_count} user memory fact(s) persisted.",
                confidence=0.92,
            )
        )
    passive_nudge_reply = await _maybe_schedule_passive_commitment_nudge(
        user_msg,
        chat_id=chat_id,
        channel_id=channel_id,
    )

    raw_timeout = session_cfg.get("chat_timeout_seconds", 90.0)
    try:
        chat_timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        chat_timeout_seconds = 90.0

    chat_req = ChatRequest(
        message=user_msg,
        user_id=chat_id,
        channel_id=channel_id,
        session_type="safe",
        history=history_for_llm,
        session_key=session_key,
    )
    try:
        result = await asyncio.wait_for(
            persona_chat(chat_req, target, None, mcp_context=mcp_context),
            timeout=chat_timeout_seconds,
        )
        action_receipts.extend(_receipts_from_value(result))
        if passive_nudge_reply:
            action_receipts.extend(_receipts_from_value(passive_nudge_reply))
        reply = _ensure_user_visible_reply(result.get("reply", ""))
        if passive_nudge_reply:
            reply = f"{reply.rstrip()}\n\n{passive_nudge_reply}"
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)
    except TimeoutError:
        logger.warning("persona_chat timed out after %.2fs for %s", chat_timeout_seconds, session_key)
        reply = (
            "I saved your message, but I timed out while generating a reply. "
            "Please try again."
        )
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)
    except Exception:
        logger.exception("persona_chat failed for %s", session_key)
        reply = (
            "I saved your message, but hit an error while generating a reply. "
            "Please try again."
        )
        reply = guard_reply_against_unreceipted_claims(reply, action_receipts)

    # ------------------------------------------------------------------
    # Step 6: Fire-and-forget assistant append + compaction (per D-11, D-12, D-14-D-17)
    # ------------------------------------------------------------------
    asst_dict = {
        "role": "assistant",
        "content": reply,
        "action_receipts": _serialize_receipts(action_receipts),
    }
    deps.conversation_cache.append(session_key, asst_dict)

    async def _save_and_compact():
        try:
            await append_message(t_path, asst_dict)
            await _maybe_schedule_periodic_memory_flush(
                session_key=session_key,
                agent_id=target,
                data_root=data_root,
                transcript_file=t_path,
                session_store=store,
                hemisphere="safe",
            )

            # Compaction pre-gate (D-14: 60% threshold, D-17: 32k safe default)
            cached = deps.conversation_cache.get(session_key) or []
            ctx_window = 32_000
            if estimate_tokens(cached) > int(ctx_window * 0.6):
                await compact_session(
                    transcript_path=t_path,
                    context_window_tokens=ctx_window,
                    llm_client=_LLMClientAdapter(deps.synapse_llm_router),
                    agent_id=target,
                    session_key=session_key,
                    store_path=store._path,
                )
                deps.conversation_cache.invalidate(session_key)
        except Exception:
            logger.exception("Background save/compact failed for %s", session_key)

    task = asyncio.create_task(_save_and_compact())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # ------------------------------------------------------------------
    # Step 7: TTS voice note (fire-and-forget, mutually exclusive with auto-continue)
    # ------------------------------------------------------------------
    # Only trigger TTS when:
    # 1. The reply exists and is non-empty
    # 2. Auto-continue was NOT triggered for this reply (check: reply ends with terminal punct)
    # 3. TTS is enabled in config (default: True)
    # Note: Channel is implicitly WhatsApp — process_message_pipeline is WhatsApp-only.
    _tts_cfg = cfg.tts if hasattr(cfg, "tts") else {}
    _tts_enabled = _tts_cfg.get("enabled", True) if _tts_cfg else True
    _terminals = (".", "!", "?", '"', "'", ")", "]", "}")
    _reply_stripped = reply.strip()
    _ends_terminal = bool(_reply_stripped) and _reply_stripped[-1] in _terminals

    if channel_id == "whatsapp" and reply and _tts_enabled and _ends_terminal:
        tts_task = asyncio.create_task(_send_voice_note(reply, chat_id))
        _background_tasks.add(tts_task)
        tts_task.add_done_callback(_background_tasks.discard)

    return reply


async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
    from sci_fi_dashboard.gateway.queue import MessageTask

    is_group = metadata.get("is_group", False)
    channel_id = metadata.get("channel_id", "whatsapp")

    # WA-FIX-04: use canonical build_session_key so on_batch_ready and
    # process_message_pipeline agree on one session-key shape.
    cfg = SynapseConfig.load()
    session_cfg = getattr(cfg, "session", {}) or {}
    target = deps._resolve_target(chat_id)
    session_key = build_session_key(
        agent_id=target,
        channel=channel_id,
        peer_id=chat_id,
        peer_kind="group" if is_group else "direct",
        account_id=channel_id,
        dm_scope=session_cfg.get("dmScope", "per-channel-peer"),
        main_key=f"{channel_id}:dm",
        identity_links=session_cfg.get("identityLinks", {}),
    )
    task = MessageTask(
        task_id=str(uuid.uuid4()),
        chat_id=chat_id,
        user_message=combined_message,
        message_id=metadata.get("message_id", ""),
        sender_name=metadata.get("sender_name", ""),
        channel_id=channel_id,
        is_group=is_group,
        session_key=session_key,
        run_id=metadata.get("run_id"),
    )
    await deps.task_queue.enqueue(task)


# ---------------------------------------------------------------------------
# Background Worker
# ---------------------------------------------------------------------------


async def gentle_worker_loop():
    """Background maintenance loop."""
    print("[WORKER] Gentle Worker: running.")
    _kg_tick = 0
    _kg_last_time = time.time()
    while True:
        try:
            battery = psutil.sensors_battery()
            is_plugged = battery.power_plugged if battery else True
            cpu_load = psutil.cpu_percent(interval=None)

            if is_plugged and cpu_load < 20.0:
                deps.brain.prune_graph()
                deps.conflicts.prune_conflicts()

                # KG extraction every 2 cycles (~20 min) or 30-min fallback
                _kg_tick += 1
                if _kg_tick >= 2 or (time.time() - _kg_last_time) >= 1800:
                    _kg_tick = 0
                    _kg_last_time = time.time()
                    try:
                        cfg = SynapseConfig.load()
                        for pid, sbs in deps.sbs_registry.items():
                            await run_batch_extraction(
                                persona_id=pid,
                                sbs_data_dir=str(sbs.data_dir),
                                llm_router=deps.synapse_llm_router,
                                graph=deps.brain,
                                memory_db_path=str(cfg.db_dir / "memory.db"),
                                entities_json_path=str(Path(__file__).parent / "entities.json"),
                                min_messages=cfg.kg_extraction.min_messages,
                                kg_role=cfg.kg_extraction.kg_role,
                            )
                    except Exception as e:
                        logger.warning("[WARN] KG extraction failed: %s", e)

                await asyncio.sleep(600)
            else:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except (KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception as e:
            print(f"[WARN] Worker: {e}")
            await asyncio.sleep(60)


# Wire flood callback -- must happen after on_batch_ready is defined.
# Some lightweight unit tests stub _deps without the gateway flood gate; production
# _deps always has it.
if getattr(deps, "flood", None) is not None:
    deps.flood.set_callback(on_batch_ready)
