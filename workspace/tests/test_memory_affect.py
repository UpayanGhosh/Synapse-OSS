import sqlite3
import sys
import importlib.util
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


def _load_backfill_module():
    script = _WORKSPACE / "scripts" / "personal" / "backfill_memory_affect.py"
    assert script.exists(), f"missing script: {script}"
    spec = importlib.util.spec_from_file_location("backfill_memory_affect", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_extract_core_life_emotions():
    cases = [
        ("I am anxious about tomorrow and scared I will mess it up", "anxious", "negative"),
        ("I am angry and pissed that he lied", "angry", "negative"),
        ("I feel sad and lonely tonight", "sad", "negative"),
        ("I love her and feel soft about this", "loving", "positive"),
        ("I am happy and grateful today", "happy", "positive"),
    ]

    for text, expected_mood, expected_sentiment in cases:
        tags = extract_affect(text)
        assert tags.mood == expected_mood
        assert tags.sentiment == expected_sentiment
        assert tags.confidence > 0


def test_extract_keeps_mixed_emotion_tags():
    tags = extract_affect(
        "I felt quietly happy and loved, but also lonely when the room got quiet."
    )

    assert tags.sentiment == "mixed"
    assert {"happy", "loving", "lonely"}.issubset(set(tags.emotion_tags))


def test_extract_jealousy_as_grounding_need():
    tags = extract_affect(
        "I saw someone I like laughing with someone else and my stomach just dropped. "
        "I know it sounds needy, but I hate how jealous I got."
    )

    assert tags.sentiment == "negative"
    assert tags.mood == "jealous"
    assert tags.tension_type == "insecurity"
    assert tags.user_need == "grounding"
    assert tags.response_style_hint == "grounding"
    assert tags.emotional_intensity >= 0.5


def test_session_archive_affect_prefers_user_lines():
    tags = extract_affect(
        "[Telegram session — 2026-04-30]\n"
        "User: I saw someone I like laughing with someone else today and my stomach "
        "just dropped. I hate how jealous I got.\n"
        "Me: Don't build a whole movie off one laugh; don't let the feeling start "
        "writing strategy for you."
    )

    assert tags.mood == "jealous"
    assert tags.tension_type == "insecurity"
    assert "focused" not in tags.emotion_tags


def test_extract_implicit_relationship_insecurity():
    tags = extract_affect(
        "I hate admitting this, but seeing the person I like get so comfortable "
        "with someone else made me feel small. My brain knows it is probably "
        "nothing, but my chest is doing drama."
    )

    assert tags.sentiment == "negative"
    assert tags.mood == "jealous"
    assert tags.tension_type == "insecurity"
    assert tags.user_need == "grounding"
    assert tags.response_style_hint == "grounding"


def test_extract_overthinking_crush_body_drop_as_insecurity():
    tags = extract_affect(
        "I’m overthinking something dumb. I like someone, but when she talks to "
        "another guy normally my stomach drops like an idiot. I know it’s childish, "
        "but it’s messing with my head."
    )

    assert tags.sentiment == "negative"
    assert tags.mood in {"jealous", "anxious"}
    assert tags.mood != "loving"
    assert tags.tension_type == "insecurity"
    assert tags.user_need == "grounding"
    assert "loving" not in tags.emotion_tags[:1]


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


def test_backfill_select_documents_without_affect_excludes_existing():
    module = _load_backfill_module()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)
    conn.execute("INSERT INTO documents (id, content) VALUES (1, 'hurt'), (2, 'neutral')")
    upsert_memory_affect(conn, 1, extract_affect("hurt"))

    rows = module.select_documents_without_affect(conn, limit=10, since_id=0)

    assert [row["id"] for row in rows] == [2]


def test_backfill_dry_run_writes_no_affect_rows(tmp_path):
    module = _load_backfill_module()
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, content TEXT)")
    ensure_memory_affect_table(conn)
    conn.execute("INSERT INTO documents (id, content) VALUES (1, 'I feel ignored')")
    conn.commit()
    conn.close()

    result = module.backfill(db_path, limit=10, dry_run=True, force=False, since_id=0)

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM memory_affect").fetchone()[0]
    conn.close()
    assert result["dry_run"] is True
    assert result["candidates"] == 1
    assert count == 0
