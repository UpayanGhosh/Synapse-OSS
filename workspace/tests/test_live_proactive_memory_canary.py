from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_live_canary_fresh_db_restart_survives_memory_personality_loop(tmp_path) -> None:
    from scripts.eval_proactive_memory_canary import run_canary

    result = run_canary(tmp_path)

    assert result["stored"]["documents"] >= 20
    assert result["stored"]["memory_affect"] >= 20
    assert result["stored"]["user_memory_facts"] >= 6
    assert result["retrieval"]["has_codename"] is True
    assert result["retrieval"]["has_project"] is True
    assert result["prompt_after_restart"]["has_style"] is True
    assert result["prompt_after_restart"]["has_routine"] is True
    assert result["proactive"]["should_reach_out"] is True
    assert result["proactive"]["has_memory_evidence"] is True


def test_live_canary_proactive_policy_respects_recent_contact(tmp_path) -> None:
    from scripts.eval_proactive_memory_canary import run_canary

    result = run_canary(tmp_path, seconds_since_last_message=600)

    assert result["proactive"]["should_reach_out"] is False
    assert result["proactive"]["reason"] == "recent_contact"
