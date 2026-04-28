import json
import time

import httpx
import pytest

from workspace.sci_fi_dashboard import openai_codex_oauth
from workspace.sci_fi_dashboard import openai_codex_provider as codex


class _FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, *, headers=None, json=None, content=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers or {},
                "json": json,
                "content": content,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


def _payload_from_call(call: dict) -> dict:
    if isinstance(call.get("json"), dict):
        return call["json"]
    raw = call.get("content")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return {}


@pytest.mark.parametrize(
    ("model_ref", "expected"),
    [
        ("openai_codex/gpt-5-codex", "gpt-5-codex"),
        ("openai-codex/gpt-5", "gpt-5-codex"),
        ("codex/gpt-5-mini", "codex-mini-latest"),
        ("openai_codex/codex-mini-latest", "codex-mini-latest"),
        ("openai_codex/gpt-5-codex-mini", "codex-mini-latest"),
        ("openai_codex/custom-future-model", "custom-future-model"),
    ],
)
def test_normalize_openai_codex_model_aliases(model_ref, expected):
    assert codex.normalize_openai_codex_model(model_ref) == expected


@pytest.mark.parametrize(
    ("model_ref", "expected"),
    [
        ("openai_codex/gpt-5-codex", True),
        ("openai-codex/gpt-5-codex", True),
        ("codex/gpt-5-codex", True),
        ("openai/gpt-5", False),
        (None, False),
    ],
)
def test_is_openai_codex_model(model_ref, expected):
    assert codex.is_openai_codex_model(model_ref) is expected


def test_parse_responses_payload_text_tool_calls_and_usage():
    payload = {
        "id": "resp_1",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "SYNAPSE"},
                    {"type": "output_text", "text": "_CODEX_OK"},
                ],
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_lookup_1",
                "name": "lookup",
                "arguments": "{\"q\":\"synapse\"}",
            },
        ],
        "usage": {
            "input_tokens": 3,
            "prompt_tokens": 30,
            "output_tokens": 4,
            "completion_tokens": 40,
        },
    }

    parsed = codex.parse_responses_payload(payload, requested_model="gpt-5-codex")

    assert parsed.text == "SYNAPSE_CODEX_OK"
    assert parsed.model == "gpt-5-codex"
    assert parsed.prompt_tokens == 3
    assert parsed.completion_tokens == 4
    assert parsed.total_tokens == 7
    assert parsed.finish_reason == "completed"
    assert parsed.tool_calls == [
        {
            "id": "call_lookup_1",
            "name": "lookup",
            "arguments": "{\"q\":\"synapse\"}",
        }
    ]


def test_build_responses_input_assistant_content_type_switch():
    messages = [{"role": "assistant", "content": "prior assistant reply"}]

    normal_items = codex.build_responses_input(messages)
    assert normal_items[0]["content"][0]["type"] == "input_text"

    stream_items = codex.build_responses_input(messages, assistant_content_type="output_text")
    assert stream_items[0]["content"][0]["type"] == "output_text"


@pytest.mark.asyncio
async def test_chat_completion_posts_responses_payload_shape(monkeypatch):
    creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )
    monkeypatch.setattr(codex.openai_codex_oauth, "load_credentials", lambda: creds)
    monkeypatch.setattr(codex.openai_codex_oauth, "refresh_access_token", lambda c: c)
    monkeypatch.setattr(codex.openai_codex_oauth, "save_credentials", lambda c: None)

    fake_http = _FakeAsyncClient(
        [
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok"}],
                        }
                    ],
                    "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                },
            )
        ]
    )
    client = codex.OpenAICodexClient(http_client=fake_http)

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Use lookup."},
        ],
        model="openai_codex/gpt-5",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Lookup a record",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            }
        ],
        temperature=0,
        top_p=0.5,
        max_tokens=256,
        stop=["END"],
    )

    assert result.text == "ok"
    assert result.model == "gpt-5-codex"
    assert result.prompt_tokens == 2
    assert result.completion_tokens == 3
    assert result.total_tokens == 5

    assert len(fake_http.calls) == 1
    call = fake_http.calls[0]
    payload = _payload_from_call(call)
    assert call["url"].endswith("/backend-api/codex/responses")
    assert call["headers"]["Authorization"] == "Bearer access-token"
    assert payload["model"] == "gpt-5-codex"
    assert payload["temperature"] == 0
    assert payload["top_p"] == 0.5
    assert payload["max_output_tokens"] == 256
    assert payload["stop"] == ["END"]

    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["role"] == "user"
    assert payload["input"][0]["content"][0]["type"] == "input_text"
    assert payload["input"][0]["content"][0]["text"] == "Be terse."
    assert payload["input"][1]["content"][0]["type"] == "input_text"
    assert payload["input"][1]["content"][0]["text"] == "Use lookup."

    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a record",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_chat_completion_gpt54_uses_stream_shape_and_parses_sse(monkeypatch):
    creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )
    monkeypatch.setattr(codex.openai_codex_oauth, "load_credentials", lambda: creds)
    monkeypatch.setattr(codex.openai_codex_oauth, "refresh_access_token", lambda c: c)
    monkeypatch.setattr(codex.openai_codex_oauth, "save_credentials", lambda c: None)

    sse = "\n".join(
        [
            "event: response.created",
            'data: {"type":"response.created","response":{"model":"gpt-5.4"}}',
            "event: response.output_text.delta",
            'data: {"type":"response.output_text.delta","delta":"hel"}',
            "event: response.output_text.delta",
            'data: {"type":"response.output_text.delta","delta":"lo"}',
            "event: response.completed",
            (
                'data: {"type":"response.completed","response":{"model":"gpt-5.4",'
                '"status":"completed","usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7}}}'
            ),
        ]
    )
    fake_http = _FakeAsyncClient([httpx.Response(200, text=sse)])
    client = codex.OpenAICodexClient(http_client=fake_http)

    result = await client.chat_completion(
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "Say hello"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "continue"},
        ],
        model="openai_codex/gpt-5.4",
        max_tokens=128,
    )

    assert result.text == "hello"
    assert result.model == "gpt-5.4"
    assert result.prompt_tokens == 3
    assert result.completion_tokens == 4
    assert result.total_tokens == 7
    assert result.finish_reason == "completed"

    payload = _payload_from_call(fake_http.calls[0])
    assert payload["model"] == "gpt-5.4"
    assert payload["stream"] is True
    assert payload["store"] is False
    assert payload["instructions"] == "Be terse."
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["text"] == {"format": {"type": "text"}, "verbosity": "medium"}
    assert payload["input"][2]["role"] == "assistant"
    assert payload["input"][2]["content"][0]["type"] == "output_text"
    assert payload["input"][2]["content"][0]["text"] == "hello"
    assert "max_output_tokens" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload


