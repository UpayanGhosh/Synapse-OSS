from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

TIER_DEFAULT_THRESHOLDS: dict[str, float] = {
    "frontier": 0.92,
    "strong_open": 0.85,
    "mid_open": 0.75,
    "small": 0.60,
}


@dataclass(frozen=True)
class ModelResponse:
    """Normalized response captured from one model for one scenario."""

    text: str
    model: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    latency_ms: int | None = None


@dataclass(frozen=True)
class ScoreResult:
    """Score for one scenario/model response."""

    score: float
    passed: bool
    reason: str
    similarity: float | None = None
    threshold: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def score_response(
    scenario: Any,
    response: ModelResponse,
    *,
    tier: str = "frontier",
    similarity_backend: Any | None = None,
) -> ScoreResult:
    """Score a model response against a scenario scoring block."""

    scoring = _scenario_scoring(scenario)
    method = str(scoring.get("method", "regex")).strip().lower()
    if method in {"regex", "contains"}:
        return _score_regex(scoring, response)
    if method == "embedding_similarity":
        return _score_embedding(scoring, response, tier, similarity_backend)
    if method == "tool_assertion":
        return _score_tool(scoring, response)
    if method == "hybrid":
        return _score_hybrid(scoring, response, tier, similarity_backend)
    raise ValueError(f"Unsupported scoring method: {method!r}")


def _scenario_scoring(scenario: Any) -> dict[str, Any]:
    if isinstance(scenario, dict):
        scoring = scenario.get("scoring", {})
    else:
        scoring = getattr(scenario, "scoring", {})
    if not isinstance(scoring, dict):
        raise TypeError("scenario.scoring must be a mapping")
    return scoring


def _score_regex(scoring: dict[str, Any], response: ModelResponse) -> ScoreResult:
    checks: list[tuple[str, bool]] = []
    text = response.text or ""

    for needle in _as_list(scoring.get("must_contain")):
        checks.append((f"contains:{needle}", _contains(text, needle)))

    any_needles = _as_list(scoring.get("must_contain_any"))
    if any_needles:
        checks.append(
            (
                "contains_any:" + "|".join(str(n) for n in any_needles),
                any(_contains(text, needle) for needle in any_needles),
            )
        )

    for pattern in _as_list(scoring.get("must_match")):
        checks.append((f"matches:{pattern}", _matches(text, pattern)))

    for forbidden in _as_list(scoring.get("forbidden")):
        checks.append((f"forbidden_absent:{forbidden}", not _contains(text, forbidden)))

    if not checks:
        return ScoreResult(score=1.0, passed=True, reason="no regex checks configured")

    failures = [name for name, ok in checks if not ok]
    score = (len(checks) - len(failures)) / len(checks)
    passed = not failures
    reason = "passed" if passed else "failed checks: " + ", ".join(failures)
    return ScoreResult(score=round(score, 4), passed=passed, reason=reason)


def _score_embedding(
    scoring: dict[str, Any],
    response: ModelResponse,
    tier: str,
    similarity_backend: Any | None,
) -> ScoreResult:
    gold = scoring.get("gold") or scoring.get("embedding_gold")
    if not gold:
        return ScoreResult(score=0.0, passed=False, reason="missing gold text")

    threshold = _threshold_for_tier(scoring, tier)
    similarity = text_similarity(response.text, str(gold), backend=similarity_backend)
    passed = similarity >= threshold
    return ScoreResult(
        score=round(similarity, 4),
        passed=passed,
        reason="passed" if passed else f"similarity {similarity:.4f} < {threshold:.4f}",
        similarity=round(similarity, 4),
        threshold=threshold,
    )


def _score_tool(scoring: dict[str, Any], response: ModelResponse) -> ScoreResult:
    checks: list[tuple[str, bool]] = []
    text_blob = _tool_text_blob(response)
    tool_names = {str(t).lower() for t in response.tools_used}

    must_tool = scoring.get("must_call_tool")
    if must_tool:
        checks.append((f"called_tool:{must_tool}", str(must_tool).lower() in tool_names))

    for needle in _as_list(scoring.get("must_contain_in_output")):
        checks.append((f"output_contains:{needle}", _contains(text_blob, needle)))

    for forbidden in _as_list(scoring.get("forbidden")):
        checks.append((f"forbidden_absent:{forbidden}", not _contains(text_blob, forbidden)))

    if not checks:
        return ScoreResult(score=1.0, passed=True, reason="no tool checks configured")

    failures = [name for name, ok in checks if not ok]
    score = (len(checks) - len(failures)) / len(checks)
    passed = not failures
    reason = "passed" if passed else "failed checks: " + ", ".join(failures)
    return ScoreResult(score=round(score, 4), passed=passed, reason=reason)


def _score_hybrid(
    scoring: dict[str, Any],
    response: ModelResponse,
    tier: str,
    similarity_backend: Any | None,
) -> ScoreResult:
    hard = _score_regex(scoring, response)
    gold = scoring.get("embedding_gold") or scoring.get("gold")
    if not gold:
        return hard

    embedding = _score_embedding(
        {**scoring, "gold": gold},
        response,
        tier,
        similarity_backend,
    )
    passed = hard.passed and embedding.passed
    score = (hard.score + embedding.score) / 2
    reasons = []
    if not hard.passed:
        reasons.append(hard.reason)
    if not embedding.passed:
        reasons.append(embedding.reason)
    return ScoreResult(
        score=round(score, 4),
        passed=passed,
        reason="passed" if passed else "; ".join(reasons),
        similarity=embedding.similarity,
        threshold=embedding.threshold,
        details={"hard_score": hard.score, "embedding_score": embedding.score},
    )


def text_similarity(text: str, gold: str, *, backend: Any | None = None) -> float:
    """Return semantic-ish similarity, using embeddings when provided."""

    if backend is not None:
        if hasattr(backend, "similarity"):
            return _clamp(float(backend.similarity(text, gold)))
        if hasattr(backend, "embed_documents"):
            vectors = backend.embed_documents([text, gold])
            if len(vectors) >= 2:
                return _cosine(vectors[0], vectors[1])
        if hasattr(backend, "embed_query"):
            return _cosine(backend.embed_query(text), backend.embed_query(gold))
    return lexical_similarity(text, gold)


def lexical_similarity(text: str, gold: str) -> float:
    """Deterministic fallback for tests or machines without embeddings."""

    a = _tokens(text)
    b = _tokens(gold)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    jaccard = len(a & b) / len(a | b)
    sequence = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return _clamp((jaccard * 0.7) + (sequence * 0.3))


def _threshold_for_tier(scoring: dict[str, Any], tier: str) -> float:
    thresholds = scoring.get("threshold_per_tier")
    if isinstance(thresholds, dict):
        if tier in thresholds:
            return float(thresholds[tier])
        if "default" in thresholds:
            return float(thresholds["default"])
    if scoring.get("threshold") is not None:
        return float(scoring["threshold"])
    return TIER_DEFAULT_THRESHOLDS.get(tier, TIER_DEFAULT_THRESHOLDS["frontier"])


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]


def _contains(text: str, needle: Any) -> bool:
    return str(needle).casefold() in text.casefold()


def _matches(text: str, pattern: Any) -> bool:
    return re.search(str(pattern), text, flags=re.IGNORECASE | re.MULTILINE) is not None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _tool_text_blob(response: ModelResponse) -> str:
    parts = [response.text, *response.tool_outputs]
    if response.raw:
        parts.append(json.dumps(response.raw, default=str, sort_keys=True))
    return "\n".join(str(p) for p in parts if p is not None)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return _clamp(dot / (norm_a * norm_b))


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
