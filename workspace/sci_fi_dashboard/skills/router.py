"""
skills/router.py — SkillRouter: description-based intent routing via embeddings.

Two-stage matching:
1. Explicit trigger match (case-insensitive substring) — always wins.
2. Cosine similarity between user message embedding and pre-embedded skill
   description vectors — returns best skill above configurable threshold.

Graceful degradation: if no embedding provider is available, falls back to
trigger-only matching without raising.

Security mitigations (T-01-08, T-01-09):
- Trigger match uses substring containment, not equality — skills cannot
  hijack other skills' triggers (first-match-wins in skill list order).
- embed_query called once per message, not once per skill — O(1) API calls
  regardless of skill count.
"""

from __future__ import annotations

import logging
import math

from sci_fi_dashboard.skills.schema import SkillManifest

logger = logging.getLogger(__name__)

# Lazy import of get_provider to avoid circular imports and allow mocking.
# Always imported at call-site, never at module level.
try:
    from sci_fi_dashboard.embedding import get_provider as _get_provider_fn
except ImportError:
    _get_provider_fn = None  # type: ignore[assignment]


def get_provider():
    """Return the singleton EmbeddingProvider, or None if unavailable."""
    if _get_provider_fn is None:
        return None
    try:
        return _get_provider_fn()
    except Exception:
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector is the zero vector (avoids divide-by-zero).
    No numpy dependency — pure Python for minimal environment requirements.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SkillRouter:
    """Routes user messages to skills based on description embeddings.

    Two-stage matching:
    1. Exact trigger match (case-insensitive substring) — always wins.
    2. Cosine similarity between user message embedding and skill description
       embeddings — returns best skill above configurable threshold.

    Usage::

        router = SkillRouter()
        router.update_skills(skill_loader.scan_directory(skills_path))
        matched = router.match(user_message)
        if matched:
            # handle matched skill
            ...

    Thread safety: update_skills() replaces internal state atomically via list
    assignment (CPython GIL). For multi-threaded use in the gateway, callers
    should synchronize externally if hot-reload races are a concern.
    """

    DEFAULT_THRESHOLD = 0.45

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        """Initialize SkillRouter.

        Args:
            threshold: Minimum cosine similarity score for an embedding match
                to be considered a hit. Default 0.45. Higher values require
                stronger semantic similarity before routing to a skill.
        """
        self._threshold = threshold
        self._skills: list[SkillManifest] = []
        self._embeddings: list[list[float]] = []  # parallel index to _skills
        self._embed_fn = None  # callable: str -> list[float], or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_skills(self, manifests: list[SkillManifest]) -> None:
        """Replace the skill list and re-embed descriptions.

        Called at startup and after hot-reload detects skill directory changes.
        If no embedding provider is available, embeddings are skipped and
        trigger-only routing remains active (logged at INFO level).

        Args:
            manifests: New list of SkillManifest objects. May be empty.
        """
        self._skills = list(manifests)

        if not manifests:
            self._embeddings = []
            self._embed_fn = None
            return

        provider = get_provider()
        if provider is not None:
            try:
                descriptions = [m.description for m in manifests]
                self._embeddings = provider.embed_documents(descriptions)
                self._embed_fn = provider.embed_query
                logger.debug(
                    "[Skills] Embedded %d skill descriptions via %s",
                    len(manifests),
                    getattr(provider, "info", lambda: type(provider).__name__)(),
                )
            except Exception as exc:
                logger.warning(
                    "[Skills] Failed to embed skill descriptions: %s — "
                    "falling back to trigger-only routing",
                    exc,
                )
                self._embeddings = []
                self._embed_fn = None
        else:
            self._embeddings = []
            self._embed_fn = None
            logger.info("[Skills] No embedding provider — trigger-only routing active")

    def match(self, user_message: str) -> SkillManifest | None:
        """Find the best-matching skill for the user message, or None.

        Stage 1 (trigger): Check if any skill's trigger phrases appear as a
        case-insensitive substring of user_message. First match wins.

        Stage 2 (embedding): If no trigger match, embed user_message and find
        the skill with highest cosine similarity. Returns that skill if its
        score >= threshold.

        Args:
            user_message: Raw user input text.

        Returns:
            The best-matching SkillManifest, or None if no skill qualifies.
        """
        if not self._skills:
            return None

        # Stage 1: Trigger bypass — always takes priority
        trigger_hit = self._try_trigger_match(user_message)
        if trigger_hit is not None:
            logger.debug(
                "[Skills] Trigger match: '%s...' -> %s",
                user_message[:50],
                trigger_hit.name,
            )
            return trigger_hit

        # Stage 2: Embedding similarity
        embedding_hit, score = self._try_embedding_match(user_message)
        if embedding_hit is not None:
            logger.debug(
                "[Skills] Embedding match: '%s...' -> %s (score=%.3f)",
                user_message[:50],
                embedding_hit.name,
                score,
            )
            return embedding_hit

        logger.debug(
            "[Skills] No skill match for '%s...' (best=%.3f)",
            user_message[:50],
            score,
        )
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_trigger_match(self, user_message: str) -> SkillManifest | None:
        """Check explicit trigger phrases (case-insensitive substring match).

        Iterates skills in list order; first skill whose trigger phrase is
        found as a substring of the (lowercased) user message wins.

        Returns first matching SkillManifest, or None.
        """
        message_lower = user_message.lower()
        for skill in self._skills:
            for trigger in skill.triggers:
                if trigger.lower() in message_lower:
                    return skill
        return None

    def _try_embedding_match(
        self, user_message: str
    ) -> tuple[SkillManifest | None, float]:
        """Embed user message and find highest-similarity skill above threshold.

        Returns:
            Tuple of (best_skill_or_None, best_score). If no embedding
            provider is configured or embeddings list is empty, returns
            (None, 0.0).
        """
        if self._embed_fn is None or not self._embeddings:
            return None, 0.0

        try:
            query_vec = self._embed_fn(user_message)
        except Exception as exc:
            logger.warning("[Skills] embed_query failed: %s", exc)
            return None, 0.0

        best_skill: SkillManifest | None = None
        best_score = 0.0

        for skill, skill_vec in zip(self._skills, self._embeddings):
            score = _cosine_similarity(query_vec, skill_vec)
            if score > best_score:
                best_score = score
                best_skill = skill

        if best_score >= self._threshold:
            return best_skill, best_score
        return None, best_score
