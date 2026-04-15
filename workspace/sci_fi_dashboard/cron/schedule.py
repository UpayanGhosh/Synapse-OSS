"""
Cron Scheduler — schedule parsing and next-run computation.

Handles all three schedule kinds (at / every / cron) and applies
deterministic stagger offsets for top-of-hour jobs.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from croniter import croniter

from .types import CronSchedule, ScheduleKind

logger = logging.getLogger(__name__)


@lru_cache(maxsize=512)
def _parse_cron_expr(expr: str) -> bool:
    """Validate a cron expression. Cached to avoid repeated parsing.

    Returns True if valid, raises ValueError if not.
    """
    if not croniter.is_valid(expr):
        raise ValueError(f"Invalid cron expression: {expr!r}")
    return True


def compute_next_run_at_ms(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute the next run time in epoch milliseconds.

    Returns:
        Epoch ms of the next run, or None if the schedule is exhausted
        (e.g. a one-shot "at" in the past).
    """
    kind = ScheduleKind(schedule.kind)

    if kind == ScheduleKind.AT:
        return _next_run_at(schedule, now_ms)
    elif kind == ScheduleKind.EVERY:
        return _next_run_every(schedule, now_ms)
    elif kind == ScheduleKind.CRON:
        return _next_run_cron(schedule, now_ms)
    else:
        raise ValueError(f"Unknown schedule kind: {kind}")


def _next_run_at(schedule: CronSchedule, now_ms: int) -> int | None:
    """One-shot: return the ISO datetime as epoch ms if in the future."""
    if not schedule.at:
        return None
    try:
        dt = datetime.fromisoformat(schedule.at)
        # If naive, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        target_ms = int(dt.timestamp() * 1000)
        return target_ms if target_ms > now_ms else None
    except (ValueError, OSError) as exc:
        logger.warning("Failed to parse 'at' datetime %r: %s", schedule.at, exc)
        return None


def _next_run_every(schedule: CronSchedule, now_ms: int) -> int | None:
    """Recurring interval: anchor + ceil((now - anchor) / every) * every."""
    every_ms = schedule.every_ms
    if not every_ms or every_ms <= 0:
        return None

    anchor = schedule.anchor_ms if schedule.anchor_ms is not None else 0
    if now_ms <= anchor:
        return anchor + schedule.stagger_ms

    elapsed = now_ms - anchor
    periods = math.ceil(elapsed / every_ms)
    next_ms = anchor + periods * every_ms
    return next_ms + schedule.stagger_ms


def _next_run_cron(schedule: CronSchedule, now_ms: int) -> int | None:
    """Cron expression: croniter.get_next() with timezone + stagger."""
    if not schedule.expr:
        return None

    # Validate (cached)
    _parse_cron_expr(schedule.expr)

    try:
        tz = ZoneInfo(schedule.tz) if schedule.tz else UTC
    except KeyError:
        logger.warning("Unknown timezone %r, falling back to UTC", schedule.tz)
        tz = UTC

    now_dt = datetime.fromtimestamp(now_ms / 1000, tz=tz)
    cron = croniter(schedule.expr, now_dt)
    next_dt: datetime = cron.get_next(datetime)
    next_ms = int(next_dt.timestamp() * 1000)
    return next_ms + schedule.stagger_ms
