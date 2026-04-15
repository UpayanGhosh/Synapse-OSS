"""
test_auth_profiles.py — Tests for AuthProfileStore, TokenRefreshManager,
ProviderFallbackChain, and related auth profile machinery.

Covers:
- select_best picks lowest-cooldown, lowest-error profile (round-robin LRU)
- report_failure sets cooldown window per failure reason
- report_success resets error count and updates last_used
- Model-scoped cooldown doesn't affect other models
- Round-robin among equal-priority profiles
- Empty store returns None
- Expired cooldown makes profile eligible again
- ProviderFallbackChain returns correct next provider
- TokenRefreshManager proactive refresh logic
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Ensure workspace/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.auth_profiles import (
    AuthProfile,
    AuthProfileStore,
    ProviderFallbackChain,
    TokenRefreshManager,
)
from sci_fi_dashboard.llm_router import AuthProfileFailureReason

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    profile_id: str = "p1",
    provider: str = "openai",
    profile_type: str = "api_key",
    **kwargs,
) -> AuthProfile:
    """Build a minimal AuthProfile for testing."""
    return AuthProfile(
        id=profile_id,
        type=profile_type,
        provider=provider,
        credentials=kwargs.pop("credentials", {"api_key": f"sk-test-{profile_id}"}),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# AuthProfileStore — select_best
# ---------------------------------------------------------------------------


class TestSelectBest:
    """Tests for AuthProfileStore.select_best()."""

    def test_empty_store_returns_none(self):
        """Empty store returns None."""
        store = AuthProfileStore([])
        assert store.select_best() is None

    def test_single_profile_returned(self):
        """Single eligible profile is returned."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])
        assert store.select_best() is p

    def test_picks_lowest_error_count(self):
        """Among eligible profiles, pick lowest error_count."""
        p1 = _make_profile("p1", error_count=3)
        p2 = _make_profile("p2", error_count=1)
        p3 = _make_profile("p3", error_count=5)
        store = AuthProfileStore([p1, p2, p3])
        best = store.select_best()
        assert best is p2

    def test_round_robin_among_equal_priority(self):
        """Ties in error_count broken by lowest last_used (LRU round-robin)."""
        p1 = _make_profile("p1", error_count=0, last_used=100.0)
        p2 = _make_profile("p2", error_count=0, last_used=50.0)
        p3 = _make_profile("p3", error_count=0, last_used=200.0)
        store = AuthProfileStore([p1, p2, p3])
        best = store.select_best()
        # p2 has lowest last_used → selected first
        assert best is p2

    def test_skips_profiles_in_global_cooldown(self):
        """Profiles in global cooldown are not eligible."""
        p1 = _make_profile("p1", cooldown_until=time.monotonic() + 9999)
        p2 = _make_profile("p2")
        store = AuthProfileStore([p1, p2])
        best = store.select_best()
        assert best is p2

    def test_skips_profiles_in_model_cooldown(self):
        """Profiles in model-scoped cooldown are skipped for that model."""
        p1 = _make_profile("p1")
        p1._model_cooldowns["gpt-4o"] = time.monotonic() + 9999
        p2 = _make_profile("p2")
        store = AuthProfileStore([p1, p2])

        # For gpt-4o, p1 is in cooldown
        best = store.select_best(model="gpt-4o")
        assert best is p2

    def test_model_scoped_cooldown_does_not_affect_other_models(self):
        """A cooldown on model A doesn't affect eligibility for model B."""
        p1 = _make_profile("p1")
        p1._model_cooldowns["gpt-4o"] = time.monotonic() + 9999
        store = AuthProfileStore([p1])

        # p1 is in cooldown for gpt-4o but NOT for gpt-3.5-turbo
        assert store.select_best(model="gpt-4o") is None
        assert store.select_best(model="gpt-3.5-turbo") is p1

    def test_all_in_cooldown_returns_none(self):
        """When all profiles are in cooldown, returns None."""
        p1 = _make_profile("p1", cooldown_until=time.monotonic() + 9999)
        p2 = _make_profile("p2", cooldown_until=time.monotonic() + 9999)
        store = AuthProfileStore([p1, p2])
        assert store.select_best() is None

    def test_expired_cooldown_makes_profile_eligible(self):
        """A profile whose cooldown has expired is eligible again."""
        p1 = _make_profile("p1", cooldown_until=time.monotonic() - 1.0)
        store = AuthProfileStore([p1])
        assert store.select_best() is p1

    def test_model_scoped_error_count_used_for_selection(self):
        """When model is specified, per-model failure_counts drive selection."""
        p1 = _make_profile("p1", error_count=0)
        p1.failure_counts["gpt-4o"] = 5

        p2 = _make_profile("p2", error_count=10)
        p2.failure_counts["gpt-4o"] = 1

        store = AuthProfileStore([p1, p2])
        # For gpt-4o, p2 has fewer model-scoped errors despite higher global count
        best = store.select_best(model="gpt-4o")
        assert best is p2


