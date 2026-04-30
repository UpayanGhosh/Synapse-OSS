from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_policy_blocks_sleep_window_even_for_urgent_context() -> None:
    from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer

    decision = ProactivePolicyScorer().score(
        ProactivePolicyInput(
            user_id="the_creator",
            channel_id="whatsapp",
            now_hour=2,
            calendar_events=[{"summary": "standup", "start": "10:00"}],
            unread_emails=[{} for _ in range(8)],
            seconds_since_last_message=12 * 3600,
        )
    )

    assert decision.should_reach_out is False
    assert decision.reason == "quiet_hours"
    assert decision.score == 0.0


def test_policy_reaches_out_for_urgent_relevant_context_after_silence_gap() -> None:
    from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer

    decision = ProactivePolicyScorer().score(
        ProactivePolicyInput(
            user_id="the_creator",
            channel_id="whatsapp",
            now_hour=14,
            calendar_events=[{"summary": "Investor call", "start": "15:00"}],
            unread_emails=[{"subject": "urgent deployment"} for _ in range(5)],
            slack_mentions=[{"text": "prod is blocked"}],
            recent_memory_summaries=["User is focused on Synapse-OSS launch."],
            seconds_since_last_message=10 * 3600,
            emotional_need=0.7,
        )
    )

    assert decision.should_reach_out is True
    assert decision.reason == "policy_score"
    assert decision.score >= 0.62
    assert decision.components["urgency"] > 0
    assert decision.components["recent_contact"] == 1.0
    assert "calendar" in decision.evidence


def test_policy_reaches_out_for_memory_emotional_need_after_silence_gap() -> None:
    from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer

    decision = ProactivePolicyScorer().score(
        ProactivePolicyInput(
            user_id="the_creator",
            channel_id="telegram",
            now_hour=14,
            recent_memory_summaries=[
                "User is anxious about tomorrow's Kestrel demo deadline and asked for a check-in."
            ],
            seconds_since_last_message=9 * 3600,
            emotional_need=0.85,
        )
    )

    assert decision.should_reach_out is True
    assert decision.reason == "policy_score"
    assert decision.score >= 0.62
    assert decision.components["urgency"] >= 0.35
    assert "memory_urgency" in decision.evidence


def test_policy_blocks_recent_contact_without_high_urgency() -> None:
    from sci_fi_dashboard.proactive_policy import ProactivePolicyInput, ProactivePolicyScorer

    decision = ProactivePolicyScorer().score(
        ProactivePolicyInput(
            user_id="the_creator",
            channel_id="whatsapp",
            now_hour=16,
            unread_emails=[{"subject": "FYI"}],
            seconds_since_last_message=30 * 60,
        )
    )

    assert decision.should_reach_out is False
    assert decision.reason == "recent_contact"


def test_policy_input_can_compute_gap_from_last_message_timestamp() -> None:
    from sci_fi_dashboard.proactive_policy import ProactivePolicyInput

    now = time.time()
    policy_input = ProactivePolicyInput(
        user_id="the_creator",
        channel_id="whatsapp",
        now_ts=now,
        last_message_time=now - 900,
    )

    assert 899 <= policy_input.resolved_seconds_since_last_message() <= 901
