"""Tests for cli/integration_steps.py — onboarding wizard hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cli.integration_steps import setup_integrations_wizard
from sci_fi_dashboard.integrations.manager import ConnectionResult


class FakePrompter:
    def __init__(self, confirm_answers: list[bool], text_answers: list[str] | None = None) -> None:
        self._confirm = list(confirm_answers)
        self._text = list(text_answers or [])
        self.confirm_calls: list[str] = []
        self.text_calls: list[str] = []

    def confirm(self, message: str, default: bool = True) -> bool:
        self.confirm_calls.append(message)
        return self._confirm.pop(0) if self._confirm else default

    def text(self, message: str, default: str = "", password: bool = False) -> str:
        self.text_calls.append(message)
        return self._text.pop(0) if self._text else default


@pytest.fixture
def fake_real_client(tmp_path) -> Path:
    path = tmp_path / "real_client.json"
    path.write_text(
        '{"installed": {"client_id": "real-id.apps.googleusercontent.com",'
        ' "client_secret": "real-secret",'
        ' "auth_uri": "https://accounts.google.com/o/oauth2/auth",'
        ' "token_uri": "https://oauth2.googleapis.com/token",'
        ' "redirect_uris": ["http://localhost"]}}',
        encoding="utf-8",
    )
    return path


def test_top_level_no_skips_everything(tmp_path):
    prompter = FakePrompter(confirm_answers=[False])
    results = setup_integrations_wizard(prompter, data_root=tmp_path)
    assert all(v == "skipped" for v in results.values())
    # Only one prompt asked (the umbrella question)
    assert len(prompter.confirm_calls) == 1


def test_skips_when_user_declines_specific_integration(tmp_path):
    # Yes to umbrella, No to every integration
    prompter = FakePrompter(confirm_answers=[True, False, False])
    results = setup_integrations_wizard(prompter, data_root=tmp_path)
    assert results.get("google_calendar") == "skipped"
    assert results.get("gmail") == "skipped"


def test_connect_with_real_client_path_calls_manager_connect(
    tmp_path,
    monkeypatch,
    fake_real_client,
):
    captured: dict[str, Any] = {}

    def fake_connect(name, *, data_root, override_client_path):
        captured["name"] = name
        captured["override_client_path"] = override_client_path
        return ConnectionResult(
            integration=name,
            connected=True,
            account_email="me@example.com",
            details={"calendar_count": 3, "upcoming_count": 2},
            auth_type="oauth2_desktop",
        )

    import cli.integration_steps as step_module

    monkeypatch.setattr(step_module, "_has_placeholder_bundled_client", lambda: True)
    monkeypatch.setattr(
        "sci_fi_dashboard.integrations.connect",
        fake_connect,
        raising=False,
    )
    import sci_fi_dashboard.integrations as ipkg

    monkeypatch.setattr(ipkg, "connect", fake_connect)

    # Yes umbrella, Yes calendar (only first available item connects), No gmail
    prompter = FakePrompter(
        confirm_answers=[True, True, False],
        text_answers=[str(fake_real_client)],
    )
    config: dict[str, Any] = {}
    results = setup_integrations_wizard(prompter, data_root=tmp_path, config=config)

    assert results.get("google_calendar") == "connected"
    assert captured["name"] == "google_calendar"
    assert captured["override_client_path"] == fake_real_client
    assert "google_calendar" in config.get("integrations_connected", [])


def test_failed_connect_records_failed_status(tmp_path, monkeypatch, fake_real_client):
    from sci_fi_dashboard.integrations import IntegrationError
    import sci_fi_dashboard.integrations as ipkg

    def fake_connect(name, **kwargs):
        raise IntegrationError("simulated failure")

    monkeypatch.setattr(ipkg, "connect", fake_connect)
    import cli.integration_steps as step_module

    monkeypatch.setattr(step_module, "_has_placeholder_bundled_client", lambda: True)

    prompter = FakePrompter(
        confirm_answers=[True, True, False],
        text_answers=[str(fake_real_client)],
    )
    results = setup_integrations_wizard(prompter, data_root=tmp_path)
    assert results.get("google_calendar") == "failed"


def test_blank_text_path_skips_integration(tmp_path, monkeypatch):
    import cli.integration_steps as step_module

    monkeypatch.setattr(step_module, "_has_placeholder_bundled_client", lambda: True)
    monkeypatch.delenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", raising=False)
    monkeypatch.delenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)

    # Yes umbrella, Yes calendar, blank path text answer
    prompter = FakePrompter(confirm_answers=[True, True, False], text_answers=[""])
    results = setup_integrations_wizard(prompter, data_root=tmp_path)
    assert results.get("google_calendar") == "skipped"


def test_env_var_override_skips_text_prompt(tmp_path, monkeypatch, fake_real_client):
    monkeypatch.setenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", str(fake_real_client))

    import sci_fi_dashboard.integrations as ipkg
    import cli.integration_steps as step_module

    captured = {}

    def fake_connect(name, *, data_root, override_client_path):
        captured["override_client_path"] = override_client_path
        return ConnectionResult(integration=name, connected=True, auth_type="oauth2_desktop")

    monkeypatch.setattr(ipkg, "connect", fake_connect)
    monkeypatch.setattr(step_module, "_has_placeholder_bundled_client", lambda: True)

    prompter = FakePrompter(confirm_answers=[True, True, False])
    results = setup_integrations_wizard(prompter, data_root=tmp_path)

    assert results.get("google_calendar") == "connected"
    assert captured["override_client_path"] == fake_real_client
    # Did NOT prompt for text path because env var resolved
    assert prompter.text_calls == []


def test_real_bundled_client_skips_text_prompt(tmp_path, monkeypatch):
    """When the bundled client_id is real (post-verification), no path prompt."""
    import sci_fi_dashboard.integrations as ipkg
    import cli.integration_steps as step_module

    captured = {}

    def fake_connect(name, *, data_root, override_client_path):
        captured["override_client_path"] = override_client_path
        return ConnectionResult(integration=name, connected=True, auth_type="oauth2_desktop")

    monkeypatch.setattr(ipkg, "connect", fake_connect)
    monkeypatch.setattr(step_module, "_has_placeholder_bundled_client", lambda: False)
    monkeypatch.delenv("SYNAPSE_GOOGLE_OAUTH_CLIENT_PATH", raising=False)
    monkeypatch.delenv("SYNAPSE_GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)

    prompter = FakePrompter(confirm_answers=[True, True, False])
    results = setup_integrations_wizard(prompter, data_root=tmp_path)

    assert results.get("google_calendar") == "connected"
    assert captured["override_client_path"] is None
    assert prompter.text_calls == []
