import asyncio
import types
from unittest.mock import AsyncMock

import pytest

from sci_fi_dashboard import openai_codex_provider
from sci_fi_dashboard.llm_router import SynapseLLMRouter


def _build_router(model: str) -> SynapseLLMRouter:
    router = object.__new__(SynapseLLMRouter)
    router._config = types.SimpleNamespace(
        model_mappings={"code": {"model": model}},
        providers={},
    )
    router._router = types.SimpleNamespace(
        acompletion=AsyncMock(
            side_effect=AssertionError(
                "litellm.Router.acompletion must be bypassed for OpenAI Codex models"
            )
        )
    )
    router._uses_copilot = False
    router._copilot_refresh_lock = asyncio.Lock()
    router._antigravity_roles = set()
    router._claude_cli_roles = set()
    return router


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_with_metadata_openai_codex_bypasses_litellm(monkeypatch):
    router = _build_router("openai_codex/gpt-5-codex")
    messages = [{"role": "user", "content": "Ship the fix."}]

    codex_response = openai_codex_provider.OpenAICodexResponse(
        text="done",
        tool_calls=[],
        model="gpt-5-codex",
        prompt_tokens=31,
        completion_tokens=9,
        total_tokens=40,
        finish_reason="completed",
    )
    fake_client = types.SimpleNamespace(chat_completion=AsyncMock(return_value=codex_response))
    get_default_client = AsyncMock(return_value=fake_client)

    monkeypatch.setattr(
        "sci_fi_dashboard.openai_codex_provider.get_default_client",
        get_default_client,
    )
    monkeypatch.setattr("sci_fi_dashboard.llm_router._write_session", lambda **_kwargs: None)

    result = await router.call_with_metadata("code", messages, temperature=0.2, max_tokens=512)

    get_default_client.assert_awaited_once()
    fake_client.chat_completion.assert_awaited_once()
    kwargs = fake_client.chat_completion.await_args.kwargs
    assert kwargs["model"] == "openai_codex/gpt-5-codex"
    assert kwargs["messages"] == messages
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 512

    assert result.model == "gpt-5-codex"
    assert result.prompt_tokens == 31
    assert result.completion_tokens == 9
    assert result.total_tokens == 40
    assert result.finish_reason == "completed"
    router._router.acompletion.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_with_tools_openai_codex_hyphen_dispatch_and_fields(monkeypatch):
    router = _build_router("openai-codex/gpt-5")
    messages = [{"role": "user", "content": "Lookup issue 42."}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_issue",
                "description": "Find issue metadata",
                "parameters": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
        }
    ]
    codex_response = openai_codex_provider.OpenAICodexResponse(
        text="",
        tool_calls=[
            {"id": "call_lookup_42", "name": "lookup_issue", "arguments": '{"id":"42"}'}
        ],
        model="gpt-5-codex",
        prompt_tokens=12,
        completion_tokens=4,
        total_tokens=16,
        finish_reason="completed",
    )
    fake_client = types.SimpleNamespace(chat_completion=AsyncMock(return_value=codex_response))
    get_default_client = AsyncMock(return_value=fake_client)

    monkeypatch.setattr(
        "sci_fi_dashboard.openai_codex_provider.get_default_client",
        get_default_client,
    )
    monkeypatch.setattr("sci_fi_dashboard.llm_router._write_session", lambda **_kwargs: None)

    result = await router.call_with_tools(
        "code",
        messages,
        tools=tools,
        temperature=0.0,
        max_tokens=256,
        tool_choice="auto",
    )

    get_default_client.assert_awaited_once()
    fake_client.chat_completion.assert_awaited_once()
    kwargs = fake_client.chat_completion.await_args.kwargs
    assert kwargs["model"] == "openai-codex/gpt-5"
    assert kwargs["messages"] == messages
    assert kwargs["tools"] == tools
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 256

    assert result.model == "gpt-5-codex"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4
    assert result.total_tokens == 16
    assert result.finish_reason == "completed"

    assert len(result.tool_calls) == 1
    tool_call = result.tool_calls[0]
    assert tool_call.id == "call_lookup_42"
    assert tool_call.name == "lookup_issue"
    assert tool_call.arguments == '{"id":"42"}'
    router._router.acompletion.assert_not_awaited()
