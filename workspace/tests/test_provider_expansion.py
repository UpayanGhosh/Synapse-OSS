"""
test_provider_expansion.py — Phase 6 Provider Expansion Regression Tests

Covers all four PROV requirements:
  - PROV-01: _KEY_MAP mirrors in sync between llm_router.py and provider_steps.py
  - PROV-02: Budget enforcement raises BudgetExceededError before LLM call
  - PROV-03: BudgetExceededError triggers fallback; propagates cleanly when no fallback
  - PROV-04: DeepSeek present in all relevant provider maps

Run:
    cd workspace && pytest tests/test_provider_expansion.py -v

No real API calls are made — all LLM interactions are mocked.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cli.provider_steps import (
    _KEY_MAP as ps_KEY_MAP,  # noqa: N811
)
from cli.provider_steps import (
    PROVIDER_GROUPS,
    VALIDATION_MODELS,
)
from sci_fi_dashboard.llm_router import (
    _KEY_MAP as router_KEY_MAP,  # noqa: N811
)
from sci_fi_dashboard.llm_router import (
    BudgetExceededError,
    get_provider_spend,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keys only in provider_steps._KEY_MAP — intentional divergences documented in 06-02-SUMMARY.md
_PS_ONLY_KEYS = {"qianfan"}

# Keys only in llm_router._KEY_MAP — none expected right now
_ROUTER_ONLY_KEYS: set[str] = set()


def _flat_provider_keys_from_groups() -> set[str]:
    """Extract all provider keys from PROVIDER_GROUPS into a flat set."""
    keys: set[str] = set()
    for group in PROVIDER_GROUPS:
        for provider in group.get("providers", []):
            keys.add(provider["key"])
    return keys


# ---------------------------------------------------------------------------
# TestProviderMaps — PROV-01 and PROV-04
# ---------------------------------------------------------------------------


class TestProviderMaps:
    @pytest.mark.unit
    def test_key_maps_in_sync(self):
        """
        PROV-01: _KEY_MAP in llm_router.py and provider_steps.py must stay in sync.

        The only intentional divergence is qianfan (provider_steps only — Baidu
        uses a dual-key scheme that doesn't map cleanly to llm_router's single
        env var contract).

        For every shared key, the env var value must be identical.
        """
        router_keys = set(router_KEY_MAP.keys())
        ps_keys = set(ps_KEY_MAP.keys())

        # Verify known divergences are exactly as expected
        actual_ps_only = ps_keys - router_keys
        actual_router_only = router_keys - ps_keys

        assert actual_ps_only == _PS_ONLY_KEYS, (
            f"provider_steps._KEY_MAP has unexpected extra keys: {actual_ps_only - _PS_ONLY_KEYS}. "
            f"If you added a new provider to provider_steps but not llm_router, add it to "
            f"llm_router._KEY_MAP too, or update _PS_ONLY_KEYS in this test."
        )
        assert actual_router_only == _ROUTER_ONLY_KEYS, (
            f"llm_router._KEY_MAP has unexpected extra keys: {actual_router_only - _ROUTER_ONLY_KEYS}. "
            f"If you added a provider to llm_router but not provider_steps, add it to "
            f"provider_steps._KEY_MAP too, or update _ROUTER_ONLY_KEYS in this test."
        )

        # Shared keys must map to identical env var names
        shared_keys = router_keys & ps_keys
        mismatches = {}
        for key in shared_keys:
            if router_KEY_MAP[key] != ps_KEY_MAP[key]:
                mismatches[key] = {
                    "router": router_KEY_MAP[key],
                    "provider_steps": ps_KEY_MAP[key],
                }
        assert (
            not mismatches
        ), f"Env var name mismatch between _KEY_MAPs for providers: {mismatches}"

    @pytest.mark.unit
    def test_deepseek_in_llm_router_key_map(self):
        """PROV-04: DeepSeek must be present in llm_router._KEY_MAP with the correct env var."""
        assert (
            "deepseek" in router_KEY_MAP
        ), "deepseek is missing from llm_router._KEY_MAP — Phase 6 regression"
        assert (
            router_KEY_MAP["deepseek"] == "DEEPSEEK_API_KEY"
        ), f"Expected DEEPSEEK_API_KEY, got {router_KEY_MAP['deepseek']}"

    @pytest.mark.unit
    def test_deepseek_in_provider_steps(self):
        """PROV-04: DeepSeek must appear in provider_steps._KEY_MAP, VALIDATION_MODELS, and PROVIDER_GROUPS."""
        # _KEY_MAP presence
        assert "deepseek" in ps_KEY_MAP, "deepseek missing from provider_steps._KEY_MAP"

        # VALIDATION_MODELS presence and correct model string
        assert "deepseek" in VALIDATION_MODELS, "deepseek missing from VALIDATION_MODELS"
        assert (
            VALIDATION_MODELS["deepseek"] == "deepseek/deepseek-chat"
        ), f"Expected deepseek/deepseek-chat, got {VALIDATION_MODELS['deepseek']}"

        # PROVIDER_GROUPS (flat) presence
        flat_keys = _flat_provider_keys_from_groups()
        assert (
            "deepseek" in flat_keys
        ), "deepseek missing from PROVIDER_GROUPS — won't appear in onboarding wizard"

    @pytest.mark.unit
    def test_provider_groups_all_have_validation_models(self):
        """
        PROV-04 / guard: Every provider in PROVIDER_GROUPS that requires an API key
        must have a VALIDATION_MODELS entry.

        Exceptions: ollama (uses validate_ollama()), github_copilot (OAuth device flow),
        vllm (httpx health check) — none of these do litellm validation pings.
        """
        _NO_VALIDATION_NEEDED = {"ollama", "github_copilot", "openai_codex", "vllm"}  # noqa: N806

        missing = []
        for group in PROVIDER_GROUPS:
            for provider in group.get("providers", []):
                key = provider["key"]
                if key not in _NO_VALIDATION_NEEDED and key not in VALIDATION_MODELS:
                    missing.append(key)

        assert not missing, (
            f"Providers in PROVIDER_GROUPS without a VALIDATION_MODELS entry: {missing}. "
            f"Add the cheapest/fastest model string for each provider so the wizard can "
            f"validate API keys."
        )


class TestProviderExpansion:
    @pytest.mark.unit
    def test_openai_codex_subscription_provider_is_in_onboarding_group(self):
        """openai_codex should be selectable in onboarding and should not use API-key maps."""
        providers = _flat_provider_keys_from_groups()
        assert (
            "openai_codex" in providers
        ), "openai_codex must be present in PROVIDER_GROUPS for onboarding selection"
        assert (
            "openai_codex" not in ps_KEY_MAP
        ), "openai_codex is OAuth/subscription-backed and must not be in provider_steps._KEY_MAP"
        assert (
            "openai_codex" not in router_KEY_MAP
        ), "openai_codex is OAuth/subscription-backed and must not be in llm_router._KEY_MAP"


# ---------------------------------------------------------------------------
# TestBudgetFallback — PROV-02 and PROV-03
# ---------------------------------------------------------------------------


class TestBudgetFallback:
    @pytest.mark.unit
    def test_budget_exceeded_error_importable(self):
        """PROV-02/03: BudgetExceededError must be importable and be an Exception subclass."""
        assert issubclass(
            BudgetExceededError, Exception
        ), "BudgetExceededError is not a subclass of Exception"

    @pytest.mark.unit
    async def test_budget_exceeded_triggers_fallback(self):
        """
        PROV-03: When _router.acompletion raises BudgetExceededError and a fallback
        is configured, _do_call() must retry with the fallback role.

        The fallback role name is f"{role}_fallback" — this is the litellm Router
        convention used in build_router() to wire fallback model entries.
        """
        from sci_fi_dashboard.llm_router import SynapseLLMRouter

        # Build a minimal mocked router instance without real initialization
        router = object.__new__(SynapseLLMRouter)

        # Config: casual role with a fallback configured
        mock_config = MagicMock()
        mock_config.model_mappings = {
            "casual": {
                "model": "openai/gpt-4o-mini",
                "fallback": "groq/llama-3.3-70b-versatile",
            }
        }
        mock_config.providers = {}  # no budget_usd → skip pre-call check
        router._config = mock_config

        # Track calls to acompletion
        call_log: list[str] = []

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "groq/llama-3.3-70b-versatile"

        async def fake_acompletion(model: str, **kwargs):
            call_log.append(model)
            if model == "casual":
                raise BudgetExceededError(2.0, 0.001, "budget exceeded")
            return mock_response

        mock_router = MagicMock()
        mock_router.acompletion = fake_acompletion
        router._router = mock_router
        router._uses_copilot = False

        result = await router._do_call("casual", [{"role": "user", "content": "hi"}])

        # The fallback role must have been called
        assert (
            "casual_fallback" in call_log
        ), f"Expected fallback role 'casual_fallback' to be called, got: {call_log}"
        assert result is mock_response

    @pytest.mark.unit
    async def test_budget_exceeded_no_fallback_raises(self):
        """
        PROV-03: When _router.acompletion raises BudgetExceededError and NO fallback
        is configured, _do_call() must re-raise BudgetExceededError (not swallow it).
        """
        from sci_fi_dashboard.llm_router import SynapseLLMRouter

        router = object.__new__(SynapseLLMRouter)

        mock_config = MagicMock()
        mock_config.model_mappings = {
            "casual": {
                "model": "openai/gpt-4o-mini",
                # no 'fallback' key
            }
        }
        mock_config.providers = {}
        router._config = mock_config

        async def fake_acompletion(model: str, **kwargs):
            raise BudgetExceededError(2.0, 0.001, "budget exceeded")

        mock_router = MagicMock()
        mock_router.acompletion = fake_acompletion
        router._router = mock_router
        router._uses_copilot = False

        with pytest.raises(BudgetExceededError):
            await router._do_call("casual", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# TestBudgetEnforcement — PROV-02
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    @pytest.mark.unit
    def test_get_provider_spend_returns_dict(self):
        """
        PROV-02: get_provider_spend() must return {"total_tokens": 0, "call_count": 0}
        when the provider has no recorded sessions (graceful fallback on empty DB / missing table).
        """
        # Use a provider that will never exist in any test DB
        result = get_provider_spend("nonexistent_provider_xyz", "daily")
        assert isinstance(result, dict), "get_provider_spend() must return a dict"
        assert "total_tokens" in result, "dict must have 'total_tokens' key"
        assert "call_count" in result, "dict must have 'call_count' key"
        assert result["total_tokens"] == 0
        assert result["call_count"] == 0

    @pytest.mark.unit
    def test_get_provider_spend_accepts_all_durations(self):
        """
        PROV-02: get_provider_spend() must accept 'daily', 'weekly', 'monthly' without error.
        Unknown durations default to monthly window (non-fatal).
        """
        for duration in ("daily", "weekly", "monthly"):
            result = get_provider_spend("openai", duration)
            assert isinstance(
                result, dict
            ), f"get_provider_spend returned non-dict for duration={duration}"
            assert "total_tokens" in result
            assert "call_count" in result

    @pytest.mark.unit
    async def test_pre_call_budget_check_raises_when_exceeded(self):
        """
        PROV-02: When a provider has budget_usd configured and the pre-call spend
        check shows the budget is exceeded, _do_call() must raise BudgetExceededError
        BEFORE calling the LLM (no acompletion call should be made).
        """
        from sci_fi_dashboard.llm_router import SynapseLLMRouter

        router = object.__new__(SynapseLLMRouter)

        mock_config = MagicMock()
        mock_config.model_mappings = {
            "casual": {
                "model": "openai/gpt-4o-mini",
                # no fallback — budget exceeded should propagate
            }
        }
        # Budget: $0.001 cap for openai, monthly
        mock_config.providers = {
            "openai": {
                "budget_usd": 0.001,
                "budget_duration": "monthly",
            }
        }
        router._config = mock_config

        # Track whether acompletion was called
        acompletion_called = False

        async def fake_acompletion(model: str, **kwargs):
            nonlocal acompletion_called
            acompletion_called = True
            return MagicMock()

        mock_router = MagicMock()
        mock_router.acompletion = fake_acompletion
        router._router = mock_router
        router._uses_copilot = False

        # Patch get_provider_spend to simulate 2M tokens spent (~$2 >> $0.001 cap)
        with (
            patch(
                "sci_fi_dashboard.llm_router.get_provider_spend",
                return_value={"total_tokens": 2_000_000, "call_count": 100},
            ),
            pytest.raises(BudgetExceededError),
        ):
            await router._do_call("casual", [{"role": "user", "content": "hi"}])

        assert not acompletion_called, (
            "acompletion was called despite budget being exceeded — "
            "pre-call check must raise BEFORE the LLM call"
        )
