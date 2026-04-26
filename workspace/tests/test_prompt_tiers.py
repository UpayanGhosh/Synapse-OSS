from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.prompt_tiers import (  # noqa: E402
    filter_tier_sections,
    get_prompt_tier_policy,
    prompt_tier_for_role,
)


@pytest.mark.unit
def test_filter_tier_sections_keeps_all_and_active_only():
    markdown = """
before
<tier:all>
identity
</tier:all>
<tier:frontier>
long incident log
</tier:frontier>
<tier:mid_open,small>
compact rule
</tier:mid_open>
after
"""

    small = filter_tier_sections(markdown, "small")
    frontier = filter_tier_sections(markdown, "frontier")

    assert "identity" in small
    assert "compact rule" in small
    assert "long incident log" not in small
    assert "long incident log" in frontier
    assert "compact rule" not in frontier


@pytest.mark.unit
def test_prompt_tier_for_role_prefers_explicit_config():
    mappings = {
        "casual": {
            "model": "gemini/gemini-2.0-flash",
            "prompt_tier": "small",
        }
    }

    assert prompt_tier_for_role(mappings, "casual") == "small"


@pytest.mark.unit
def test_prompt_tier_for_role_infers_local_ollama_from_num_ctx():
    mappings = {
        "vault": {
            "model": "ollama_chat/llama3.2:3b",
            "ollama_options": {"num_ctx": 8192},
        },
        "local_mid": {
            "model": "ollama_chat/qwen2.5:7b",
            "ollama_options": {"num_ctx": 12288},
        },
    }

    assert prompt_tier_for_role(mappings, "vault") == "small"
    assert prompt_tier_for_role(mappings, "local_mid") == "mid_open"


@pytest.mark.unit
def test_mid_open_policy_uses_native_tool_schemas():
    policy = get_prompt_tier_policy("mid_open")

    assert policy.native_tool_schemas is True
    assert policy.include_mcp_context is True


@pytest.mark.unit
def test_small_policy_is_minimal_and_skips_expensive_blocks():
    policy = get_prompt_tier_policy("small")

    assert policy.memory_limit == 1
    assert policy.memory_min_score == 0.85
    assert policy.include_graph_context is False
    assert policy.include_mcp_context is False
    assert policy.history_turns == 2
    assert policy.cognitive_detail == "strategy"
    assert policy.native_tool_schemas is False
