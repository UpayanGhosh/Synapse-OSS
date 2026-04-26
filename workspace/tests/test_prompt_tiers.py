from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.prompt_tiers import (  # noqa: E402
    ConfigError,
    filter_tier_sections,
    get_prompt_tier_policy,
    infer_tier_from_any_model,
    prompt_tier_for_role,
    validate_role_tier,
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


# ---------------------------------------------------------------------------
# Phase 5: MODEL_TIER_MAP + infer_tier_from_any_model + validate_role_tier
# ---------------------------------------------------------------------------

# Canonical model strings drawn from synapse.json.example model_mappings
_EXAMPLE_MODELS = [
    ("gemini/gemini-2.0-flash", "mid_open"),
    ("anthropic/claude-sonnet-4-6", "frontier"),
    ("openai/gpt-4o", "frontier"),
    ("anthropic/claude-opus-4-6", "frontier"),
    ("ollama_chat/qwen2.5:7b", "mid_open"),
    ("openrouter/meta-llama/llama-3.3-70b-instruct", "frontier"),
    ("gemini/gemini-2.5-flash-lite", "small"),
    ("gemini/gemini-2.5-flash", "mid_open"),
    ("google_antigravity/gemini-3-flash-lite-preview", "small"),
    ("google_antigravity/gemini-3-flash", "mid_open"),
    ("groq/llama-3.3-70b-versatile", "frontier"),
    ("gemini/gemini-2.0-pro", "frontier"),
]


@pytest.mark.unit
def test_model_tier_map_covers_canonical_models():
    """Every model string from synapse.json.example resolves to a non-None tier."""
    for model, expected_tier in _EXAMPLE_MODELS:
        result = infer_tier_from_any_model(model)
        assert result is not None, f"infer_tier_from_any_model({model!r}) returned None"
        assert (
            result == expected_tier
        ), f"infer_tier_from_any_model({model!r}) = {result!r}, expected {expected_tier!r}"


@pytest.mark.unit
def test_validate_role_tier_warns_on_downgrade(caplog):
    """frontier config on a small local model emits a WARNING."""
    cfg = {"model": "ollama_chat/gemma:4b", "prompt_tier": "frontier"}
    with caplog.at_level(logging.WARNING, logger="sci_fi_dashboard.prompt_tiers"):
        validate_role_tier("test_role", cfg, strict=False)
    assert any(
        "mismatch" in r.message.lower() for r in caplog.records if r.levelno == logging.WARNING
    ), "Expected a WARNING about tier mismatch but none was found"


@pytest.mark.unit
def test_validate_role_tier_silent_on_match(caplog):
    """No WARNING when configured tier matches inferred tier."""
    cfg = {"model": "google_antigravity/gemini-3-flash", "prompt_tier": "mid_open"}
    with caplog.at_level(logging.WARNING, logger="sci_fi_dashboard.prompt_tiers"):
        validate_role_tier("casual", cfg, strict=False)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not warnings, f"Unexpected WARNING(s): {[r.message for r in warnings]}"


@pytest.mark.unit
def test_validate_role_tier_info_on_upgrade(caplog):
    """frontier model with small configured tier → INFO, not WARNING."""
    cfg = {"model": "anthropic/claude-sonnet-4-6", "prompt_tier": "small"}
    with caplog.at_level(logging.DEBUG, logger="sci_fi_dashboard.prompt_tiers"):
        validate_role_tier("code", cfg, strict=False)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert not warnings, f"Unexpected WARNING(s): {[r.message for r in warnings]}"
    assert infos, "Expected an INFO log for upgrade (deliberate cost shedding) but none found"


@pytest.mark.unit
def test_validate_role_tier_strict_mode_raises():
    """frontier configured on a 3B model with strict=True → ConfigError."""
    cfg = {"model": "ollama_chat/phi-3-mini:3b", "prompt_tier": "frontier"}
    with pytest.raises(ConfigError, match="strict"):
        validate_role_tier("cheap_role", cfg, strict=True)


@pytest.mark.unit
def test_unknown_model_does_not_warn(caplog):
    """Completely unknown model string resolves to None and emits no WARNING."""
    cfg = {"model": "openai/some-future-model-xyz-2099", "prompt_tier": "frontier"}
    with caplog.at_level(logging.WARNING, logger="sci_fi_dashboard.prompt_tiers"):
        validate_role_tier("future_role", cfg, strict=False)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not warnings, f"Unexpected WARNING(s) for unknown model: {[r.message for r in warnings]}"


@pytest.mark.unit
def test_infer_tier_regex_ordering_flash_lite_before_flash():
    """flash-lite must not be absorbed by the broader flash pattern."""
    assert infer_tier_from_any_model("gemini/gemini-2.5-flash-lite") == "small"
    assert infer_tier_from_any_model("gemini/gemini-2.5-flash") == "mid_open"
    assert infer_tier_from_any_model("google_antigravity/gemini-3-flash-lite-preview") == "small"
    assert infer_tier_from_any_model("google_antigravity/gemini-3-flash") == "mid_open"


@pytest.mark.unit
def test_infer_tier_gpt_mini_is_mid_open_not_small():
    """gpt-5-mini has frontier-class context — must map to mid_open, not small."""
    assert infer_tier_from_any_model("openai/gpt-4o-mini") == "mid_open"
    assert infer_tier_from_any_model("openai/gpt-5-mini") == "mid_open"


@pytest.mark.unit
def test_infer_tier_o_series_is_frontier():
    """o1/o3/o4 reasoning models are frontier regardless of suffix."""
    assert infer_tier_from_any_model("openai/o1") == "frontier"
    assert infer_tier_from_any_model("openai/o3") == "frontier"
    assert infer_tier_from_any_model("openai/o4-mini") == "frontier"


@pytest.mark.unit
def test_validate_role_tier_strict_off_by_one_only_warns(caplog):
    """frontier→mid_open downgrade with strict=True warns but does NOT raise."""
    # gemini-3-flash is mid_open; configured as frontier → off-by-one downgrade
    cfg = {"model": "google_antigravity/gemini-3-flash", "prompt_tier": "frontier"}
    with caplog.at_level(logging.WARNING, logger="sci_fi_dashboard.prompt_tiers"):
        # Should not raise even in strict mode (gap == 1, not >= 2)
        validate_role_tier("casual", cfg, strict=True)
    assert any(
        r.levelno == logging.WARNING for r in caplog.records
    ), "Expected a WARNING for off-by-one downgrade"


@pytest.mark.unit
@pytest.mark.parametrize(
    "model,expected_tier",
    [
        # Bug 1 — generic size catch-alls misclassifying 22B/33B/35B as small
        # The (?<!\d) lookbehind on the small pattern, plus explicit mid_open
        # enumeration for 22/27/33/35B, prevent first-digit-greedy mismatches.
        ("ollama_chat/codestral:22b", "mid_open"),  # was: small (matched '2b')
        ("ollama_chat/yi:34b", "mid_open"),  # already correct via explicit list
        ("ollama_chat/qwen:33b", "mid_open"),  # was: small via qwen.*[1-4]b '3b' hit
        ("ollama_chat/mistral:7b", "mid_open"),  # family rule fires before size catch-all
        # Bug 2 — versioned cloud IDs returning None due to strict $ anchors
        ("gemini/gemini-2.0-flash-001", "mid_open"),  # -001 version suffix
        ("gemini/gemini-2.5-pro-002", "frontier"),  # -002 version suffix
        ("openai/gpt-4o-2024-11-20", "frontier"),  # date-versioned GPT-4o
        ("openai/o1-2024-12-17", "frontier"),  # date-versioned o1
        ("openai/o3-mini-2025-01-31", "frontier"),  # date-versioned o3-mini
        ("gemini/gemini-2.0-flash-thinking-exp", "mid_open"),  # compound suffix
        # ── Lookbehind regression: multi-digit sizes must not hit small rules ──
        # llama: 33B must NOT match llama.*(?<!\d)[1-9]b (would match '3b')
        ("ollama_chat/llama:33b", "mid_open"),
        ("ollama_chat/llama:22b", "mid_open"),
        # gemma: 22B must NOT match gemma.*(?<!\d)[1-4][b.] (would match '2b')
        ("ollama_chat/gemma:22b", "mid_open"),
        # deepseek: 33B must NOT match deepseek.*(?<!\d)[1-9]b (would match '3b')
        ("ollama_chat/deepseek:33b", "mid_open"),
        ("ollama_chat/deepseek-coder:33b", "mid_open"),
    ],
)
def test_infer_tier_versioned_and_size_real_world_ids(model, expected_tier):
    """Regression: versioned cloud IDs and multi-digit local sizes resolve correctly."""
    result = infer_tier_from_any_model(model)
    assert (
        result == expected_tier
    ), f"infer_tier_from_any_model({model!r}) returned {result!r}, expected {expected_tier!r}"


@pytest.mark.unit
def test_smoke_google_antigravity_gemini3_flash_no_false_positive(caplog):
    """google_antigravity/gemini-3-flash with mid_open config → zero warnings.

    This is the canonical config from the user's synapse.json — must be clean.
    """
    cfg = {"model": "google_antigravity/gemini-3-flash", "prompt_tier": "mid_open"}
    with caplog.at_level(logging.WARNING, logger="sci_fi_dashboard.prompt_tiers"):
        validate_role_tier("casual", cfg, strict=False)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not warnings, f"False-positive warning on sane config: {[r.message for r in warnings]}"