# ---------------------------------------------------------------------------
# AuthProfileStore — report_failure
# ---------------------------------------------------------------------------


class TestReportFailure:
    """Tests for AuthProfileStore.report_failure()."""

    def test_sets_global_cooldown_on_failure(self):
        """report_failure without model sets global cooldown."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        assert p.cooldown_until > time.monotonic()
        assert p.error_count == 1

    def test_rate_limit_cooldown_is_60s(self):
        """Rate limit failure sets ~60s cooldown."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        before = time.monotonic()
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        expected_deadline = before + 60.0

        # Cooldown should be approximately 60s from now (allow 1s tolerance)
        assert abs(p.cooldown_until - expected_deadline) < 1.0

    def test_auth_failed_cooldown_is_300s(self):
        """Auth failure sets ~300s cooldown."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        before = time.monotonic()
        store.report_failure("p1", AuthProfileFailureReason.AUTH)
        expected_deadline = before + 300.0

        assert abs(p.cooldown_until - expected_deadline) < 1.0

    def test_server_error_cooldown_is_30s(self):
        """Server error (OVERLOADED) sets ~30s cooldown."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        before = time.monotonic()
        store.report_failure("p1", AuthProfileFailureReason.OVERLOADED)
        expected_deadline = before + 30.0

        assert abs(p.cooldown_until - expected_deadline) < 1.0

    def test_model_scoped_failure_sets_model_cooldown(self):
        """report_failure with model sets per-model cooldown, not global."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")

        # Model-scoped cooldown set
        assert p._model_cooldowns.get("gpt-4o", 0.0) > time.monotonic()
        # Global cooldown unchanged (default 0.0)
        assert p.cooldown_until == 0.0

    def test_model_scoped_failure_increments_model_count(self):
        """report_failure with model increments per-model failure count."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")

        assert p.failure_counts["gpt-4o"] == 2
        # Global error count also incremented
        assert p.error_count == 2

    def test_unknown_profile_id_is_noop(self):
        """report_failure for unknown profile ID is a no-op (no crash)."""
        store = AuthProfileStore([])
        # Should not raise
        store.report_failure("nonexistent", AuthProfileFailureReason.AUTH)

    def test_multiple_failures_accumulate(self):
        """Multiple failures increment error_count."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)

        assert p.error_count == 3


# ---------------------------------------------------------------------------
# AuthProfileStore — report_success
# ---------------------------------------------------------------------------


class TestReportSuccess:
    """Tests for AuthProfileStore.report_success()."""

    def test_resets_error_count(self):
        """report_success resets error_count to 0."""
        p = _make_profile("p1", error_count=5)
        store = AuthProfileStore([p])

        store.report_success("p1")
        assert p.error_count == 0

    def test_updates_last_used(self):
        """report_success updates last_used to current time."""
        p = _make_profile("p1", last_used=0.0)
        store = AuthProfileStore([p])

        before = time.monotonic()
        store.report_success("p1")
        after = time.monotonic()

        assert before <= p.last_used <= after

    def test_unknown_profile_id_is_noop(self):
        """report_success for unknown profile ID is a no-op."""
        store = AuthProfileStore([])
        # Should not raise
        store.report_success("nonexistent")

    def test_success_after_failure_resets_error(self):
        """After failures, a success resets error_count."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT)
        assert p.error_count == 2

        store.report_success("p1")
        assert p.error_count == 0

    def test_success_with_model_clears_model_failure_count(self):
        """report_success(model=...) clears per-model failure count."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")
        assert p.failure_counts["gpt-4o"] == 2

        store.report_success("p1", model="gpt-4o")
        assert p.failure_counts.get("gpt-4o", 0) == 0
        assert p.error_count == 0

    def test_success_with_model_clears_model_cooldown(self):
        """report_success(model=...) also clears the model-scoped cooldown."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")
        assert p._model_cooldowns.get("gpt-4o", 0.0) > time.monotonic()

        store.report_success("p1", model="gpt-4o")
        # Model cooldown should be gone
        assert "gpt-4o" not in p._model_cooldowns

    def test_success_with_model_does_not_affect_other_models(self):
        """Clearing one model's failure count doesn't affect another model."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])

        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="gpt-4o")
        store.report_failure("p1", AuthProfileFailureReason.RATE_LIMIT, model="claude-3")
        assert p.failure_counts["gpt-4o"] == 1
        assert p.failure_counts["claude-3"] == 1

        store.report_success("p1", model="gpt-4o")
        assert p.failure_counts.get("gpt-4o", 0) == 0
        assert p.failure_counts["claude-3"] == 1  # unaffected

    def test_recovered_profile_reranked_after_model_success(self):
        """Bug regression: a profile that failed for a model then succeeded
        should no longer be permanently deprioritized for that model."""
        p1 = _make_profile("p1")
        p2 = _make_profile("p2")
        store = AuthProfileStore([p1, p2])

        # p1 fails once for gpt-4o
        store.report_failure("p1", AuthProfileFailureReason.OVERLOADED, model="gpt-4o")
        # Cooldown expires (simulate)
        p1._model_cooldowns["gpt-4o"] = 0.0

        # Before fix: p1 would still rank worse because failure_counts["gpt-4o"]=1
        # After fix: report_success clears the model failure count
        store.report_success("p1", model="gpt-4o")

        # Now both profiles should have 0 model errors for gpt-4o
        # p1.last_used was just updated, so p2 (last_used=0) should be picked
        # But the key assertion: p1's model error count is 0, not 1
        assert p1.failure_counts.get("gpt-4o", 0) == 0


# ---------------------------------------------------------------------------
# AuthProfileStore — cooldown_remaining
# ---------------------------------------------------------------------------


class TestCooldownRemaining:
    """Tests for AuthProfileStore.cooldown_remaining()."""

    def test_returns_zero_when_no_cooldown(self):
        """Profile with no cooldown returns 0.0."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])
        assert store.cooldown_remaining("p1") == 0.0

    def test_returns_positive_during_cooldown(self):
        """Profile in active cooldown returns positive remaining seconds."""
        p = _make_profile("p1", cooldown_until=time.monotonic() + 100.0)
        store = AuthProfileStore([p])
        remaining = store.cooldown_remaining("p1")
        assert 99.0 < remaining <= 100.0

    def test_returns_zero_after_cooldown_expired(self):
        """Expired cooldown returns 0.0."""
        p = _make_profile("p1", cooldown_until=time.monotonic() - 10.0)
        store = AuthProfileStore([p])
        assert store.cooldown_remaining("p1") == 0.0

    def test_unknown_profile_returns_zero(self):
        """Unknown profile ID returns 0.0."""
        store = AuthProfileStore([])
        assert store.cooldown_remaining("nonexistent") == 0.0


