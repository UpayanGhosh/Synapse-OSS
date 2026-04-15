"""
test_llm_router_gaps.py — Gap-fill tests for llm_router.py

Covers areas NOT in test_llm_router.py:
  - LLMResult dataclass
  - ToolCall / LLMToolResult dataclasses
  - normalize_tool_schemas (Gemini, xAI, OpenAI provider fixes)
  - normalize_tool_calls (missing IDs, empty names, malformed JSON)
  - _attempt_json_repair
  - _inject_provider_keys (key injection, Bedrock, no overwrite)
  - resolve_env_var (${ENV_VAR} syntax)
  - classify_llm_error
  - execute_with_api_key_rotation (retryable, non-retryable, dedup keys)
  - _provider_from_model
  - build_router (ollama/ prefix rejection, fallback wiring)
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.llm_router import (
    AuthProfileFailureReason,
    LLMResult,
    LLMToolResult,
    ToolCall,
    _attempt_json_repair,
    _inject_provider_keys,
    _provider_from_model,
    build_router,
    classify_llm_error,
    execute_with_api_key_rotation,
    normalize_tool_calls,
    normalize_tool_schemas,
    resolve_env_var,
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestLLMResult:
    def test_construction(self):
        r = LLMResult(
            text="Hello",
            model="gemini/flash",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            finish_reason="stop",
        )
        assert r.text == "Hello"
        assert r.model == "gemini/flash"
        assert r.total_tokens == 30
        assert r.finish_reason == "stop"

    def test_defaults(self):
        r = LLMResult(text="", model="x", prompt_tokens=0, completion_tokens=0, total_tokens=0)
        assert r.finish_reason is None


class TestToolCall:
    def test_construction(self):
        tc = ToolCall(id="call_1", name="web_search", arguments='{"q": "test"}')
        assert tc.id == "call_1"
        assert tc.name == "web_search"
        assert tc.arguments == '{"q": "test"}'


class TestLLMToolResult:
    def test_construction(self):
        r = LLMToolResult(
            text="result",
            tool_calls=[],
            model="m",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        assert r.text == "result"
        assert r.tool_calls == []


# ---------------------------------------------------------------------------
# normalize_tool_schemas
# ---------------------------------------------------------------------------


class TestNormalizeToolSchemas:
    def test_empty_tools_returns_empty(self):
        assert normalize_tool_schemas([], "gemini") == []

    def test_gemini_strips_forbidden_keys(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "$schema": "http://json-schema.org/draft-07",
                        "$id": "test",
                        "examples": ["x"],
                        "default": "y",
                        "$defs": {},
                        "type": "object",
                        "properties": {"q": {"type": "string", "default": "hi"}},
                    },
                },
            }
        ]
        result = normalize_tool_schemas(tools, "gemini")
        params = result[0]["function"]["parameters"]
        assert "$schema" not in params
        assert "$id" not in params
        assert "examples" not in params
        assert "default" not in params
        assert "$defs" not in params
        # Nested default should also be stripped
        assert "default" not in params["properties"]["q"]

    def test_xai_strips_numeric_keys(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "count": {"type": "integer", "minimum": 0, "maximum": 100},
                            "name": {"type": "string", "minLength": 1, "maxLength": 50},
                        },
                    },
                },
            }
        ]
        result = normalize_tool_schemas(tools, "xai")
        count_props = result[0]["function"]["parameters"]["properties"]["count"]
        assert "minimum" not in count_props
        assert "maximum" not in count_props
        name_props = result[0]["function"]["parameters"]["properties"]["name"]
        assert "minLength" not in name_props
        assert "maxLength" not in name_props

    def test_openai_adds_additional_properties(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = normalize_tool_schemas(tools, "openai")
        params = result[0]["function"]["parameters"]
        assert params["additionalProperties"] is False

    def test_openai_preserves_existing_additional_properties(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                },
            }
        ]
        result = normalize_tool_schemas(tools, "openai")
        assert result[0]["function"]["parameters"]["additionalProperties"] is True

    def test_does_not_mutate_original(self):
        original = [
            {
                "type": "function",
                "function": {
                    "name": "test",
                    "parameters": {"$schema": "x", "type": "object"},
                },
            }
        ]
        normalize_tool_schemas(original, "gemini")
        assert "$schema" in original[0]["function"]["parameters"]


# ---------------------------------------------------------------------------
# normalize_tool_calls
# ---------------------------------------------------------------------------


class TestNormalizeToolCalls:
    def test_none_returns_empty(self):
        assert normalize_tool_calls(None) == []

    def test_empty_list(self):
        assert normalize_tool_calls([]) == []

    def test_normal_tool_call(self):
        mock_tc = MagicMock()
        mock_tc.id = "call_123"
        mock_tc.function.name = "search"
        mock_tc.function.arguments = '{"q": "test"}'

        result = normalize_tool_calls([mock_tc])
        assert len(result) == 1
        assert result[0].name == "search"
        assert result[0].id == "call_123"

    def test_missing_id_generates_one(self):
        mock_tc = MagicMock()
        mock_tc.id = None
        mock_tc.function.name = "test"
        mock_tc.function.arguments = "{}"

        result = normalize_tool_calls([mock_tc])
        assert result[0].id.startswith("call_")

    def test_empty_name_skipped(self):
        mock_tc = MagicMock()
        mock_tc.function.name = ""
        mock_tc.function.arguments = "{}"

        result = normalize_tool_calls([mock_tc])
        assert len(result) == 0

    def test_whitespace_name_stripped(self):
        mock_tc = MagicMock()
        mock_tc.id = "c1"
        mock_tc.function.name = "  search  "
        mock_tc.function.arguments = "{}"

        result = normalize_tool_calls([mock_tc])
        assert result[0].name == "search"

    def test_malformed_json_repaired(self):
        mock_tc = MagicMock()
        mock_tc.id = "c1"
        mock_tc.function.name = "test"
        mock_tc.function.arguments = '{"q": "hello'  # truncated

        result = normalize_tool_calls([mock_tc])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _attempt_json_repair
# ---------------------------------------------------------------------------


class TestAttemptJsonRepair:
    def test_valid_json_unchanged(self):
        result = _attempt_json_repair('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_missing_closing_brace(self):
        result = _attempt_json_repair('{"key": "value"')
        import json

        assert json.loads(result)  # should be valid JSON

    def test_multiple_missing_braces(self):
        result = _attempt_json_repair('{"a": {"b": "c"')
        import json

        assert json.loads(result)

    def test_unrepairable_returns_empty(self):
        result = _attempt_json_repair("not json at all [[[")
        assert result == "{}"


# ---------------------------------------------------------------------------
# _inject_provider_keys
# ---------------------------------------------------------------------------


class TestInjectProviderKeys:
    def test_injects_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        providers = {"gemini": {"api_key": "test-key-123"}}
        _inject_provider_keys(providers)
        assert os.environ.get("GEMINI_API_KEY") == "test-key-123"
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_does_not_overwrite_existing(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "existing-key")
        providers = {"gemini": {"api_key": "new-key"}}
        _inject_provider_keys(providers)
        assert os.environ["GEMINI_API_KEY"] == "existing-key"

    def test_string_provider_value(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        providers = {"openai": "sk-test-key"}
        _inject_provider_keys(providers)
        assert os.environ.get("OPENAI_API_KEY") == "sk-test-key"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_bedrock_credentials(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        providers = {
            "bedrock": {
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "secret",
                "aws_region_name": "us-east-1",
            }
        }
        _inject_provider_keys(providers)
        assert os.environ.get("AWS_ACCESS_KEY_ID") == "AKID"
        assert os.environ.get("AWS_SECRET_ACCESS_KEY") == "secret"
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AWS_REGION_NAME", raising=False)

    def test_empty_key_skipped(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        providers = {"gemini": {"api_key": ""}}
        _inject_provider_keys(providers)
        assert "GEMINI_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# resolve_env_var
# ---------------------------------------------------------------------------


class TestResolveEnvVar:
    def test_resolves_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "resolved-value")
        assert resolve_env_var("${MY_KEY}") == "resolved-value"

    def test_unset_env_var_returns_original(self, monkeypatch):
        monkeypatch.delenv("UNSET_VAR", raising=False)
        assert resolve_env_var("${UNSET_VAR}") == "${UNSET_VAR}"

    def test_non_env_var_syntax_unchanged(self):
        assert resolve_env_var("plain-string") == "plain-string"
        assert resolve_env_var("not-${partial") == "not-${partial"

    def test_empty_string_unchanged(self):
        assert resolve_env_var("") == ""


# ---------------------------------------------------------------------------
# classify_llm_error
# ---------------------------------------------------------------------------


class TestClassifyLlmError:
    def test_rate_limit(self):
        from litellm import RateLimitError

        err = RateLimitError(message="rate limited", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.RATE_LIMIT

    def test_auth_error(self):
        from litellm import AuthenticationError

        err = AuthenticationError(message="bad key", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.AUTH

    def test_bad_request(self):
        from litellm import BadRequestError

        err = BadRequestError(message="bad", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.FORMAT

    def test_timeout(self):
        from litellm import Timeout

        err = Timeout(message="timeout", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.TIMEOUT

    def test_service_unavailable(self):
        from litellm import ServiceUnavailableError

        err = ServiceUnavailableError(message="down", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.OVERLOADED

    def test_connection_error(self):
        from litellm import APIConnectionError

        err = APIConnectionError(message="conn failed", llm_provider="test", model="test")
        assert classify_llm_error(err) == AuthProfileFailureReason.TIMEOUT

    def test_unknown_error(self):
        assert classify_llm_error(ValueError("wat")) == AuthProfileFailureReason.UNKNOWN


# ---------------------------------------------------------------------------
# execute_with_api_key_rotation
# ---------------------------------------------------------------------------


class TestExecuteWithApiKeyRotation:
    @pytest.mark.asyncio
    async def test_first_key_succeeds(self):
        async def fn(key):
            return f"ok-{key}"

        result = await execute_with_api_key_rotation("test", ["key1", "key2"], fn)
        assert result == "ok-key1"

    @pytest.mark.asyncio
    async def test_rotates_on_rate_limit(self):
        from litellm import RateLimitError

        call_count = 0

        async def fn(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError(message="rate limited", llm_provider="test", model="test")
            return f"ok-{key}"

        result = await execute_with_api_key_rotation("test", ["key1", "key2"], fn)
        assert result == "ok-key2"

    @pytest.mark.asyncio
    async def test_raises_on_non_retryable(self):
        from litellm import AuthenticationError

        async def fn(key):
            raise AuthenticationError(message="bad key", llm_provider="test", model="test")

        with pytest.raises(AuthenticationError):
            await execute_with_api_key_rotation("test", ["key1", "key2"], fn)

    @pytest.mark.asyncio
    async def test_raises_when_all_keys_exhausted(self):
        from litellm import RateLimitError

        async def fn(key):
            raise RateLimitError(message="rate limited", llm_provider="test", model="test")

        with pytest.raises(RateLimitError):
            await execute_with_api_key_rotation("test", ["key1", "key2"], fn)

    @pytest.mark.asyncio
    async def test_no_keys_raises_value_error(self):
        async def fn(key):
            return "ok"

        with pytest.raises(ValueError, match="No API keys"):
            await execute_with_api_key_rotation("test", [], fn)

    @pytest.mark.asyncio
    async def test_deduplicates_keys(self):
        calls = []

        async def fn(key):
            calls.append(key)
            return "ok"

        await execute_with_api_key_rotation("test", ["key1", "key1", "key1"], fn)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_strips_empty_keys(self):
        with pytest.raises(ValueError, match="No API keys"):
            await execute_with_api_key_rotation("test", ["", None, "  "], lambda k: k)

    @pytest.mark.asyncio
    async def test_custom_retry_fn(self):
        call_count = 0

        async def fn(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("custom error")
            return "ok"

        # Custom retry function says always retry
        result = await execute_with_api_key_rotation(
            "test", ["k1", "k2"], fn, should_retry_fn=lambda exc, idx: True
        )
        assert result == "ok"


# ---------------------------------------------------------------------------
# _provider_from_model
# ---------------------------------------------------------------------------


class TestProviderFromModel:
    def test_gemini(self):
        assert _provider_from_model("gemini/gemini-2.0-flash") == "gemini"

    def test_ollama_chat(self):
        assert _provider_from_model("ollama_chat/mistral") == "ollama"

    def test_anthropic(self):
        assert _provider_from_model("anthropic/claude-3-5-sonnet") == "anthropic"

    def test_no_prefix(self):
        assert _provider_from_model("bare-model") is None


# ---------------------------------------------------------------------------
# build_router
# ---------------------------------------------------------------------------


class TestBuildRouter:
    def test_ollama_prefix_rejected(self):
        with pytest.raises(ValueError, match="must be ollama_chat/"):
            build_router(
                {"vault": {"model": "ollama/mistral"}},
                {},
            )

    def test_builds_with_valid_mappings(self):
        router = build_router(
            {"casual": {"model": "gemini/gemini-2.0-flash"}},
            {},
        )
        assert router is not None

    def test_fallback_wiring(self):
        router = build_router(
            {"casual": {"model": "gemini/flash", "fallback": "groq/llama"}},
            {},
        )
        assert router is not None

    def test_ollama_api_base_from_providers(self):
        router = build_router(
            {"vault": {"model": "ollama_chat/mistral"}},
            {"ollama": {"api_base": "http://custom:11434"}},
        )
        assert router is not None

    def test_copilot_model(self):
        with patch("sci_fi_dashboard.llm_router._copilot_litellm_params") as mock:
            mock.return_value = {
                "model": "openai/gpt-4o",
                "api_key": "x",
                "timeout": 60,
                "stream": False,
            }
            router = build_router(
                {"copilot": {"model": "github_copilot/gpt-4o"}},
                {},
            )
            assert router is not None

    def test_hosted_vllm_model(self):
        router = build_router(
            {"vllm": {"model": "hosted_vllm/my-model"}},
            {"vllm": {"api_base": "http://localhost:8000"}},
        )
        assert router is not None
