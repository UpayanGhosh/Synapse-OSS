"""Unit tests for sci_fi_dashboard.integrations.token_store."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from sci_fi_dashboard.integrations.errors import IntegrationError
from sci_fi_dashboard.integrations.registry import IntegrationDefinition, get_integration
from sci_fi_dashboard.integrations.token_store import (
    data_root,
    delete_token,
    find_existing_token,
    integration_dir,
    legacy_token_paths,
    save_credentials,
    save_token_json,
    token_path,
)


@pytest.fixture
def calendar_def() -> IntegrationDefinition:
    return get_integration("google_calendar")


def _fake_home(monkeypatch, home: Path) -> None:
    """Cross-platform monkeypatch for $HOME/$USERPROFILE/Path.home()."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def test_token_path_default_when_synapse_home_unset(monkeypatch, calendar_def, tmp_path):
    monkeypatch.delenv("SYNAPSE_HOME", raising=False)
    _fake_home(monkeypatch, tmp_path)
    expected = tmp_path / ".synapse" / "integrations" / "google_calendar" / "token.json"
    assert token_path(calendar_def) == expected


def test_data_root_honors_synapse_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    assert data_root() == tmp_path


def test_save_token_json_writes_atomically(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    path = save_token_json(calendar_def, '{"token": "abc"}')
    assert path.exists()
    assert path.read_text(encoding="utf-8") == '{"token": "abc"}'
    # tmp file is cleaned up by os.replace
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod only")
def test_save_token_json_chmods_600_on_posix(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    path = save_token_json(calendar_def, '{"token": "abc"}')
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600


def test_save_credentials_persists_to_json(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    class FakeCreds:
        def to_json(self):
            return '{"token": "xyz"}'

    path = save_credentials(calendar_def, FakeCreds())
    assert path.exists()
    assert '"token": "xyz"' in path.read_text(encoding="utf-8")


def test_save_credentials_raises_when_missing_to_json(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    class BrokenCreds:
        pass

    with pytest.raises(IntegrationError, match="to_json"):
        save_credentials(calendar_def, BrokenCreds())


def test_find_existing_token_prefers_new_location(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    new = save_token_json(calendar_def, '{"a": 1}')
    # Also create a legacy file
    legacy = legacy_token_paths(calendar_def)[0]
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"legacy": true}', encoding="utf-8")
    assert find_existing_token(calendar_def) == new


def test_find_existing_token_falls_back_to_legacy(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    _fake_home(monkeypatch, tmp_path)
    legacy = legacy_token_paths(calendar_def)[0]
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"legacy": true}', encoding="utf-8")
    found = find_existing_token(calendar_def)
    assert found == legacy


def test_find_existing_token_returns_none_when_nothing(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    _fake_home(monkeypatch, tmp_path)
    assert find_existing_token(calendar_def) is None


def test_delete_token_removes_new_and_legacy(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    _fake_home(monkeypatch, tmp_path)
    new = save_token_json(calendar_def, '{"a": 1}')
    legacy = legacy_token_paths(calendar_def)[0]
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{}", encoding="utf-8")

    assert delete_token(calendar_def) is True
    assert not new.exists()
    assert not legacy.exists()


def test_delete_token_returns_false_when_nothing(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    _fake_home(monkeypatch, tmp_path)
    assert delete_token(calendar_def) is False


def test_legacy_token_paths_resolves_tilde(monkeypatch, calendar_def, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    paths = legacy_token_paths(calendar_def)
    # registry says "~/.synapse/google/calendar_token.json"
    assert paths[0] == tmp_path / ".synapse" / "google" / "calendar_token.json"
    # Tilde fully expanded — no '~' segment remains
    assert "~" not in str(paths[0])


def test_integration_dir_layout(monkeypatch, calendar_def, tmp_path):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    assert integration_dir(calendar_def) == tmp_path / "integrations" / "google_calendar"
