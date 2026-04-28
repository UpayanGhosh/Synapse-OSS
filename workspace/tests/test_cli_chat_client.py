from unittest.mock import Mock

from cli.chat_client import ChatClient
from cli.chat_types import ChatLaunchOptions, ChatTurn


def test_send_turn_posts_expected_payload(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"reply": "hello", "model": "x"}
    calls = []
    monkeypatch.setattr("cli.chat_client.httpx.post", lambda url, **kwargs: calls.append((url, kwargs)) or response)
    monkeypatch.setattr("cli.chat_client.gateway_headers", lambda: {"x-api-key": "token"})

    client = ChatClient(base_url="http://127.0.0.1:8000")
    reply = client.send_turn(
        "hi",
        options=ChatLaunchOptions(target="the_creator", user_id="local", session_key="cli:test"),
        history=[ChatTurn(role="assistant", content="old")],
    )

    assert reply.reply == "hello"
    assert calls[0][0] == "http://127.0.0.1:8000/chat/the_creator"
    assert calls[0][1]["headers"] == {"x-api-key": "token"}
    assert calls[0][1]["json"]["message"] == "hi"
    assert calls[0][1]["json"]["user_id"] == "local"
    assert calls[0][1]["json"]["session_key"] == "cli:test"
    assert calls[0][1]["json"]["history"] == [{"role": "assistant", "content": "old"}]


def test_send_turn_raises_for_gateway_error(monkeypatch):
    response = Mock(status_code=500, text="bad")
    response.json.side_effect = ValueError("not json")
    monkeypatch.setattr("cli.chat_client.httpx.post", lambda *a, **k: response)
    monkeypatch.setattr("cli.chat_client.gateway_headers", lambda: {})

    client = ChatClient(base_url="http://127.0.0.1:8000")
    try:
        client.send_turn("hi", options=ChatLaunchOptions(), history=[])
    except RuntimeError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
