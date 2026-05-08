import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner


class FakeCredentials:
    def __init__(self, token_json='{"token": "calendar-token"}'):
        self._token_json = token_json
        self.expired = False
        self.refresh_token = "refresh-token"
        self.refreshed = False

    def to_json(self):
        return self._token_json

    def refresh(self, _request):
        self.refreshed = True
        self.expired = False


class FakeFlow:
    def __init__(self, credentials):
        self.credentials = credentials
        self.calls = []

    def run_local_server(self, **kwargs):
        self.calls.append(kwargs)
        return self.credentials


class FakeCalendarRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeCalendarService:
    def __init__(self):
        self.calendar_list_calls = []
        self.event_list_calls = []

    def calendarList(self):
        return self

    def events(self):
        return self

    def list(self, **kwargs):
        if "calendarId" in kwargs:
            self.event_list_calls.append(kwargs)
            return FakeCalendarRequest(
                {
                    "items": [
                        {
                            "id": "evt_1",
                            "summary": "Standup",
                            "start": {"dateTime": "2026-05-09T10:00:00+05:30"},
                        }
                    ]
                }
            )
        self.calendar_list_calls.append(kwargs)
        return FakeCalendarRequest({"items": [{"id": "primary", "summary": "Main"}]})


def test_connect_calendar_runs_oauth_saves_token_updates_config_and_verifies(tmp_path):
    from cli.calendar_commands import connect_calendar

    client_secret = tmp_path / "calendar-client.json"
    client_secret.write_text("{}", encoding="utf-8")
    flow = FakeFlow(FakeCredentials())
    service = FakeCalendarService()

    result = connect_calendar(
        data_root=tmp_path,
        client_secret_path=client_secret,
        flow_factory=lambda path, scopes: flow,
        service_builder=lambda token_path, scopes: service,
    )

    token_path = tmp_path / "google" / "calendar_token.json"
    config = json.loads((tmp_path / "synapse.json").read_text(encoding="utf-8"))
    assert token_path.exists()
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "calendar-token"
    assert config["mcp"]["enabled"] is True
    assert config["mcp"]["builtin_servers"]["calendar"]["enabled"] is True
    assert config["mcp"]["builtin_servers"]["calendar"]["token_path"] == str(token_path)
    assert config["mcp"]["builtin_servers"]["calendar"]["credentials_path"] == str(client_secret)
    assert config["mcp"]["calendar_preferences"]["trusted_quick_add"] is True
    assert result.connected is True
    assert result.calendar_count == 1
    assert result.upcoming_count == 1
    assert flow.calls[0]["open_browser"] is True


def test_connect_calendar_preserves_existing_synapse_config(tmp_path):
    from cli.calendar_commands import connect_calendar

    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "providers": {"gemini": {"api_key": "fake"}},
                "mcp": {"custom_servers": {"local": {"command": "python"}}},
            }
        ),
        encoding="utf-8",
    )
    client_secret = tmp_path / "client.json"
    client_secret.write_text("{}", encoding="utf-8")

    connect_calendar(
        data_root=tmp_path,
        client_secret_path=client_secret,
        flow_factory=lambda *_: FakeFlow(FakeCredentials()),
        service_builder=lambda *_: FakeCalendarService(),
    )

    config = json.loads((tmp_path / "synapse.json").read_text(encoding="utf-8"))
    assert config["providers"]["gemini"]["api_key"] == "fake"
    assert config["mcp"]["custom_servers"]["local"]["command"] == "python"
    assert config["mcp"]["builtin_servers"]["calendar"]["enabled"] is True


def test_connect_calendar_missing_client_secret_has_product_facing_error(tmp_path):
    from cli.calendar_commands import CalendarConnectError, connect_calendar

    with pytest.raises(CalendarConnectError, match="Calendar OAuth client is not configured"):
        connect_calendar(data_root=tmp_path)


def test_verify_calendar_uses_existing_config_and_refreshes_expired_token(tmp_path):
    from cli.calendar_commands import verify_calendar_connection

    token_path = tmp_path / "google" / "calendar_token.json"
    token_path.parent.mkdir(parents=True)
    token_path.write_text('{"token": "old"}', encoding="utf-8")
    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "mcp": {
                    "enabled": True,
                    "builtin_servers": {
                        "calendar": {"enabled": True, "token_path": str(token_path)}
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    creds = FakeCredentials('{"token": "new"}')
    creds.expired = True

    result = verify_calendar_connection(
        data_root=tmp_path,
        credentials_loader=lambda path, scopes: creds,
        request_factory=lambda: object(),
        service_factory=lambda credentials: FakeCalendarService(),
    )

    assert result.connected is True
    assert result.calendar_count == 1
    assert result.upcoming_count == 1
    assert creds.refreshed is True
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "new"


def test_calendar_cli_connect_prints_success(monkeypatch, tmp_path):
    from synapse_cli import app
    import cli.calendar_commands as calendar_commands

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.setattr(
        calendar_commands,
        "connect_calendar",
        lambda **_: SimpleNamespace(
            connected=True,
            account="user@example.com",
            token_path=tmp_path / "token.json",
            calendar_count=2,
            upcoming_count=3,
        ),
    )

    result = CliRunner().invoke(app, ["calendar", "connect"])

    assert result.exit_code == 0
    assert "Calendar connected" in result.output
    assert "calendars: 2" in result.output


def test_calendar_cli_verify_returns_nonzero_when_not_connected(monkeypatch, tmp_path):
    from synapse_cli import app
    import cli.calendar_commands as calendar_commands

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.setattr(
        calendar_commands,
        "verify_calendar_connection",
        lambda **_: SimpleNamespace(connected=False, error="Calendar not configured"),
    )

    result = CliRunner().invoke(app, ["calendar", "verify"])

    assert result.exit_code == 1
    assert "Calendar not configured" in result.output