# ---------------------------------------------------------------------------
# AuthProfileStore — get
# ---------------------------------------------------------------------------


class TestGet:
    """Tests for AuthProfileStore.get()."""

    def test_get_existing_profile(self):
        """get() returns the profile for a known ID."""
        p = _make_profile("p1")
        store = AuthProfileStore([p])
        assert store.get("p1") is p

    def test_get_unknown_profile_returns_none(self):
        """get() returns None for unknown ID."""
        store = AuthProfileStore([])
        assert store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# AuthProfile — is_eligible
# ---------------------------------------------------------------------------


class TestIsEligible:
    """Tests for AuthProfile.is_eligible()."""

    def test_eligible_by_default(self):
        """Fresh profile is eligible."""
        p = _make_profile("p1")
        assert p.is_eligible() is True

    def test_not_eligible_during_global_cooldown(self):
        """Profile in global cooldown is not eligible."""
        p = _make_profile("p1", cooldown_until=time.monotonic() + 100)
        assert p.is_eligible() is False

    def test_not_eligible_during_model_cooldown(self):
        """Profile in model-scoped cooldown is not eligible for that model."""
        p = _make_profile("p1")
        p._model_cooldowns["gpt-4o"] = time.monotonic() + 100
        assert p.is_eligible(model="gpt-4o") is False
        assert p.is_eligible(model="other-model") is True
        assert p.is_eligible() is True  # global is fine


