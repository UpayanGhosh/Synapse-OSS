"""
test_config_schema.py — Unit tests for config/schema.py (Pydantic v2 models).

Covers:
  - Valid config round-trips through SynapseConfigSchema
  - Invalid types rejected
  - Bare string model_mappings normalized to AgentModelConfig
  - Extra keys preserved
  - Empty config produces valid defaults
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.schema import (
    AgentModelConfig,
    AuthProfileConfig,
    ChannelConfig,
    CronRetentionConfig,
    GatewayConfig,
    GroupPolicyConfig,
    GroupPolicyRule,
    ModelFallbackEntry,
    ProviderConfig,
    SecretInput,
    SessionConfig,
    SynapseConfigSchema,
    ThinkingLevel,
)


# ---------------------------------------------------------------------------
# Empty config → valid defaults
# ---------------------------------------------------------------------------


class TestEmptyConfig:
    def test_empty_dict_produces_valid_defaults(self):
        """An empty dict should produce a valid SynapseConfigSchema with all defaults."""
        schema = SynapseConfigSchema()
        assert schema.providers == {}
        assert schema.channels == {}
        assert schema.model_mappings == {}
        assert schema.gateway.port == 8765
        assert schema.gateway.host == "127.0.0.1"
        assert schema.session.dm_scope == "main"
        assert schema.session.context_window == 200000
        assert schema.group_policy.default == "allow"
        assert schema.group_policy.rules == []
        assert schema.cron_retention.days == 30
        assert schema.cron_retention.max_runs == 1000
        assert schema.auth_profiles == []
        assert schema.mcp == {}

    def test_empty_dict_input(self):
        """Passing ``{}`` explicitly should work identically to no args."""
        schema = SynapseConfigSchema(**{})
        assert schema.providers == {}
        assert schema.gateway.port == 8765


# ---------------------------------------------------------------------------
# Valid config round-trip
# ---------------------------------------------------------------------------


class TestValidRoundTrip:
    def test_full_config_round_trips(self):
        """A fully specified config should round-trip through model_dump."""
        raw = {
            "providers": {
                "gemini": {"api_key": "test-key-123", "api_base": "https://api.google.com"},
                "openrouter": {"api_key": "or-key", "enabled": False},
            },
            "channels": {
                "whatsapp": {"enabled": True, "token": "wa-token", "dm_history_limit": 100},
                "telegram": {"enabled": False},
            },
            "model_mappings": {
                "casual": {"model": "gemini/gemini-2.0-flash-exp"},
                "code": {
                    "model": "anthropic/claude-3-5-sonnet",
                    "fallback": "gemini/gemini-pro",
                    "thinking": {"mode": "high", "budget_tokens": 5000},
                },
            },
            "gateway": {"port": 9000, "host": "0.0.0.0", "token": "gw-secret"},
            "session": {"dmScope": "per-peer", "identityLinks": {"alice": ["wa:123", "tg:456"]}},
            "mcp": {"tools_server": {"port": 8989}},
            "group_policy": {
                "default": "deny",
                "rules": [
                    {"channel_id": "whatsapp", "group_pattern": "family-*", "action": "allow"},
                ],
            },
            "cron_retention": {"days": 7, "max_runs": 500},
            "auth_profiles": [
                {"id": "main", "type": "api_key", "provider": "gemini", "credentials": {}},
            ],
        }

        schema = SynapseConfigSchema(**raw)
        dumped = schema.model_dump(by_alias=True)

        # Spot-check key fields survived the round-trip
        assert dumped["providers"]["gemini"]["api_key"] == "test-key-123"
        assert dumped["channels"]["whatsapp"]["dm_history_limit"] == 100
        assert dumped["model_mappings"]["code"]["model"] == "anthropic/claude-3-5-sonnet"
        assert dumped["gateway"]["port"] == 9000
        assert dumped["session"]["dmScope"] == "per-peer"
        assert dumped["group_policy"]["default"] == "deny"
        assert dumped["cron_retention"]["days"] == 7

    def test_model_dump_and_reconstruct(self):
        """model_dump → SynapseConfigSchema(**dump) should produce equal schemas."""
        raw = {
            "providers": {"ollama": {"api_base": "http://localhost:11434"}},
            "model_mappings": {"casual": {"model": "ollama_chat/mistral"}},
        }
        schema1 = SynapseConfigSchema(**raw)
        dump = schema1.model_dump(by_alias=True)
        schema2 = SynapseConfigSchema(**dump)
        assert schema1.model_dump() == schema2.model_dump()


# ---------------------------------------------------------------------------
# Bare string model_mappings → AgentModelConfig normalization
# ---------------------------------------------------------------------------


class TestBareModelNormalization:
    def test_bare_string_normalized(self):
        """A bare string in model_mappings should be normalized to AgentModelConfig."""
        raw = {"model_mappings": {"casual": "gemini/gemini-2.0-flash-exp"}}
        schema = SynapseConfigSchema(**raw)
        cfg = schema.model_mappings["casual"]
        assert isinstance(cfg, AgentModelConfig)
        assert cfg.model == "gemini/gemini-2.0-flash-exp"
        assert cfg.fallback is None
        assert cfg.fallbacks == []
        assert cfg.thinking is None

    def test_mixed_bare_and_full(self):
        """Mix of bare strings and full dicts should both work."""
        raw = {
            "model_mappings": {
                "casual": "gemini/flash",
                "code": {"model": "anthropic/sonnet", "fallback": "gemini/pro"},
            }
        }
        schema = SynapseConfigSchema(**raw)
        assert schema.model_mappings["casual"].model == "gemini/flash"
        assert schema.model_mappings["code"].model == "anthropic/sonnet"
        assert schema.model_mappings["code"].fallback == "gemini/pro"


# ---------------------------------------------------------------------------
# Invalid types rejected
# ---------------------------------------------------------------------------


class TestInvalidTypes:
    def test_invalid_gateway_port_type(self):
        """Gateway port must be an int — passing a non-numeric string should fail."""
        with pytest.raises(Exception):
            SynapseConfigSchema(**{"gateway": {"port": "not-a-number"}})

    def test_invalid_thinking_mode(self):
        """ThinkingLevel mode must be one of the allowed literals."""
        with pytest.raises(Exception):
            ThinkingLevel(mode="ultra")  # type: ignore[arg-type]

    def test_invalid_group_policy_action(self):
        """GroupPolicyRule action must be 'allow' or 'deny'."""
        with pytest.raises(Exception):
            GroupPolicyRule(channel_id="wa", group_pattern="*", action="maybe")  # type: ignore[arg-type]

    def test_invalid_auth_profile_type(self):
        """AuthProfileConfig type must be one of the allowed literals."""
        with pytest.raises(Exception):
            AuthProfileConfig(id="x", type="biometric")  # type: ignore[arg-type]

    def test_invalid_provider_config_nested(self):
        """Provider with non-bool enabled should be rejected."""
        with pytest.raises(Exception):
            SynapseConfigSchema(**{"providers": {"bad": {"enabled": "yes-please"}}})


# ---------------------------------------------------------------------------
# Extra keys preserved
# ---------------------------------------------------------------------------


class TestExtraKeys:
    def test_root_extra_keys_preserved(self):
        """Unknown top-level keys in synapse.json should be preserved."""
        raw = {"custom_feature": {"enabled": True}, "experiment_flag": 42}
        schema = SynapseConfigSchema(**raw)
        # Pydantic v2 extra="allow" stores extras — access via model fields
        dumped = schema.model_dump()
        assert dumped.get("custom_feature") == {"enabled": True}
        assert dumped.get("experiment_flag") == 42

    def test_provider_extra_keys_preserved(self):
        """Provider-specific keys not in the schema should be preserved."""
        raw = {
            "providers": {
                "gemini": {
                    "api_key": "key",
                    "custom_timeout": 30,
                    "retry_count": 3,
                }
            }
        }
        schema = SynapseConfigSchema(**raw)
        gemini = schema.providers["gemini"]
        dumped = gemini.model_dump()
        assert dumped["custom_timeout"] == 30
        assert dumped["retry_count"] == 3

    def test_channel_extra_keys_preserved(self):
        """Channel-specific keys not in the schema should be preserved."""
        raw = {
            "channels": {
                "whatsapp": {
                    "enabled": True,
                    "bridge_port": 5010,
                    "max_retries": 5,
                }
            }
        }
        schema = SynapseConfigSchema(**raw)
        wa = schema.channels["whatsapp"]
        dumped = wa.model_dump()
        assert dumped["bridge_port"] == 5010
        assert dumped["max_retries"] == 5


# ---------------------------------------------------------------------------
# Individual model tests
# ---------------------------------------------------------------------------


class TestIndividualModels:
    def test_secret_input_defaults(self):
        s = SecretInput()
        assert s.type is None
        assert s.ref is None
        assert s.value is None

    def test_secret_input_with_ref(self):
        s = SecretInput(type="secret-ref", ref="providers.gemini.api_key")
        assert s.type == "secret-ref"
        assert s.ref == "providers.gemini.api_key"

    def test_thinking_level_defaults(self):
        t = ThinkingLevel()
        assert t.mode == "auto"
        assert t.budget_tokens is None

    def test_model_fallback_entry(self):
        f = ModelFallbackEntry(provider="gemini", model="gemini-pro")
        assert f.provider == "gemini"
        assert f.model == "gemini-pro"

    def test_agent_model_config_with_fallbacks(self):
        cfg = AgentModelConfig(
            model="gemini/flash",
            fallbacks=[
                ModelFallbackEntry(provider="anthropic", model="sonnet"),
                ModelFallbackEntry(provider="openrouter", model="mixtral"),
            ],
            thinking=ThinkingLevel(mode="high", budget_tokens=3000),
        )
        assert len(cfg.fallbacks) == 2
        assert cfg.thinking.mode == "high"
        assert cfg.thinking.budget_tokens == 3000

    def test_session_config_alias(self):
        """SessionConfig should accept both alias (dmScope) and field name (dm_scope)."""
        s1 = SessionConfig(dmScope="per-peer")
        assert s1.dm_scope == "per-peer"

        s2 = SessionConfig(dm_scope="per-channel-peer")
        assert s2.dm_scope == "per-channel-peer"

    def test_cron_retention_defaults(self):
        c = CronRetentionConfig()
        assert c.days == 30
        assert c.max_runs == 1000

    def test_group_policy_config_defaults(self):
        g = GroupPolicyConfig()
        assert g.default == "allow"
        assert g.rules == []
