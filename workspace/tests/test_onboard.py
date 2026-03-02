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


# ===========================================================================
# ONB-03: litellm called with max_tokens=1
# ===========================================================================


def test_provider_validation_calls_max_tokens_1(tmp_path, monkeypatch):
    """ONB-03: Validation call uses max_tokens=1 — never higher."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    mock_acomp = _make_mock_acompletion()

    with patch("litellm.acompletion", mock_acomp):
        result = runner.invoke(
            app,
            ["onboard", "--non-interactive"],
            env={
                "SYNAPSE_HOME": str(tmp_path),
                "SYNAPSE_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "test-key",
            },
        )
    assert result.exit_code == 0
    assert mock_acomp.called, "litellm.acompletion should have been called"
    call_kwargs = mock_acomp.call_args[1]
    assert call_kwargs.get("max_tokens") == 1, (
        f"max_tokens must be 1, got {call_kwargs.get('max_tokens')}"
    )


# ===========================================================================
# ONB-03: RateLimitError treated as valid key
# ===========================================================================


def test_rate_limit_error_accepts_key(tmp_path, monkeypatch):
    """ONB-03: RateLimitError means key is VALID (quota exhausted, not invalid auth)."""
    from cli.provider_steps import validate_provider
    from litellm import RateLimitError

    async def _raise_rate_limit(*args, **kwargs):
        raise RateLimitError(
            message="quota exceeded",
            llm_provider="gemini",
            model="gemini/gemini-2.0-flash",
            response=MagicMock(status_code=429),
        )

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=_raise_rate_limit):
        result = validate_provider("gemini", "valid-key-but-quota")

    assert result.ok is True, f"RateLimitError must yield ok=True, got {result}"
    assert result.error == "quota_exceeded"


def test_authentication_error_rejects_key(tmp_path):
    """ONB-03: AuthenticationError means key is invalid — reject."""
    from cli.provider_steps import validate_provider
    from litellm import AuthenticationError

    async def _raise_auth_error(*args, **kwargs):
        raise AuthenticationError(
            message="invalid key",
            llm_provider="gemini",
            model="gemini/gemini-2.0-flash",
            response=MagicMock(status_code=401),
        )

    with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=_raise_auth_error):
        result = validate_provider("gemini", "bad-key")

    assert result.ok is False
    assert result.error == "invalid_key"


# ===========================================================================
# ONB-03: os.environ restored after validation call
# ===========================================================================


def test_validate_provider_restores_env(tmp_path):
    """ONB-03: os.environ is restored after validate_provider() regardless of outcome."""
    from cli.provider_steps import validate_provider

    sentinel = "ORIGINAL_VALUE_SENTINEL"
    os.environ["GEMINI_API_KEY"] = sentinel

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp:
        mock_acomp.return_value = MagicMock(choices=[MagicMock()])
        validate_provider("gemini", "new-test-key")

    assert os.environ.get("GEMINI_API_KEY") == sentinel, (
        "os.environ[GEMINI_API_KEY] must be restored to original value after validation"
    )
    del os.environ["GEMINI_API_KEY"]


# ===========================================================================
# ONB-02: All 19 providers in PROVIDER_LIST
# ===========================================================================


def test_provider_list_completeness():
    """ONB-02: PROVIDER_LIST must contain all expected providers."""
    from cli.provider_steps import PROVIDER_LIST

    expected = {
        "anthropic", "openai", "gemini", "groq", "openrouter", "mistral",
        "xai", "togetherai", "minimax", "moonshot", "zai", "volcengine",
        "ollama", "bedrock", "huggingface", "nvidia_nim", "github_copilot",
    }
    missing = expected - set(PROVIDER_LIST)
    assert not missing, f"Missing providers from PROVIDER_LIST: {missing}"


# ===========================================================================
# ONB-04: CHANNEL_LIST completeness
# ===========================================================================


def test_channel_list_completeness():
    """ONB-04: CHANNEL_LIST must contain all four supported channels."""
    from cli.channel_steps import CHANNEL_LIST

    assert set(CHANNEL_LIST) == {"whatsapp", "telegram", "discord", "slack"}


# ===========================================================================
# ONB-05 + ONB-06: channel validation functions
# ===========================================================================


def test_validate_telegram_token_401_raises():
    """ONB-05: Telegram 401 → ValueError with clear message."""
    from cli.channel_steps import validate_telegram_token

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(ValueError, match="401"):
            validate_telegram_token("bad-token")


def test_validate_discord_token_401_raises():
    """ONB-05: Discord 401 → ValueError with clear message."""
    from cli.channel_steps import validate_discord_token

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("httpx.get", return_value=mock_resp):
        with pytest.raises(ValueError, match="401"):
            validate_discord_token("bad-token")


def test_validate_slack_prefix_check_bot_token():
    """ONB-05: Slack bot token must start with xoxb- (no network call)."""
    from cli.channel_steps import validate_slack_tokens

    with pytest.raises(ValueError, match="xoxb-"):
        validate_slack_tokens("bad-token", "xapp-valid")


def test_validate_slack_prefix_check_app_token():
    """ONB-05: Slack app token must start with xapp- (no network call)."""
    from cli.channel_steps import validate_slack_tokens

    with pytest.raises(ValueError, match="xapp-"):
        validate_slack_tokens("xoxb-valid", "bad-token")


def test_whatsapp_qr_flow_aborts_no_node(tmp_path):
    """ONB-06: WhatsApp QR flow returns False when Node.js not on PATH."""
    from cli.channel_steps import run_whatsapp_qr_flow

    with patch("shutil.which", return_value=None):
        result = run_whatsapp_qr_flow(bridge_dir=str(tmp_path))
    assert result is False


# ===========================================================================
# ONB-08: migration detection (_check_for_openclaw)
# ===========================================================================


def test_migration_offer_shown_when_openclaw_exists(tmp_path, monkeypatch):
    """ONB-08: _check_for_openclaw returns the path when directory exists."""
    from cli.onboard import _check_for_openclaw

    fake_openclaw = tmp_path / ".openclaw"
    fake_openclaw.mkdir()
    result = _check_for_openclaw(openclaw_root=fake_openclaw)
    assert result == fake_openclaw


def test_no_migration_offer_when_openclaw_absent(tmp_path):
    """ONB-08: _check_for_openclaw returns None when directory does not exist."""
    from cli.onboard import _check_for_openclaw

    fake_home = tmp_path / "no-openclaw-here"
    result = _check_for_openclaw(openclaw_root=fake_home)
    assert result is None


# ===========================================================================
# ONB-10: GitHub Copilot device flow invoked
# ===========================================================================


def test_github_copilot_device_flow_is_async():
    """ONB-10: GitHub Copilot provider triggers device flow function (not password prompt)."""
    from cli.provider_steps import github_copilot_device_flow
    import inspect

    assert inspect.iscoroutinefunction(github_copilot_device_flow), (
        "github_copilot_device_flow must be async (coroutine function)"
    )


def test_github_copilot_device_flow_polls_github(tmp_path):
    """ONB-10: Device flow POSTs to github.com/login/device/code."""
    from cli.provider_steps import github_copilot_device_flow
    from rich.console import Console

    mock_device_resp = MagicMock()
    mock_device_resp.json.return_value = {
        "device_code": "dev123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://github.com/login/device",
        "interval": 1,
    }
    mock_token_resp = MagicMock()
    mock_token_resp.json.return_value = {"access_token": "gho_fake_token"}

    async def _run():
        console = Console(quiet=True)
        with patch("webbrowser.open"), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            # First call = device/code, subsequent calls = access_token
            mock_client.post = AsyncMock(side_effect=[mock_device_resp, mock_token_resp])
            mock_client_cls.return_value = mock_client
            token = await github_copilot_device_flow(console)
        return token

    import asyncio

    os.environ.setdefault("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path))
    token = asyncio.run(_run())
    assert token == "gho_fake_token", f"Expected token, got: {token}"


# ===========================================================================
# Interactive flow tests using force_interactive=True
# ===========================================================================


def test_interactive_provider_selection_writes_config(tmp_path, monkeypatch):
    """Interactive flow: selecting gemini provider → writes synapse.json."""
    from cli.onboard import run_wizard

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    mock_acomp = _make_mock_acompletion()

    with patch("litellm.acompletion", mock_acomp), \
         patch("questionary.confirm") as mock_confirm, \
         patch("questionary.checkbox") as mock_checkbox, \
         patch("questionary.password") as mock_password, \
         patch("cli.onboard._check_for_openclaw", return_value=None):
        # No existing config → skip reconfigure confirm
        mock_confirm.return_value.ask.return_value = False
        # Provider checkbox → select gemini only; then channel checkbox → none
        mock_checkbox.return_value.ask.side_effect = [
            ["gemini"],  # Step 4: provider selection
            [],          # Step 6: channel selection (none)
        ]
        # Password prompt → fake key
        mock_password.return_value.ask.return_value = "fake-gemini-key"

        run_wizard(force_interactive=True)

    config_path = tmp_path / "synapse.json"
    assert config_path.exists(), "synapse.json should be written after interactive wizard"
    config = json.loads(config_path.read_text())
    assert "gemini" in config.get("providers", {}), (
        f"Expected 'gemini' in providers, got: {config.get('providers')}"
    )


def test_interactive_aborts_on_no_providers(tmp_path, monkeypatch):
    """Interactive flow: selecting zero providers → wizard exits 0 without writing config."""
    from cli.onboard import run_wizard
    import typer

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    with patch("questionary.confirm") as mock_confirm, \
         patch("questionary.checkbox") as mock_checkbox, \
         patch("cli.onboard._check_for_openclaw", return_value=None):
        mock_confirm.return_value.ask.return_value = False
        mock_checkbox.return_value.ask.return_value = []  # empty selection

        with pytest.raises(typer.Exit) as exc_info:
            run_wizard(force_interactive=True)
        assert exc_info.value.exit_code == 0, "Empty provider list should exit 0"

    assert not (tmp_path / "synapse.json").exists(), (
        "synapse.json must NOT be written when no providers selected"
    )


def test_interactive_migration_offer_on_openclaw_present(tmp_path, monkeypatch):
    """ONB-08: Interactive flow shows migration confirm when _check_for_openclaw returns a path."""
    from cli.onboard import run_wizard

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    fake_openclaw = tmp_path / ".openclaw"
    fake_openclaw.mkdir()

    mock_acomp = _make_mock_acompletion()
    migration_confirm_called = []

    def confirm_side_effect(question, **kwargs):
        mock_ans = MagicMock()
        if "Migrate" in question or "igrate" in question:
            migration_confirm_called.append(question)
            mock_ans.ask.return_value = False  # decline migration
        else:
            mock_ans.ask.return_value = False  # decline reconfigure
        return mock_ans

    with patch("litellm.acompletion", mock_acomp), \
         patch("questionary.confirm", side_effect=confirm_side_effect), \
         patch("questionary.checkbox") as mock_checkbox, \
         patch("questionary.password") as mock_password, \
         patch("cli.onboard._check_for_openclaw", return_value=fake_openclaw):
        mock_checkbox.return_value.ask.side_effect = [["gemini"], []]
        mock_password.return_value.ask.return_value = "fake-key"
        run_wizard(force_interactive=True)

    assert migration_confirm_called, (
        "Migration confirm should be shown when _check_for_openclaw returns a path"
    )
