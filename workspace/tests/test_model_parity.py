from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.model_parity.scoring_engine import (  # noqa: E402
    ModelResponse,
    score_response,
)
from sci_fi_dashboard.model_parity.test_runner import (  # noqa: E402
    FixtureParityClient,
    Scenario,
    load_model_candidates,
    load_scenarios,
    run_parity,
)


def test_bundled_scenarios_load():
    scenarios = load_scenarios()

    assert {s.id for s in scenarios} >= {"s_math", "s_tool_bash_count", "s_persona_casual"}
    assert "s_identity" not in {s.id for s in scenarios}
    assert all(s.prompt for s in scenarios)
    assert all("method" in s.scoring for s in scenarios)
    serialized = " ".join(f"{s.prompt} {s.scoring}" for s in scenarios).casefold()
    assert not any(token in serialized for token in ("upayan", "shreya", "boumuni"))


def test_identity_specific_example_loads():
    path = (
        Path(__file__).parents[1]
        / "sci_fi_dashboard"
        / "model_parity"
        / "scenarios.identity_specific.yaml.example"
    )
    scenarios = load_scenarios(path)

    assert {s.id for s in scenarios} >= {"s_identity", "s_rag_momos", "s_kg_partner"}


def test_regex_scoring_checks_required_any_and_forbidden():
    scenario = Scenario(
        id="s_identity",
        category="identity",
        prompt="Who is your master?",
        scoring={
            "method": "regex",
            "must_contain": ["upayan"],
            "must_contain_any": ["bhai", "master"],
            "forbidden": ["I am an AI assistant"],
        },
    )

    result = score_response(
        scenario,
        ModelResponse(text="Upayan bhai is my master.", model="fixture/frontier"),
    )

    assert result.passed is True
    assert result.score == 1.0


def test_tool_assertion_uses_tools_used_and_reply_text():
    scenario = Scenario(
        id="s_tool",
        category="tool",
        prompt="run calc",
        scoring={
            "method": "tool_assertion",
            "must_call_tool": "bash_exec",
            "must_contain_in_output": ["1764"],
        },
    )

    result = score_response(
        scenario,
        ModelResponse(
            text="The command returned 1764.",
            model="fixture/local",
            tools_used=["bash_exec"],
        ),
    )

    assert result.passed is True


def test_hybrid_scoring_combines_hard_and_similarity():
    scenario = Scenario(
        id="s_kg",
        category="kg",
        prompt="partner?",
        scoring={
            "method": "hybrid",
            "must_contain": ["boumuni"],
            "embedding_gold": "Shreya is loyal protective and values certainty",
            "threshold_per_tier": {"mid_open": 0.1},
        },
    )

    result = score_response(
        scenario,
        ModelResponse(
            text="Boumuni Shreya is loyal and protective.",
            model="fixture/qwen",
        ),
        tier="mid_open",
    )

    assert result.passed is True
    assert result.similarity is not None


@dataclass
class _Config:
    model_mappings: dict


def test_load_model_candidates_reads_roles_and_tiers():
    cfg = _Config(
        model_mappings={
            "casual": {"model": "anthropic/claude-sonnet-4-6", "capability_tier": "frontier"},
            "local": {"model": "ollama_chat/qwen2.5:7b", "prompt_tier": "mid_open"},
            "tiny": {"model": "ollama_chat/phi3.5:3b"},
        }
    )

    candidates = load_model_candidates(cfg)

    assert [c.role for c in candidates] == ["casual", "local", "tiny"]
    assert candidates[0].tier == "frontier"
    assert candidates[1].tier == "mid_open"
    assert candidates[2].tier == "small"


@pytest.mark.asyncio
async def test_run_parity_writes_artifacts(tmp_path: Path):
    scenarios = [
        Scenario(
            id="s_math",
            category="closed_form",
            prompt="What is 7 times 8?",
            scoring={"method": "regex", "must_contain": ["56"]},
        )
    ]
    candidates = load_model_candidates(
        _Config(
            model_mappings={"fixture": {"model": "fixture/frontier", "capability_tier": "frontier"}}
        )
    )
    client = FixtureParityClient({("fixture", "s_math"): "7 times 8 is 56."})

    result = await run_parity(
        scenarios=scenarios,
        candidates=candidates,
        client=client,
        output_dir=tmp_path,
    )

    assert result.passed is True
    assert (tmp_path / "parity_matrix.csv").exists()
    assert (tmp_path / "per_model_failures.md").exists()
    assert (tmp_path / "trend.json").exists()
    assert (tmp_path / "raw_results.json").exists()