# ---------------------------------------------------------------------------
# ProviderFallbackChain
# ---------------------------------------------------------------------------


class TestProviderFallbackChain:
    """Tests for ProviderFallbackChain."""

    def test_next_provider_returns_next_in_chain(self):
        """next_provider returns the provider after the failed one."""
        chain = ProviderFallbackChain(["anthropic", "google", "groq"])
        assert chain.next_provider("anthropic") == "google"
        assert chain.next_provider("google") == "groq"

    def test_last_provider_returns_none(self):
        """End of chain returns None."""
        chain = ProviderFallbackChain(["anthropic", "google", "groq"])
        assert chain.next_provider("groq") is None

    def test_unknown_provider_returns_first(self):
        """Unknown provider returns first in chain."""
        chain = ProviderFallbackChain(["anthropic", "google", "groq"])
        assert chain.next_provider("openai") == "anthropic"

    def test_empty_chain(self):
        """Empty chain returns None for any provider."""
        chain = ProviderFallbackChain([])
        assert chain.next_provider("anything") is None

    def test_single_provider_chain(self):
        """Single-provider chain: that provider returns None, unknown returns it."""
        chain = ProviderFallbackChain(["anthropic"])
        assert chain.next_provider("anthropic") is None
        assert chain.next_provider("openai") == "anthropic"

    def test_providers_property(self):
        """providers property returns ordered list."""
        chain = ProviderFallbackChain(["a", "b", "c"])
        assert chain.providers == ["a", "b", "c"]
        # Verify it's a copy, not a reference
        chain.providers.append("d")
        assert len(chain.providers) == 3


# ---------------------------------------------------------------------------
# TokenRefreshManager
# ---------------------------------------------------------------------------


