"""Deterministic proactive reach-out policy.

This layer separates "can Synapse send?" from "what should it say?". It scores
context using stable local signals and keeps proactive behavior explainable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

_MEMORY_URGENCY_TERMS = (
    "urgent",
    "blocked",
    "deadline",
    "due",
    "meeting",
    "demo",
    "interview",
    "remind",
    "reminder",
    "check-in",
    "check in",
    "follow up",
    "tomorrow",
    "today",
    "anxious",
    "anxiety",
    "worried",
    "stressed",
    "stress",
    "scared",
    "fear",
    "panic",
)


@dataclass(frozen=True)
class ProactivePolicyInput:
    user_id: str
    channel_id: str
    now_hour: int | None = None
    now_ts: float | None = None
    last_message_time: float | None = None
    seconds_since_last_message: float | None = None
    calendar_events: list[dict] = field(default_factory=list)
    unread_emails: list[dict] = field(default_factory=list)
    slack_mentions: list[dict] = field(default_factory=list)
    recent_memory_summaries: list[str] = field(default_factory=list)
    emotional_need: float = 0.0
    confidence: float = 1.0

    def resolved_seconds_since_last_message(self) -> float | None:
        if self.seconds_since_last_message is not None:
            return float(self.seconds_since_last_message)
        if self.last_message_time is None:
            return None
        now = float(self.now_ts if self.now_ts is not None else time.time())
        return max(0.0, now - float(self.last_message_time))


@dataclass(frozen=True)
class ProactiveDecision:
    should_reach_out: bool
    score: float
    reason: str
    components: dict[str, float]
    evidence: list[str]


class ProactivePolicyScorer:
    def __init__(
        self,
        *,
        threshold: float = 0.62,
        quiet_start_hour: int = 23,
        quiet_end_hour: int = 8,
        silence_gap_seconds: float = 8 * 3600,
        urgent_recent_gap_seconds: float = 45 * 60,
    ) -> None:
        self.threshold = float(threshold)
        self.quiet_start_hour = int(quiet_start_hour)
        self.quiet_end_hour = int(quiet_end_hour)
        self.silence_gap_seconds = float(silence_gap_seconds)
        self.urgent_recent_gap_seconds = float(urgent_recent_gap_seconds)

    def score(self, policy_input: ProactivePolicyInput) -> ProactiveDecision:
        hour = policy_input.now_hour
        if hour is not None and self._in_quiet_hours(hour):
            return ProactiveDecision(
                should_reach_out=False,
                score=0.0,
                reason="quiet_hours",
                components={},
                evidence=[],
            )

        gap = policy_input.resolved_seconds_since_last_message()
        urgency, urgency_evidence = self._urgency(policy_input)
        urgent_recent_allowed = self._allows_urgent_recent_contact(
            gap,
            urgency,
            policy_input.emotional_need,
            policy_input.recent_memory_summaries,
        )
        if gap is not None and gap < self.silence_gap_seconds and not urgent_recent_allowed:
            return ProactiveDecision(
                should_reach_out=False,
                score=0.0,
                reason="recent_contact",
                components={"urgency": urgency},
                evidence=urgency_evidence,
            )

        recent_contact = 1.0 if gap is None else min(1.0, gap / self.silence_gap_seconds)
        if urgent_recent_allowed:
            recent_contact = max(recent_contact, 0.45)
        relevance = min(1.0, 0.35 * len(policy_input.recent_memory_summaries))
        if policy_input.calendar_events and policy_input.recent_memory_summaries:
            relevance = min(1.0, relevance + 0.25)
        emotional_need = _clamp(policy_input.emotional_need)
        confidence = _clamp(policy_input.confidence)
        availability = 1.0

        components = {
            "urgency": urgency,
            "relevance": relevance,
            "availability": availability,
            "emotional_need": emotional_need,
            "recent_contact": recent_contact,
            "confidence": confidence,
        }
        weighted = (
            urgency * 0.34
            + relevance * 0.18
            + availability * 0.12
            + emotional_need * 0.16
            + recent_contact * 0.14
            + confidence * 0.06
        )
        final_score = round(_clamp(weighted), 3)
        should_reach_out = final_score >= self.threshold
        return ProactiveDecision(
            should_reach_out=should_reach_out,
            score=final_score,
            reason="policy_score" if should_reach_out else "low_score",
            components=components,
            evidence=urgency_evidence + _memory_evidence(policy_input),
        )

    def _in_quiet_hours(self, hour: int) -> bool:
        normalized_hour = int(hour) % 24
        start = self.quiet_start_hour % 24
        end = self.quiet_end_hour % 24
        if start == end:
            return False
        if start > end:
            return normalized_hour >= start or normalized_hour < end
        return start <= normalized_hour < end

    def _urgency(self, policy_input: ProactivePolicyInput) -> tuple[float, list[str]]:
        score = 0.0
        evidence: list[str] = []
        if policy_input.calendar_events:
            score += 0.45
            evidence.append("calendar")
        if len(policy_input.unread_emails) > 3:
            score += 0.32
            evidence.append("email_backlog")
        if policy_input.slack_mentions:
            score += 0.24
            evidence.append("mentions")
        joined = " ".join(
            str(item.get("subject") or item.get("text") or "")
            for item in [*policy_input.unread_emails, *policy_input.slack_mentions]
        ).lower()
        if any(term in joined for term in ("urgent", "blocked", "prod", "deadline")):
            score += 0.22
            evidence.append("urgent_terms")

        memory_text = " ".join(policy_input.recent_memory_summaries).lower()
        if memory_text and any(term in memory_text for term in _MEMORY_URGENCY_TERMS):
            score += 0.55
            evidence.append("memory_urgency")
        elif memory_text and policy_input.emotional_need >= 0.75:
            score += 0.28
            evidence.append("memory_emotional_need")
        return _clamp(score), evidence

    def _allows_urgent_recent_contact(
        self,
        gap: float | None,
        urgency: float,
        emotional_need: float,
        recent_memory_summaries: list[str],
    ) -> bool:
        if gap is None or gap >= self.silence_gap_seconds:
            return True
        if gap < self.urgent_recent_gap_seconds:
            return False
        has_memory = bool(recent_memory_summaries)
        return has_memory and urgency >= 0.5 and _clamp(emotional_need) >= 0.75


def _memory_evidence(policy_input: ProactivePolicyInput) -> list[str]:
    if not policy_input.recent_memory_summaries:
        return []
    return ["memory"]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
