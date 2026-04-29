from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.eval_personality_differentiation import run_eval


def test_personality_differentiation_eval_markers(tmp_path) -> None:
    result = run_eval(tmp_path)

    assert result["user_a_contains"] == "concise technical replies"
    assert result["user_b_contains"] == "warm emotionally supportive replies"
    assert result["prompts_are_different"] is True
