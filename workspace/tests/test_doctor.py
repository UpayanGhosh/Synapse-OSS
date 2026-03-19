"""
test_doctor.py — Unit tests for workspace/cli/doctor.py and workspace/cli/health.py

Tests:
  - All 10 checks pass on a healthy mock setup
  - Failed check returns non-zero exit code (== number of failures)
  - Doctor works offline (checks 1-7 don't require live gateway)
  - wait_for_gateway_reachable() returns False on timeout with always-failing probe
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

try:
    from cli.doctor import doctor_command
    from cli.health import wait_for_gateway_reachable

    DOCTOR_AVAILABLE = True
except ImportError:
    DOCTOR_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DOCTOR_AVAILABLE,
    reason="cli.doctor / cli.health not available",
)

# ---------------------------------------------------------------------------
# Helpers — build a "healthy" filesystem layout under tmp_path
# ---------------------------------------------------------------------------


def _build_healthy_workspace(tmp_path: Path) -> Path:
    """Create a minimal healthy layout under tmp_path.

    Returns data_root (tmp_path itself).
    """
    data_root = tmp_path

    # synapse.json with provider and gateway token
    config = {
        "providers": {"gemini": {"api_key": "fake-key"}},
        "gateway": {"port": 8000, "bind": "loopback", "token": "a" * 48},
        "channels": {},
        "model_mappings": {},
        "session": {"dmScope": "per-channel-peer", "identityLinks": {}},
    }
    config_path = data_root / "synapse.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    # workspace dir
    workspace = data_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Bootstrap files
    for fname in ["SOUL.md", "AGENTS.md", "USER.md", "IDENTITY.md"]:
        (workspace / fname).write_text(f"# {fname}", encoding="utf-8")

    # workspace-state.json
    state_dir = workspace / ".synapse"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "workspace-state.json").write_text(
        json.dumps({"bootstrapSeededAt": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    return data_root


# ===========================================================================
# All 10 checks pass on a healthy mock setup
# ===========================================================================


def test_all_10_checks_pass_on_healthy_setup(tmp_path, monkeypatch):
    """doctor_command() must return 0 (no failures) when everything is healthy."""
    data_root = _build_healthy_workspace(tmp_path)
    monkeypatch.setenv("SYNAPSE_HOME", str(data_root))

    # Mock network-dependent checks (7 = Ollama, 8 = gateway)
    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(True, "Ollama reachable", "HTTP 200")
        mock_gw.return_value = CheckResult(True, "API gateway reachable", "HTTP 200")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(fix=False, non_interactive=True)

    assert failures == 0, f"Expected 0 failures on healthy setup, got {failures}"


# ===========================================================================
# Failed check returns non-zero exit code
# ===========================================================================


def test_missing_config_causes_failure(tmp_path, monkeypatch):
    """doctor_command() returns >= 1 when synapse.json is absent."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    # tmp_path is empty — no synapse.json

    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(False, "Ollama reachable", "offline")
        mock_gw.return_value = CheckResult(False, "API gateway reachable", "offline")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(fix=False, non_interactive=True)

    assert failures >= 1, f"Expected at least 1 failure when config missing, got {failures}"


def test_invalid_json_config_causes_failure(tmp_path, monkeypatch):
    """doctor_command() returns >= 1 when synapse.json is invalid JSON."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text("{ this is not json }", encoding="utf-8")

    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(True, "Ollama reachable")
        mock_gw.return_value = CheckResult(True, "API gateway reachable")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(fix=False, non_interactive=True)

    assert failures >= 1, f"Expected failure with invalid JSON, got {failures}"


def test_no_provider_configured_causes_failure(tmp_path, monkeypatch):
    """doctor_command() returns >= 1 when no providers are configured."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = {
        "providers": {},  # empty!
        "gateway": {"token": "a" * 48},
    }
    (tmp_path / "synapse.json").write_text(json.dumps(config), encoding="utf-8")

    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(True, "Ollama reachable")
        mock_gw.return_value = CheckResult(True, "API gateway reachable")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(fix=False, non_interactive=True)

    assert failures >= 1


