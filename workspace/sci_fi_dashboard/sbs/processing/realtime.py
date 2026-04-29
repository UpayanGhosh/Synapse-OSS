import logging
import re
import time

from ..ingestion.schema import RawMessage
from ..profile.manager import ProfileManager

# Pre-compiled patterns (loaded once, used forever)
BANGLISH_MARKERS = {
    # Generic South Asian / code-switching markers.
    # These are learned from conversation — add your own in ~/.synapse/sbs/vocab/
    r"l[yi]a+dh?": "lyadh",
    r"ghu+m": "ghum",
    r"kha+[ow]a": "khaowa",
    r"cha+[iy]": "chai",
    r"bh+a+i": "the_brother",
    r"ar+[ea]y?": "arey",
    r"ki\s*kor(chi|bo|ish)": "ki_korchi_family",
    r"achh?[io]s?h?": "acchis",
}

MOOD_KEYWORDS = {
    "stressed": [
        r"\bpressure\b",
        r"\bdeadline\b",
        r"\bpagol\b",
        r"\ber\s*upor\b",
        r"\bjhame+la\b",
    ],
    "playful": [r"\blol\b", r"\bhaha+\b", r"\brofl\b", r"\bmoja\b", r"\bmaza\b"],
    "tired": [r"\bl[yi]a+dh\b", r"\bghu+m\b", r"\bthak\w*\b", r"\buff+\b", r"\[sleep\]"],
    "focused": [r"\bimplement\b", r"\bbuild\b", r"\bcode\b", r"\bdebug\b", r"\bfix\b", r"\bdeploy\b"],
    "excited": [r"!{2,}", r"\[fire\]", r"\bdaru+n\b", r"\bjhakkas\b", r"\blet'?s\s*go\b"],
    "frustrated": [r"\bwtf\b", r"\bkeno\b", r"\bkaaj\s*kor(che)?\s*na\b", r"\bbroken\b", r"\berror\b"],
}

COMPILED_BANGLISH = {re.compile(k, re.IGNORECASE): v for k, v in BANGLISH_MARKERS.items()}
COMPILED_MOOD = {
    mood: [re.compile(p, re.IGNORECASE) for p in patterns]
    for mood, patterns in MOOD_KEYWORDS.items()
}


