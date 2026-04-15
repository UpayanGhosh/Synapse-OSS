"""
Test Suite: SBS ExemplarSelector
=================================
Tests for the principled few-shot exemplar selection algorithm.

Covers:
- Building conversation pairs from DB (response_to and adjacency fallback)
- Scoring pairs (recency, quality, language richness, mood)
- Slot allocation (recent, topic-diverse, mood-diverse, banglish, personality, wildcard)
- Format output
- Edge cases (empty DB, no pairs, no matching slots)
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sbs.processing.selectors.exemplar import ExemplarSelector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_db(db_path: Path, messages: list[tuple]):
    """Create a messages DB and insert rows."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                msg_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                session_id TEXT,
                response_to TEXT,
                char_count INTEGER,
                word_count INTEGER,
                has_emoji BOOLEAN,
                is_question BOOLEAN,
                rt_sentiment REAL,
                rt_language TEXT,
                rt_mood_signal TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            messages,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExemplarSelector:
    """Tests for ExemplarSelector few-shot selection."""

    @pytest.fixture
    def populated_db(self, tmp_path):
        """DB with user-assistant pairs covering various topics and moods."""
        db_path = tmp_path / "messages.db"
        now = datetime.now()
        messages = [
            # Recent pair with response_to
            (
                "u1",
                now.isoformat(),
                "user",
                "hey bhai, let me implement the python api endpoint",
                "s1",
                None,
                50,
                9,
                0,
                0,
                0.3,
                "mixed",
                "focused",
            ),
            (
                "a1",
                now.isoformat(),
                "assistant",
                "sure bhai, let me build the fastapi route for you. chal dekh this approach",
                "s1",
                "u1",
                60,
                12,
                0,
                0,
                0.5,
                "mixed",
                None,
            ),
            # Banglish pair
            (
                "u2",
                (now - timedelta(hours=12)).isoformat(),
                "user",
                "arey chai khaowa ghum lyadh",
                "s1",
                None,
                25,
                5,
                0,
                0,
                -0.2,
                "banglish",
                "tired",
            ),
            (
                "a2",
                (now - timedelta(hours=12)).isoformat(),
                "assistant",
                "arey bhai, rest kor ektu! chai baniye dichi",
                "s1",
                "u2",
                40,
                7,
                0,
                0,
                0.3,
                "banglish",
                None,
            ),
            # Personal/mood pair
            (
                "u3",
                (now - timedelta(days=2)).isoformat(),
                "user",
                "feeling stressed about the deadline, pressure is real",
                "s1",
                None,
                45,
                8,
                0,
                0,
                -0.4,
                "en",
                "stressed",
            ),
            (
                "a3",
                (now - timedelta(days=2)).isoformat(),
                "assistant",
                "I understand, lets break it down into smaller tasks and prioritize",
                "s1",
                "u3",
                55,
                10,
                0,
                0,
                0.2,
                "en",
                None,
            ),
            # Planning pair
            (
                "u4",
                (now - timedelta(days=5)).isoformat(),
                "user",
                "plan the todo schedule for this project goal",
                "s1",
                None,
                40,
                7,
                0,
                0,
                0.0,
                "en",
                None,
            ),
            (
                "a4",
                (now - timedelta(days=5)).isoformat(),
                "assistant",
                "here is your project schedule with clear milestones and deliverables",
                "s1",
                "u4",
                55,
                9,
                0,
                0,
                0.1,
                "en",
                None,
            ),
            # Playful pair
            (
                "u5",
                (now - timedelta(hours=6)).isoformat(),
                "user",
                "haha lol moja that was hilarious",
                "s1",
                None,
                30,
                6,
                0,
                0,
                0.6,
                "mixed",
                "playful",
            ),
            (
                "a5",
                (now - timedelta(hours=6)).isoformat(),
                "assistant",
                "haha glad you liked it! arey more jokes coming",
                "s1",
                "u5",
                35,
                7,
                0,
                0,
                0.5,
                "mixed",
                None,
            ),
        ]
        _create_db(db_path, messages)
        return db_path

    @pytest.fixture
    def empty_db(self, tmp_path):
        """DB with the messages table but no rows."""
        db_path = tmp_path / "empty.db"
        _create_db(db_path, [])
        return db_path

    @pytest.mark.unit
    def test_select_returns_list(self, populated_db):
        """select() should return a list of formatted exemplars."""
        selector = ExemplarSelector(populated_db)
        results = selector.select(max_exemplars=14)
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.unit
    def test_select_respects_max_exemplars(self, populated_db):
        """select() should not exceed max_exemplars."""
        selector = ExemplarSelector(populated_db)
        results = selector.select(max_exemplars=3)
        assert len(results) <= 3

    @pytest.mark.unit
    def test_empty_db_returns_empty_list(self, empty_db):
        """select() on an empty DB should return an empty list."""
        selector = ExemplarSelector(empty_db)
        results = selector.select()
        assert results == []

    @pytest.mark.unit
    def test_build_pairs_uses_response_to(self, populated_db):
        """_build_pairs should match user->assistant via response_to."""
        selector = ExemplarSelector(populated_db)
        pairs = selector._build_pairs()
        assert len(pairs) >= 5
        # Each pair should have user_msg and assistant_msg
        for pair in pairs:
            assert pair["user_msg"]["role"] == "user"
            assert pair["assistant_msg"]["role"] == "assistant"

    @pytest.mark.unit
    def test_build_pairs_adjacency_fallback(self, tmp_path):
        """When response_to is None, _build_pairs should use adjacency."""
        db_path = tmp_path / "adj.db"
        now = datetime.now()
        messages = [
            ("u1", now.isoformat(), "user", "hello", "s1", None, 5, 1, 0, 0, 0.0, "en", None),
            (
                "a1",
                now.isoformat(),
                "assistant",
                "hi there",
                "s1",
                None,
                8,
                2,
                0,
                0,
                0.0,
                "en",
                None,
            ),  # No response_to
        ]
        _create_db(db_path, messages)

        selector = ExemplarSelector(db_path)
        pairs = selector._build_pairs()
        assert len(pairs) == 1
        assert pairs[0]["user_msg"]["content"] == "hello"
        assert pairs[0]["assistant_msg"]["content"] == "hi there"

    @pytest.mark.unit
    def test_score_pairs_assigns_scores(self, populated_db):
        """_score_pairs should add a 'scores' dict to each pair."""
        selector = ExemplarSelector(populated_db)
        pairs = selector._build_pairs()
        scored = selector._score_pairs(pairs)

        for pair in scored:
            assert "scores" in pair
            assert "composite" in pair["scores"]
            assert "recency" in pair["scores"]
            assert "length" in pair["scores"]

    @pytest.mark.unit
    def test_score_pairs_sorted_by_composite(self, populated_db):
        """_score_pairs should return pairs sorted by composite score descending."""
        selector = ExemplarSelector(populated_db)
        pairs = selector._build_pairs()
        scored = selector._score_pairs(pairs)

        composites = [p["scores"]["composite"] for p in scored]
        assert composites == sorted(composites, reverse=True)

    @pytest.mark.unit
    def test_format_exemplar_structure(self, populated_db):
        """Formatted exemplars should have the expected keys."""
        selector = ExemplarSelector(populated_db)
        results = selector.select(max_exemplars=1)
        assert len(results) >= 1

        ex = results[0]
        assert "pair_id" in ex
        assert "user" in ex
        assert "assistant" in ex
        assert "context" in ex
        assert "mood" in ex["context"]
        assert "language" in ex["context"]
        assert "topic_hint" in ex["context"]
        assert "selected_at" in ex
        assert "original_timestamp" in ex

    @pytest.mark.unit
    def test_infer_topic_technical(self, populated_db):
        """_infer_topic should identify technical keywords."""
        selector = ExemplarSelector(populated_db)
        assert selector._infer_topic("let me implement the code") == "technical"
        assert selector._infer_topic("need to debug this build") == "technical"

    @pytest.mark.unit
    def test_infer_topic_emotional(self, populated_db):
        """_infer_topic should identify emotional keywords."""
        selector = ExemplarSelector(populated_db)
        assert selector._infer_topic("feeling so tired today") == "emotional"

    @pytest.mark.unit
    def test_infer_topic_planning(self, populated_db):
        """_infer_topic should identify planning keywords."""
        selector = ExemplarSelector(populated_db)
        assert selector._infer_topic("plan the todo for next week") == "planning"

    @pytest.mark.unit
    def test_infer_topic_general(self, populated_db):
        """_infer_topic should return general for unrecognized text."""
        selector = ExemplarSelector(populated_db)
        assert selector._infer_topic("random unrelated sentence") == "general"

    @pytest.mark.unit
    def test_select_recent_quality(self, populated_db):
        """_select_recent_quality should return pairs from last 48h."""
        selector = ExemplarSelector(populated_db)
        pairs = selector._build_pairs()
        scored = selector._score_pairs(pairs)
        recent = selector._select_recent_quality(scored, set(), count=4)
        # Should have at least the pairs from the last 48 hours
        assert len(recent) >= 1

    @pytest.mark.unit
    def test_select_banglish_showcase(self, populated_db):
        """_select_banglish_showcase should return pairs with banglish/mixed language."""
        selector = ExemplarSelector(populated_db)
        pairs = selector._build_pairs()
        scored = selector._score_pairs(pairs)
        banglish = selector._select_banglish_showcase(scored, set(), count=2)
        for pair in banglish:
            assert pair["user_msg"].get("rt_language") in ("banglish", "mixed")

    @pytest.mark.unit
    def test_no_duplicate_pairs_in_selection(self, populated_db):
        """The final selection should not contain duplicate pair_ids."""
        selector = ExemplarSelector(populated_db)
        results = selector.select(max_exemplars=14)
        pair_ids = [r["pair_id"] for r in results]
        assert len(pair_ids) == len(set(pair_ids)), "Duplicate pair_ids found"
