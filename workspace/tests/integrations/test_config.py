"""Unit tests for sci_fi_dashboard.integrations.config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_fi_dashboard.integrations import config as integrations_config
from sci_fi_dashboard.integrations.errors import IntegrationError
from sci_fi_dashboard.integrations.registry import get_integration


def _read_synapse_json(data_root: Path) -> dict:
    return json.loads((data_root / "synapse.json").read_text(encoding="utf-8"))


def test_mark_connected_writes_new_and_legacy_keys(tmp_path):
    integration = get_integration("google_calendar")
    token_path = tmp_path / "integrations" / "google_calendar" / "token.json"

    integrations_config.mark_connected(
        data_root=tmp_path,
        integration=integration,
        token_path=token_path,
        account_email="me@example.com",
    )

    cfg = _read_synapse_json(tmp_path)
    new_entry = cfg["integrations"]["google_calendar"]
    assert new_entry["enabled"] is True
    assert new_entry["token_path"] == str(token_path)
    assert new_entry["account_email"] == "me@example.com"
    assert new_entry["auth_type"] == "oauth2_desktop"

    legacy = cfg["mcp"]["builtin_servers"]["calendar"]
    assert legacy["enabled"] is True
    assert legacy["token_path"] == str(token_path)


def test_mark_connected_preserves_unrelated_keys(tmp_path):
    integration = get_integration("google_calendar")
    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "providers": {"gemini": {"api_key": "fake"}},
                "mcp": {"custom_servers": {"local": {"command": "python"}}},
            }
        ),
        encoding="utf-8",
    )

    integrations_config.mark_connected(
        data_root=tmp_path,
        integration=integration,
        token_path=tmp_path / "tok.json",
    )

    cfg = _read_synapse_json(tmp_path)
    assert cfg["providers"]["gemini"]["api_key"] == "fake"
    assert cfg["mcp"]["custom_servers"]["local"]["command"] == "python"
    assert cfg["integrations"]["google_calendar"]["enabled"] is True


def test_mark_disconnected_flips_enabled_in_both_places(tmp_path):
    integration = get_integration("google_calendar")
    integrations_config.mark_connected(
        data_root=tmp_path,
        integration=integration,
        token_path=tmp_path / "tok.json",
    )
    integrations_config.mark_disconnected(
        data_root=tmp_path,
        integration=integration,
    )

    cfg = _read_synapse_json(tmp_path)
    assert cfg["integrations"]["google_calendar"]["enabled"] is False
    assert cfg["mcp"]["builtin_servers"]["calendar"]["enabled"] is False
    assert "disconnected_at" in cfg["integrations"]["google_calendar"]


def test_get_entry_returns_empty_when_no_synapse_json(tmp_path):
    integration = get_integration("google_calendar")
    assert integrations_config.get_entry(data_root=tmp_path, integration=integration) == {}


def test_set_dotted_creates_nested_dicts_via_mark_connected(tmp_path):
    """`_set_dotted` is exercised through mark_connected on a fresh tmp_path —
    legacy keys like `mcp.builtin_servers.calendar.token_path` require nested
    dict creation."""
    integration = get_integration("google_calendar")
    integrations_config.mark_connected(
        data_root=tmp_path,
        integration=integration,
        token_path=tmp_path / "tok.json",
    )
    cfg = _read_synapse_json(tmp_path)
    assert isinstance(cfg["mcp"], dict)
    assert isinstance(cfg["mcp"]["builtin_servers"], dict)
    assert isinstance(cfg["mcp"]["builtin_servers"]["calendar"], dict)


def test_load_raw_config_raises_on_malformed_json(tmp_path):
    (tmp_path / "synapse.json").write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(IntegrationError, match="Could not read synapse.json"):
        integrations_config.load_raw_config(tmp_path)


def test_load_raw_config_returns_empty_when_missing(tmp_path):
    assert integrations_config.load_raw_config(tmp_path) == {}
