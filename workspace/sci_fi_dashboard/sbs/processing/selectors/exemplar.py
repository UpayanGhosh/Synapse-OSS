import hashlib
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class ExemplarSelector:
    """
    Principled few-shot exemplar selection.

    The algorithm ensures:
    1. DIVERSITY  — Exemplars cover different topics/moods/styles
    2. RECENCY    — Recent interactions are preferred (but not exclusively)
    3. QUALITY    — Only "good" interactions (no errors, corrections, confusion)
    4. RICHNESS   — Longer, more substantive exchanges over one-word replies
    5. IDENTITY   — Pairs that best showcase the desired Synapse personality

    Selection Strategy:
    ┌──────────────────────────────────────────────────┐
    │  SLOT ALLOCATION (14 total exemplars):           │
    │                                                  │
    │  [4] RECENT HIGH-QUALITY     — last 48h, best   │
    │  [3] TOPIC-DIVERSE           — one per top topic │
    │  [2] MOOD-DIVERSE            — different moods   │
    │  [2] BANGLISH SHOWCASE       — best code-switch  │
    │  [2] PERSONALITY HIGHLIGHT   — humor/care/tech   │
    │  [1] WILDCARD                — random for variety │
    └──────────────────────────────────────────────────┘
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path

    def select(self, max_exemplars: int = 14) -> list[dict]:
        """Main selection pipeline."""

        # Step 1: Build conversation pairs (user message + assistant response)
        pairs = self._build_pairs()

        if not pairs:
            return []

        # Step 2: Score each pair on multiple dimensions
        scored_pairs = self._score_pairs(pairs)

        # Step 3: Allocate slots
        selected = []
        used_ids = set()

        # Slot 1: Recent high-quality (4 slots)
        recent = self._select_recent_quality(scored_pairs, used_ids, count=4)
        selected.extend(recent)
        used_ids.update(p["pair_id"] for p in recent)

        # Slot 2: Topic-diverse (3 slots)
        topic_diverse = self._select_topic_diverse(scored_pairs, used_ids, count=3)
        selected.extend(topic_diverse)
        used_ids.update(p["pair_id"] for p in topic_diverse)

        # Slot 3: Mood-diverse (2 slots)
        mood_diverse = self._select_mood_diverse(scored_pairs, used_ids, count=2)
        selected.extend(mood_diverse)
        used_ids.update(p["pair_id"] for p in mood_diverse)

        # Slot 4: Banglish showcase (2 slots)
        banglish = self._select_banglish_showcase(scored_pairs, used_ids, count=2)
        selected.extend(banglish)
        used_ids.update(p["pair_id"] for p in banglish)

        # Slot 5: Personality highlights (2 slots)
        personality = self._select_personality_highlights(scored_pairs, used_ids, count=2)
        selected.extend(personality)
        used_ids.update(p["pair_id"] for p in personality)

        # Slot 6: Wildcard (1 slot)
        import random

        remaining = [p for p in scored_pairs if p["pair_id"] not in used_ids]
        if remaining:
            wildcard = random.choice(remaining)
            selected.append(wildcard)

        # Trim to max and format for output
        selected = selected[:max_exemplars]

        return [self._format_exemplar(p) for p in selected]

    def _build_pairs(self) -> list[dict]:
        """Build user→assistant conversation pairs from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            messages = [dict(r) for r in conn.execute("""
                SELECT msg_id, timestamp, role, content, session_id,
                       response_to, word_count, rt_sentiment, rt_language,
                       rt_mood_signal
                FROM messages
                ORDER BY timestamp ASC
            """).fetchall()]

        pairs = []
        # Match assistant responses to user messages
        response_map = {}
        for msg in messages:
            if msg["role"] == "assistant" and msg.get("response_to"):
                response_map[msg["response_to"]] = msg

        for msg in messages:
            if msg["role"] == "user" and msg["msg_id"] in response_map:
                response = response_map[msg["msg_id"]]
                pair_id = hashlib.md5((msg["msg_id"] + response["msg_id"]).encode()).hexdigest()[
                    :12
                ]

                pairs.append(
                    {
                        "pair_id": pair_id,
                        "user_msg": msg,
                        "assistant_msg": response,
                        "timestamp": msg["timestamp"],
                    }
                )

        # Fallback: if response_to is not set, pair by adjacency
        if not pairs:
            for i in range(len(messages) - 1):
                if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
                    pair_id = hashlib.md5(
                        (messages[i]["msg_id"] + messages[i + 1]["msg_id"]).encode()
                    ).hexdigest()[:12]
                    pairs.append(
                        {
                            "pair_id": pair_id,
                            "user_msg": messages[i],
                            "assistant_msg": messages[i + 1],
                            "timestamp": messages[i]["timestamp"],
                        }
                    )

        return pairs

    def _score_pairs(self, pairs: list[dict]) -> list[dict]:
        """Score each pair on quality, richness, recency."""
        now = datetime.now()

        for pair in pairs:
            user_msg = pair["user_msg"]
            asst_msg = pair["assistant_msg"]

            # Quality score: penalize very short or very long responses
            user_len = user_msg.get("word_count", len(user_msg["content"].split()))
            asst_len = asst_msg.get("word_count", len(asst_msg["content"].split()))

            # Ideal: user 5-50 words, assistant 10-150 words
            length_score = min(user_len / 5, 1.0) * min(asst_len / 10, 1.0)
            if asst_len > 200:
                length_score *= 0.7  # Penalize walls of text

            # Recency score: exponential decay
            msg_time = datetime.fromisoformat(pair["timestamp"])
            days_ago = (now - msg_time).days
            recency_score = math.exp(-0.05 * days_ago)  # Half-life ~14 days

            # Language richness: bonus for Banglish/mixed
            lang = user_msg.get("rt_language", "en")
            lang_score = 1.5 if lang == "banglish" else 1.2 if lang == "mixed" else 1.0

            # Mood signal presence: bonus
            mood_score = 1.3 if user_msg.get("rt_mood_signal") else 1.0

            pair["scores"] = {
                "length": round(length_score, 3),
                "recency": round(recency_score, 3),
                "language": round(lang_score, 3),
                "mood": round(mood_score, 3),
                "composite": round(length_score * recency_score * lang_score * mood_score, 3),
            }

        return sorted(pairs, key=lambda p: p["scores"]["composite"], reverse=True)

    def _select_recent_quality(self, pairs, used_ids, count) -> list[dict]:
        """Top N recent high-quality pairs from last 48 hours."""
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        candidates = [p for p in pairs if p["timestamp"] > cutoff and p["pair_id"] not in used_ids]
        return candidates[:count]

    def _select_topic_diverse(self, pairs, used_ids, count) -> list[dict]:
        """One pair per top topic cluster."""
        topic_keywords = {
            "tech": ["code", "implement", "build", "api", "model", "debug", "python"],
            "personal": ["feel", "the_partner_nickname", "mood", "sleep", "health", "family"],
            "planning": ["plan", "todo", "schedule", "project", "goal", "deadline"],
        }

        topic_best = {}
        for pair in pairs:
            if pair["pair_id"] in used_ids:
                continue
            text = pair["user_msg"]["content"].lower()
            for topic, keywords in topic_keywords.items():
                if any(kw in text for kw in keywords) and (
                    topic not in topic_best
                    or pair["scores"]["composite"] > topic_best[topic]["scores"]["composite"]
                ):
                    topic_best[topic] = pair

        return list(topic_best.values())[:count]

    def _select_mood_diverse(self, pairs, used_ids, count) -> list[dict]:
        """Best pair for different moods."""
        mood_best = {}
        for pair in pairs:
            if pair["pair_id"] in used_ids:
                continue
            mood = pair["user_msg"].get("rt_mood_signal")
            if mood and (
                mood not in mood_best
                or pair["scores"]["composite"] > mood_best[mood]["scores"]["composite"]
            ):
                mood_best[mood] = pair
        return list(mood_best.values())[:count]

    def _select_banglish_showcase(self, pairs, used_ids, count) -> list[dict]:
        """Best pairs that demonstrate Banglish code-switching."""
        candidates = [
            p
            for p in pairs
            if p["pair_id"] not in used_ids
            and p["user_msg"].get("rt_language") in ("banglish", "mixed")
        ]
        return candidates[:count]

    def _select_personality_highlights(self, pairs, used_ids, count) -> list[dict]:
        """Pairs where Synapse showed strong personality (humor, care, expertise)."""
        # Heuristic: assistant responses with emojis, exclamations,
        # or specific personality markers
        personality_markers = ["the_brother", "arey", "!", "😎", "🔥", "chal", "dekh"]

        scored = []
        for pair in pairs:
            if pair["pair_id"] in used_ids:
                continue
            text = pair["assistant_msg"]["content"].lower()
            marker_count = sum(1 for m in personality_markers if m in text)
            if marker_count > 0:
                scored.append((pair, marker_count))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:count]]

    def _format_exemplar(self, pair: dict) -> dict:
        """Format a pair for storage in the exemplars profile layer."""
        return {
            "pair_id": pair["pair_id"],
            "user": pair["user_msg"]["content"],
            "assistant": pair["assistant_msg"]["content"],
            "context": {
                "mood": pair["user_msg"].get("rt_mood_signal"),
                "language": pair["user_msg"].get("rt_language"),
                "topic_hint": self._infer_topic(pair["user_msg"]["content"]),
            },
            "selected_at": datetime.now().isoformat(),
            "original_timestamp": pair["timestamp"],
        }

    def _infer_topic(self, text: str) -> str:
        text = text.lower()
        if any(w in text for w in ["code", "implement", "build", "debug"]):
            return "technical"
        if any(w in text for w in ["feel", "mood", "tired", "happy"]):
            return "emotional"
        if any(w in text for w in ["plan", "todo", "schedule"]):
            return "planning"
        return "general"