@pytest.mark.asyncio
async def test_chat_completion_refreshes_once_after_401_and_saves_token(monkeypatch):
    old_creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="old-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 3600,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )
    new_creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="new-token",
        refresh_token="refresh-token",
        expires_at=time.time() + 7200,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )
    refresh_calls = []
    saved = []

    monkeypatch.setattr(codex.openai_codex_oauth, "load_credentials", lambda: old_creds)
    monkeypatch.setattr(
        codex.openai_codex_oauth,
        "refresh_access_token",
        lambda creds: refresh_calls.append(creds) or new_creds,
    )
    monkeypatch.setattr(codex.openai_codex_oauth, "save_credentials", lambda creds: saved.append(creds))

    fake_http = _FakeAsyncClient(
        [
            httpx.Response(401, json={"error": {"message": "expired"}}),
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "retried-ok"}],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            ),
        ]
    )
    client = codex.OpenAICodexClient(http_client=fake_http)

    result = await client.chat_completion(
        messages=[{"role": "user", "content": "Ping"}],
        model="openai_codex/gpt-5-codex",
    )

    assert result.text == "retried-ok"
    assert refresh_calls == [old_creds]
    assert saved == [new_creds]
    assert len(fake_http.calls) == 2
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer old-token"
    assert fake_http.calls[1]["headers"]["Authorization"] == "Bearer new-token"


@pytest.mark.asyncio
async def test_chat_completion_uses_loaded_token_without_expiry_refresh(monkeypatch):
    creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="stored-token",
        refresh_token="refresh-token",
        expires_at=time.time() - 120,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )
    saved = []

    monkeypatch.setattr(codex.openai_codex_oauth, "load_credentials", lambda: creds)

    def _refresh_must_not_run(_creds):
        raise AssertionError("Codex token must refresh only after an auth error")

    monkeypatch.setattr(codex.openai_codex_oauth, "refresh_access_token", _refresh_must_not_run)
    monkeypatch.setattr(codex.openai_codex_oauth, "save_credentials", lambda c: saved.append(c))

    fake_http = _FakeAsyncClient(
        [
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok-with-stored-token"}],
                        }
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            )
        ]
    )
    client = codex.OpenAICodexClient(http_client=fake_http)

    result = await client.chat_completion(
        messages=[{"role": "user", "content": "Ping"}],
        model="openai_codex/gpt-5-codex",
    )

    assert result.text == "ok-with-stored-token"
    assert saved == []
    assert len(fake_http.calls) == 1
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer stored-token"


@pytest.mark.asyncio
async def test_chat_completion_raises_auth_error_when_refresh_fails_and_token_expired(monkeypatch):
    creds = openai_codex_oauth.OpenAICodexCredentials(
        access_token="expired-token",
        refresh_token="refresh-token",
        expires_at=time.time() - 30,
        email="user@example.com",
        account_id="acct-1",
        profile_name="user@example.com",
    )

    monkeypatch.setattr(codex.openai_codex_oauth, "load_credentials", lambda: creds)

    def _refresh_raises(_creds):
        raise RuntimeError("refresh endpoint down")

    monkeypatch.setattr(codex.openai_codex_oauth, "refresh_access_token", _refresh_raises)
    monkeypatch.setattr(codex.openai_codex_oauth, "save_credentials", lambda _c: None)

    fake_http = _FakeAsyncClient([httpx.Response(401, json={"error": {"message": "expired"}})])
    client = codex.OpenAICodexClient(http_client=fake_http)

    with pytest.raises(codex.AuthenticationError) as exc_info:
        await client.chat_completion(
            messages=[{"role": "user", "content": "Ping"}],
            model="openai_codex/gpt-5-codex",
        )

    assert "token refresh failed" in str(exc_info.value).lower()
    assert len(fake_http.calls) == 1
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer expired-token"
