"""
Tests for sci_fi_dashboard.mcp_config — MCP configuration Pydantic models.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.mcp_config import (
    BuiltinServerConfig,
    CustomServerConfig,
    MCPConfig,
    ProactiveConfig,
    ProactiveSourceConfig,
    load_mcp_config,
)

# ---------------------------------------------------------------------------
# ProactiveSourceConfig
# ---------------------------------------------------------------------------


class TestProactiveSourceConfig:
    def test_defaults(self):
        cfg = ProactiveSourceConfig()
        assert cfg.proactive is True
        assert cfg.lookahead_minutes == 30
        assert cfg.max_unread == 5
        assert cfg.mentions_only is True

    def test_custom_values(self):
        cfg = ProactiveSourceConfig(
            proactive=False, lookahead_minutes=60, max_unread=10, mentions_only=False
        )
        assert cfg.proactive is False
        assert cfg.lookahead_minutes == 60


# ---------------------------------------------------------------------------
# ProactiveConfig
# ---------------------------------------------------------------------------


class TestProactiveConfig:
    def test_defaults(self):
        cfg = ProactiveConfig()
        assert cfg.enabled is True
        assert cfg.poll_interval_seconds == 60
        assert cfg.sources == {}

    def test_poll_interval_min_bound(self):
        with pytest.raises(Exception):  # noqa: B017
            ProactiveConfig(poll_interval_seconds=5)  # below 10

    def test_poll_interval_max_bound(self):
        with pytest.raises(Exception):  # noqa: B017
            ProactiveConfig(poll_interval_seconds=7200)  # above 3600


# ---------------------------------------------------------------------------
# BuiltinServerConfig
# ---------------------------------------------------------------------------


class TestBuiltinServerConfig:
    def test_defaults(self):
        cfg = BuiltinServerConfig()
        assert cfg.enabled is True
        assert cfg.credentials_path == ""
        assert cfg.token_path == ""
        assert cfg.bot_token == ""
        assert cfg.user_token == ""

    def test_custom_values(self):
        cfg = BuiltinServerConfig(enabled=False, token_path="~/.tokens/gmail.json")
        assert cfg.enabled is False
        assert cfg.token_path == "~/.tokens/gmail.json"


# ---------------------------------------------------------------------------
# CustomServerConfig
# ---------------------------------------------------------------------------


class TestCustomServerConfig:
    def test_valid_config(self):
        cfg = CustomServerConfig(command="python", args=["-m", "server"])
        assert cfg.command == "python"
        assert cfg.args == ["-m", "server"]
        assert cfg.env == {}

    def test_empty_command_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            CustomServerConfig(command="")

    def test_whitespace_command_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            CustomServerConfig(command="   ")

    def test_with_env(self):
        cfg = CustomServerConfig(command="node", args=["server.js"], env={"PORT": "3000"})
        assert cfg.env["PORT"] == "3000"


# ---------------------------------------------------------------------------
# MCPConfig
# ---------------------------------------------------------------------------


class TestMCPConfig:
    def test_defaults(self):
        cfg = MCPConfig()
        assert cfg.enabled is True
        assert cfg.builtin_servers == {}
        assert cfg.custom_servers == {}

    def test_is_server_enabled_builtin(self):
        cfg = MCPConfig(
            builtin_servers={
                "gmail": BuiltinServerConfig(enabled=True),
                "slack": BuiltinServerConfig(enabled=False),
            }
        )
        assert cfg.is_server_enabled("gmail") is True
        assert cfg.is_server_enabled("slack") is False

    def test_is_server_enabled_custom(self):
        cfg = MCPConfig(
            custom_servers={
                "custom1": CustomServerConfig(command="python"),
            }
        )
        assert cfg.is_server_enabled("custom1") is True
        assert cfg.is_server_enabled("nonexistent") is False


# ---------------------------------------------------------------------------
# load_mcp_config
# ---------------------------------------------------------------------------


class TestLoadMcpConfig:
    def test_none_returns_disabled(self):
        cfg = load_mcp_config(None)
        assert cfg.enabled is False

    def test_empty_dict_returns_disabled(self):
        cfg = load_mcp_config({})
        assert cfg.enabled is False

    def test_valid_config_parsed(self):
        raw = {
            "enabled": True,
            "proactive": {
                "enabled": True,
                "poll_interval_seconds": 120,
                "sources": {
                    "calendar": {
                        "proactive": True,
                        "lookahead_minutes": 45,
                    }
                },
            },
            "builtin_servers": {
                "gmail": {"enabled": True, "token_path": "~/.tokens/gmail.json"},
            },
            "custom_servers": {
                "my_server": {"command": "python", "args": ["-m", "my_srv"]},
            },
        }
        cfg = load_mcp_config(raw)
        assert cfg.enabled is True
        assert cfg.proactive.poll_interval_seconds == 120
        assert "calendar" in cfg.proactive.sources
        assert cfg.proactive.sources["calendar"].lookahead_minutes == 45
        assert "gmail" in cfg.builtin_servers
        assert "my_server" in cfg.custom_servers

    def test_invalid_poll_interval_raises(self):
        with pytest.raises(Exception):  # noqa: B017
            load_mcp_config({"proactive": {"poll_interval_seconds": 1}})
