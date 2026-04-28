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
  ONB-08: migration offer shown when legacy install exists; not shown when absent
  ONB-09: --non-interactive exit codes: 0 (success), 1 (missing vars)
  ONB-10: GitHub Copilot uses async device flow, not password prompt

All tests use typer.testing.CliRunner and unittest.mock — no live API calls,
no real terminal, no real Baileys bridge.
"""

import json
import os
import sys
import tomllib
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip if wizard module not yet installed
# ---------------------------------------------------------------------------

try:
    from cli.onboard import run_wizard  # noqa: F401
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


def test_onboard_command_passes_launch_chat_option(monkeypatch):
    from typer.testing import CliRunner
    from synapse_cli import app

    captured = {}
    monkeypatch.setattr("cli.onboard.run_wizard", lambda **kwargs: captured.update(kwargs))
    result = CliRunner().invoke(app, ["onboard", "--no-launch-chat"])

    assert result.exit_code == 0
    assert captured["launch_chat"] is False


def test_post_onboard_chat_nonzero_exit_raises():
    import typer
    from cli.onboard import _raise_for_chat_exit_code

    with pytest.raises(typer.Exit) as exc_info:
        _raise_for_chat_exit_code(7)

    assert exc_info.value.exit_code == 7


def test_non_interactive_launch_chat_propagates_chat_exit_code(tmp_path, monkeypatch):
    """Regression: --launch-chat must return the chat loop exit code."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    with (
        patch(
            "cli.onboard.validate_provider",
            return_value=MagicMock(ok=True, error=None, detail=None),
        ),
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 9012, "bind": "loopback", "token": "a" * 48},
        ),
        patch("cli.onboard._validate_environment"),
        patch("cli.chat_loop.run_cli_chat", return_value=7) as run_chat,
    ):
        result = runner.invoke(
            app,
            ["onboard", "--non-interactive", "--accept-risk", "--launch-chat"],
            env={
                "SYNAPSE_HOME": str(tmp_path),
                "SYNAPSE_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "fake-test-key",
            },
        )

    assert result.exit_code == 7
    run_chat.assert_called_once()
    assert run_chat.call_args.args[0].port == 9012


def test_interactive_launch_chat_propagates_chat_exit_code(tmp_path, monkeypatch):
    """Regression: accepted post-onboard chat prompt must propagate failures."""
    import typer
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    stub = MagicMock()
    stub.multiselect.return_value = ["gemini"]
    stub.confirm.side_effect = lambda message, default=True: message == "Start local CLI chat now?"

    def seed_provider(_prompter, config, _selected):
        config["providers"]["gemini"] = {"api_key": "fake-test-key"}

    with (
        patch("cli.onboard._check_for_legacy_install", return_value=None),
        patch("cli.onboard._collect_provider_keys", side_effect=seed_provider),
        patch(
            "cli.onboard.setup_whatsapp",
            return_value={"enabled": True, "bridge_port": 5010, "dm_policy": "pairing"},
        ) as setup_wa,
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 9013, "bind": "loopback", "token": "a" * 48},
        ),
        patch(
            "cli.onboard._build_model_mappings_interactive",
            return_value={"chat": {"model": "gemini/gemini-pro", "fallback": None}},
        ),
        patch("cli.onboard._run_sbs_questions"),
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.onboard._validate_environment"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        patch("cli.chat_loop.run_cli_chat", return_value=7) as run_chat,
    ):
        with pytest.raises(typer.Exit) as exc_info:
            _run_interactive(prompter=stub, flow="quickstart", launch_chat=True)

    assert exc_info.value.exit_code == 7
    setup_wa.assert_not_called()
    run_chat.assert_called_once()
    assert run_chat.call_args.args[0].port == 9013


def test_cli_chat_modules_are_part_of_workspace_package():
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    packages = data["tool"]["setuptools"]["packages"]["find"]["where"]
    package_data = data["tool"]["setuptools"]["package-data"]

    assert packages == ["workspace"]
    assert "templates/*.md" in package_data["cli"]
    assert "agent_workspace/*.md.template" in package_data["sci_fi_dashboard"]


def test_setup_paths_install_synapse_console_script():
    repo_root = Path(__file__).resolve().parents[2]

    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    how_to_run = (repo_root / "HOW_TO_RUN.md").read_text(encoding="utf-8")
    onboard_bat = (repo_root / "synapse_onboard.bat").read_text(encoding="utf-8")
    onboard_sh = (repo_root / "synapse_onboard.sh").read_text(encoding="utf-8")

    assert "pip install -e ." in readme
    assert "pip install -e ." in how_to_run
    assert 'pip.exe" install -e "%PROJECT_ROOT%"' in onboard_bat
    assert '"$VENV_PIP" install -e "$SCRIPT_DIR"' in onboard_sh


# ===========================================================================
# ONB-09: non-interactive mode exit codes
# ===========================================================================


