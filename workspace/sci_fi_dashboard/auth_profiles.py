"""
auth_profiles.py — Auth profile management for multi-key LLM routing.

Provides AuthProfileStore for round-robin key rotation with per-model cooldowns,
TokenRefreshManager for proactive OAuth token refresh, and ProviderFallbackChain
for provider-level failover.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum

from sci_fi_dashboard.llm_router import AuthProfileFailureReason

logger = logging.getLogger(__name__)

# Cooldown durations (seconds) per failure reason
_COOLDOWN_SECONDS: dict[AuthProfileFailureReason, float] = {
    AuthProfileFailureReason.RATE_LIMIT: 60.0,
    AuthProfileFailureReason.AUTH: 300.0,
    AuthProfileFailureReason.AUTH_PERMANENT: 600.0,
    AuthProfileFailureReason.OVERLOADED: 30.0,
    AuthProfileFailureReason.TIMEOUT: 30.0,
    AuthProfileFailureReason.BILLING: 3600.0,
}

# Margin before OAuth token expiry to trigger proactive refresh
REFRESH_MARGIN_S = 60.0

# Background refresh interval
_REFRESH_INTERVAL_S = 30.0


@dataclass
class AuthProfile:
    """A single authentication credential for an LLM provider.

    Attributes:
        id: Unique identifier for this profile.
        type: Credential type — "api_key", "oauth", or "token".
        provider: Provider name (e.g., "anthropic", "openai", "github_copilot").
        credentials: Credential payload. For api_key: {"api_key": "sk-..."},
            for oauth/token: {"access_token": "...", "refresh_token": "...",
            "expires_at": <unix_timestamp>}.
        cooldown_until: Monotonic timestamp until which this profile is ineligible.
            Per-model cooldowns are stored in _model_cooldowns.
        error_count: Global error count (reset on success).
        last_used: Monotonic timestamp of last successful use.
        failure_counts: Per-model failure counts — a profile failing on one model
            doesn't penalise it for other models.
    """

    id: str
    type: str  # "api_key" | "oauth" | "token"
    provider: str
    credentials: dict = field(default_factory=dict)
    cooldown_until: float = 0.0
    error_count: int = 0
    last_used: float = 0.0
    failure_counts: dict[str, int] = field(default_factory=dict)
    _model_cooldowns: dict[str, float] = field(default_factory=dict)

    def is_eligible(self, model: str | None = None) -> bool:
        """Check if this profile is eligible (not in cooldown).

        Args:
            model: If provided, check model-scoped cooldown. Otherwise check
                global cooldown.

        Returns:
            True if the profile can be used now.
        """
        now = time.monotonic()
        if now < self.cooldown_until:
            return False
        if model and now < self._model_cooldowns.get(model, 0.0):
            return False
        return True


class AuthProfileStore:
    """Manages a pool of auth profiles with round-robin selection and cooldowns.

    Selection strategy: among eligible profiles (not in cooldown for the
    requested model), pick the one with the lowest error_count. Ties are
    broken by least-recently-used (lowest last_used) for round-robin
    distribution.
    """

    def __init__(self, profiles: list[AuthProfile] | None = None) -> None:
        self._profiles: dict[str, AuthProfile] = {}
        for p in profiles or []:
            self._profiles[p.id] = p

    @property
    def profiles(self) -> list[AuthProfile]:
        """All registered profiles."""
        return list(self._profiles.values())

    def get(self, profile_id: str) -> AuthProfile | None:
        """Look up a profile by ID."""
        return self._profiles.get(profile_id)

    def select_best(self, model: str | None = None) -> AuthProfile | None:
        """Pick the best eligible profile for a given model.

        Selection criteria (in order):
        1. Filter to profiles not in cooldown for the model.
        2. Among those, pick lowest error_count.
        3. Ties broken by lowest last_used (round-robin LRU).

        Args:
            model: Optional model string for model-scoped cooldown filtering.

        Returns:
            The best AuthProfile, or None if no eligible profile exists.
        """
        eligible = [p for p in self._profiles.values() if p.is_eligible(model)]
        if not eligible:
            return None
        # Sort by (error_count_for_model, last_used) for deterministic round-robin
        def _sort_key(p: AuthProfile) -> tuple[int, float]:
            model_errors = p.failure_counts.get(model, 0) if model else p.error_count
            return (model_errors, p.last_used)

        eligible.sort(key=_sort_key)
        return eligible[0]

    def report_failure(
        self,
        profile_id: str,
        reason: AuthProfileFailureReason,
        model: str | None = None,
    ) -> None:
        """Record a failure for a profile, applying cooldown.

        Cooldown duration depends on the failure reason (see _COOLDOWN_SECONDS).
        If a model is specified, the cooldown is model-scoped — the profile
        remains eligible for other models.

        Args:
            profile_id: The profile that failed.
            reason: Why the call failed.
            model: Optional model for model-scoped cooldown.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            logger.warning("report_failure: unknown profile %r", profile_id)
            return

        profile.error_count += 1
        cooldown_s = _COOLDOWN_SECONDS.get(reason, 30.0)
        now = time.monotonic()
        deadline = now + cooldown_s

        if model:
            profile.failure_counts[model] = profile.failure_counts.get(model, 0) + 1
            profile._model_cooldowns[model] = deadline
            logger.info(
                "Profile %s cooldown %.0fs for model %s (reason=%s, errors=%d)",
                profile_id,
                cooldown_s,
                model,
                reason.value,
                profile.failure_counts[model],
            )
        else:
            profile.cooldown_until = deadline
            logger.info(
                "Profile %s global cooldown %.0fs (reason=%s, errors=%d)",
                profile_id,
                cooldown_s,
                reason.value,
                profile.error_count,
            )

    def report_success(self, profile_id: str, model: str | None = None) -> None:
        """Record a successful call for a profile.

        Resets error_count and updates last_used for round-robin rotation.
        If a model is specified, also clears the per-model failure count and
        model-scoped cooldown so the profile re-enters normal rotation for
        that model.

        Args:
            profile_id: The profile that succeeded.
            model: Optional model whose per-model failure count should be cleared.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            logger.warning("report_success: unknown profile %r", profile_id)
            return

        profile.error_count = 0
        profile.last_used = time.monotonic()

        if model:
            profile.failure_counts.pop(model, None)
            profile._model_cooldowns.pop(model, None)

    def cooldown_remaining(self, profile_id: str) -> float:
        """Seconds remaining in this profile's global cooldown.

        Args:
            profile_id: The profile to check.

        Returns:
            Seconds until eligible, or 0.0 if already eligible.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            return 0.0
        remaining = profile.cooldown_until - time.monotonic()
        return max(0.0, remaining)