class TestTokenRefreshManager:
    """Tests for TokenRefreshManager."""

    @pytest.mark.asyncio
    async def test_api_key_profile_is_noop(self):
        """ensure_fresh is a no-op for api_key profiles."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        p = _make_profile("p1", profile_type="api_key")
        result = await mgr.ensure_fresh(p)
        assert result is p
        # refresh_fn should NOT have been called
        mgr._refresh_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_profile_not_near_expiry_is_noop(self):
        """ensure_fresh is a no-op when token is far from expiry."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        p = _make_profile(
            "p1",
            profile_type="oauth",
            credentials={
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_at": time.time() + 3600,  # 1 hour away
            },
        )
        result = await mgr.ensure_fresh(p)
        assert result is p
        mgr._refresh_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_profile_near_expiry_triggers_refresh(self):
        """ensure_fresh refreshes when expires_at - now < REFRESH_MARGIN_S."""
        new_creds = {
            "access_token": "new_tok",
            "refresh_token": "new_ref",
            "expires_at": time.time() + 3600,
        }
        refresh_fn = AsyncMock(return_value=new_creds)
        mgr = TokenRefreshManager(refresh_fn=refresh_fn)

        p = _make_profile(
            "p1",
            profile_type="oauth",
            credentials={
                "access_token": "old_tok",
                "refresh_token": "old_ref",
                "expires_at": time.time() + 10,  # 10s < REFRESH_MARGIN_S (60s)
            },
        )
        result = await mgr.ensure_fresh(p)
        assert result is p
        refresh_fn.assert_called_once_with(p)
        assert p.credentials["access_token"] == "new_tok"

    @pytest.mark.asyncio
    async def test_no_refresh_fn_logs_warning(self):
        """ensure_fresh with no refresh_fn returns profile unchanged on near-expiry."""
        mgr = TokenRefreshManager(refresh_fn=None)
        p = _make_profile(
            "p1",
            profile_type="oauth",
            credentials={
                "access_token": "tok",
                "expires_at": time.time() + 10,
            },
        )
        result = await mgr.ensure_fresh(p)
        assert result is p
        assert p.credentials["access_token"] == "tok"  # unchanged

    @pytest.mark.asyncio
    async def test_refresh_fn_exception_is_handled(self):
        """ensure_fresh handles refresh_fn exceptions gracefully."""
        refresh_fn = AsyncMock(side_effect=RuntimeError("network error"))
        mgr = TokenRefreshManager(refresh_fn=refresh_fn)
        p = _make_profile(
            "p1",
            profile_type="oauth",
            credentials={
                "access_token": "tok",
                "expires_at": time.time() + 10,
            },
        )
        # Should not raise
        result = await mgr.ensure_fresh(p)
        assert result is p
        assert p.credentials["access_token"] == "tok"  # unchanged

    @pytest.mark.asyncio
    async def test_no_expires_at_is_noop(self):
        """ensure_fresh is a no-op when credentials lack expires_at."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        p = _make_profile(
            "p1",
            profile_type="token",
            credentials={"access_token": "tok"},
        )
        result = await mgr.ensure_fresh(p)
        assert result is p
        mgr._refresh_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_background_refresh_creates_task(self):
        """start_background_refresh creates an asyncio task."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        store = AuthProfileStore([])

        await mgr.start_background_refresh(store)
        assert mgr._task is not None
        assert not mgr._task.done()
        mgr.stop()

    @pytest.mark.asyncio
    async def test_start_background_refresh_idempotent(self):
        """Calling start_background_refresh twice doesn't create duplicate tasks."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        store = AuthProfileStore([])

        await mgr.start_background_refresh(store)
        task1 = mgr._task
        await mgr.start_background_refresh(store)
        task2 = mgr._task

        assert task1 is task2
        mgr.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() cancels the background task."""
        mgr = TokenRefreshManager(refresh_fn=AsyncMock())
        store = AuthProfileStore([])

        await mgr.start_background_refresh(store)
        task = mgr._task
        mgr.stop()

        assert mgr._task is None
        # Allow one event loop iteration for cancellation to propagate
        await asyncio.sleep(0)
        assert task.cancelled()


# ---------------------------------------------------------------------------
# FAILOVER_MAP — structural test
# ---------------------------------------------------------------------------


class TestFailoverMap:
    """Tests for FAILOVER_MAP structure."""

    def test_failover_map_has_expected_keys(self):
        """FAILOVER_MAP includes entries for FORMAT, RATE_LIMIT, AUTH."""
        from sci_fi_dashboard.auth_profiles import FAILOVER_MAP

        assert AuthProfileFailureReason.FORMAT in FAILOVER_MAP
        assert AuthProfileFailureReason.RATE_LIMIT in FAILOVER_MAP
        assert AuthProfileFailureReason.AUTH in FAILOVER_MAP

    def test_failover_map_values_are_strings(self):
        """All FAILOVER_MAP values are strategy strings."""
        from sci_fi_dashboard.auth_profiles import FAILOVER_MAP

        for key, value in FAILOVER_MAP.items():
            assert isinstance(value, str), f"FAILOVER_MAP[{key}] is not a string: {value!r}"
