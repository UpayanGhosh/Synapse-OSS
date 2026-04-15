"""
Cron Scheduler — type definitions.

All dataclasses and StrEnums used across the cron module live here to avoid
circular imports and keep the public API surface clean.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScheduleKind(StrEnum):
    AT = "at"  # one-shot: ISO datetime
    EVERY = "every"  # recurring: interval in ms + optional anchor
    CRON = "cron"  # recurring: cron expression + timezone


class PayloadKind(StrEnum):
    SYSTEM_EVENT = "systemEvent"
    AGENT_TURN = "agentTurn"


class SessionTarget(StrEnum):
    MAIN = "main"
    ISOLATED = "isolated"
    CURRENT = "current"


class DeliveryMode(StrEnum):
    NONE = "none"
    ANNOUNCE = "announce"
    WEBHOOK = "webhook"


class WakeMode(StrEnum):
    NOW = "now"
    NEXT_HEARTBEAT = "next-heartbeat"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CronSchedule:
    kind: ScheduleKind
    at: str | None = None  # ISO-8601 datetime (ScheduleKind.AT)
    every_ms: int | None = None  # interval milliseconds (ScheduleKind.EVERY)
    anchor_ms: int | None = None  # epoch ms anchor for EVERY
    expr: str | None = None  # cron expression (ScheduleKind.CRON)
    tz: str = "UTC"
    stagger_ms: int = 0


@dataclass
class CronDelivery:
    mode: DeliveryMode = DeliveryMode.NONE
    channel: str | None = None
    to: str | None = None  # channel target or webhook URL
    account_id: str | None = None
    best_effort: bool = True
    failure_destination: str | None = None


@dataclass
class CronFailureAlert:
    after: int = 3  # consecutive errors before alerting
    channel: str | None = None
    to: str | None = None
    cooldown_ms: int = 300_000  # 5 minutes
    mode: DeliveryMode = DeliveryMode.NONE
    account_id: str | None = None


@dataclass
class CronPayload:
    kind: PayloadKind = PayloadKind.SYSTEM_EVENT
    message: str | None = None
    model_override: str | None = None
    fallbacks: list[str] | None = None
    thinking: bool = False
    timeout_seconds: int = 300
    tools_allow: list[str] | None = None
    deliver: CronDelivery | None = None
    light_context: bool = False


@dataclass
class CronJobState:
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_run_status: str = "pending"
    last_error: str | None = None
    last_duration_ms: int | None = None
    consecutive_errors: int = 0
    last_failure_alert_at_ms: int = 0
    schedule_error_count: int = 0
    last_delivery_status: str | None = None


@dataclass
class CronJob:
    id: str
    name: str
    schedule: CronSchedule
    payload: CronPayload
    delivery: CronDelivery = field(default_factory=CronDelivery)
    failure_alert: CronFailureAlert | None = None
    session_target: SessionTarget = SessionTarget.MAIN
    wake_mode: WakeMode = WakeMode.NOW
    enabled: bool = True
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0

    def __post_init__(self):
        if self.created_at_ms == 0:
            self.created_at_ms = int(time.time() * 1000)