# --- Runtime failover map ---

FAILOVER_MAP: dict[AuthProfileFailureReason, str] = {
    AuthProfileFailureReason.FORMAT: "use_larger_context_model",  # context overflow via FORMAT
    AuthProfileFailureReason.RATE_LIMIT: "use_same_role_fallback",
    AuthProfileFailureReason.AUTH: "use_different_provider",
    AuthProfileFailureReason.AUTH_PERMANENT: "use_different_provider",
}


class ProviderFallbackChain:
    """Ordered chain of providers for failover.

    When a provider fails, next_provider() returns the next one in the chain.
    Wraps around to None when the chain is exhausted.

    Example:
        chain = ProviderFallbackChain(["anthropic", "google", "groq"])
        chain.next_provider("anthropic")  # → "google"
        chain.next_provider("groq")       # → None (end of chain)
    """

    def __init__(self, chain: list[str]) -> None:
        self._chain = list(chain)

    @property
    def providers(self) -> list[str]:
        """The ordered provider list."""
        return list(self._chain)

    def next_provider(self, failed_provider: str) -> str | None:
        """Return the next provider after the failed one, or None if exhausted.

        Args:
            failed_provider: The provider that just failed.

        Returns:
            Next provider name, or None if no more providers.
        """
        try:
            idx = self._chain.index(failed_provider)
        except ValueError:
            # Unknown provider — return first in chain if available
            return self._chain[0] if self._chain else None
        next_idx = idx + 1
        if next_idx < len(self._chain):
            return self._chain[next_idx]
        return None


# --- Token Refresh Manager ---


class TokenRefreshManager:
    """Proactive background refresh for OAuth/token-based auth profiles.

    Checks all OAuth profiles periodically and refreshes tokens before they
    expire. Primary use case: GitHub Copilot ghu_ tokens.

    The refresh_fn callback should accept an AuthProfile and return updated
    credentials dict, or raise on failure.
    """

    def __init__(
        self,
        refresh_fn=None,  # Callable[[AuthProfile], Awaitable[dict]] | None
    ) -> None:
        self._refresh_fn = refresh_fn
        self._task: asyncio.Task | None = None

    async def ensure_fresh(self, profile: AuthProfile) -> AuthProfile:
        """Refresh the profile's token if it's close to expiry.

        Proactively refreshes when expires_at - now < REFRESH_MARGIN_S.
        No-op for api_key profiles or profiles without expires_at.

        Args:
            profile: The auth profile to check and possibly refresh.

        Returns:
            The profile (possibly with updated credentials).
        """
        if profile.type == "api_key":
            return profile

        expires_at = profile.credentials.get("expires_at")
        if expires_at is None:
            return profile

        remaining = expires_at - time.time()
        if remaining > REFRESH_MARGIN_S:
            return profile

        if self._refresh_fn is None:
            logger.warning(
                "Profile %s token expires in %.0fs but no refresh_fn configured",
                profile.id,
                remaining,
            )
            return profile

        try:
            new_creds = await self._refresh_fn(profile)
            profile.credentials.update(new_creds)
            logger.info("Refreshed token for profile %s", profile.id)
        except Exception as exc:
            logger.error("Token refresh failed for profile %s: %s", profile.id, exc)

        return profile

    async def start_background_refresh(self, store: AuthProfileStore) -> None:
        """Start a background task that refreshes all OAuth profiles periodically.

        Checks every REFRESH_INTERVAL_S (30s). Safe to call multiple times —
        subsequent calls are no-ops if a task is already running.

        Args:
            store: The AuthProfileStore containing profiles to monitor.
        """
        if self._task is not None and not self._task.done():
            return

        self._task = asyncio.create_task(self._refresh_loop(store))

    async def _refresh_loop(self, store: AuthProfileStore) -> None:
        """Internal loop that refreshes OAuth profiles."""
        while True:
            try:
                for profile in store.profiles:
                    if profile.type in ("oauth", "token"):
                        await self.ensure_fresh(profile)
            except Exception as exc:
                logger.error("Background refresh error: %s", exc)
            await asyncio.sleep(_REFRESH_INTERVAL_S)

    def stop(self) -> None:
        """Cancel the background refresh task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None
