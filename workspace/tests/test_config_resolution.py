"""
test_config_resolution.py — Unit tests for config/layered_resolution.py

Covers:
  - 5-layer priority chain tested
  - Runtime override via merge_patch
  - Session override file read/write
  - Missing layer skipped gracefully
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.layered_resolution import ConfigResolver
from config.schema import AgentModelConfig, SynapseConfigSchema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_schema():
    """A SynapseConfigSchema with two model mappings."""
    return SynapseConfigSchema(
        **{
            "model_mappings": {
                "casual": {"model": "gemini/flash"},
                "code": {
                    "model": "anthropic/sonnet",
                    "fallback": "gemini/pro",
                    "thinking": {"mode": "high", "budget_tokens": 5000},
                },
            },
        }
    )


@pytest.fixture
def resolver(base_schema, tmp_path):
    """A ConfigResolver with a temp data_root."""
    return ConfigResolver(base_config=base_schema, data_root=tmp_path)


# ---------------------------------------------------------------------------
# Layer 5: Gateway defaults (lowest priority)
# ---------------------------------------------------------------------------


class TestGatewayDefaults:
    def test_unknown_agent_falls_back_to_gateway_defaults(self, resolver):
        """When agent_id is unknown, gateway defaults should be used."""
        result = resolver.resolve_model_for_session("sess-1", agent_id="unknown_role")
        assert result.model == "gemini/gemini-2.0-flash-exp"
        assert result.fallback is None

    def test_no_agent_id_uses_gateway_defaults(self, resolver):
        """When no agent_id is given, gateway defaults apply."""
        result = resolver.resolve_model_for_session("sess-1")
        assert result.model == "gemini/gemini-2.0-flash-exp"


# ---------------------------------------------------------------------------
# Layer 4: Agent-level config
# ---------------------------------------------------------------------------


class TestAgentLayer:
    def test_agent_config_overrides_defaults(self, resolver):
        """Agent-level config should override gateway defaults."""
        result = resolver.resolve_model_for_session("sess-1", agent_id="casual")
        assert result.model == "gemini/flash"

    def test_agent_config_with_thinking(self, resolver):
        """Agent config with thinking settings should preserve them."""
        result = resolver.resolve_model_for_session("sess-1", agent_id="code")
        assert result.model == "anthropic/sonnet"
        assert result.fallback == "gemini/pro"
        assert result.thinking is not None
        assert result.thinking.mode == "high"
        assert result.thinking.budget_tokens == 5000


# ---------------------------------------------------------------------------
# Layer 3: Session overrides
# ---------------------------------------------------------------------------


class TestSessionLayer:
    def test_session_override_wins_over_agent(self, resolver, tmp_path):
        """Session-level override should override agent config."""
        # Write a session override
        resolver.write_session_override("sess-1", {"model": "ollama_chat/llama3"})

        result = resolver.resolve_model_for_session("sess-1", agent_id="casual")
        assert result.model == "ollama_chat/llama3"

    def test_session_override_file_created(self, resolver, tmp_path):
        """write_session_override should create the session config file."""
        resolver.write_session_override("sess-2", {"model": "test/model"})

        config_file = tmp_path / "sessions" / "sess-2" / "config.json"
        assert config_file.exists()

        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["model"] == "test/model"

    def test_session_override_merges_on_write(self, resolver, tmp_path):
        """Successive writes to session override should merge, not replace."""
        resolver.write_session_override("sess-3", {"model": "model-a"})
        resolver.write_session_override("sess-3", {"fallback": "model-b"})

        config_file = tmp_path / "sessions" / "sess-3" / "config.json"
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["model"] == "model-a"
        assert data["fallback"] == "model-b"

    def test_missing_session_file_skipped(self, resolver):
        """If no session config file exists, layer is skipped gracefully."""
        result = resolver.resolve_model_for_session("nonexistent-session", agent_id="casual")
        assert result.model == "gemini/flash"  # falls through to agent layer


# ---------------------------------------------------------------------------
# Layer 2: Runtime overrides
# ---------------------------------------------------------------------------


class TestRuntimeLayer:
    def test_runtime_override_wins_over_session(self, resolver, tmp_path):
        """Runtime override should override session config."""
        resolver.write_session_override("sess-1", {"model": "session/model"})
        resolver.apply_runtime_override({"model": "runtime/model"})

        result = resolver.resolve_model_for_session("sess-1", agent_id="casual")
        assert result.model == "runtime/model"

    def test_runtime_override_accumulates(self, resolver):
        """Multiple runtime overrides should merge."""
        resolver.apply_runtime_override({"model": "model-1"})
        resolver.apply_runtime_override({"fallback": "fallback-1"})

        result = resolver.resolve_model_for_session("sess-1")
        assert result.model == "model-1"
        assert result.fallback == "fallback-1"


# ---------------------------------------------------------------------------
# Layer 1: CLI overrides (highest priority)
# ---------------------------------------------------------------------------


class TestCLILayer:
    def test_cli_override_wins_over_everything(self, resolver, tmp_path):
        """CLI overrides should have the highest priority."""
        resolver.write_session_override("sess-1", {"model": "session/model"})
        resolver.apply_runtime_override({"model": "runtime/model"})

        result = resolver.resolve_model_for_session(
            "sess-1",
            agent_id="code",
            cli_overrides={"model": "cli/model"},
        )
        assert result.model == "cli/model"

    def test_cli_override_partial(self, resolver):
        """CLI override of one field should leave others intact."""
        result = resolver.resolve_model_for_session(
            "sess-1",
            agent_id="code",
            cli_overrides={"fallback": "cli/fallback"},
        )
        assert result.model == "anthropic/sonnet"  # from agent layer
        assert result.fallback == "cli/fallback"  # from CLI


# ---------------------------------------------------------------------------
# Full 5-layer priority chain
# ---------------------------------------------------------------------------


class TestFullPriorityChain:
    def test_all_five_layers(self, resolver, tmp_path):
        """When all 5 layers have values, priority should be:
        CLI > runtime > session > agent > gateway defaults."""
        # Set up all layers
        resolver.write_session_override("sess-1", {"model": "session/model"})
        resolver.apply_runtime_override({"fallback": "runtime/fallback"})

        result = resolver.resolve_model_for_session(
            "sess-1",
            agent_id="code",
            cli_overrides={"model": "cli/model"},
        )

        # CLI wins for model
        assert result.model == "cli/model"
        # Runtime wins for fallback (over agent's "gemini/pro")
        assert result.fallback == "runtime/fallback"
        # Agent's thinking config survives (no higher layer sets it)
        assert result.thinking is not None
        assert result.thinking.mode == "high"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_corrupt_session_file_skipped(self, resolver, tmp_path):
        """A corrupt session config file should be skipped gracefully."""
        session_dir = tmp_path / "sessions" / "corrupt-sess"
        session_dir.mkdir(parents=True)
        (session_dir / "config.json").write_text("not valid json", encoding="utf-8")

        result = resolver.resolve_model_for_session("corrupt-sess", agent_id="casual")
        assert result.model == "gemini/flash"  # falls through to agent layer

    def test_none_cli_overrides(self, resolver):
        """Passing None for cli_overrides should be equivalent to no override."""
        result = resolver.resolve_model_for_session(
            "sess-1", agent_id="casual", cli_overrides=None
        )
        assert result.model == "gemini/flash"

    def test_empty_cli_overrides(self, resolver):
        """Passing {} for cli_overrides should be equivalent to no override."""
        result = resolver.resolve_model_for_session(
            "sess-1", agent_id="casual", cli_overrides={}
        )
        assert result.model == "gemini/flash"

    def test_result_is_agent_model_config(self, resolver):
        """resolve_model_for_session should always return an AgentModelConfig."""
        result = resolver.resolve_model_for_session("sess-1")
        assert isinstance(result, AgentModelConfig)