class RealtimeProcessor:
    """
    Lightweight per-message analysis.

    Responsibilities:
    1. Detect language mix ratio
    2. Quick sentiment estimation
    3. Mood signal detection
    4. Trigger profile hot-updates for volatile dimensions (emotional state)

    NOT responsible for:
    - Deep vocabulary analysis (batch)
    - Exemplar selection (batch)
    - Style drift detection (batch)
    """

    # Flush emotional state to disk at most every N seconds
    _FLUSH_INTERVAL = 10  # seconds
    _FLUSH_BATCH = 5  # or every N mood updates

    def __init__(self, profile_manager: ProfileManager):
        self.profile_mgr = profile_manager
        self._sentiment_lexicon = self._load_sentiment_lexicon()
        self._mood_buffer: list[dict] = []
        self._last_flush: float = time.monotonic()

    def _load_sentiment_lexicon(self) -> dict:
        """
        Simple lexicon-based sentiment. Not using VADER because
        it doesn't understand Banglish. Custom bilingual lexicon.
        """
        return {
            # Positive
            "bhalo": 0.5,
            "darun": 0.8,
            "moja": 0.6,
            "great": 0.7,
            "awesome": 0.8,
            "thanks": 0.3,
            "love": 0.7,
            "perfect": 0.8,
            "jhakkas": 0.9,
            "[FIRE]": 0.6,
            "[HEART]": 0.5,
            "[HAPPY]": 0.4,
            # Negative
            "kharap": -0.5,
            "baje": -0.6,
            "problem": -0.3,
            "error": -0.4,
            "broken": -0.5,
            "hate": -0.7,
            "pagol": -0.3,
            "uff": -0.4,
            "[TRIUMPH]": -0.5,
            "[SAD]": -0.6,
            "wtf": -0.6,
            # Neutral-ish
            "ok": 0.0,
            "hmm": -0.1,
            "accha": 0.1,
        }

    def process(self, message: RawMessage) -> dict:
        """
        Returns realtime analysis results.
        Fast path only -- must complete in < 50ms.
        """
        text = message.content.lower()
        words = text.split()

        # 1. Language Detection
        language = self._detect_language(text, words)

        # 2. Sentiment Scoring
        sentiment = self._score_sentiment(words)

        # 3. Mood Signal
        mood = self._detect_mood(text)

        # 4. Hot-update emotional state if mood changed
        if mood and message.role == "user":
            self._hot_update_emotional_state(mood, sentiment, message.timestamp)
        else:
            self._retry_pending_flush()

        return {"rt_sentiment": sentiment, "rt_language": language, "rt_mood_signal": mood}

    def _detect_language(self, text: str, words: list) -> str:
        """Classify as en, bn, banglish, or mixed."""
        banglish_count = 0
        english_count = 0

        for word in words:
            matched_banglish = False
            for pattern in COMPILED_BANGLISH:
                if pattern.search(word):
                    banglish_count += 1
                    matched_banglish = True
                    break
            if not matched_banglish and word.isascii() and word.isalpha():
                english_count += 1

        total = len(words) if words else 1
        banglish_ratio = banglish_count / total
        english_ratio = english_count / total

        if banglish_ratio > 0.5:
            return "banglish"
        elif banglish_ratio > 0.15 and english_ratio > 0.3:
            return "mixed"
        elif english_ratio > 0.7:
            return "en"
        else:
            return "mixed"  # default for ambiguous

    def _score_sentiment(self, words: list) -> float:
        """Lexicon-based sentiment. Returns -1.0 to 1.0."""
        scores = [self._sentiment_lexicon.get(w, 0.0) for w in words]
        if not scores:
            return 0.0
        return max(-1.0, min(1.0, sum(scores) / max(len(scores), 1)))

    def _detect_mood(self, text: str) -> str | None:
        """Returns dominant mood or None."""
        mood_scores = {}
        for mood, patterns in COMPILED_MOOD.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                mood_scores[mood] = score

        if not mood_scores:
            return None
        return max(mood_scores, key=mood_scores.get)

    def _hot_update_emotional_state(self, mood: str, sentiment: float, timestamp):
        """
        Buffer mood updates and flush to disk periodically to avoid
        writing JSON on every single mood message.
        """
        self._mood_buffer.append(
            {"mood": mood, "sentiment": sentiment, "timestamp": timestamp.isoformat()}
        )

        now = time.monotonic()
        should_flush = (
            len(self._mood_buffer) >= self._FLUSH_BATCH
            or (now - self._last_flush) >= self._FLUSH_INTERVAL
        )
        if should_flush:
            self._safe_flush("hot_update")

    def _retry_pending_flush(self):
        """Retry pending mood persistence during subsequent processing turns."""
        if not self._mood_buffer:
            return
        now = time.monotonic()
        if (now - self._last_flush) >= self._FLUSH_INTERVAL:
            self._safe_flush("periodic_retry")

    def _flush_emotional_state(self):
        """Write buffered mood updates to the emotional_state profile layer."""
        if not self._mood_buffer:
            return

        from collections import Counter

        emotional = self.profile_mgr.load_layer("emotional_state")

        mood_history = emotional.get("mood_history", [])
        mood_history.extend(self._mood_buffer)
        # Keep only last 10
        mood_history = mood_history[-10:]

        recent_moods = [m["mood"] for m in mood_history[-5:]]
        dominant = Counter(recent_moods).most_common(1)[0][0] if recent_moods else "neutral"

        avg_sentiment = sum(m["sentiment"] for m in mood_history[-5:]) / max(
            len(mood_history[-5:]), 1
        )

        emotional["mood_history"] = mood_history
        emotional["current_dominant_mood"] = dominant
        emotional["current_sentiment_avg"] = round(avg_sentiment, 3)
        emotional["last_updated"] = self._mood_buffer[-1]["timestamp"]

        self.profile_mgr.save_layer("emotional_state", emotional)
        self._mood_buffer.clear()
        self._last_flush = time.monotonic()

    def _safe_flush(self, source: str):
        """Flush wrapper that keeps realtime pipeline alive on persistence failures."""
        try:
            self._flush_emotional_state()
        except Exception:
            logging.getLogger("sbs").warning(
                f"Realtime emotional flush failed from {source}; keeping buffer for retry.",
                exc_info=True,
            )

    def flush(self):
        """Public flush hook for orchestrator to persist pending realtime updates immediately."""
        self._safe_flush("manual_flush")
