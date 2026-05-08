"""Unit tests for sci_fi_dashboard.integrations.registry."""

from __future__ import annotations

import pytest

from sci_fi_dashboard.integrations import registry as reg_mod
from sci_fi_dashboard.integrations.registry import (
    IntegrationDefinition,
    SYNAPSE_GOOGLE_OAUTH_CLIENT,
    get_integration,
    google_oauth_client_override_path,
    list_definitions,
    register,
    registry,
)


def test_registry_has_expected_integrations():
    assert "google_calendar" in registry
    assert "gmail" in registry
    assert "notion" in registry
    assert "slack" in registry


def test_registry_auth_types_match_spec():
    assert registry["google_calendar"].auth_type == "oauth2_desktop"
    assert registry["gmail"].auth_type == "oauth2_desktop"
    assert registry["notion"].auth_type == "oauth2_workspace"
    assert registry["slack"].auth_type == "bot_token"


def test_get_integration_returns_dataclass():
    definition = get_integration("google_calendar")
    assert isinstance(definition, IntegrationDefinition)
    assert definition.name == "google_calendar"
    assert definition.display_name == "Google Calendar"


def test_get_integration_unknown_raises_with_helpful_message():
    with pytest.raises(KeyError) as excinfo:
        get_integration("nonexistent_thing")
    msg = str(excinfo.value)
    assert "nonexistent_thing" in msg
    assert "Known:" in msg


def test_list_definitions_excludes_unavailable_when_requested():
    available = list_definitions(include_unavailable=False)
    names = {d.name for d in available}
    assert "google_calendar" in names
    assert "gmail" in names
    assert "notion" not in names
    assert "slack" not in names


def test_list_definitions_default_includes_unavailable():
    everything = list_definitions()
    names = {d.name for d in everything}
    assert {"google_calendar", "gmail", "notion", "slack"}.issubset(names)


def test_calendar_bundled_client_id_is_placeholder():
    block = SYNAPSE_GOOGLE_OAUTH_CLIENT["installed"]
    assert str(block["client_id"]).startswith("PLACEHOLDER")


def test_calendar_scopes_include_events_and_readonly():
    scopes = registry["google_calendar"].scopes
    assert any(s.endswith("/auth/calendar.events") for s in scopes)
    assert any(s.endswith("/auth/calendar.readonly") for s in scopes)


def test_gmail_scopes_include_modify():
    scopes = registry["gmail"].scopes
    assert any(s.endswith("/auth/gmail.modify") for s in scopes)


def test_register_duplicate_name_raises_value_error():
    existing = registry["google_calendar"]
    with pytest.raises(ValueError, match="already registered"):
        register(existing)


def test_google_oauth_client_override_path_reads_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)
    fake_path = str(tmp_path / "client.json")
    monkeypatch.setenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", fake_path)
    assert google_oauth_client_override_path() == fake_path


def test_google_oauth_client_override_path_legacy_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", raising=False)
    legacy = str(tmp_path / "legacy.json")
    monkeypatch.setenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", legacy)
    assert google_oauth_client_override_path() == legacy


def test_google_oauth_client_override_path_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", raising=False)
    monkeypatch.delenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)
    assert google_oauth_client_override_path() is None
