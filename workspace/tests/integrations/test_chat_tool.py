"""Unit tests for the connect_integration chat-tool factory."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import sci_fi_dashboard.integrations as integrations_pkg
from sci_fi_dashboard.integrations.manager import ConnectionResult
from sci_fi_dashboard.tool_registry import (
    SynapseTool,
    ToolContext,
    _connect_integration_factory,
)


def _ctx(*, owner: bool) -> ToolContext:
    return ToolContext(
        chat_id="c1",
        sender_id="s1",
        sender_is_owner=owner,
        workspace_dir="/tmp/ws",
        config={},
        channel_id="test",
    )


def test_factory_returns_none_for_non_owner():
    assert _connect_integration_factory(_ctx(owner=False)) is None


def test_factory_returns_synapse_tool_for_owner():
    tool = _connect_integration_factory(_ctx(owner=True))
    assert isinstance(tool, SynapseTool)
    assert tool.name == "connect_integration"
    assert tool.owner_only is True
    assert tool.serial is True


def test_action_list_returns_registry_summary():
    tool = _connect_integration_factory(_ctx(owner=True))
    result = asyncio.run(tool.execute({"action": "list"}))
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["action"] == "list"
    names = {item["name"] for item in payload["integrations"]}
    assert {"google_calendar", "gmail", "notion", "slack"}.issubset(names)


def test_action_connect_runs_manager_connect(monkeypatch, tmp_path):
    captured = {}

    def fake_connect(name, **kwargs):
        captured["name"] = name
        return ConnectionResult(
            integration=name,
            connected=True,
            token_path=tmp_path / "token.json",
            account_email="me@example.com",
            enabled=True,
            auth_type="oauth2_desktop",
            details={"calendar_count": 4},
        )

    monkeypatch.setattr(integrations_pkg, "connect", fake_connect)

    tool = _connect_integration_factory(_ctx(owner=True))
    result = asyncio.run(
        tool.execute({"action": "connect", "integration": "google_calendar"})
    )
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["integration"] == "google_calendar"
    assert payload["connected"] is True
    assert payload["account_email"] == "me@example.com"
    assert payload["details"]["calendar_count"] == 4
    assert captured["name"] == "google_calendar"


def test_calendar_alias_normalizes_to_google_calendar(monkeypatch, tmp_path):
    captured = {}

    def fake_connect(name, **kwargs):
        captured["name"] = name
        return ConnectionResult(
            integration=name,
            connected=True,
            auth_type="oauth2_desktop",
        )

    monkeypatch.setattr(integrations_pkg, "connect", fake_connect)

    tool = _connect_integration_factory(_ctx(owner=True))
    result = asyncio.run(
        tool.execute({"action": "connect", "integration": "calendar"})
    )
    assert not result.is_error
    assert captured["name"] == "google_calendar"


def test_empty_integration_with_connect_action_falls_through_to_list():
    """The factory's `action == 'list' or not raw_name` short-circuit means an
    empty integration with action=connect routes to the list path."""
    tool = _connect_integration_factory(_ctx(owner=True))
    result = asyncio.run(tool.execute({"action": "connect", "integration": ""}))
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["action"] == "list"
    assert "integrations" in payload


def test_connect_propagates_integration_error_as_error_result(monkeypatch):
    from sci_fi_dashboard.integrations import IntegrationError

    def boom(name, **kwargs):
        raise IntegrationError("placeholder client")

    monkeypatch.setattr(integrations_pkg, "connect", boom)

    tool = _connect_integration_factory(_ctx(owner=True))
    result = asyncio.run(
        tool.execute({"action": "connect", "integration": "google_calendar"})
    )
    assert result.is_error
    assert "placeholder" in result.content
