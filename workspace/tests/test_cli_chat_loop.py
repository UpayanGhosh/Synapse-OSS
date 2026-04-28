import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.chat_loop import run_cli_chat
from cli.chat_types import ChatLaunchOptions


class FakeClient:
    def __init__(self):
        self.messages = []

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

    try:
        run_cli_chat(
            options,
            client=FailingClient(),
            gateway_manager=manager,
            input_fn=input,
            output_fn=lambda text: None,
        )
    except RuntimeError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert manager.ensured is True
    assert manager.stopped is True
