import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.chat_loop import run_cli_chat
from cli.chat_types import ChatLaunchOptions


class FakeClient:
    def __init__(self):
        self.messages = []

    def probe_health(self):
        return True, "ok"

    def get_style_policy(self, session_key):
        return True, {
            "tone": "professional_precise",
            "length": "concise",
            "source": "session_override",
            "scope": "session",
            "session_key": session_key,
        }

    def send_turn(self, message, *, options, history):
        self.messages.append((message, options.resolved_session_type(), list(history)))
        return type("Reply", (), {"reply": f"reply:{message}", "model": "fake"})()


def test_cli_loop_sends_initial_message_and_exits(capsys):
    client = FakeClient()
    options = ChatLaunchOptions(initial_message="Wake up", exit_after_initial=True)
    run_cli_chat(options, client=client, gateway_manager=None, input_fn=input, output_fn=print)

    assert client.messages[0][0] == "Wake up"
    assert "reply:Wake up" in capsys.readouterr().out


def test_cli_loop_switches_session_mode(monkeypatch, capsys):
    client = FakeClient()
    inputs = iter(["/spicy", "hello", "/safe", "bye", "/quit"])
    run_cli_chat(
        ChatLaunchOptions(),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    assert client.messages[0][1] == "spicy"
    assert client.messages[1][1] == "safe"
    out = capsys.readouterr().out
    assert "SPICY" in out
    assert "SAFE" in out


def test_cli_loop_preserves_history_between_turns():
    client = FakeClient()
    inputs = iter(["hello", "again", "/quit"])
    run_cli_chat(
        ChatLaunchOptions(),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=lambda text: None,
    )

    second_history = client.messages[1][2]
    assert [turn.role for turn in second_history] == ["user", "assistant"]


def test_cli_loop_prompt_shows_current_mode():
    client = FakeClient()
    prompts = []
    inputs = iter(["/spicy", "hello", "/quit"])

    run_cli_chat(
        ChatLaunchOptions(),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: prompts.append(prompt) or next(inputs),
        output_fn=lambda text: None,
    )

    assert prompts[0] == "[SAFE] > "
    assert prompts[1] == "[SPICY] > "
    assert prompts[2] == "[SPICY] > "


def test_cli_loop_prints_startup_greeting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "providers": {"openai_codex": {}},
                "model_mappings": {"casual": {"model": "openai_codex/codex-mini-latest"}},
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient()
    inputs = iter(["/quit"])

    run_cli_chat(
        ChatLaunchOptions(),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert "Hi, I'm Synapse" in out
    assert "openai_codex/gpt-5.4" in out
    assert "Gateway:" in out


def test_cli_loop_help_status_and_model_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    (tmp_path / "synapse.json").write_text(
        json.dumps(
            {
                "providers": {"gemini": {"api_key": "fake"}},
                "model_mappings": {"casual": {"model": "gemini/gemini-2.0-flash"}},
                "gateway": {"port": 8123},
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient()
    inputs = iter(["/help", "/status", "/model", "/quit"])

    run_cli_chat(
        ChatLaunchOptions(port=8123),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert "/status" in out
    assert "/model" in out
    assert "Safe-chat model: gemini/gemini-2.0-flash" in out
    assert "Style: professional_precise, concise, source=session_override, scope=session" in out
    assert "Target: the_creator" in out
    assert f"Config: {tmp_path / 'synapse.json'}" in out
    assert "Gateway: reachable at http://127.0.0.1:8123 (ok)" in out


def test_cli_loop_error_hint_for_unknown_model(capsys):
    class UnknownModelClient(FakeClient):
        def send_turn(self, message, *, options, history):
            raise RuntimeError("Gateway chat failed: HTTP 500: unknown model: gpt-missing")

    inputs = iter(["hello", "/quit"])
    code = run_cli_chat(
        ChatLaunchOptions(),
        client=UnknownModelClient(),
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "unknown model" in out
    assert "Diagnostic hint" in out
    assert "/status" in out
    assert "synapse verify" in out


def test_cli_loop_error_hint_for_gateway_auth_mismatch(capsys):
    class AuthMismatchClient(FakeClient):
        def send_turn(self, message, *, options, history):
            raise RuntimeError(
                'Gateway authentication failed: HTTP 401: {"detail":"Invalid API key"}'
            )

    inputs = iter(["hello", "/quit"])
    code = run_cli_chat(
        ChatLaunchOptions(),
        client=AuthMismatchClient(),
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "gateway token mismatch" in out.lower()
    assert "not the Gemini/provider key" in out
    assert "SYNAPSE_GATEWAY_TOKEN" in out


def test_cli_loop_error_hint_for_zero_token_reply(capsys):
    class ZeroTokenClient(FakeClient):
        def send_turn(self, message, *, options, history):
            return type(
                "Reply",
                (),
                {
                    "reply": "",
                    "model": "gemini/gemini-2.0-flash",
                    "raw": {"usage": {"total_tokens": 0}},
                },
            )()

    inputs = iter(["hello", "/quit"])
    code = run_cli_chat(
        ChatLaunchOptions(),
        client=ZeroTokenClient(),
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Diagnostic hint" in out
    assert "zero tokens" in out.lower()
    assert "/status" in out


def test_cli_loop_error_hint_for_zero_token_footer(capsys):
    class ZeroFooterClient(FakeClient):
        def send_turn(self, message, *, options, history):
            return type(
                "Reply",
                (),
                {
                    "reply": "I encountered an error processing your request. Please try again.\n\n---\n**Tokens:** 0 in / 0 out / 0 total",
                    "model": "gemini/gemini-2.0-flash",
                    "raw": {"reply": "same footer only"},
                },
            )()

    inputs = iter(["hello", "/quit"])
    code = run_cli_chat(
        ChatLaunchOptions(),
        client=ZeroFooterClient(),
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Diagnostic hint" in out
    assert "zero tokens" in out.lower()
    assert "/status" in out


def test_cli_loop_reports_turn_error_and_continues(capsys):
    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def send_turn(self, message, *, options, history):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("gateway offline")
            return type("Reply", (), {"reply": f"reply:{message}", "model": "fake"})()

    client = FlakyClient()
    inputs = iter(["first", "second", "/quit"])

    code = run_cli_chat(
        ChatLaunchOptions(),
        client=client,
        gateway_manager=None,
        input_fn=lambda prompt: next(inputs),
        output_fn=print,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Error: gateway offline" in out
    assert "reply:second" in out


def test_cli_loop_degrades_unicode_when_console_encoding_rejects_it():
    class EmojiClient:
        def send_turn(self, message, *, options, history):
            return type("Reply", (), {"reply": "hi \U0001f604", "model": "fake"})()

    outputs = []

    def cp1252_output(text):
        text.encode("cp1252")
        outputs.append(text)

    code = run_cli_chat(
        ChatLaunchOptions(initial_message="hello", exit_after_initial=True),
        client=EmojiClient(),
        gateway_manager=None,
        input_fn=input,
        output_fn=cp1252_output,
    )

    assert code == 0
    assert "Hi, I'm Synapse" in outputs[0]
    assert outputs[-1] == "hi ?"


def test_cli_loop_returns_nonzero_when_initial_message_fails(capsys):
    class FailingClient:
        def send_turn(self, message, *, options, history):
            raise RuntimeError("gateway offline")

    code = run_cli_chat(
        ChatLaunchOptions(initial_message="Wake up", exit_after_initial=True),
        client=FailingClient(),
        gateway_manager=None,
        input_fn=input,
        output_fn=print,
    )

    assert code == 1
    assert "Error: gateway offline" in capsys.readouterr().out


def test_cli_loop_stops_gateway_manager_when_client_fails():
    class FakeGatewayManager:
        def __init__(self):
            self.ensured = False
            self.stopped = False

        def ensure_running(self):
            self.ensured = True

        def stop(self):
            self.stopped = True

    class FailingClient:
        def send_turn(self, message, *, options, history):
            raise RuntimeError("boom")

    manager = FakeGatewayManager()
    options = ChatLaunchOptions(initial_message="Wake up", exit_after_initial=True)

    code = run_cli_chat(
        options,
        client=FailingClient(),
        gateway_manager=manager,
        input_fn=input,
        output_fn=lambda text: None,
    )

    assert code == 1
    assert manager.ensured is True
    assert manager.stopped is True
