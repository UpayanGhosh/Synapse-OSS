"""
test_config.py — Unit tests for workspace/synapse_config.py

Covers requirements:
  CONF-02: SynapseConfig.load() reads providers/channels from synapse.json
  CONF-03: SYNAPSE_HOME env var overrides the default data_root
  CONF-04: Three-layer precedence (env > file > defaults)
  CONF-05: write_config() creates synapse.json with mode 600

Tests are intentionally sync (no async) — asyncio_mode=auto is set in pytest.ini
but is not required here.
"""

import os
import sys
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from synapse_config import SynapseConfig, write_config  # noqa: E402


# ---------------------------------------------------------------------------
# CONF-03 / default behaviour
# ---------------------------------------------------------------------------


def test_load_defaults(monkeypatch):
    """When no SYNAPSE_HOME is set and no synapse.json exists, SynapseConfig.load()
    returns a config with data_root == Path.home() / '.synapse'."""
    monkeypatch.delenv("SYNAPSE_HOME", raising=False)
    config = SynapseConfig.load()
    expected = Path.home() / ".synapse"
    assert config.data_root == expected, f"Expected {expected}, got {config.data_root}"
    assert config.db_dir == expected / "workspace" / "db"


# ---------------------------------------------------------------------------
# CONF-03: SYNAPSE_HOME override
# ---------------------------------------------------------------------------


def test_synapse_home_override(tmp_path, monkeypatch):
    """SYNAPSE_HOME env var must override data_root. Verifies CONF-03."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = SynapseConfig.load()
    assert config.data_root == tmp_path.resolve(), (
        f"Expected data_root={tmp_path.resolve()}, got {config.data_root}"
    )


# ---------------------------------------------------------------------------
# CONF-02: reads synapse.json
# ---------------------------------------------------------------------------


def test_reads_synapse_json(tmp_path, monkeypatch):
    """SynapseConfig.load() reads providers/channels from synapse.json. Verifies CONF-02."""
    payload = {"providers": {"gemini": {"api_key": "test-key"}}, "channels": {}}
    write_config(tmp_path, payload)
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = SynapseConfig.load()
    assert config.providers["gemini"]["api_key"] == "test-key", (
        "providers.gemini.api_key should have been read from synapse.json"
    )


# ---------------------------------------------------------------------------
# CONF-04: file values override defaults
# ---------------------------------------------------------------------------


def test_precedence_file_over_defaults(tmp_path, monkeypatch):
    """File values override empty defaults. Partially verifies CONF-04."""
    payload = {
        "providers": {"openrouter": {"api_key": "or-key", "model": "mixtral"}},
        "channels": {"whatsapp": {"enabled": True}},
    }
    write_config(tmp_path, payload)
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = SynapseConfig.load()
    # File content must win over empty-dict defaults
    assert config.providers, "providers should not be empty — file values must win over defaults"
    assert config.channels, "channels should not be empty — file values must win over defaults"
    assert config.providers["openrouter"]["api_key"] == "or-key"


# ---------------------------------------------------------------------------
# CONF-05: write_config mode 600
# ---------------------------------------------------------------------------


def test_write_config_creates_file_with_mode_600(tmp_path):
    """write_config() creates synapse.json and (on non-Windows) enforces mode 600. Verifies CONF-05."""
    write_config(tmp_path, {"providers": {}, "channels": {}})
    config_file = tmp_path / "synapse.json"
    assert config_file.exists(), "synapse.json should be created by write_config()"

    if sys.platform != "win32":
        actual_mode = oct(config_file.stat().st_mode & 0o777)
        assert actual_mode == "0o600", (
            f"synapse.json should have mode 0o600, got {actual_mode}"
        )


# ---------------------------------------------------------------------------
# RuntimeError on uncreatable SYNAPSE_HOME
# ---------------------------------------------------------------------------


def test_invalid_synapse_home_raises(monkeypatch):
    """SynapseConfig.load() raises RuntimeError with 'cannot be created' when
    SYNAPSE_HOME points to a path whose mkdir() raises PermissionError."""
    monkeypatch.setenv("SYNAPSE_HOME", "/nonexistent_root_path/deeply/nested/cannot_exist")

    def _mock_mkdir(self, *args, **kwargs):  # noqa: ANN001
        raise PermissionError("Permission denied")

    with patch.object(Path, "mkdir", _mock_mkdir):
        with pytest.raises(RuntimeError, match="cannot be created"):
            SynapseConfig.load()


# ---------------------------------------------------------------------------
# Not cached at import time
# ---------------------------------------------------------------------------


def test_load_is_not_cached_at_import(tmp_path, monkeypatch):
    """Calling SynapseConfig.load() twice with different SYNAPSE_HOME values must
    return configs with different data_root values, confirming no import-time caching."""
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()

    monkeypatch.setenv("SYNAPSE_HOME", str(dir_a))
    config_a = SynapseConfig.load()

    monkeypatch.setenv("SYNAPSE_HOME", str(dir_b))
    config_b = SynapseConfig.load()

    assert config_a.data_root != config_b.data_root, (
        "SynapseConfig.load() must not be cached — two calls with different "
        "SYNAPSE_HOME env vars must return different data_root values"
    )
    assert config_a.data_root == dir_a.resolve()
    assert config_b.data_root == dir_b.resolve()
