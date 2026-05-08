"""MCP configuration models — Pydantic validation for synapse.json mcp section."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from sci_fi_dashboard.calendar_core.models import CalendarPreferences


class ProactiveSourceConfig(BaseModel):
    proactive: bool = True
    lookahead_minutes: int = 30
    max_unread: int = 5
    mentions_only: bool = True


class ProactiveConfig(BaseModel):
    enabled: bool = True
    poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    sources: dict[str, ProactiveSourceConfig] = Field(default_factory=dict)


class BuiltinServerConfig(BaseModel):
    enabled: bool = True
    credentials_path: str = ""
    token_path: str = ""
    bot_token: str = ""
    user_token: str = ""


class CalendarPreferencesConfig(BaseModel):
    default_calendar_id: str = "primary"
    timezone: str = "Asia/Calcutta"
    locale_country: str = "IN"
    trusted_quick_add: bool = True
    default_event_duration_minutes: int = Field(default=60, ge=1)
    allow_open_ended_recurring_personal_events: bool = True

    @field_validator("default_calendar_id", "timezone", "locale_country")
    @classmethod
    def required_text_not_empty(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(f"{info.field_name} must be a non-empty string")
        return v

    def to_calendar_preferences(self) -> CalendarPreferences:
        return CalendarPreferences(
            default_calendar_id=self.default_calendar_id,
            timezone=self.timezone,
            locale_country=self.locale_country,
            trusted_quick_add=self.trusted_quick_add,
            default_event_duration_minutes=self.default_event_duration_minutes,
            allow_open_ended_recurring_personal_events=(
                self.allow_open_ended_recurring_personal_events
            ),
        )


class CustomServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("command must be a non-empty string")
        return v


class MCPConfig(BaseModel):
    enabled: bool = True
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    calendar_preferences: CalendarPreferencesConfig = Field(
        default_factory=CalendarPreferencesConfig
    )
    builtin_servers: dict[str, BuiltinServerConfig] = Field(default_factory=dict)
    custom_servers: dict[str, CustomServerConfig] = Field(default_factory=dict)

    def is_server_enabled(self, name: str) -> bool:
        if name in self.builtin_servers:
            return self.builtin_servers[name].enabled
        return name in self.custom_servers


def load_mcp_config(raw_mcp: dict | None) -> MCPConfig:
    """Parse the 'mcp' section of synapse.json into validated MCPConfig."""
    if not raw_mcp:
        return MCPConfig(enabled=False)
    return MCPConfig(**raw_mcp)
