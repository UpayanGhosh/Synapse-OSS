"""
test_inference_loop.py — Tests for InferenceLoop retry and recovery logic.

Covers:
- Rate limited: verify retry with exponential backoff
- Context overflow: verify compact_fn called then retry succeeds
- Auth failed: verify profile rotation via AuthProfileStore
- Model not found: verify fallback model tried
- Max attempts respected (no infinite loops)
- Success on first attempt returns immediately
- Server error / timeout: single retry with backoff
- tool_loop_cb observability callback invoked correctly
"""

import asyncio
import sys
import time
import unittest.mock
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from litellm import (
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from sci_fi_dashboard.auth_profiles import AuthProfile, AuthProfileStore
from sci_fi_dashboard.llm_router import (
    AuthProfileFailureReason,
    InferenceLoop,
    LLMResult,
    SynapseLLMRouter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(text: str = "mock response", model: str = "test-model"):
    """Build a minimal mock litellm response object."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].finish_reason = "stop"
    resp.model = model
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 20
    usage.total_tokens = 30
    resp.usage = usage
    return resp


def _make_router_mock() -> SynapseLLMRouter:
    """Build a mock SynapseLLMRouter with _do_call as an AsyncMock."""
    router = MagicMock(spec=SynapseLLMRouter)
    router._do_call = AsyncMock()
    return router


def _make_auth_store(profiles: list[AuthProfile] | None = None) -> AuthProfileStore:
    """Build an AuthProfileStore with test profiles."""
    if profiles is None:
        profiles = [
            AuthProfile(
                id="p1",
                type="api_key",
                provider="openai",
                credentials={"api_key": "sk-1"},
            ),
            AuthProfile(
                id="p2",
                type="api_key",
                provider="openai",
                credentials={"api_key": "sk-2"},
            ),
        ]
    return AuthProfileStore(profiles)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """Tests for successful inference (no retries needed)."""

    async def test_success_on_first_attempt(self):
        """First attempt succeeds — returns immediately without retries."""
        router = _make_router_mock()
        router._do_call.return_value = _make_mock_response("hello")

        loop = InferenceLoop(router, max_attempts=3)
        result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert isinstance(result, LLMResult)
        assert result.text == "hello"
        assert result.model == "test-model"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30
        assert result.finish_reason == "stop"
        router._do_call.assert_called_once()

    async def test_result_metadata_populated(self):
        """LLMResult fields are correctly populated from response."""
        router = _make_router_mock()
        resp = _make_mock_response("detailed answer", model="gemini/flash")
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 50
        resp.usage.total_tokens = 150
        router._do_call.return_value = resp

        loop = InferenceLoop(router)
        result = await loop.run("analysis", [{"role": "user", "content": "q"}])

        assert result.text == "detailed answer"
        assert result.model == "gemini/flash"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150


# ---------------------------------------------------------------------------
# Rate limited — exponential backoff
# ---------------------------------------------------------------------------


class TestRateLimited:
    """Tests for rate limit retry with exponential backoff."""

    async def test_rate_limited_retries_with_backoff(self):
        """Rate limit error triggers retry with backoff, then succeeds."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [rate_err, _make_mock_response("ok")]

        loop = InferenceLoop(router, max_attempts=3)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"
        assert router._do_call.call_count == 2
        # Sleep was called with a positive delay (exponential backoff)
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        # First retry: base_delay = 2^1 = 2, jitter up to 1.0 → delay in [2.0, 3.0]
        assert 2.0 <= delay <= 3.0

    async def test_rate_limited_all_attempts_exhausted(self):
        """Rate limit on all attempts raises the error."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = rate_err

        loop = InferenceLoop(router, max_attempts=2)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError):
                await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert router._do_call.call_count == 2

    async def test_rate_limited_reports_failure_to_auth_store(self):
        """Rate limit error reports failure to AuthProfileStore if available."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [rate_err, _make_mock_response("ok")]

        store = _make_auth_store()
        loop = InferenceLoop(router, max_attempts=3, auth_store=store)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"


# ---------------------------------------------------------------------------
# Context overflow — compact_fn → retry
# ---------------------------------------------------------------------------


class TestContextOverflow:
    """Tests for context overflow detection and compaction."""

    async def test_context_overflow_calls_compact_fn(self):
        """Context overflow invokes compact_fn, then retries successfully."""
        router = _make_router_mock()
        overflow_err = BadRequestError(
            message="context_length_exceeded: too many tokens",
            llm_provider="openai",
            model="gpt-4o",
        )
        router._do_call.side_effect = [overflow_err, _make_mock_response("compacted")]

        compacted_messages = [{"role": "user", "content": "shorter"}]
        compact_fn = AsyncMock(return_value=compacted_messages)

        loop = InferenceLoop(router, max_attempts=3, compact_fn=compact_fn)
        result = await loop.run(
            "casual", [{"role": "user", "content": "very long message"}]
        )

        assert result.text == "compacted"
        compact_fn.assert_called_once()
        assert router._do_call.call_count == 2

    async def test_context_overflow_without_compact_fn_raises(self):
        """Context overflow with no compact_fn raises immediately."""
        router = _make_router_mock()
        overflow_err = BadRequestError(
            message="context_length_exceeded: too many tokens",
            llm_provider="openai",
            model="gpt-4o",
        )
        router._do_call.side_effect = overflow_err

        loop = InferenceLoop(router, max_attempts=3, compact_fn=None)

        with pytest.raises(BadRequestError):
            await loop.run("casual", [{"role": "user", "content": "long"}])

        # Only 1 attempt — no retry without compact_fn
        router._do_call.assert_called_once()

    async def test_context_overflow_detected_by_various_messages(self):
        """Context overflow detection works for different error message formats."""
        router = _make_router_mock()
        compact_fn = AsyncMock(
            return_value=[{"role": "user", "content": "short"}]
        )

        messages_to_test = [
            "maximum context length",
            "too many tokens in request",
            "token limit exceeded",
            "request too large for model",
            "content too large",
        ]

        for msg_text in messages_to_test:
            router._do_call.reset_mock()
            router._do_call.side_effect = [
                BadRequestError(
                    message=msg_text, llm_provider="openai", model="gpt-4o"
                ),
                _make_mock_response("ok"),
            ]
            compact_fn.reset_mock()

            loop = InferenceLoop(router, max_attempts=3, compact_fn=compact_fn)
            result = await loop.run("casual", [{"role": "user", "content": "hi"}])
            assert result.text == "ok", f"Failed for overflow message: {msg_text}"
            compact_fn.assert_called_once()


# ---------------------------------------------------------------------------
# Auth failed — profile rotation
# ---------------------------------------------------------------------------


class TestAuthFailed:
    """Tests for auth failure and profile rotation."""

    async def test_auth_failed_rotates_profile(self):
        """Auth error triggers profile rotation and retry."""
        router = _make_router_mock()
        auth_err = AuthenticationError(
            message="Invalid API key", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [auth_err, _make_mock_response("ok")]

        store = _make_auth_store()
        loop = InferenceLoop(router, max_attempts=3, auth_store=store)
        result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"
        assert router._do_call.call_count == 2

    async def test_auth_failed_without_store_raises(self):
        """Auth error without auth_store raises immediately."""
        router = _make_router_mock()
        auth_err = AuthenticationError(
            message="Invalid API key", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = auth_err

        loop = InferenceLoop(router, max_attempts=3, auth_store=None)

        with pytest.raises(AuthenticationError):
            await loop.run("casual", [{"role": "user", "content": "hi"}])

        router._do_call.assert_called_once()

    async def test_auth_failed_all_profiles_exhausted(self):
        """Auth error with all profiles in cooldown raises."""
        router = _make_router_mock()
        auth_err = AuthenticationError(
            message="Invalid API key", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = auth_err

        # Store with one profile — after first failure it goes to cooldown,
        # select_best returns None on next attempt
        store = _make_auth_store([
            AuthProfile(
                id="p1", type="api_key", provider="openai",
                credentials={"api_key": "sk-1"},
            ),
        ])

        loop = InferenceLoop(router, max_attempts=3, auth_store=store)

        with pytest.raises(AuthenticationError):
            await loop.run("casual", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Model not found — fallback model
# ---------------------------------------------------------------------------


class TestModelNotFound:
    """Tests for model-not-found handling with fallback."""

    async def test_model_not_found_tries_fallback(self):
        """Model not found triggers fallback role attempt."""
        router = _make_router_mock()
        not_found_err = BadRequestError(
            message="model_not_found: gpt-5 does not exist",
            llm_provider="openai",
            model="gpt-5",
        )
        fallback_response = _make_mock_response("fallback ok", model="gpt-4o")

        # First call (primary) raises model_not_found
        # Second call (fallback role) succeeds
        router._do_call.side_effect = [not_found_err, fallback_response]

        loop = InferenceLoop(router, max_attempts=3)
        result = await loop.run("code", [{"role": "user", "content": "hi"}])

        assert result.text == "fallback ok"
        assert router._do_call.call_count == 2
        # Second call should use fallback role
        second_call = router._do_call.call_args_list[1]
        assert second_call[0][0] == "code_fallback"

    async def test_model_not_found_fallback_also_fails(self):
        """When fallback also fails, raises the original error."""
        router = _make_router_mock()
        not_found_err = BadRequestError(
            message="model_not_found: gpt-5 does not exist",
            llm_provider="openai",
            model="gpt-5",
        )
        fallback_err = BadRequestError(
            message="fallback also failed", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [not_found_err, fallback_err]

        loop = InferenceLoop(router, max_attempts=3)

        with pytest.raises(BadRequestError, match="model_not_found"):
            await loop.run("code", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Server error / timeout — single retry
# ---------------------------------------------------------------------------


class TestServerError:
    """Tests for server error and timeout with single retry."""

    async def test_server_error_retries_once(self):
        """Server unavailable error retries once with backoff."""
        router = _make_router_mock()
        server_err = ServiceUnavailableError(
            message="server overloaded", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [server_err, _make_mock_response("ok")]

        loop = InferenceLoop(router, max_attempts=3)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"
        assert router._do_call.call_count == 2
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        # Server error delay: 2.0 + jitter[0, 1.0]
        assert 2.0 <= delay <= 3.0

    async def test_server_error_only_retries_once(self):
        """Server error retries only once — second failure raises."""
        router = _make_router_mock()
        server_err = ServiceUnavailableError(
            message="server overloaded", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = server_err

        loop = InferenceLoop(router, max_attempts=5)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ServiceUnavailableError):
                await loop.run("casual", [{"role": "user", "content": "hi"}])

        # Should try exactly 2 times (original + 1 retry)
        assert router._do_call.call_count == 2

    async def test_timeout_retries_once(self):
        """Timeout error retries once like server error."""
        router = _make_router_mock()
        timeout_err = Timeout(
            message="request timed out", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [timeout_err, _make_mock_response("ok")]

        loop = InferenceLoop(router, max_attempts=3)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"
        assert router._do_call.call_count == 2


# ---------------------------------------------------------------------------
# Max attempts — no infinite loops
# ---------------------------------------------------------------------------


class TestMaxAttempts:
    """Tests for max_attempts enforcement."""

    async def test_max_attempts_respected(self):
        """Loop does not exceed max_attempts."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = rate_err

        loop = InferenceLoop(router, max_attempts=3)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RateLimitError):
                await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert router._do_call.call_count == 3

    async def test_max_attempts_1_no_retry(self):
        """With max_attempts=1, no retries at all."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = rate_err

        loop = InferenceLoop(router, max_attempts=1)

        with pytest.raises(RateLimitError):
            await loop.run("casual", [{"role": "user", "content": "hi"}])

        router._do_call.assert_called_once()

    async def test_max_attempts_clamped_to_1(self):
        """max_attempts < 1 is clamped to 1."""
        router = _make_router_mock()
        router._do_call.return_value = _make_mock_response("ok")

        loop = InferenceLoop(router, max_attempts=0)
        assert loop._max_attempts == 1


# ---------------------------------------------------------------------------
# Non-retryable errors — immediate raise
# ---------------------------------------------------------------------------


class TestNonRetryable:
    """Tests for non-retryable errors (FORMAT without context cues, etc.)."""

    async def test_bad_request_not_context_overflow_raises(self):
        """BadRequestError without context overflow indicators raises immediately."""
        router = _make_router_mock()
        bad_req = BadRequestError(
            message="invalid prompt format", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = bad_req

        loop = InferenceLoop(router, max_attempts=3)

        with pytest.raises(BadRequestError, match="invalid prompt format"):
            await loop.run("casual", [{"role": "user", "content": "hi"}])

        router._do_call.assert_called_once()


# ---------------------------------------------------------------------------
# tool_loop_cb — observability callback
# ---------------------------------------------------------------------------


class TestToolLoopCallback:
    """Tests for the tool_loop_cb observability callback."""

    async def test_callback_invoked_on_success(self):
        """tool_loop_cb called with (attempt=0, error=None) on first success."""
        router = _make_router_mock()
        router._do_call.return_value = _make_mock_response("ok")

        cb = MagicMock()
        loop = InferenceLoop(router, max_attempts=3, tool_loop_cb=cb)
        await loop.run("casual", [{"role": "user", "content": "hi"}])

        cb.assert_called_once_with(0, None)

    async def test_callback_invoked_on_failure_and_success(self):
        """tool_loop_cb called for each attempt (failure + success)."""
        router = _make_router_mock()
        rate_err = RateLimitError(
            message="rate limited", llm_provider="openai", model="gpt-4o"
        )
        router._do_call.side_effect = [rate_err, _make_mock_response("ok")]

        cb = MagicMock()
        loop = InferenceLoop(router, max_attempts=3, tool_loop_cb=cb)

        with patch("sci_fi_dashboard.llm_router.asyncio.sleep", new_callable=AsyncMock):
            await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert cb.call_count == 2
        # First call: failure
        assert cb.call_args_list[0][0][0] == 0  # attempt 0
        assert cb.call_args_list[0][0][1] is rate_err  # the error
        # Second call: success
        assert cb.call_args_list[1][0][0] == 1  # attempt 1
        assert cb.call_args_list[1][0][1] is None  # no error

    async def test_no_callback_is_fine(self):
        """InferenceLoop works without tool_loop_cb."""
        router = _make_router_mock()
        router._do_call.return_value = _make_mock_response("ok")

        loop = InferenceLoop(router, max_attempts=3, tool_loop_cb=None)
        result = await loop.run("casual", [{"role": "user", "content": "hi"}])
        assert result.text == "ok"


# ---------------------------------------------------------------------------
# Auth store success reporting
# ---------------------------------------------------------------------------


class TestAuthStoreSuccessReporting:
    """Tests for auth store success reporting on successful calls."""

    async def test_reports_success_to_auth_store(self):
        """Successful call reports success to AuthProfileStore."""
        router = _make_router_mock()
        router._do_call.return_value = _make_mock_response("ok")

        store = _make_auth_store()
        loop = InferenceLoop(router, max_attempts=3, auth_store=store)

        result = await loop.run("casual", [{"role": "user", "content": "hi"}])

        assert result.text == "ok"
        # The best profile should have been updated
        best = store.select_best()
        # last_used should have been updated (non-zero)
        # Since we called report_success, error_count should be 0
        assert best.error_count == 0


# ---------------------------------------------------------------------------
# InferenceLoop — _is_context_overflow / _is_model_not_found (static methods)
# ---------------------------------------------------------------------------


class TestHeuristicDetectors:
    """Tests for the static heuristic detection methods."""

    @pytest.mark.parametrize(
        "msg",
        [
            "context_length_exceeded",
            "maximum context length is 128k tokens",
            "too many tokens in the request",
            "token limit exceeded",
            "request too large",
            "content too large for this model",
        ],
    )
    def test_is_context_overflow_positive(self, msg):
        """_is_context_overflow returns True for known overflow messages."""
        err = BadRequestError(message=msg, llm_provider="openai", model="m")
        assert InferenceLoop._is_context_overflow(err) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "invalid prompt format",
            "bad json payload",
            "missing required field",
        ],
    )
    def test_is_context_overflow_negative(self, msg):
        """_is_context_overflow returns False for non-overflow messages."""
        err = BadRequestError(message=msg, llm_provider="openai", model="m")
        assert InferenceLoop._is_context_overflow(err) is False

    @pytest.mark.parametrize(
        "msg",
        [
            "model_not_found",
            "The model gpt-5 does not exist",
            "no such model: gpt-5",
            "invalid model specified",
            "unknown model gpt-5",
        ],
    )
    def test_is_model_not_found_positive(self, msg):
        """_is_model_not_found returns True for known not-found messages."""
        err = BadRequestError(message=msg, llm_provider="openai", model="m")
        assert InferenceLoop._is_model_not_found(err) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "invalid prompt format",
            "context_length_exceeded",
            "rate limit exceeded",
        ],
    )
    def test_is_model_not_found_negative(self, msg):
        """_is_model_not_found returns False for non-model-not-found messages."""
        err = BadRequestError(message=msg, llm_provider="openai", model="m")
        assert InferenceLoop._is_model_not_found(err) is False


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructor:
    """Tests for InferenceLoop constructor."""

    def test_default_max_attempts(self):
        """Default max_attempts is 3."""
        router = _make_router_mock()
        loop = InferenceLoop(router)
        assert loop._max_attempts == 3

    def test_custom_max_attempts(self):
        """Custom max_attempts is stored."""
        router = _make_router_mock()
        loop = InferenceLoop(router, max_attempts=5)
        assert loop._max_attempts == 5

    def test_compact_fn_stored(self):
        """compact_fn is stored."""
        router = _make_router_mock()
        fn = AsyncMock()
        loop = InferenceLoop(router, compact_fn=fn)
        assert loop._compact_fn is fn

    def test_auth_store_stored(self):
        """auth_store is stored."""
        router = _make_router_mock()
        store = _make_auth_store()
        loop = InferenceLoop(router, auth_store=store)
        assert loop._auth_store is store
