"""
SkillRouter — routes user messages to skills using description embeddings.

Two-stage matching:
  1. Exact trigger match (case-insensitive substring) — always wins
  2. Cosine similarity between user message embedding and skill descriptions

Falls back to trigger-only routing when no embedding provider is available.
"""

from __future__ import annotations

import logging
import math

from sci_fi_dashboard.skills.schema import SkillManifest

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors. No numpy dependency."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SkillRouter:
    """Routes user messages to skills based on description embeddings.

    Priority:
    1. Exact trigger phrase match (case-insensitive substring)
    2. Cosine similarity >= threshold between user message and skill description
    """

    DEFAULT_THRESHOLD = 0.45

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self._threshold = threshold
        self._skills: list[SkillManifest] = []
        self._embeddings: list[list[float]] = []  # parallel to _skills
        self._embed_fn = None  # provider.embed_query, or None

    def update_skills(self, manifests: list[SkillManifest]) -> None:
        """Replace the skill list and re-embed descriptions."""
        self._skills = list(manifests)
        self._embeddings = []
        self._embed_fn = None

        if not manifests:
            return

        try:
            from sci_fi_dashboard.embedding import get_provider

            provider = get_provider()
            if provider is None:
                raise RuntimeError("No embedding provider available")

            self._embeddings = provider.embed_documents([m.description for m in manifests])
            self._embed_fn = provider.embed_query
            logger.info("[Skills] SkillRouter: embedded %d skill descriptions", len(manifests))
        except Exception as exc:
            logger.info("[Skills] No embedding provider — trigger-only routing active (%s)", exc)
            self._embeddings = []
            self._embed_fn = None

    def match(self, user_message: str) -> SkillManifest | None:
        """Find the best-matching skill for the user message, or None."""
        if not self._skills:
            return None

        # Stage 1: Exact trigger match
        trigger_hit = self._try_trigger_match(user_message)
        if trigger_hit is not None:
            logger.info(
                "[Skills] Trigger match: '%s...' -> %s",
                user_message[:50],
                trigger_hit.name,
            )
            return trigger_hit

        # Stage 2: Embedding similarity
        embedding_hit, score = self._try_embedding_match(user_message)
        if embedding_hit is not None:
            logger.info(
                "[Skills] Embedding match: '%s...' -> %s (score=%.3f)",
                user_message[:50],
                embedding_hit.name,
                score,
            )
            return embedding_hit

        logger.debug(
            "[Skills] No skill match for '%s...' (best_score=%.3f)",
            user_message[:50],
            score,
        )
        return None

    def _try_trigger_match(self, user_message: str) -> SkillManifest | None:
        """Check explicit trigger phrases (case-insensitive substring match)."""
        msg_lower = user_message.lower()
        for skill in self._skills:
            for trigger in skill.triggers:
                if trigger.lower() in msg_lower:
                    return skill
        return None

    def _try_embedding_match(self, user_message: str) -> tuple[SkillManifest | None, float]:
        """Embed user message and find highest-similarity skill above threshold."""
        if self._embed_fn is None or not self._embeddings:
            return None, 0.0

        try:
            query_vec = self._embed_fn(user_message)
        except Exception as exc:
            logger.warning("[Skills] Embedding query failed: %s", exc)
            return None, 0.0

        best_skill: SkillManifest | None = None
        best_score = 0.0

        for skill, emb in zip(self._skills, self._embeddings, strict=False):
            score = _cosine_similarity(query_vec, emb)
            if score > best_score:
                best_score = score
                if score >= self._threshold:
                    best_skill = skill

        return best_skill, best_score
