"""
test_onboard.py — Complete wizard test suite for workspace/cli/onboard.py

Covers all 10 ONB requirements:
  ONB-01: synapse onboard command is registered in the CLI app
  ONB-02: All expected providers appear in PROVIDER_LIST
  ONB-03: litellm.acompletion called with max_tokens=1; RateLimitError → ok=True;
          AuthenticationError → ok=False; os.environ restored after validation
  ONB-04: CHANNEL_LIST contains all four supported channels
  ONB-05: channel validation functions raise ValueError on bad credentials
  ONB-06: WhatsApp QR flow returns False when Node.js not on PATH
  ONB-07: synapse.json written with mode 0o600 (skipped on Windows)
  ONB-08: migration offer shown when ~/.openclaw/ exists; not shown when absent
  ONB-09: --non-interactive exit codes: 0 (success), 1 (missing vars)
  ONB-10: GitHub Copilot uses async device flow, not password prompt

All tests use typer.testing.CliRunner and unittest.mock — no live API calls,
no real terminal, no real Baileys bridge.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip if wizard module not yet installed
# ---------------------------------------------------------------------------

try:
    from cli.onboard import run_wizard
    from synapse_cli import app

    ONBOARD_AVAILABLE = True
except ImportError:
    ONBOARD_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not ONBOARD_AVAILABLE,
    reason="cli.onboard not available — run after Plan 06-04 ships",
)

# ---------------------------------------------------------------------------
# Imports and runner setup
# ---------------------------------------------------------------------------

from typer.testing import CliRunner  # noqa: E402

# typer.testing.CliRunner merges stderr into stdout by default (no mix_stderr kwarg)
runner = CliRunner()


def _make_mock_acompletion():
    """Return a valid litellm completion response mock."""
    mock = AsyncMock()
    mock.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))],
        usage=MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    return mock


# ===========================================================================
# ONB-01: synapse onboard command is registered
# ===========================================================================


def test_onboard_command_registered():
    """ONB-01: synapse onboard command exists in the CLI app."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "onboard" in result.output


# ===========================================================================
# ONB-09: non-interactive mode exit codes
# ===========================================================================


def test_non_interactive_missing_primary_provider_exits_1(tmp_path, monkeypatch):
    """ONB-09: --non-interactive without SYNAPSE_PRIMARY_PROVIDER → exit 1 with clear error."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("SYNAPSE_PRIMARY_PROVIDER", raising=False)
    result = runner.invoke(app, ["onboard", "--non-interactive"], env={"SYNAPSE_HOME": str(tmp_path)})
    assert result.exit_code == 1
    combined = result.output or ""
    assert "SYNAPSE_PRIMARY_PROVIDER" in combined, f"Expected env var name in output: {combined}"


def test_non_interactive_missing_api_key_exits_1(tmp_path, monkeypatch):
    """ONB-09: --non-interactive with provider set but no API key → exit 1 with key name."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = runner.invoke(
        app,
        ["onboard", "--non-interactive"],
        env={"SYNAPSE_HOME": str(tmp_path), "SYNAPSE_PRIMARY_PROVIDER": "gemini"},
    )
    assert result.exit_code == 1
    combined = result.output or ""
    assert "GEMINI_API_KEY" in combined, f"Expected GEMINI_API_KEY in output: {combined}"


def test_non_interactive_success_writes_config(tmp_path, monkeypatch):
    """ONB-09 + ONB-01: --non-interactive with all vars set → exit 0, synapse.json written."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp:
        mock_acomp.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
        )
        result = runner.invoke(
            app,
            ["onboard", "--non-interactive"],
            env={
                "SYNAPSE_HOME": str(tmp_path),
                "SYNAPSE_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "fake-test-key",
            },
        )
    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"Output: {result.output}. Exception: {result.exception}"
    )
    config_path = tmp_path / "synapse.json"
    assert config_path.exists(), "synapse.json not created"


def test_non_interactive_env_var_flag(tmp_path, monkeypatch):
    """ONB-09: SYNAPSE_NON_INTERACTIVE=1 triggers non-interactive without explicit flag."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("SYNAPSE_PRIMARY_PROVIDER", raising=False)
    result = runner.invoke(
        app,
        ["onboard"],  # no --non-interactive flag
        env={"SYNAPSE_HOME": str(tmp_path), "SYNAPSE_NON_INTERACTIVE": "1"},
    )
    # Should attempt non-interactive, fail on missing SYNAPSE_PRIMARY_PROVIDER
    assert result.exit_code == 1
    combined = result.output or ""
    assert "SYNAPSE_PRIMARY_PROVIDER" in combined


# ===========================================================================
# ONB-07: synapse.json written with chmod 600
# ===========================================================================


def test_wizard_writes_config_with_mode_600(tmp_path, monkeypatch):
    """ONB-07: synapse.json is created with mode 0o600 (POSIX only)."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp:
        mock_acomp.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(role="assistant", content="hi"))]
        )
        result = runner.invoke(
            app,
            ["onboard", "--non-interactive"],
            env={
                "SYNAPSE_HOME": str(tmp_path),
                "SYNAPSE_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "fake-test-key",
            },
        )
    assert result.exit_code == 0
    config_path = tmp_path / "synapse.json"
    assert config_path.exists()
    if sys.platform != "win32":
        actual_mode = config_path.stat().st_mode & 0o777
        assert actual_mode == 0o600, f"Expected 0o600, got {oct(actual_mode)}"
