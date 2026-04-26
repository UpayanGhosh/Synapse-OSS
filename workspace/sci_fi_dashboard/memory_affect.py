"""Affect-aware memory helpers.

This module keeps emotional context as a safe overlay on top of ``documents``.
It is deterministic by design so memory writes do not depend on cloud LLMs.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

EXTRACTOR_VERSION = "heuristic-v1"


@dataclass(frozen=True)
class AffectTags:
    sentiment: str = "neutral"
    mood: str = "neutral"
    emotional_intensity: float = 0.0
    tension_type: str = "none"
    user_need: str = "none"
    response_style_hint: str = "warm"
    topics: list[str] = field(default_factory=list)
    confidence: float = 0.0
    extractor_version: str = EXTRACTOR_VERSION


MOOD_PATTERNS: dict[str, list[str]] = {
    "hurt": [
        r"\bhurt\b",
        r"\bunseen\b",
        r"\bignored?\b",
        r"\bforgot\b",
        r"\bforgotten\b",
        r"\bdismissed\b",
    ],
    "anxious": [r"\banxious\b", r"\bworried\b", r"\bscared\b", r"\bpanic\b", r"\btension\b"],
    "frustrated": [
        r"\bstuck\b",
        r"\bfrustrated\b",
        r"\bstressed\b",
        r"\bdeadline\b",
        r"\bpressure\b",
        r"\bbroken\b",
    ],
    "lonely": [r"\blonely\b", r"\balone\b", r"\bmissing\b", r"\bmiss\b", r"\babandoned\b"],
    "excited": [r"\blet'?s go\b", r"\bexcited\b", r"\bworks\b", r"!!+", r"\bamazing\b"],
    "proud": [r"\bproud\b", r"\bwon\b", r"\bfinished\b", r"\bshipped\b", r"\bgraduated\b"],
    "playful": [r"\blol\b", r"\bhaha+\b", r"\btease\b", r"\bgoofy\b", r"\bfunny\b"],
    "tired": [r"\btired\b", r"\bexhausted\b", r"\bsleepy\b", r"\bdrained\b"],
    "focused": [
        r"\bbuild\b",
        r"\bdebug\b",
        r"\bimplement\b",
        r"\barchitecture\b",
        r"\bcode\b",
    ],
    "vulnerable": [r"\bvulnerable\b", r"\bopened up\b", r"\bcry\b", r"\bcrying\b"],
}

TENSION_PATTERNS: dict[str, list[str]] = {
    "neglect": [r"\bunseen\b", r"\bignored?\b", r"\bforgot\b", r"\bpriority\b", r"\babsent\b"],
    "rejection": [r"\breject", r"\bdesired\b", r"\bunwanted\b", r"\bnot enough\b"],
    "conflict": [r"\bfight\b", r"\bargument\b", r"\bwrong\b", r"\bmisunderstood\b"],
    "uncertainty": [r"\bconfused\b", r"\bunsure\b", r"\bdon't know\b", r"\buncertain\b"],
    "pressure": [r"\bstressed\b", r"\bdeadline\b", r"\bpressure\b", r"\boverwhelmed\b", r"\bwork\b"],
    "boundary": [r"\bboundar", r"\blimit\b", r"\brespect\b", r"\bspace\b"],
    "growth": [r"\bfinished\b", r"\bshipped\b", r"\bimproved\b", r"\bprogress\b", r"\bwon\b"],
    "desire": [r"\bdesire\b", r"\bintimacy\b", r"\bflirt\b", r"\bsexual\b", r"\btouch\b"],
    "safety": [r"\bsafe\b", r"\bprotect\b", r"\bcomfort\b", r"\breassur"],
}

NEED_PATTERNS: dict[str, list[str]] = {
    "validation": [r"\bunseen\b", r"\bignored?\b", r"\bheard\b", r"\bunderstood\b"],
    "reassurance": [r"\breassur", r"\bscared\b", r"\banxious\b", r"\bworried\b"],
    "clarity": [r"\bstuck\b", r"\bconfused\b", r"\bwhat should\b", r"\bdeadline\b", r"\bwork\b"],
    "comfort": [r"\bhurt\b", r"\bcry", r"\bsad\b", r"\blonely\b"],
    "space": [r"\bspace\b", r"\bboundar", r"\blimit\b"],
    "accountability": [r"\bforgot\b", r"\bagain\b", r"\bchanged?\b", r"\beffort\b"],
    "encouragement": [r"\bfinished\b", r"\bshipped\b", r"\btrying\b", r"\bprogress\b"],
    "playfulness": [r"\blol\b", r"\bhaha+\b", r"\btease\b", r"\bfun\b"],
    "directness": [r"\bbe honest\b", r"\btell me\b", r"\bdirect\b"],
    "protection": [r"\bunsafe\b", r"\bprotect\b", r"\bscared\b"],
}

STYLE_FOR_NEED = {
    "validation": "soft",
    "reassurance": "soft",
    "clarity": "grounding",
    "comfort": "soft",
    "space": "firm",
    "accountability": "direct",
    "encouragement": "celebratory",
    "playfulness": "playful",
    "directness": "direct",
    "protection": "protective",
    "none": "warm",
}

POSITIVE_PATTERNS = [
    r"\blove\b",
    r"\bhappy\b",
    r"\bexcited\b",
    r"\bproud\b",
    r"\bgrateful\b",
    r"\bamazing\b",
    r"\bworks\b",
    r"\bwon\b",
    r"\bfinished\b",
]

NEGATIVE_PATTERNS = [
    r"\bhurt\b",
    r"\bsad\b",
    r"\bangry\b",
    r"\banxious\b",
    r"\bworried\b",
    r"\bignored?\b",
    r"\bunseen\b",
    r"\blonely\b",
    r"\bstressed\b",
    r"\bfrustrated\b",
    r"\boverwhelmed\b",
    r"\bscared\b",
]

STOPWORDS = {
    "about",
    "again",
    "because",
    "feel",
    "from",
    "have",
    "that",
    "this",
    "with",
    "what",
    "when",
    "where",
    "which",
    "while",
    "would",
    "should",
}


def ensure_memory_affect_table(conn: sqlite3.Connection) -> None:
    """Create the affect overlay table and indexes idempotently."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memory_affect (
            doc_id              INTEGER PRIMARY KEY,
            sentiment           TEXT NOT NULL DEFAULT 'neutral',
            mood                TEXT NOT NULL DEFAULT 'neutral',
            emotional_intensity REAL NOT NULL DEFAULT 0.0,
            tension_type        TEXT NOT NULL DEFAULT 'none',
            user_need           TEXT NOT NULL DEFAULT 'none',
            response_style_hint TEXT NOT NULL DEFAULT 'warm',
            topics_json         TEXT NOT NULL DEFAULT '[]',
            confidence          REAL NOT NULL DEFAULT 0.0,
            extractor_version   TEXT NOT NULL DEFAULT 'heuristic-v1',
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_memory_affect_mood
            ON memory_affect(mood);
        CREATE INDEX IF NOT EXISTS idx_memory_affect_tension
            ON memory_affect(tension_type);
        CREATE INDEX IF NOT EXISTS idx_memory_affect_need
            ON memory_affect(user_need);
    """)
    conn.commit()


def _pattern_scores(text: str, groups: dict[str, list[str]]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for label, patterns in groups.items():
        score = sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))
        if score:
            scores[label] = score
    return scores


def _best_label(scores: dict[str, int], default: str) -> str:
    if not scores:
        return default
    return max(scores, key=lambda key: (scores[key], -list(scores).index(key)))


def _count_patterns(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def _sentiment(text: str) -> str:
    positive = _count_patterns(text, POSITIVE_PATTERNS)
    negative = _count_patterns(text, NEGATIVE_PATTERNS)
    if positive and negative:
        return "mixed"
    if positive:
        return "positive"
    if negative:
        return "negative"
    return "neutral"


def _topics(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z_'-]{3,}", text.lower())
    topics: list[str] = []
    for word in words:
        if word in STOPWORDS or word in topics:
            continue
        topics.append(word)
        if len(topics) >= 5:
            break
    return topics


def extract_affect(text: str) -> AffectTags:
    """Extract deterministic affect tags from text."""
    compact = " ".join(str(text or "").split())
    if not compact:
        return AffectTags()

    lower = compact.lower()
    mood_scores = _pattern_scores(lower, MOOD_PATTERNS)
    tension_scores = _pattern_scores(lower, TENSION_PATTERNS)
    need_scores = _pattern_scores(lower, NEED_PATTERNS)

    mood = _best_label(mood_scores, "neutral")
    tension_type = _best_label(tension_scores, "none")
    user_need = _best_label(need_scores, "none")
    if mood == "hurt" and tension_type == "neglect":
        user_need = "validation"
    elif tension_type == "pressure":
        user_need = "clarity"
    response_style_hint = STYLE_FOR_NEED.get(user_need, "warm")
    sentiment = _sentiment(lower)

    signal_count = sum(mood_scores.values()) + sum(tension_scores.values()) + sum(need_scores.values())
    punctuation_boost = 0.1 if re.search(r"!!+|\?\?+", compact) else 0.0
    direct_distress_boost = 0.15 if re.search(r"\bi feel\b|\bi am\b|\bi'm\b", lower) else 0.0
    emotional_intensity = min(1.0, (signal_count / 8.0) + punctuation_boost + direct_distress_boost)
    confidence = min(1.0, 0.2 + (signal_count / 8.0))
    if mood == "neutral" and tension_type == "none" and user_need == "none":
        confidence = 0.0
        emotional_intensity = 0.0

    return AffectTags(
        sentiment=sentiment,
        mood=mood,
        emotional_intensity=round(emotional_intensity, 3),
        tension_type=tension_type,
        user_need=user_need,
        response_style_hint=response_style_hint,
        topics=_topics(lower),
        confidence=round(confidence, 3),
    )


def upsert_memory_affect(conn: sqlite3.Connection, doc_id: int, tags: AffectTags) -> None:
    """Insert or update affect tags for a document."""
    ensure_memory_affect_table(conn)
    conn.execute(
        """
        INSERT INTO memory_affect
            (doc_id, sentiment, mood, emotional_intensity, tension_type, user_need,
             response_style_hint, topics_json, confidence, extractor_version, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(doc_id) DO UPDATE SET
            sentiment = excluded.sentiment,
            mood = excluded.mood,
            emotional_intensity = excluded.emotional_intensity,
            tension_type = excluded.tension_type,
            user_need = excluded.user_need,
            response_style_hint = excluded.response_style_hint,
            topics_json = excluded.topics_json,
            confidence = excluded.confidence,
            extractor_version = excluded.extractor_version,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(doc_id),
            tags.sentiment,
            tags.mood,
            float(tags.emotional_intensity),
            tags.tension_type,
            tags.user_need,
            tags.response_style_hint,
            json.dumps(tags.topics, ensure_ascii=False),
            float(tags.confidence),
            tags.extractor_version,
        ),
    )


