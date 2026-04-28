import os
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.chat_client import ChatClient, gateway_headers
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


def test_send_turn_defaults_user_to_creator(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"reply": "hello", "model": "x"}
    calls = []
    monkeypatch.setattr("cli.chat_client.httpx.post", lambda url, **kwargs: calls.append((url, kwargs)) or response)
    monkeypatch.setattr("cli.chat_client.gateway_headers", lambda: {})

    client = ChatClient(base_url="http://127.0.0.1:8000")
    client.send_turn("hi", options=ChatLaunchOptions(), history=[])

    assert calls[0][1]["json"]["user_id"] == "the_creator"


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


def test_gateway_headers_uses_env_token_first(monkeypatch):
    config_module = ModuleType("synapse_config")
    config_module.SynapseConfig = Mock()
    config_module.gateway_token = Mock(return_value="config-token")
    monkeypatch.setitem(sys.modules, "synapse_config", config_module)
    monkeypatch.setenv("SYNAPSE_GATEWAY_TOKEN", "env-token")

    assert gateway_headers() == {"x-api-key": "env-token"}
    config_module.gateway_token.assert_not_called()


def test_gateway_headers_falls_back_to_config_token(monkeypatch):
    config = object()
    config_module = ModuleType("synapse_config")
    config_module.SynapseConfig = Mock()
    config_module.SynapseConfig.load.return_value = config
    config_module.gateway_token = Mock(return_value="config-token")
    monkeypatch.setitem(sys.modules, "synapse_config", config_module)
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    assert gateway_headers() == {"x-api-key": "config-token"}
    config_module.gateway_token.assert_called_once_with(config)


def test_gateway_headers_returns_empty_when_config_fails(monkeypatch):
    config_module = ModuleType("synapse_config")
    config_module.SynapseConfig = Mock()
    config_module.SynapseConfig.load.side_effect = RuntimeError("missing config")
    config_module.gateway_token = Mock()
    monkeypatch.setitem(sys.modules, "synapse_config", config_module)
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    assert gateway_headers() == {}


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/the_creator",
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        }
    )


def test_server_api_key_accepts_env_token_when_config_missing(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import validate_api_key

    monkeypatch.setenv("SYNAPSE_GATEWAY_TOKEN", " env-token ")
    monkeypatch.setattr(SynapseConfig, "load", Mock(side_effect=RuntimeError("missing config")))

    validate_api_key(_request({"x-api-key": "env-token"}))


def test_server_api_key_prefers_env_token_over_config(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import validate_api_key

    config = Mock()
    config.gateway = {"token": "config-token"}
    monkeypatch.setenv("SYNAPSE_GATEWAY_TOKEN", "env-token")
    monkeypatch.setattr(SynapseConfig, "load", Mock(return_value=config))

    validate_api_key(_request({"x-api-key": "env-token"}))
    with pytest.raises(HTTPException) as exc_info:
        validate_api_key(_request({"x-api-key": "config-token"}))
    assert exc_info.value.status_code == 401
    SynapseConfig.load.assert_not_called()


def test_server_api_key_rejects_wrong_env_token_when_config_missing(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import validate_api_key

    monkeypatch.setenv("SYNAPSE_GATEWAY_TOKEN", "env-token")
    monkeypatch.setattr(SynapseConfig, "load", Mock(side_effect=RuntimeError("missing config")))

    with pytest.raises(HTTPException) as exc_info:
        validate_api_key(_request({"x-api-key": "wrong"}))
    assert exc_info.value.status_code == 401


def test_server_api_key_rejects_when_config_load_fails_without_env(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import validate_api_key

    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)
    monkeypatch.setattr(SynapseConfig, "load", Mock(side_effect=RuntimeError("missing config")))

    with pytest.raises(HTTPException) as exc_info:
        validate_api_key(_request({}))
    assert exc_info.value.status_code == 401


def test_server_api_key_open_when_no_token_configured(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import validate_api_key

    config = Mock()
    config.gateway = {}
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)
    monkeypatch.setattr(SynapseConfig, "load", Mock(return_value=config))

    validate_api_key(_request({}))


def test_require_gateway_auth_rejects_when_config_load_fails_without_env(monkeypatch):
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.middleware import _require_gateway_auth

    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)
    monkeypatch.setattr(SynapseConfig, "load", Mock(side_effect=RuntimeError("missing config")))

    with pytest.raises(HTTPException) as exc_info:
        _require_gateway_auth(_request({}))
    assert exc_info.value.status_code == 401
