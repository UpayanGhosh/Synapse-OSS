"""
Tests for SkillRouter: embedding-based intent matching with trigger bypass.

TDD RED — tests written before implementation. All tests should fail until
workspace/sci_fi_dashboard/skills/router.py is implemented.

Test coverage:
- Test 1: Embedding match returns best skill above threshold
- Test 2: Returns None when no skill similarity exceeds threshold
- Test 3: Trigger phrase match (case-insensitive substring)
- Test 4: Trigger match takes priority over embedding similarity
- Test 5: update_skills() re-embeds and replaces skill list
- Test 6: Graceful fallback to trigger-only when no embedding provider
- Test 7: Cosine similarity threshold is configurable (default 0.45)
- Test 8: Empty skill list always returns None
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

from sci_fi_dashboard.skills.router import SkillRouter
from sci_fi_dashboard.skills.schema import SkillManifest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_manifest(
    name: str,
    description: str,
    triggers: list[str] | None = None,
    version: str = "1.0.0",
) -> SkillManifest:
    """Create a minimal SkillManifest for testing."""
    return SkillManifest(
        name=name,
        description=description,
        version=version,
        triggers=triggers or [],
    )


def _make_fake_provider(
    query_vec: list[float],
    doc_vecs: list[list[float]],
) -> MagicMock:
    """Return a mock EmbeddingProvider.

    embed_query always returns query_vec.
    embed_documents always returns doc_vecs.
    """
    provider = MagicMock()
    provider.embed_query.return_value = query_vec
    provider.embed_documents.return_value = doc_vecs
    return provider


# ---------------------------------------------------------------------------
# Test 1: Embedding match returns best skill above threshold
# ---------------------------------------------------------------------------


def test_match_returns_best_skill():
    """With two skills and a user message clearly matching skill 1, match() returns skill 1."""
    weather = _make_manifest("weather-checker", "check the weather forecast")
    coder = _make_manifest("code-helper", "help write python code")

    # weather-checker is at [1.0, 0.0, 0.0]; coder at [0.0, 1.0, 0.0]
    # Query for "what's the weather like" -> [0.9, 0.1, 0.0]
    # cosine(query, weather) ≈ 0.994 (very high)
    # cosine(query, coder)   ≈ 0.099 (low)
    fake_provider = _make_fake_provider(
        query_vec=[0.9, 0.1, 0.0],
        doc_vecs=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=fake_provider):
        router = SkillRouter()
        router.update_skills([weather, coder])
        result = router.match("what's the weather like")

    assert result is not None, "Expected a skill match but got None"
    assert result.name == "weather-checker", f"Expected weather-checker, got {result.name}"


# ---------------------------------------------------------------------------
# Test 2: Returns None when no skill matches threshold
# ---------------------------------------------------------------------------


def test_match_returns_none_below_threshold():
    """With a user message unrelated to any skill, match() returns None."""
    weather = _make_manifest("weather-checker", "check the weather forecast")
    coder = _make_manifest("code-helper", "help write python code")

    # "hello how are you" -> [0.3, 0.3, 0.3] — low similarity to both skills
    # cosine([0.3,0.3,0.3], [1.0,0.0,0.0]) ≈ 0.577  -- this actually exceeds threshold
    # Use different vectors to get genuinely low similarity
    fake_provider = _make_fake_provider(
        query_vec=[0.0, 0.0, 1.0],  # orthogonal to both skill vectors
        doc_vecs=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=fake_provider):
        router = SkillRouter(threshold=0.45)
        router.update_skills([weather, coder])
        result = router.match("hello how are you")

    assert result is None, f"Expected None but got skill: {result}"


# ---------------------------------------------------------------------------
# Test 3: Trigger phrase case-insensitive substring match
# ---------------------------------------------------------------------------


def test_trigger_phrase_case_insensitive_match():
    """A trigger phrase substring in the user message matches, regardless of case."""
    skill = _make_manifest(
        "skill-creator",
        "create a new skill from a template",
        triggers=["create a skill"],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=None):
        router = SkillRouter()
        router.update_skills([skill])
        # "CREATE A SKILL for me" contains trigger "create a skill" case-insensitively
        result = router.match("CREATE A SKILL for me")

    assert result is not None, "Expected trigger match but got None"
    assert result.name == "skill-creator"


# ---------------------------------------------------------------------------
# Test 4: Trigger match takes priority over embedding similarity
# ---------------------------------------------------------------------------


def test_trigger_priority_over_embedding():
    """When a trigger phrase matches, it wins even if another skill has higher embedding sim."""
    skill_a = _make_manifest(
        "skill-a",
        "first skill description",
        triggers=["special keyword"],
    )
    skill_b = _make_manifest(
        "skill-b",
        "second skill with higher embedding similarity",
    )

    # Embedding says skill_b matches better (score=0.99 vs skill_a=0.0)
    # But skill_a has a trigger phrase in the message
    fake_provider = _make_fake_provider(
        query_vec=[0.0, 1.0, 0.0],
        doc_vecs=[[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]],  # skill_a=ortho, skill_b=identical
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=fake_provider):
        router = SkillRouter()
        router.update_skills([skill_a, skill_b])
        result = router.match("use the special keyword please")

    assert result is not None
    assert (
        result.name == "skill-a"
    ), f"Expected trigger-matched skill-a, got {result.name if result else None}"


# ---------------------------------------------------------------------------
# Test 5: update_skills() re-embeds when skill list changes
# ---------------------------------------------------------------------------


def test_update_skills_reembeds():
    """Calling update_skills() with new manifests replaces old skills and re-embeds."""
    old_skill = _make_manifest("old-skill", "old description")
    new_skill = _make_manifest("new-skill", "new description for new functionality")

    # First load with old_skill -> [1.0, 0.0, 0.0]
    # Query -> [0.9, 0.1, 0.0] matches old_skill

    initial_provider = _make_fake_provider(
        query_vec=[0.9, 0.1, 0.0],
        doc_vecs=[[1.0, 0.0, 0.0]],
    )

    # After update, only new_skill exists -> [0.0, 1.0, 0.0]
    # Query -> [0.1, 0.9, 0.0] matches new_skill
    updated_provider = _make_fake_provider(
        query_vec=[0.1, 0.9, 0.0],
        doc_vecs=[[0.0, 1.0, 0.0]],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider") as mock_get:
        # First call (initial load) uses initial_provider
        mock_get.return_value = initial_provider
        router = SkillRouter()
        router.update_skills([old_skill])

        # Switch the query vector for the initial state check
        result_before = router.match("old thing")
        assert result_before is not None and result_before.name == "old-skill"

        # Now update skills with new_skill using updated_provider
        mock_get.return_value = updated_provider
        router.update_skills([new_skill])

        # After update, query should match new_skill
        result_after = router.match("new functionality request")
        assert (
            result_after is not None and result_after.name == "new-skill"
        ), f"Expected new-skill after update, got {result_after}"


# ---------------------------------------------------------------------------
# Test 6: Graceful fallback to trigger-only when no embedding provider
# ---------------------------------------------------------------------------


def test_no_provider_trigger_only_fallback():
    """When no embedding provider is available, trigger matching still works."""
    skill = _make_manifest(
        "no-embed-skill",
        "this skill has no embedding support",
        triggers=["activate no embed"],
    )

    # Simulate no provider by returning None
    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=None):
        router = SkillRouter()
        router.update_skills([skill])

        # Trigger match should work without embeddings
        trigger_result = router.match("please activate no embed now")
        assert trigger_result is not None, "Expected trigger match without provider"
        assert trigger_result.name == "no-embed-skill"

        # Non-trigger match should return None (no embeddings available)
        no_match_result = router.match("something completely different")
        assert no_match_result is None, "Expected None when no provider and no trigger match"


# ---------------------------------------------------------------------------
# Test 7: Cosine similarity threshold is configurable
# ---------------------------------------------------------------------------


def test_configurable_threshold():
    """SkillRouter respects custom threshold — higher threshold means fewer matches."""
    skill = _make_manifest("threshold-skill", "skill for threshold testing")

    # cos([0.8, 0.6, 0.0], [1.0, 0.0, 0.0]) = 0.8 / (1.0 * 1.0) = 0.8
    # cos([0.8, 0.6, 0.0], [1.0, 0.0, 0.0]) = 0.8
    fake_provider = _make_fake_provider(
        query_vec=[0.8, 0.6, 0.0],
        doc_vecs=[[1.0, 0.0, 0.0]],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=fake_provider):
        # With threshold=0.7, score=0.8 should match
        router_low = SkillRouter(threshold=0.7)
        router_low.update_skills([skill])
        result_low = router_low.match("test message")
        assert result_low is not None, "Expected match with threshold=0.7 and score=0.8"

        # With threshold=0.9, score=0.8 should NOT match
        router_high = SkillRouter(threshold=0.9)
        router_high.update_skills([skill])
        result_high = router_high.match("test message")
        assert result_high is None, "Expected no match with threshold=0.9 and score=0.8"


# ---------------------------------------------------------------------------
# Test 8: Empty skill list always returns None
# ---------------------------------------------------------------------------


def test_empty_skill_list_returns_none():
    """With no skills loaded, match() always returns None."""
    router = SkillRouter()
    router.update_skills([])

    result = router.match("any message at all")
    assert result is None, f"Expected None for empty skill list, got {result}"


# ---------------------------------------------------------------------------
# Additional tests for edge cases
# ---------------------------------------------------------------------------


def test_default_threshold_is_0_45():
    """Default threshold should be 0.45."""
    router = SkillRouter()
    assert router._threshold == 0.45


def test_multiple_triggers_any_matches():
    """A skill with multiple triggers matches if any trigger is found."""
    skill = _make_manifest(
        "multi-trigger-skill",
        "skill with multiple triggers",
        triggers=["trigger alpha", "trigger beta", "trigger gamma"],
    )

    with patch("sci_fi_dashboard.skills.router.get_provider", return_value=None):
        router = SkillRouter()
        router.update_skills([skill])

        assert router.match("use trigger beta here") is not None
        assert router.match("trigger gamma please") is not None
        assert router.match("trigger alpha now") is not None
        assert router.match("no trigger here") is None
