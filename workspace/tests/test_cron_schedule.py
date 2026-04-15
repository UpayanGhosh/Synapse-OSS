"""
Tests for sci_fi_dashboard.cron.schedule — cron parser and next-run computation.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sci_fi_dashboard.cron.schedule import (
    _parse_cron_expr,
    compute_next_run_at_ms,
)
from sci_fi_dashboard.cron.types import CronSchedule, ScheduleKind

# ---------------------------------------------------------------------------
# ScheduleKind.AT
# ---------------------------------------------------------------------------


class TestAtSchedule:
    def test_future_iso_returns_ms(self):
        """A future ISO datetime should return its epoch ms."""
        future_dt = datetime(2099, 6, 15, 12, 0, 0, tzinfo=UTC)
        schedule = CronSchedule(kind=ScheduleKind.AT, at=future_dt.isoformat())
        now_ms = int(time.time() * 1000)

        result = compute_next_run_at_ms(schedule, now_ms)

        assert result is not None
        expected_ms = int(future_dt.timestamp() * 1000)
        assert result == expected_ms

    def test_past_iso_returns_none(self):
        """A past ISO datetime should return None (schedule exhausted)."""
        past_dt = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        schedule = CronSchedule(kind=ScheduleKind.AT, at=past_dt.isoformat())
        now_ms = int(time.time() * 1000)

        result = compute_next_run_at_ms(schedule, now_ms)
        assert result is None

    def test_naive_iso_treated_as_utc(self):
        """A naive (no timezone) ISO string should be treated as UTC."""
        future_dt = datetime(2099, 1, 1, 0, 0, 0)
        schedule = CronSchedule(kind=ScheduleKind.AT, at=future_dt.isoformat())
        now_ms = int(time.time() * 1000)

        result = compute_next_run_at_ms(schedule, now_ms)
        assert result is not None
        # Should be treated as UTC
        expected_ms = int(future_dt.replace(tzinfo=UTC).timestamp() * 1000)
        assert result == expected_ms

    def test_missing_at_returns_none(self):
        schedule = CronSchedule(kind=ScheduleKind.AT, at=None)
        result = compute_next_run_at_ms(schedule, int(time.time() * 1000))
        assert result is None


# ---------------------------------------------------------------------------
# ScheduleKind.EVERY
# ---------------------------------------------------------------------------


class TestEverySchedule:
    def test_correct_interval_from_anchor(self):
        """The next run should be the first multiple of every_ms after now."""
        anchor_ms = 1_000_000_000_000  # some epoch
        every_ms = 60_000  # 60 seconds
        now_ms = anchor_ms + 150_000  # 2.5 intervals past anchor

        schedule = CronSchedule(
            kind=ScheduleKind.EVERY,
            every_ms=every_ms,
            anchor_ms=anchor_ms,
        )
        result = compute_next_run_at_ms(schedule, now_ms)

        # ceil(150000 / 60000) = 3 → anchor + 3 * 60000 = anchor + 180000
        assert result == anchor_ms + 180_000

    def test_now_before_anchor(self):
        """If now < anchor, the next run is the anchor itself."""
        anchor_ms = int(time.time() * 1000) + 100_000
        schedule = CronSchedule(
            kind=ScheduleKind.EVERY,
            every_ms=60_000,
            anchor_ms=anchor_ms,
        )
        now_ms = anchor_ms - 50_000
        result = compute_next_run_at_ms(schedule, now_ms)
        assert result == anchor_ms  # stagger_ms defaults to 0

    def test_zero_anchor_defaults(self):
        """If anchor_ms is None, it defaults to 0."""
        every_ms = 10_000
        now_ms = 25_000
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=every_ms)

        result = compute_next_run_at_ms(schedule, now_ms)
        # ceil(25000 / 10000) = 3 → 0 + 3 * 10000 = 30000
        assert result == 30_000

    def test_invalid_every_ms_returns_none(self):
        schedule = CronSchedule(kind=ScheduleKind.EVERY, every_ms=0)
        assert compute_next_run_at_ms(schedule, 1000) is None

        schedule2 = CronSchedule(kind=ScheduleKind.EVERY, every_ms=None)
        assert compute_next_run_at_ms(schedule2, 1000) is None


# ---------------------------------------------------------------------------
# ScheduleKind.CRON
# ---------------------------------------------------------------------------


class TestCronSchedule:
    def test_every_5_minutes(self):
        """``*/5 * * * *`` should give the next 5-minute mark."""
        # Fix now to a known time: 2099-01-01 00:02:00 UTC
        fixed_dt = datetime(2099, 1, 1, 0, 2, 0, tzinfo=UTC)
        now_ms = int(fixed_dt.timestamp() * 1000)

        schedule = CronSchedule(kind=ScheduleKind.CRON, expr="*/5 * * * *")
        result = compute_next_run_at_ms(schedule, now_ms)

        # Next 5-min mark after 00:02 is 00:05
        expected_dt = datetime(2099, 1, 1, 0, 5, 0, tzinfo=UTC)
        expected_ms = int(expected_dt.timestamp() * 1000)
        assert result == expected_ms

    def test_stagger_adds_offset(self):
        """Stagger should be added on top of the cron-computed time."""
        fixed_dt = datetime(2099, 1, 1, 0, 2, 0, tzinfo=UTC)
        now_ms = int(fixed_dt.timestamp() * 1000)
        stagger = 5_000  # 5 seconds

        schedule = CronSchedule(kind=ScheduleKind.CRON, expr="*/5 * * * *", stagger_ms=stagger)
        result = compute_next_run_at_ms(schedule, now_ms)

        expected_dt = datetime(2099, 1, 1, 0, 5, 0, tzinfo=UTC)
        expected_ms = int(expected_dt.timestamp() * 1000) + stagger
        assert result == expected_ms

    def test_invalid_cron_raises(self):
        """An invalid cron expression should raise ValueError."""
        schedule = CronSchedule(kind=ScheduleKind.CRON, expr="not-a-cron")
        with pytest.raises(ValueError, match="Invalid cron expression"):
            compute_next_run_at_ms(schedule, int(time.time() * 1000))

    def test_missing_expr_returns_none(self):
        schedule = CronSchedule(kind=ScheduleKind.CRON, expr=None)
        result = compute_next_run_at_ms(schedule, int(time.time() * 1000))
        assert result is None


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------


class TestCronExprCache:
    def test_cache_hit_for_repeated_expressions(self):
        """Repeated calls with the same expression should hit the cache."""
        _parse_cron_expr.cache_clear()  # start fresh

        _parse_cron_expr("0 * * * *")
        _parse_cron_expr("0 * * * *")
        _parse_cron_expr("0 * * * *")

        info = _parse_cron_expr.cache_info()
        assert info.hits >= 2
        assert info.misses == 1

    def test_cache_miss_for_different_expressions(self):
        _parse_cron_expr.cache_clear()

        _parse_cron_expr("0 * * * *")
        _parse_cron_expr("*/5 * * * *")

        info = _parse_cron_expr.cache_info()
        assert info.misses == 2


# ---------------------------------------------------------------------------
# Stagger (via schedule module integration)
# ---------------------------------------------------------------------------


class TestStaggerIntegration:
    def test_every_with_stagger(self):
        """Stagger should be added to EVERY schedule results."""
        anchor_ms = 0
        every_ms = 60_000
        stagger = 3_000
        now_ms = 25_000

        schedule = CronSchedule(
            kind=ScheduleKind.EVERY,
            every_ms=every_ms,
            anchor_ms=anchor_ms,
            stagger_ms=stagger,
        )
        result = compute_next_run_at_ms(schedule, now_ms)
        # ceil(25000/60000) = 1 → 0 + 1 * 60000 + 3000 = 63000
        assert result == 63_000