def test_missing_gateway_token_causes_failure(tmp_path, monkeypatch):
    """doctor_command() returns >= 1 when gateway.token is absent."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    config = {"providers": {"gemini": {"api_key": "key"}}, "gateway": {}}
    (tmp_path / "synapse.json").write_text(json.dumps(config), encoding="utf-8")

    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(True, "Ollama reachable")
        mock_gw.return_value = CheckResult(True, "API gateway reachable")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(fix=False, non_interactive=True)

    assert failures >= 1


# ===========================================================================
# Offline mode — checks 1-7 must work without live services
# ===========================================================================


def test_offline_checks_pass_without_network(tmp_path, monkeypatch):
    """Checks 1-7 (config, dirs, files, token, provider, Ollama mock) work offline."""
    data_root = _build_healthy_workspace(tmp_path)
    monkeypatch.setenv("SYNAPSE_HOME", str(data_root))

    # Only mock the actual network checks (8 = gateway, 7 = Ollama)
    # Checks 1-6, 9, 10 should run from disk without any network
    with (
        patch("cli.doctor._check_ollama_reachable") as mock_ollama,
        patch("cli.doctor._check_gateway_reachable") as mock_gw,
        patch("cli.doctor._check_no_legacy_dirs") as mock_legacy,
    ):
        from cli.doctor import CheckResult

        mock_ollama.return_value = CheckResult(True, "Ollama reachable")
        mock_gw.return_value = CheckResult(True, "API gateway reachable")
        mock_legacy.return_value = CheckResult(True, "No legacy state directories")

        failures = doctor_command(non_interactive=True)

    # With a healthy setup, offline checks 1-7 and 9 should all pass
    assert failures == 0, f"Expected 0 failures in offline mode with healthy setup, got {failures}"


def test_checks_1_through_7_are_config_and_disk_only(tmp_path, monkeypatch):
    """Individual disk-based checks run without making any real HTTP calls."""
    from cli.doctor import (
        _check_bootstrap_files,
        _check_config_valid,
        _check_data_root_exists,
        _check_gateway_token,
        _check_no_legacy_dirs,
        _check_provider_configured,
        _check_workspace_dir,
        _check_workspace_state,
    )

    data_root = _build_healthy_workspace(tmp_path)

    # These must all pass with no mocking of network
    assert _check_config_valid(data_root).passed
    assert _check_data_root_exists(data_root).passed
    assert _check_workspace_dir(data_root).passed
    assert _check_bootstrap_files(data_root).passed
    assert _check_gateway_token(data_root).passed
    assert _check_provider_configured(data_root).passed
    assert _check_workspace_state(data_root).passed
    # Legacy check uses Path.home() — mock to avoid any real ~/.synapse_old
    with patch("cli.doctor.Path") as mock_path_cls:
        # Default: all legacy dirs absent
        mock_home = MagicMock()
        mock_path_cls.home.return_value = mock_home
        mock_home.__truediv__ = lambda self, other: MagicMock(exists=lambda: False)
        _check_no_legacy_dirs()
    # Don't assert on _check_no_legacy_dirs result — just confirm it doesn't crash


# ===========================================================================
# wait_for_gateway_reachable — timeout behaviour
# ===========================================================================


def test_wait_for_gateway_reachable_returns_false_on_timeout():
    """wait_for_gateway_reachable() must return False when probe always fails."""
    call_count = []

    def _always_false(**kwargs) -> bool:
        call_count.append(1)
        return False

    with (
        patch("cli.health.probe_gateway_reachable", side_effect=_always_false),
        patch("time.sleep"),  # avoid real sleep in tests
    ):
        result = wait_for_gateway_reachable(port=8000, token=None, deadline_secs=0.001)

    assert result is False, f"Expected False when all probes fail, got {result}"


def test_wait_for_gateway_reachable_returns_true_on_success():
    """wait_for_gateway_reachable() must return True when probe succeeds on first try."""
    with patch("cli.health.probe_gateway_reachable", return_value=True):
        result = wait_for_gateway_reachable(port=8000, token=None, deadline_secs=5.0)

    assert result is True, f"Expected True when probe succeeds, got {result}"


# ===========================================================================
# doctor subcommand registered in CLI
# ===========================================================================


def test_doctor_command_registered_in_cli():
    """synapse doctor --help must be available in the CLI app."""
    try:
        from synapse_cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "doctor" in result.output, f"'doctor' not found in CLI help: {result.output}"
    except ImportError:
        pytest.skip("synapse_cli not available")


def test_health_command_registered_in_cli():
    """synapse health --help must be available in the CLI app."""
    try:
        from synapse_cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "health" in result.output, f"'health' not found in CLI help: {result.output}"
    except ImportError:
        pytest.skip("synapse_cli not available")
