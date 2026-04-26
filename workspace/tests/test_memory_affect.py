import sqlite3
import sys
from pathlib import Path

_WORKSPACE = Path(__file__).parent.parent
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from sci_fi_dashboard.memory_affect import (
    AffectTags,
    ensure_memory_affect_table,
    extract_affect,
    format_affect_hints,
    score_affect_match,
    upsert_memory_affect,
)


def test_schema_created():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")

    ensure_memory_affect_table(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_affect)")}
    assert {"doc_id", "mood", "tension_type", "user_need", "response_style_hint"} <= cols


def test_extract_hurt_neglect():
    tags = extract_affect("I feel unseen and hurt because he forgot again")

    assert tags.sentiment == "negative"
    assert tags.mood == "hurt"
    assert tags.tension_type == "neglect"
    assert tags.user_need in {"validation", "reassurance"}
    assert tags.response_style_hint == "soft"
    assert tags.emotional_intensity > 0.4


def test_extract_pressure_grounding():
    tags = extract_affect("I am stuck and stressed about this work deadline")

    assert tags.mood in {"frustrated", "anxious"}
    assert tags.tension_type == "pressure"
    assert tags.user_need == "clarity"
    assert tags.response_style_hint == "grounding"


def test_upsert_and_format_hints():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)

    upsert_memory_affect(conn, 1, extract_affect("I feel ignored and lonely"))

    row = conn.execute("SELECT mood, tension_type, user_need FROM memory_affect WHERE doc_id=1").fetchone()
    assert row[0] in {"hurt", "lonely"}
    hints = format_affect_hints(
        [
            {
                "mood": row[0],
                "tension_type": row[1],
                "user_need": row[2],
                "response_style_hint": "soft",
            }
        ]
    )
    assert "respond softly" in hints.lower()


def test_affect_match_beats_neutral_only_when_query_emotional():
    query = AffectTags(
        mood="hurt",
        sentiment="negative",
        emotional_intensity=0.8,
        tension_type="neglect",
        user_need="validation",
        response_style_hint="soft",
        confidence=0.8,
    )
    matching = AffectTags(
        mood="hurt",
        sentiment="negative",
        emotional_intensity=0.7,
        tension_type="neglect",
        user_need="validation",
        response_style_hint="soft",
        confidence=0.8,
    )
    neutral = AffectTags()

    assert score_affect_match(query, matching) > score_affect_match(query, neutral)
    assert score_affect_match(AffectTags(), matching) == 0.0
