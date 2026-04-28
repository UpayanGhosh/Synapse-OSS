import os
import sys

from typer.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapse_cli import app


def test_chat_command_passes_options(monkeypatch):
    captured = {}

    def fake_run(options):
        captured["options"] = options
        return 0

    monkeypatch.setattr("cli.chat_loop.run_cli_chat", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "chat",
            "--target",
            "the_creator",
            "--user-id",
            "tester",
            "--session",
            "spicy",
            "--port",
            "8123",
            "--message",
            "Wake up",
            "--no-auto-start",
            "--exit-after-message",
        ],
    )

    assert result.exit_code == 0
    opts = captured["options"]
    assert opts.target == "the_creator"
    assert opts.user_id == "tester"
    assert opts.session_type == "spicy"
    assert opts.port == 8123
    assert opts.auto_start_gateway is False
    assert opts.initial_message == "Wake up"
    assert opts.exit_after_initial is True


def test_chat_command_rejects_invalid_session_before_running(monkeypatch):
    called = False

    def fake_run(options):
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr("cli.chat_loop.run_cli_chat", fake_run)
    result = CliRunner().invoke(app, ["chat", "--session", "admin", "--no-auto-start"])

    assert result.exit_code != 0
    assert called is False
    assert "safe" in result.output
    assert "spicy" in result.output


def test_chat_command_propagates_runner_exit_code(monkeypatch):
    def fake_run(options):
        return 7

    monkeypatch.setattr("cli.chat_loop.run_cli_chat", fake_run)
    result = CliRunner().invoke(app, ["chat", "--no-auto-start"])

    assert result.exit_code == 7