def _row_to_tags(row: sqlite3.Row | tuple[Any, ...]) -> AffectTags:
    if isinstance(row, sqlite3.Row):
        data = dict(row)
    else:
        keys = [
            "doc_id",
            "sentiment",
            "mood",
            "emotional_intensity",
            "tension_type",
            "user_need",
            "response_style_hint",
            "topics_json",
            "confidence",
            "extractor_version",
        ]
        data = dict(zip(keys, row, strict=False))
    try:
        topics = json.loads(data.get("topics_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        topics = []
    return AffectTags(
        sentiment=str(data.get("sentiment") or "neutral"),
        mood=str(data.get("mood") or "neutral"),
        emotional_intensity=float(data.get("emotional_intensity") or 0.0),
        tension_type=str(data.get("tension_type") or "none"),
        user_need=str(data.get("user_need") or "none"),
        response_style_hint=str(data.get("response_style_hint") or "warm"),
        topics=[str(t) for t in topics[:5]] if isinstance(topics, list) else [],
        confidence=float(data.get("confidence") or 0.0),
        extractor_version=str(data.get("extractor_version") or EXTRACTOR_VERSION),
    )


def load_affect_for_doc_ids(
    conn: sqlite3.Connection, doc_ids: list[int] | tuple[int, ...]
) -> dict[int, AffectTags]:
    """Load affect tags for document IDs."""
    clean_ids = [int(doc_id) for doc_id in doc_ids if doc_id is not None]
    if not clean_ids:
        return {}

    placeholders = ",".join("?" for _ in clean_ids)
    cursor = conn.execute(
        f"""
        SELECT doc_id, sentiment, mood, emotional_intensity, tension_type, user_need,
               response_style_hint, topics_json, confidence, extractor_version
        FROM memory_affect
        WHERE doc_id IN ({placeholders})
        """,
        clean_ids,
    )
    return {int(row[0]): _row_to_tags(row) for row in cursor.fetchall()}


def score_affect_match(query: AffectTags, memory: AffectTags | None) -> float:
    """Return 0..1 match score between current affect and memory affect."""
    if memory is None:
        return 0.0
    if query.emotional_intensity < 0.25 and query.confidence < 0.35:
        return 0.0

    score = 0.0
    if query.mood == memory.mood and query.mood != "neutral":
        score += 0.30
    if query.tension_type == memory.tension_type and query.tension_type != "none":
        score += 0.30
    if query.user_need == memory.user_need and query.user_need != "none":
        score += 0.25
    if (
        query.response_style_hint == memory.response_style_hint
        and query.response_style_hint != "warm"
    ):
        score += 0.10
    score += 0.05 * (1.0 - abs(query.emotional_intensity - memory.emotional_intensity))

    confidence = min(1.0, max(query.confidence, memory.confidence))
    return round(min(1.0, score * confidence), 4)


def tags_to_public_dict(tags: AffectTags, score: float = 0.0) -> dict[str, Any]:
    """Compact metadata safe for internal prompts/logs."""
    data = asdict(tags)
    data.pop("extractor_version", None)
    data["score"] = score
    return data


def _coerce_hint_row(row: dict[str, Any] | AffectTags) -> dict[str, Any]:
    if isinstance(row, AffectTags):
        return asdict(row)
    return dict(row)


def format_affect_hints(rows: list[dict[str, Any] | AffectTags], limit: int = 3) -> str:
    """Format subtle prompt hints from affect metadata."""
    clean = [_coerce_hint_row(row) for row in rows[:limit] if row]
    clean = [
        row
        for row in clean
        if row.get("mood", "neutral") != "neutral"
        or row.get("tension_type", "none") != "none"
        or row.get("user_need", "none") != "none"
    ]
    if not clean:
        return ""

    lines = ["[EMOTIONAL MEMORY SIGNALS]"]
    for row in clean:
        style = str(row.get("response_style_hint") or "warm")
        need = str(row.get("user_need") or "none")
        tension = str(row.get("tension_type") or "none")
        mood = str(row.get("mood") or "neutral")
        phrase = f"similar past mood: {mood}"
        if tension != "none":
            phrase += f", pattern: {tension}"
        if need != "none":
            phrase += f", likely need: {need}"
        phrase += f"; respond {style.replace('_', ' ')}ly"
        if style == "soft":
            phrase = phrase.replace("respond softlyly", "respond softly")
        lines.append(f"- {phrase}.")
    return "\n".join(lines)
