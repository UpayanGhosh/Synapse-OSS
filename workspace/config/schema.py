"""
config/schema.py — Pydantic v2 validated configuration schema for Synapse-OSS.

All models use strict validation where appropriate but allow extra fields
so that unknown keys in synapse.json are preserved (future-proofing).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


class SecretInput(BaseModel):
    """Reference to a secret value — either inline or via external ref."""

    type: Literal["secret-ref"] | None = None
    ref: str | None = None
    value: str | None = None


class ThinkingLevel(BaseModel):
    """Controls thinking/reasoning budget for a model call."""

    mode: Literal["auto", "none", "low", "medium", "high"] = "auto"
    budget_tokens: int | None = None


class AuthProfileConfig(BaseModel):
    """Authentication profile for a provider."""

    id: str
    type: Literal["api_key", "oauth", "token"] = "api_key"
    provider: str | None = None
    credentials: dict[str, Any] = Field(default_factory=dict)


class ModelFallbackEntry(BaseModel):
    """A single fallback model specification."""

    provider: str
    model: str


class AgentModelConfig(BaseModel):
    """Per-role model configuration with optional fallback chain."""

    model: str
    fallback: str | None = None
    fallbacks: list[ModelFallbackEntry] = Field(default_factory=list)
    thinking: ThinkingLevel | None = None


class ProviderConfig(BaseModel, extra="allow"):
    """Provider configuration — extra keys preserved for provider-specific settings."""

    api_key: str | SecretInput | None = None
    api_base: str | None = None
    enabled: bool = True


class ChannelConfig(BaseModel, extra="allow"):
    """Channel configuration — extra keys preserved for channel-specific settings."""

    enabled: bool = True
    token: str | None = None
    dm_history_limit: int = 50
    proxy_url: str | None = None


class SessionConfig(BaseModel):
    """Session management configuration."""

    dm_scope: str = Field(default="main", alias="dmScope")
    identity_links: dict[str, list[str]] = Field(default_factory=dict, alias="identityLinks")
    context_window: int = 200000

    model_config = {"populate_by_name": True}


class GatewayConfig(BaseModel):
    """WebSocket gateway configuration."""

    port: int = 8765
    host: str = "127.0.0.1"
    token: str | None = None


class GroupPolicyRule(BaseModel):
    """A single group policy rule matching channel + group pattern."""

    channel_id: str
    group_pattern: str
    action: Literal["allow", "deny"] = "allow"


class GroupPolicyConfig(BaseModel):
    """Group-level access policy with glob-based rules."""

    default: Literal["allow", "deny"] = "allow"
    rules: list[GroupPolicyRule] = Field(default_factory=list)


class CronRetentionConfig(BaseModel):
    """Retention policy for cron/scheduled job history."""

    days: int = 30
    max_runs: int = 1000


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------


class ReconnectPolicySchema(BaseModel, extra="forbid"):
    """Schema for the `reconnect` key in synapse.json (SUPV-02)."""

    initialMs: int | None = Field(default=None, ge=100, le=60_000)
    maxMs: int | None = Field(default=None, ge=1_000, le=600_000)
    factor: float | None = Field(default=None, ge=1.0, le=10.0)
    jitter: float | None = Field(default=None, ge=0.0, le=1.0)
    maxAttempts: int | None = Field(default=None, ge=1, le=100)


class SynapseConfigSchema(BaseModel, extra="allow"):
    """Root configuration schema for synapse.json.

    Extra keys are preserved so that unknown top-level sections don't
    cause validation failures — forward-compatible by design.
    """

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    model_mappings: dict[str, AgentModelConfig] = Field(default_factory=dict)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    mcp: dict[str, Any] = Field(default_factory=dict)
    group_policy: GroupPolicyConfig = Field(default_factory=GroupPolicyConfig)
    cron_retention: CronRetentionConfig = Field(default_factory=CronRetentionConfig)
    auth_profiles: list[AuthProfileConfig] = Field(default_factory=list)
    reconnect: ReconnectPolicySchema | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize_model_mappings(cls, data: Any) -> Any:
        """Normalize bare string model_mappings values to AgentModelConfig dicts.

        Allows shorthand like ``{"casual": "gemini/gemini-2.0-flash"}`` which
        gets expanded to ``{"casual": {"model": "gemini/gemini-2.0-flash"}}``.
        """
        if not isinstance(data, dict):
            return data

        mappings = data.get("model_mappings")
        if not isinstance(mappings, dict):
            return data

        normalized: dict[str, Any] = {}
        for role, value in mappings.items():
            if isinstance(value, str):
                normalized[role] = {"model": value}
            else:
                normalized[role] = value
        data = {**data, "model_mappings": normalized}
        return data
