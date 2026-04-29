from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_longitudinal_personality_eval_three_users_diverge(tmp_path) -> None:
    from scripts.eval_longitudinal_personality import run_eval

    result = run_eval(tmp_path)

    assert result["user_count"] == 3
    assert result["all_prompts_distinct"] is True
    assert result["same_prompt"] == "I am stuck. What should I do next?"
    assert result["users"]["user_a"]["markers"]["direct"] is True
    assert result["users"]["user_b"]["markers"]["supportive"] is True
    assert result["users"]["user_c"]["markers"]["strategic"] is True
    assert result["users"]["user_a"]["proactive_hint"] != result["users"]["user_b"]["proactive_hint"]
