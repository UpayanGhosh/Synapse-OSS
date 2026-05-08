"""Unit tests for sci_fi_dashboard.integrations.manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sci_fi_dashboard.integrations import manager
from sci_fi_dashboard.integrations.errors import IntegrationError
from sci_fi_dashboard.integrations.manager import (
    ConnectionResult,
    connect,
    disconnect,
    list_integrations,
    status,
    verify,
)
from sci_fi_dashboard.integrations.registry import get_integration


REAL_LOOKING_CLIENT = {
    "installed": {
        "client_id": "1234567890-abc.apps.googleusercontent.com",
        "client_secret": "GOCSPX-realish",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}


class FakeCredentials:
    def __init__(self, token_json='{"token": "abc"}', expired=False, refresh_token="r"):
        self._token_json = token_json
        self.expired = expired
        self.refresh_token = refresh_token
        self.refreshed = False

    def to_json(self):
        return self._token_json

    def refresh(self, _request):
        self.refreshed = True
        self.expired = False


@pytest.fixture
def client_secret(tmp_path) -> Path:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps(REAL_LOOKING_CLIENT), encoding="utf-8")
    return path


def _flow_factory_returning(creds):
    def factory(_config, _scopes):
        return _FakeFlow(creds)
    return factory


class _FakeFlow:
    def __init__(self, creds):
        self.creds = creds


def _server_runner(flow):
    return flow.creds


def test_connect_success_writes_token_and_config(tmp_path, client_secret):
    creds = FakeCredentials()
    captured = {}

    def fake_verify(c):
        captured["creds"] = c
        return {"email_address": "me@example.com", "calendar_count": 3}

    result = connect(
        "google_calendar",
        data_root=tmp_path,
        override_client_path=client_secret,
        flow_factory=_flow_factory_returning(creds),
        server_runner=_server_runner,
        verify_handler=fake_verify,
    )

    assert isinstance(result, ConnectionResult)
    assert result.connected is True
    assert result.account_email == "me@example.com"
    assert result.details["calendar_count"] == 3
    assert result.token_path is not None
    assert result.token_path.exists()
    assert captured["creds"] is creds

    cfg = json.loads((tmp_path / "synapse.json").read_text(encoding="utf-8"))
    assert cfg["integrations"]["google_calendar"]["enabled"] is True
    assert cfg["mcp"]["builtin_servers"]["calendar"]["enabled"] is True


def test_connect_propagates_oauth_integration_error(tmp_path):
    """No override_path + bundled placeholder client → IntegrationError."""
    with pytest.raises(IntegrationError, match="placeholder"):
        connect(
            "google_calendar",
            data_root=tmp_path,
            flow_factory=_flow_factory_returning(FakeCredentials()),
            server_runner=_server_runner,
            verify_handler=lambda c: {},
        )


def test_connect_works_when_verify_handler_is_none(tmp_path, client_secret, monkeypatch):
    # Disable any built-in verify handler so we don't need google libs
    monkeypatch.setattr(manager, "verify_handler_for", lambda _name: None)
    result = connect(
        "google_calendar",
        data_root=tmp_path,
        override_client_path=client_secret,
        flow_factory=_flow_factory_returning(FakeCredentials()),
        server_runner=_server_runner,
        verify_handler=None,
    )
    assert result.connected is True
    assert result.details == {}
    assert result.account_email == ""


def test_connect_swallows_non_integration_verify_errors(tmp_path, client_secret):
    def explode(_creds):
        raise RuntimeError("transient API blip")

    result = connect(
        "google_calendar",
        data_root=tmp_path,
        override_client_path=client_secret,
        flow_factory=_flow_factory_returning(FakeCredentials()),
        server_runner=_server_runner,
        verify_handler=explode,
    )
    assert result.connected is True
    assert "verify_error" in result.details
    assert "transient" in result.details["verify_error"]


def test_verify_returns_connected_when_token_valid(tmp_path):
    integration = get_integration("google_calendar")
    # Pre-create a token file at the canonical location
    token_dir = tmp_path / "integrations" / "google_calendar"
    token_dir.mkdir(parents=True)
    (token_dir / "token.json").write_text('{"token": "abc"}', encoding="utf-8")

    creds = FakeCredentials(expired=False)
    result = verify(
        "google_calendar",
        data_root=tmp_path,
        credentials_loader=lambda path, scopes: creds,
        request_factory=lambda: object(),
        verify_handler=lambda c: {"email_address": "me@example.com"},
    )
    assert result.connected is True
    assert result.account_email == "me@example.com"
    assert creds.refreshed is False


def test_verify_refreshes_when_credentials_expired(tmp_path):
    integration = get_integration("google_calendar")
    token_dir = tmp_path / "integrations" / "google_calendar"
    token_dir.mkdir(parents=True)
    (token_dir / "token.json").write_text("{}", encoding="utf-8")

    creds = FakeCredentials(token_json='{"token": "fresh"}', expired=True, refresh_token="r")
    result = verify(
        "google_calendar",
        data_root=tmp_path,
        credentials_loader=lambda path, scopes: creds,
        request_factory=lambda: object(),
        verify_handler=lambda c: {"email_address": "me@example.com"},
    )
    assert result.connected is True
    assert creds.refreshed is True
    persisted = (token_dir / "token.json").read_text(encoding="utf-8")
    assert "fresh" in persisted


def test_verify_fails_when_no_token(tmp_path):
    result = verify("google_calendar", data_root=tmp_path)
    assert result.connected is False
    assert "not connected" in result.error


def test_status_reflects_token_presence(tmp_path):
    # No token → connected False
    result = status("google_calendar", data_root=tmp_path)
    assert result.connected is False

    token_dir = tmp_path / "integrations" / "google_calendar"
    token_dir.mkdir(parents=True)
    (token_dir / "token.json").write_text("{}", encoding="utf-8")

    result2 = status("google_calendar", data_root=tmp_path)
    assert result2.connected is True
    assert result2.token_path is not None


def test_disconnect_removes_token_and_disables(tmp_path):
    integration = get_integration("google_calendar")
    token_dir = tmp_path / "integrations" / "google_calendar"
    token_dir.mkdir(parents=True)
    token_file = token_dir / "token.json"
    token_file.write_text("{}", encoding="utf-8")

    # Pre-populate config so mark_disconnected has something to flip
    from sci_fi_dashboard.integrations import config as integrations_config
    integrations_config.mark_connected(
        data_root=tmp_path,
        integration=integration,
        token_path=token_file,
    )

    removed = disconnect("google_calendar", data_root=tmp_path)
    assert removed is True
    assert not token_file.exists()

    cfg = json.loads((tmp_path / "synapse.json").read_text(encoding="utf-8"))
    assert cfg["integrations"]["google_calendar"]["enabled"] is False


def test_list_integrations_returns_one_per_definition(tmp_path):
    results = list_integrations(data_root=tmp_path, include_unavailable=True)
    names = {r.integration for r in results}
    assert {"google_calendar", "gmail", "notion", "slack"}.issubset(names)
    # All disconnected on a fresh tmp_path
    for r in results:
        assert r.connected is False
