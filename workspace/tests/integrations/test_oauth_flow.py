"""Unit tests for sci_fi_dashboard.integrations.oauth_flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_fi_dashboard.integrations.errors import IntegrationError
from sci_fi_dashboard.integrations.oauth_flow import (
    OAuthResult,
    _is_placeholder_client,
    _resolve_client_config,
    run_oauth_desktop_flow,
)
from sci_fi_dashboard.integrations.registry import (
    SYNAPSE_GOOGLE_OAUTH_CLIENT,
    get_integration,
)


REAL_LOOKING_CLIENT = {
    "installed": {
        "client_id": "1234567890-abc.apps.googleusercontent.com",
        "client_secret": "GOCSPX-realish",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", raising=False)
    monkeypatch.delenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)


class _FakeFlow:
    def __init__(self, creds):
        self.creds = creds
        self.run_calls: list[dict] = []


class _FakeCreds:
    def to_json(self):
        return '{"token": "fake"}'


def test_placeholder_client_without_override_raises():
    integration = get_integration("google_calendar")
    with pytest.raises(IntegrationError, match="placeholder"):
        run_oauth_desktop_flow(
            integration,
            flow_factory=lambda c, s: _FakeFlow(_FakeCreds()),
            server_runner=lambda f: f.creds,
        )


def test_override_path_with_valid_json_returns_used_override(tmp_path):
    integration = get_integration("google_calendar")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")

    creds = _FakeCreds()
    result = run_oauth_desktop_flow(
        integration,
        override_path=client_file,
        flow_factory=lambda c, s: _FakeFlow(creds),
        server_runner=lambda f: f.creds,
    )
    assert isinstance(result, OAuthResult)
    assert result.used_override is True
    assert result.credentials is creds


def test_override_path_nonexistent_raises(tmp_path):
    integration = get_integration("google_calendar")
    missing = tmp_path / "nope.json"
    with pytest.raises(IntegrationError, match="not found"):
        run_oauth_desktop_flow(
            integration,
            override_path=missing,
            flow_factory=lambda c, s: _FakeFlow(_FakeCreds()),
            server_runner=lambda f: f.creds,
        )


def test_env_var_override_picked_up_by_resolver(monkeypatch, tmp_path):
    integration = get_integration("google_calendar")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")
    monkeypatch.setenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", str(client_file))

    config, used_override = _resolve_client_config(integration)
    assert used_override is True
    assert config["installed"]["client_id"] == REAL_LOOKING_CLIENT["installed"]["client_id"]


def test_legacy_env_var_override(monkeypatch, tmp_path):
    integration = get_integration("google_calendar")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")
    monkeypatch.setenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", str(client_file))

    config, used_override = _resolve_client_config(integration)
    assert used_override is True


def test_run_oauth_desktop_flow_returns_credentials(tmp_path):
    integration = get_integration("google_calendar")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")
    creds = _FakeCreds()
    captured = {}

    def flow_factory(config, scopes):
        captured["config"] = config
        captured["scopes"] = scopes
        return _FakeFlow(creds)

    def server_runner(flow):
        captured["flow"] = flow
        return flow.creds

    result = run_oauth_desktop_flow(
        integration,
        override_path=client_file,
        flow_factory=flow_factory,
        server_runner=server_runner,
    )
    assert result.credentials is creds
    assert captured["scopes"] == list(integration.scopes)
    assert isinstance(captured["flow"], _FakeFlow)


def test_run_oauth_desktop_flow_rejects_non_desktop_auth_type():
    notion = get_integration("notion")
    with pytest.raises(IntegrationError, match="oauth2_desktop"):
        run_oauth_desktop_flow(
            notion,
            flow_factory=lambda c, s: _FakeFlow(_FakeCreds()),
            server_runner=lambda f: f.creds,
        )


def test_run_oauth_desktop_flow_wraps_server_runner_exceptions(tmp_path):
    integration = get_integration("google_calendar")
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")

    def boom(_flow):
        raise RuntimeError("network down")

    with pytest.raises(IntegrationError, match="OAuth failed"):
        run_oauth_desktop_flow(
            integration,
            override_path=client_file,
            flow_factory=lambda c, s: _FakeFlow(_FakeCreds()),
            server_runner=boom,
        )


def test_is_placeholder_client_detects_bundled_config():
    assert _is_placeholder_client(SYNAPSE_GOOGLE_OAUTH_CLIENT) is True


def test_is_placeholder_client_false_for_real_looking_config():
    assert _is_placeholder_client(REAL_LOOKING_CLIENT) is False