def test_non_interactive_missing_primary_provider_exits_1(tmp_path, monkeypatch):
    """ONB-09: --non-interactive without SYNAPSE_PRIMARY_PROVIDER → exit 1 with clear error."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("SYNAPSE_PRIMARY_PROVIDER", raising=False)
    result = runner.invoke(
        app,
        ["onboard", "--non-interactive", "--accept-risk"],
        env={"SYNAPSE_HOME": str(tmp_path)},
    )
    assert result.exit_code == 1
    combined = result.output or ""
    assert "SYNAPSE_PRIMARY_PROVIDER" in combined, f"Expected env var name in output: {combined}"


def test_non_interactive_missing_api_key_exits_1(tmp_path, monkeypatch):
    """ONB-09: --non-interactive with provider set but no API key → exit 1 with key name."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = runner.invoke(
        app,
        ["onboard", "--non-interactive", "--accept-risk"],
        env={"SYNAPSE_HOME": str(tmp_path), "SYNAPSE_PRIMARY_PROVIDER": "gemini"},
    )
    assert result.exit_code == 1
    combined = result.output or ""
    assert "GEMINI_API_KEY" in combined, f"Expected GEMINI_API_KEY in output: {combined}"


def test_non_interactive_openai_codex_unsupported_exits_1(tmp_path, monkeypatch):
    """openai_codex non-interactive setup must fail clearly (OAuth device flow only)."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    result = runner.invoke(
        app,
        ["onboard", "--non-interactive", "--accept-risk"],
        env={
            "SYNAPSE_HOME": str(tmp_path),
            "SYNAPSE_PRIMARY_PROVIDER": "openai_codex",
            "OPENAI_CODEX_API_KEY": "ignored-if-present",
        },
    )
    assert result.exit_code == 1
    combined = result.output or ""
    assert "openai_codex" in combined
    assert "non-interactive" in combined.lower()
    assert "oauth" in combined.lower()


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
            ["onboard", "--non-interactive", "--accept-risk"],
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
        env={
            "SYNAPSE_HOME": str(tmp_path),
            "SYNAPSE_NON_INTERACTIVE": "1",
            "SYNAPSE_ACCEPT_RISK": "1",
        },
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
            ["onboard", "--non-interactive", "--accept-risk"],
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
            ["onboard", "--non-interactive", "--accept-risk"],
            env={
                "SYNAPSE_HOME": str(tmp_path),
                "SYNAPSE_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "test-key",
            },
        )
    assert result.exit_code == 0
    assert mock_acomp.called, "litellm.acompletion should have been called"
    call_kwargs = mock_acomp.call_args[1]
    assert (
        call_kwargs.get("max_tokens") == 1
    ), f"max_tokens must be 1, got {call_kwargs.get('max_tokens')}"


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

    assert (
        os.environ.get("GEMINI_API_KEY") == sentinel
    ), "os.environ[GEMINI_API_KEY] must be restored to original value after validation"
    del os.environ["GEMINI_API_KEY"]


def test_validate_provider_vertex_ai_uses_existing_env(monkeypatch):
    """Vertex AI has no single api_key — validate_provider must not touch _KEY_MAP.

    Creds (VERTEXAI_PROJECT, VERTEXAI_LOCATION, GOOGLE_APPLICATION_CREDENTIALS)
    are pre-set by the caller; validate_provider reads them via litellm directly.
    The api_key arg is a logging label only (typically the project_id).
    """
    from cli.provider_steps import validate_provider

    monkeypatch.setenv("VERTEXAI_PROJECT", "test-proj")
    monkeypatch.setenv("VERTEXAI_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/fake/sa.json")

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp:
        mock_acomp.return_value = MagicMock(choices=[MagicMock()])
        result = validate_provider("vertex_ai", "test-proj")

    assert result.ok is True
    # Env vars still set by the caller — validate_provider did not restore or pop them.
    assert os.environ.get("VERTEXAI_PROJECT") == "test-proj"
    assert os.environ.get("VERTEXAI_LOCATION") == "us-central1"
    assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") == "/fake/sa.json"


def test_validate_provider_vertex_ai_does_not_raise_keyerror(monkeypatch):
    """Regression: validate_provider('vertex_ai', ...) must not KeyError on _KEY_MAP."""
    from cli.provider_steps import validate_provider

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acomp:
        mock_acomp.return_value = MagicMock(choices=[MagicMock()])
        # Should complete without raising KeyError (vertex_ai not in _KEY_MAP).
        result = validate_provider("vertex_ai", "any-project-id")
    assert result.ok is True


# ===========================================================================
# ONB-02: All 19 providers in PROVIDER_LIST
# ===========================================================================


def test_provider_list_completeness():
    """ONB-02: PROVIDER_LIST must contain all expected providers."""
    from cli.provider_steps import PROVIDER_LIST

    expected = {
        "anthropic",
        "openai",
        "gemini",
        "groq",
        "openrouter",
        "mistral",
        "xai",
        "togetherai",
        "minimax",
        "moonshot",
        "zai",
        "volcengine",
        "ollama",
        "bedrock",
        "vertex_ai",
        "huggingface",
        "nvidia_nim",
        "github_copilot",
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
    with patch("httpx.get", return_value=mock_resp), pytest.raises(ValueError, match="401"):
        validate_telegram_token("bad-token")


def test_validate_discord_token_401_raises():
    """ONB-05: Discord 401 → ValueError with clear message."""
    from cli.channel_steps import validate_discord_token

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    with patch("httpx.get", return_value=mock_resp), pytest.raises(ValueError, match="401"):
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
    """ONB-06: WhatsApp QR flow raises NodeJsMissingError when Node.js not on PATH."""
    from cli.channel_steps import NodeJsMissingError, run_whatsapp_qr_flow

    with patch("shutil.which", return_value=None), pytest.raises(NodeJsMissingError):
        run_whatsapp_qr_flow(bridge_dir=str(tmp_path))


# ===========================================================================
# ONB-08: migration detection (_check_for_legacy_install)
# ===========================================================================


def test_migration_offer_shown_when_legacy_exists(tmp_path, monkeypatch):
    """ONB-08: _check_for_legacy_install returns the path when directory exists."""
    from cli.onboard import _check_for_legacy_install

    fake_legacy_dir = tmp_path / ".openclaw"
    fake_legacy_dir.mkdir()
    result = _check_for_legacy_install(legacy_root=fake_legacy_dir)
    assert result == fake_legacy_dir


def test_no_migration_offer_when_legacy_absent(tmp_path):
    """ONB-08: _check_for_legacy_install returns None when directory does not exist."""
    from cli.onboard import _check_for_legacy_install

    fake_home = tmp_path / "no-legacy-here"
    result = _check_for_legacy_install(legacy_root=fake_home)
    assert result is None


# ===========================================================================
# ONB-10: GitHub Copilot device flow invoked
# ===========================================================================


def test_github_copilot_device_flow_is_async():
    """ONB-10: GitHub Copilot provider triggers device flow function (not password prompt)."""
    import inspect

    from cli.provider_steps import github_copilot_device_flow

    assert inspect.iscoroutinefunction(
        github_copilot_device_flow
    ), "github_copilot_device_flow must be async (coroutine function)"


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
        with patch("webbrowser.open"), patch("httpx.AsyncClient") as mock_client_cls:
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


def test_collect_provider_keys_openai_codex_device_flow():
    """openai_codex onboarding should map device-flow metadata into provider config."""
    from cli import onboard

    config = {"providers": {}, "model_mappings": {}, "channels": {}}
    prompter = MagicMock()
    mock_codex_flow = AsyncMock(
        return_value={
            "email": "me@example.com",
            "profile_name": "me@example.com",
            "account_id": "acct-123",
        }
    )

    with patch(
        "cli.onboard.openai_codex_device_flow",
        new=mock_codex_flow,
    ), patch(
        "cli.onboard.validate_provider",
        return_value=MagicMock(ok=True, error=None, detail=None),
    ) as mock_validate_provider:
        # openai_codex should use device flow only (no API key prompt/validation).
        onboard._collect_provider_keys(
            prompter=prompter,
            config=config,
            selected_providers=["openai_codex"],
        )

    mock_validate_provider.assert_not_called()
    prompter.text.assert_not_called()
    prompter.confirm.assert_not_called()
    mock_codex_flow.assert_called_once()
    assert config["providers"]["openai_codex"] == {
        "oauth_email": "me@example.com",
        "profile_name": "me@example.com",
        "account_id": "acct-123",
    }


def test_openai_codex_device_flow_retries_once_on_unknown_device_auth():
    """openai_codex device flow retries once when OpenAI returns unknown device auth."""
    import asyncio
    from types import SimpleNamespace

    from cli.provider_steps import openai_codex_device_flow

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    fake_creds = SimpleNamespace(
        email="me@example.com",
        profile_name="me@example.com",
        account_id="acct-123",
    )

    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=None,
    ), patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code",
        side_effect=[
            RuntimeError("OpenAI OAuth HTTP 403: Device authorization is unknown. Please try again."),
            fake_creds,
        ],
    ) as mock_login, patch(
        "sci_fi_dashboard.openai_codex_oauth.import_codex_cli_credentials",
        return_value=None,
    ):
        metadata = asyncio.run(openai_codex_device_flow(console))

    assert mock_login.call_count == 2
    assert metadata == {
        "email": "me@example.com",
        "profile_name": "me@example.com",
        "account_id": "acct-123",
    }
    assert any("retrying once" in m.lower() for m in console.messages)


def test_openai_codex_device_flow_shows_security_guidance_on_repeated_unknown_device_auth():
    """openai_codex device flow should show security-setting guidance on repeated unknown auth."""
    import asyncio

    from cli.provider_steps import openai_codex_device_flow

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=None,
    ), patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code",
        side_effect=[
            RuntimeError("OpenAI OAuth HTTP 403: Device authorization is unknown. Please try again."),
            RuntimeError("OpenAI OAuth HTTP 403: Device authorization is unknown. Please try again."),
        ],
    ) as mock_login, patch(
        "sci_fi_dashboard.openai_codex_oauth.import_codex_cli_credentials",
        return_value=None,
    ):
        metadata = asyncio.run(openai_codex_device_flow(console))

    assert mock_login.call_count == 2
    assert metadata is None
    assert any("device code authorization for codex" in m.lower() for m in console.messages)


def test_openai_codex_device_flow_reuses_existing_credentials_before_new_device_flow():
    """openai_codex device flow should short-circuit when active local creds already exist."""
    import asyncio
    from types import SimpleNamespace

    from cli.provider_steps import openai_codex_device_flow

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    existing = SimpleNamespace(
        access_token="tok",
        refresh_token="ref",
        email="me@example.com",
        profile_name="me@example.com",
        account_id="acct-123",
    )
    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=existing,
    ) as mock_get_active, patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code"
    ) as mock_login:
        metadata = asyncio.run(openai_codex_device_flow(console))

    mock_get_active.assert_called_once_with(refresh_if_needed=True)
    mock_login.assert_not_called()
    assert metadata == {
        "email": "me@example.com",
        "profile_name": "me@example.com",
        "account_id": "acct-123",
    }
    assert any("using existing openai codex oauth credentials" in m.lower() for m in console.messages)


def test_openai_codex_device_flow_imports_codex_cli_credentials_on_cloudflare_when_opted_in(
    monkeypatch,
):
    """openai_codex device flow can import Codex CLI auth only when explicitly enabled."""
    import asyncio
    from types import SimpleNamespace

    from cli.provider_steps import openai_codex_device_flow

    monkeypatch.setenv("SYNAPSE_OPENAI_CODEX_IMPORT_FROM_CODEX", "1")

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    imported = SimpleNamespace(
        access_token="tok",
        refresh_token="ref",
        email="me@example.com",
        profile_name="me@example.com",
        account_id="acct-123",
    )
    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=None,
    ) as mock_get_active, patch(
        "sci_fi_dashboard.openai_codex_oauth.import_codex_cli_credentials",
        return_value=imported,
    ) as mock_import, patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code",
        side_effect=RuntimeError(
            "OpenAI OAuth HTTP 403: Cloudflare challenge blocked OpenAI OAuth request"
        ),
    ) as mock_login:
        metadata = asyncio.run(openai_codex_device_flow(console))

    mock_get_active.assert_called_once_with(refresh_if_needed=True)
    mock_import.assert_called_once()
    mock_login.assert_called_once()
    assert metadata == {
        "email": "me@example.com",
        "profile_name": "me@example.com",
        "account_id": "acct-123",
    }
    assert any("imported openai codex credentials" in m.lower() for m in console.messages)


def test_openai_codex_device_flow_cloudflare_error_shows_guidance():
    """openai_codex device flow should classify cloudflare challenge errors clearly."""
    import asyncio

    from cli.provider_steps import openai_codex_device_flow

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=None,
    ), patch(
        "sci_fi_dashboard.openai_codex_oauth.import_codex_cli_credentials",
        return_value=None,
    ) as mock_import, patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code",
        side_effect=RuntimeError("OpenAI OAuth HTTP 403: Cloudflare challenge blocked OpenAI OAuth request"),
    ):
        metadata = asyncio.run(openai_codex_device_flow(console))

    assert metadata is None
    mock_import.assert_not_called()
    assert any("cloudflare challenge" in m.lower() for m in console.messages)


def test_openai_codex_device_flow_force_reauth_ignores_existing_credentials(monkeypatch):
    """force-reauth flag should bypass existing Synapse Codex credentials."""
    import asyncio
    from types import SimpleNamespace

    from cli.provider_steps import openai_codex_device_flow

    monkeypatch.setenv("SYNAPSE_OPENAI_CODEX_FORCE_REAUTH", "1")

    class _CaptureConsole:
        def __init__(self):
            self.messages = []

        def print(self, msg):
            self.messages.append(str(msg))

    existing = SimpleNamespace(
        access_token="tok-old",
        refresh_token="ref-old",
        email="old@example.com",
        profile_name="old@example.com",
        account_id="acct-old",
    )
    fresh = SimpleNamespace(
        email="new@example.com",
        profile_name="new@example.com",
        account_id="acct-new",
    )
    console = _CaptureConsole()
    with patch(
        "sci_fi_dashboard.openai_codex_oauth.get_active_credentials",
        return_value=existing,
    ), patch(
        "sci_fi_dashboard.openai_codex_oauth.import_codex_cli_credentials",
        return_value=None,
    ), patch(
        "sci_fi_dashboard.openai_codex_oauth.login_device_code",
        return_value=fresh,
    ) as mock_login:
        metadata = asyncio.run(openai_codex_device_flow(console))

    mock_login.assert_called_once()
    assert metadata == {
        "email": "new@example.com",
        "profile_name": "new@example.com",
        "account_id": "acct-new",
    }
    assert any("force_reauth=1" in m.lower() for m in console.messages)


def test_collect_provider_keys_openai_codex_retries_until_success():
    """openai_codex onboarding should retry failed auth before proceeding."""
    from cli import onboard

    config = {"providers": {}, "model_mappings": {}, "channels": {}}
    prompter = MagicMock()
    prompter.confirm.side_effect = [True]
    mock_codex_flow = AsyncMock(
        side_effect=[
            None,
            {
                "email": "me@example.com",
                "profile_name": "me@example.com",
                "account_id": "acct-123",
            },
        ]
    )

    with patch(
        "cli.onboard.openai_codex_device_flow",
        new=mock_codex_flow,
    ):
        onboard._collect_provider_keys(
            prompter=prompter,
            config=config,
            selected_providers=["openai_codex"],
        )

    assert mock_codex_flow.await_count == 2
    prompter.confirm.assert_called_once()
    assert config["providers"]["openai_codex"] == {
        "oauth_email": "me@example.com",
        "profile_name": "me@example.com",
        "account_id": "acct-123",
    }


def test_collect_provider_keys_openai_codex_can_skip_after_failed_auth():
    """openai_codex onboarding allows explicit skip after failed auth."""
    from cli import onboard

    config = {"providers": {}, "model_mappings": {}, "channels": {}}
    prompter = MagicMock()
    prompter.confirm.side_effect = [False]
    mock_codex_flow = AsyncMock(return_value=None)

    with patch(
        "cli.onboard.openai_codex_device_flow",
        new=mock_codex_flow,
    ):
        onboard._collect_provider_keys(
            prompter=prompter,
            config=config,
            selected_providers=["openai_codex"],
        )

    assert mock_codex_flow.await_count == 1
    prompter.confirm.assert_called_once()
    assert "openai_codex" not in config["providers"]


def test_verify_openai_codex_missing_credentials_fails():
    """verify_steps: openai_codex must fail when local OAuth state is missing."""
    import asyncio

    from cli.verify_steps import _validate_all_providers

    with patch("sci_fi_dashboard.openai_codex_oauth.load_credentials", return_value=None):
        results = asyncio.run(_validate_all_providers({"openai_codex": {}}))

    assert len(results) == 1
    name, ok, msg = results[0]
    assert name == "openai_codex"
    assert ok is False
    assert "credentials missing" in msg.lower()


def test_verify_openai_codex_credentials_present_passes():
    """verify_steps: openai_codex passes when OAuth credentials exist locally."""
    import asyncio

    from cli.verify_steps import _validate_all_providers

    fake_creds = MagicMock(access_token="tok", refresh_token="ref")
    with patch("sci_fi_dashboard.openai_codex_oauth.load_credentials", return_value=fake_creds):
        results = asyncio.run(_validate_all_providers({"openai_codex": {}}))

    assert len(results) == 1
    name, ok, msg = results[0]
    assert name == "openai_codex"
    assert ok is True
    assert "credentials present" in msg.lower()


def test_pick_model_fuzzy_reraises_wizard_cancelled_error(monkeypatch):
    """_pick_model_fuzzy must propagate WizardCancelledError from fuzzy UI path."""
    from cli.onboard import _pick_model_fuzzy
    from cli.wizard_prompter import WizardCancelledError

    class _FakePrompt:
        def execute(self):
            raise WizardCancelledError()

    class _FakeInquirer:
        @staticmethod
        def fuzzy(**kwargs):
            return _FakePrompt()

    monkeypatch.setitem(
        sys.modules,
        "InquirerPy",
        types.SimpleNamespace(inquirer=_FakeInquirer),
    )

    with pytest.raises(WizardCancelledError):
        _pick_model_fuzzy(
            role="code",
            desc="Code generation",
            flat=[{"value": "openai/gpt-4o", "label": "GPT-4o"}],
            prompter=MagicMock(),
        )


# ===========================================================================
# Interactive flow tests using force_interactive=True
# ===========================================================================


def test_interactive_provider_selection_writes_config(tmp_path, monkeypatch):
    """Interactive flow: selecting gemini provider → writes synapse.json."""
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    mock_acomp = _make_mock_acompletion()

    stub = MagicMock()
    stub.confirm.return_value = False  # no reconfigure
    stub.multiselect.side_effect = [["gemini"], []]  # providers, then channels
    stub.text.return_value = "fake-gemini-key"

    _fake_wa = {"enabled": True, "bridge_port": 5010, "dm_policy": "pairing"}
    with (
        patch("litellm.acompletion", mock_acomp),
        patch("cli.onboard._check_for_legacy_install", return_value=None),
        patch("cli.onboard.setup_whatsapp", return_value=_fake_wa),
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
        ),
    ):
        _run_interactive(prompter=stub)

    config_path = tmp_path / "synapse.json"
    assert config_path.exists(), "synapse.json should be written after interactive wizard"
    config = json.loads(config_path.read_text())
    assert "gemini" in config.get(
        "providers", {}
    ), f"Expected 'gemini' in providers, got: {config.get('providers')}"


def test_quickstart_whatsapp_opt_in_configures_once(tmp_path, monkeypatch):
    """Selecting optional WhatsApp must not fall through to generic channel setup."""
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    mock_acomp = _make_mock_acompletion()
    stub = MagicMock()
    stub.multiselect.return_value = ["gemini"]
    stub.text.return_value = "fake-gemini-key"
    stub.confirm.side_effect = (
        lambda message, default=True: message
        == "Configure WhatsApp now? You can skip this and use CLI chat."
    )
    fake_wa = {"enabled": True, "bridge_port": 5010, "dm_policy": "pairing"}

    with (
        patch("litellm.acompletion", mock_acomp),
        patch("cli.onboard._check_for_legacy_install", return_value=None),
        patch("cli.onboard.setup_whatsapp", return_value=fake_wa) as setup_wa,
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
        ),
    ):
        _run_interactive(prompter=stub)

    setup_wa.assert_called_once()
    config = json.loads((tmp_path / "synapse.json").read_text())
    assert config["channels"]["whatsapp"] == fake_wa


def test_interactive_aborts_on_no_providers(tmp_path, monkeypatch):
    """Interactive flow: selecting zero providers → wizard exits 0 without writing config."""
    import typer
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    stub = MagicMock()
    stub.confirm.return_value = False
    stub.multiselect.return_value = []  # empty provider selection

    with patch("cli.onboard._check_for_legacy_install", return_value=None):
        with pytest.raises(typer.Exit) as exc_info:
            _run_interactive(prompter=stub)
        assert exc_info.value.exit_code == 0, "Empty provider list should exit 0"

    assert not (
        tmp_path / "synapse.json"
    ).exists(), "synapse.json must NOT be written when no providers selected"


def test_interactive_migration_offer_on_legacy_present(tmp_path, monkeypatch):
    """ONB-08: Interactive flow shows migration confirm when _check_for_legacy_install returns a path."""
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    fake_legacy_dir = tmp_path / ".openclaw"
    fake_legacy_dir.mkdir()

    mock_acomp = _make_mock_acompletion()
    migration_confirm_called = []

    stub = MagicMock()

    def confirm_side_effect(message, default=True):
        if "igrate" in message or "Migrate" in message:
            migration_confirm_called.append(message)
            return False  # decline migration
        return False  # decline reconfigure

    stub.confirm.side_effect = confirm_side_effect
    stub.multiselect.side_effect = [["gemini"], []]
    stub.text.return_value = "fake-key"

    _fake_wa = {"enabled": True, "bridge_port": 5010, "dm_policy": "pairing"}
    with (
        patch("litellm.acompletion", mock_acomp),
        patch("cli.onboard._check_for_legacy_install", return_value=fake_legacy_dir),
        patch("cli.onboard.setup_whatsapp", return_value=_fake_wa),
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
        ),
    ):
        _run_interactive(prompter=stub)

    assert (
        migration_confirm_called
    ), "Migration confirm should be shown when _check_for_legacy_install returns a path"


# ===========================================================================
# ONB-11: --flow quickstart skips workspace dir prompt; token auto-generated
# ===========================================================================


def test_quickstart_flow_writes_config_with_gateway_token(tmp_path, monkeypatch):
    """ONB-11: --flow quickstart does not prompt for workspace dir; gateway.token is 48 hex chars."""
    from cli.onboard import _run_interactive

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    mock_acomp = _make_mock_acompletion()

    stub = MagicMock()
    stub.confirm.return_value = False
    stub.multiselect.return_value = ["gemini"]  # quickstart: no channel multiselect
    stub.text.return_value = "fake-gemini-key"

    # Use a valid 48-char hex token from the mocked gateway step
    fake_token = "ab" * 24  # 48 chars, all valid hex
    _fake_wa = {"enabled": True, "bridge_port": 5010, "dm_policy": "pairing"}
    with (
        patch("litellm.acompletion", mock_acomp),
        patch("cli.onboard._check_for_legacy_install", return_value=None),
        patch("cli.onboard.setup_whatsapp", return_value=_fake_wa),
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 8000, "bind": "loopback", "token": fake_token},
        ),
    ):
        _run_interactive(prompter=stub, flow="quickstart")

    config_path = tmp_path / "synapse.json"
    assert config_path.exists(), "synapse.json should be written"
    config = json.loads(config_path.read_text())

    token = config.get("gateway", {}).get("token", "")
    assert token, "gateway.token must be set"
    assert len(token) == 48, f"Expected 48-char hex token, got len={len(token)}: {token!r}"
    assert all(c in "0123456789abcdef" for c in token), f"Token not hex: {token!r}"


# ===========================================================================
# ONB-12: --flow advanced prompts for workspace dir
# ===========================================================================


def test_advanced_flow_prompts_for_workspace_dir(tmp_path, monkeypatch):
    """ONB-12: --flow advanced must ask for workspace dir (StubPrompter sees the question)."""
    from cli.onboard import _run_interactive
    from cli.wizard_prompter import StubPrompter

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    workspace_questions_asked = []

    class TrackingPrompter(StubPrompter):
        def text(self, message, default="", password=False):
            if "workspace" in message.lower() or "agent" in message.lower():
                workspace_questions_asked.append(message)
            # Return default for any text prompt
            return default or ""

    stub = TrackingPrompter(
        answers={
            "synapse.json already exists. Reconfigure?": False,
            "Migrate data to ~/.synapse/ now?": False,
        }
    )

    mock_acomp = _make_mock_acompletion()

    with (
        patch("litellm.acompletion", mock_acomp),
        patch("cli.onboard._check_for_legacy_install", return_value=None),
        patch("cli.onboard._wizard_daemon_install"),
        patch("cli.workspace_seeding.ensure_agent_workspace", return_value={}),
        # Provider multiselect: return gemini; channel multiselect: return []
        patch.object(TrackingPrompter, "multiselect", side_effect=[["gemini"], []]),
        # Password prompt for gemini key
        patch.object(TrackingPrompter, "text", wraps=stub.text),
        patch("cli.onboard._collect_provider_keys"),  # skip key collection for speed
        patch(
            "cli.gateway_steps.configure_gateway",
            return_value={"port": 8000, "bind": "loopback", "token": "a" * 48},
        ),
        patch("synapse_config.write_config"),
    ):
        try:
            _run_interactive(prompter=stub, flow="advanced")
        except SystemExit:
            pass
        except Exception:
            pass  # Some prompts may be unexpected — that's OK for this test

    # The workspace dir question should have been asked
    assert (
        workspace_questions_asked
    ), "Advanced flow must prompt for workspace directory, but no workspace question was seen"


# ===========================================================================
# ONB-13: --non-interactive without --accept-risk exits 1
# ===========================================================================


def test_non_interactive_without_accept_risk_exits_1(tmp_path, monkeypatch):
    """ONB-13: --non-interactive without --accept-risk must exit 1 with error containing 'accept-risk'."""
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    from synapse_cli import app

    result = runner.invoke(
        app,
        ["onboard", "--non-interactive"],  # no --accept-risk
        env={"SYNAPSE_HOME": str(tmp_path)},
    )
    assert (
        result.exit_code == 1
    ), f"Expected exit 1 without --accept-risk, got {result.exit_code}. Output: {result.output}"
    combined = result.output or ""
    assert (
        "accept-risk" in combined.lower()
    ), f"Expected 'accept-risk' in error message, got: {combined}"


# ===========================================================================
# ONB-14: --reset config backs up synapse.json and wizard completes fresh
# ===========================================================================


def test_reset_config_moves_synapse_json(tmp_path, monkeypatch):
    """ONB-14: --reset config moves synapse.json to a backup path before wizard runs."""
    from cli.onboard import _handle_reset

    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))

    # Create an existing synapse.json
    existing_config = tmp_path / "synapse.json"
    existing_config.write_text('{"providers": {}}', encoding="utf-8")
    assert existing_config.exists()

    # Run reset
    _handle_reset("config", tmp_path)

    # synapse.json should be gone from its original location
    assert not existing_config.exists(), "synapse.json should be moved away after --reset config"

    # A backup should exist in tmp_path/backups/
    backups_dir = tmp_path / "backups"
    assert backups_dir.exists(), "backups/ directory should be created"
    backup_files = list(backups_dir.rglob("synapse.json"))
    assert backup_files, "synapse.json should be present in backups dir"


def test_reset_full_scope_moves_all_contents(tmp_path, monkeypatch):
    """ONB-14: --reset full moves all data_root contents (except backups/) to backup dir."""
    from cli.onboard import _handle_reset

    # Create some files to reset
    (tmp_path / "synapse.json").write_text("{}", encoding="utf-8")
    (tmp_path / "credentials").mkdir()
    (tmp_path / "sessions").mkdir()

    _handle_reset("full", tmp_path)

    assert not (tmp_path / "synapse.json").exists()
    assert not (tmp_path / "credentials").exists()
    assert not (tmp_path / "sessions").exists()


def test_reset_invalid_scope_exits_1(tmp_path, monkeypatch):
    """ONB-14: --reset with invalid scope must exit 1."""
    import typer
    from cli.onboard import _handle_reset

    with pytest.raises(typer.Exit) as exc_info:
        _handle_reset("invalid-scope", tmp_path)

    assert exc_info.value.exit_code == 1


# ===========================================================================
# ONB-15: ensure_agent_workspace() seeding, idempotency, and completion detection
# ===========================================================================


def test_ensure_agent_workspace_seeds_all_7_files(tmp_path):
    """ONB-15: First call seeds all 7 template files and sets bootstrapSeededAt."""
    from cli.workspace_seeding import ensure_agent_workspace

    workspace = tmp_path / "workspace"
    state = ensure_agent_workspace(workspace, ensure_bootstrap_files=True)

    assert "bootstrapSeededAt" in state, "bootstrapSeededAt must be set after first seeding"
    assert state["bootstrapSeededAt"], "bootstrapSeededAt must be a non-empty string"

    # All 7 template files must exist
    expected_files = [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "TOOLS.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]
    for fname in expected_files:
        fpath = workspace / fname
        assert fpath.exists(), f"Template file {fname} should be seeded in workspace"


def test_ensure_agent_workspace_second_call_is_idempotent(tmp_path):
    """ONB-15: Second call with BOOTSTRAP.md present does NOT overwrite any files."""
    from cli.workspace_seeding import ensure_agent_workspace

    workspace = tmp_path / "workspace"

    # First call — seeds
    ensure_agent_workspace(workspace, ensure_bootstrap_files=True)

    # Overwrite SOUL.md with a sentinel value
    sentinel_content = "SENTINEL_DO_NOT_OVERWRITE"
    (workspace / "SOUL.md").write_text(sentinel_content, encoding="utf-8")

    # Second call — should NOT overwrite existing files
    ensure_agent_workspace(workspace, ensure_bootstrap_files=True)

    assert (workspace / "SOUL.md").read_text(
        encoding="utf-8"
    ) == sentinel_content, "Second call must not overwrite existing SOUL.md"


def test_ensure_agent_workspace_bootstrap_deleted_sets_completed_at(tmp_path):
    """ONB-15: Deleting BOOTSTRAP.md after seeding triggers setupCompletedAt on next call."""
    from cli.workspace_seeding import ensure_agent_workspace

    workspace = tmp_path / "workspace"

    # First call — seeds (sets bootstrapSeededAt)
    state1 = ensure_agent_workspace(workspace, ensure_bootstrap_files=True)
    assert "bootstrapSeededAt" in state1

    # Delete BOOTSTRAP.md (simulate agent completing bootstrap ritual)
    (workspace / "BOOTSTRAP.md").unlink()
    assert not (workspace / "BOOTSTRAP.md").exists()

    # Third call — should set setupCompletedAt
    state2 = ensure_agent_workspace(workspace, ensure_bootstrap_files=True)
    assert (
        "setupCompletedAt" in state2
    ), "setupCompletedAt must be set when BOOTSTRAP.md has been deleted"
    assert state2["setupCompletedAt"], "setupCompletedAt must be non-empty"


def test_ensure_agent_workspace_legacy_git_dir_sets_completed_at(tmp_path):
    """ONB-15: Workspace with .git dir gets setupCompletedAt immediately (no template writes)."""
    from cli.workspace_seeding import ensure_agent_workspace

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Simulate a legacy workspace (has .git)
    (workspace / ".git").mkdir()

    state = ensure_agent_workspace(workspace, ensure_bootstrap_files=True)

    assert (
        "setupCompletedAt" in state
    ), "setupCompletedAt must be set immediately for legacy (.git) workspace"
    # BOOTSTRAP.md must NOT be written
    assert not (
        workspace / "BOOTSTRAP.md"
    ).exists(), "BOOTSTRAP.md must NOT be created for a legacy (.git) workspace"


# ===========================================================================
# ONB-16: Ollama model validation
# ===========================================================================


def test_validate_ollama_model_not_found():
    """ONB-16: validate_ollama returns model_not_found when requested model is not downloaded."""
    from cli.provider_steps import validate_ollama

    version_resp = MagicMock()
    version_resp.status_code = 200
    version_resp.json.return_value = {"version": "0.5.0"}

    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {
        "models": [
            {"name": "mistral:latest"},
            {"name": "phi3:mini"},
        ]
    }

    with patch("httpx.get", side_effect=[version_resp, tags_resp]):
        result = validate_ollama(model="llama3.3")

    assert result.ok is True, "Ollama is reachable — ok should still be True"
    assert result.error == "model_not_found", f"Expected model_not_found, got: {result.error}"
    assert "llama3.3" in (result.detail or ""), "detail must mention the missing model name"
    assert "ollama pull llama3.3" in (result.detail or ""), "detail must include pull command"


def test_validate_ollama_model_found():
    """ONB-16: validate_ollama returns ok=True with no error when model is present."""
    from cli.provider_steps import validate_ollama

    version_resp = MagicMock()
    version_resp.status_code = 200
    version_resp.json.return_value = {"version": "0.5.0"}

    tags_resp = MagicMock()
    tags_resp.status_code = 200
    tags_resp.json.return_value = {
        "models": [
            {"name": "llama3.3:latest"},
            {"name": "mistral:latest"},
        ]
    }

    with patch("httpx.get", side_effect=[version_resp, tags_resp]):
        result = validate_ollama(model="llama3.3")

    assert result.ok is True
    assert result.error != "model_not_found", "Model is present — must not return model_not_found"
