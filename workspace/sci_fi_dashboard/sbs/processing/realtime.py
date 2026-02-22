import re
from typing import Optional
from ..ingestion.schema import RawMessage
from ..profile.manager import ProfileManager

# Pre-compiled patterns (loaded once, used forever)
BANGLISH_MARKERS = {
    # Common Banglish words with normalized forms
    r"l[yi]a+dh?": "lyadh",
    r"ghu+m": "ghum", 
    r"kha+[ow]a": "khaowa",
    r"bo+u?muni": "the_partner_nickname",
    r"cha+[iy]": "chai",
    r"bh+a+i": "the_brother",
    r"ar+[ea]y?": "arey",
    r"ki\\s*kor(chi|bo|ish)": "ki_korchi_family",
    r"achh?[io]s?h?": "acchis",
    # ... extend as discovered
}

MOOD_KEYWORDS = {
    "stressed":  [r"pressure", r"deadline", r"pagol", r"er\\s*upor", r"jhame+la"],
    "playful":   [r"lol", r"haha+", r"😂", r"🤣", r"moja", r"maza"],
    "tired":     [r"l[yi]a+dh", r"ghu+m", r"thak", r"uff+", r"😴"],
    "focused":   [r"implement", r"build", r"code", r"debug", r"fix", r"deploy"],
    "excited":   [r"!!+", r"🔥", r"daru+n", r"jhakkas", r"let'?s\\s*go"],
    "frustrated":[r"wtf", r"keno", r"kaaj\\s*kor(che)?\\s*na", r"broken", r"error"],
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
    
    def __init__(self, profile_manager: ProfileManager):
        self.profile_mgr = profile_manager
        self._sentiment_lexicon = self._load_sentiment_lexicon()
    
    def _load_sentiment_lexicon(self) -> dict:
        """
        Simple lexicon-based sentiment. Not using VADER because 
        it doesn't understand Banglish. Custom bilingual lexicon.
        """
        return {
            # Positive
            "bhalo": 0.5, "darun": 0.8, "moja": 0.6, "great": 0.7,
            "awesome": 0.8, "thanks": 0.3, "love": 0.7, "perfect": 0.8,
            "jhakkas": 0.9, "🔥": 0.6, "❤️": 0.5, "😊": 0.4,
            # Negative  
            "kharap": -0.5, "baje": -0.6, "problem": -0.3, "error": -0.4,
            "broken": -0.5, "hate": -0.7, "pagol": -0.3, "uff": -0.4,
            "😤": -0.5, "😢": -0.6, "wtf": -0.6,
            # Neutral-ish
            "ok": 0.0, "hmm": -0.1, "accha": 0.1,
        }
    
    def process(self, message: RawMessage) -> dict:
        """
        Returns realtime analysis results.
        Fast path only — must complete in < 50ms.
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
        
        return {
            "rt_sentiment": sentiment,
            "rt_language": language,
            "rt_mood_signal": mood
        }
    
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
    
    def _detect_mood(self, text: str) -> Optional[str]:
        """Returns dominant mood or None."""
        mood_scores = {}
        for mood, patterns in COMPILED_MOOD.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                mood_scores[mood] = score
        
        if not mood_scores:
            return None
        return max(mood_scores, key=mood_scores.get)
    
    def _hot_update_emotional_state(self, mood: str, sentiment: float, 
                                      timestamp):
        """
        Immediately update the emotional_state profile layer.
        This is the ONLY profile layer updated in real-time.
        Everything else waits for batch.
        """
        emotional = self.profile_mgr.load_layer("emotional_state")
        
        # Sliding window of last 10 mood signals
        mood_history = emotional.get("mood_history", [])
        mood_history.append({
            "mood": mood,
            "sentiment": sentiment,
            "timestamp": timestamp.isoformat()
        })
        # Keep only last 10
        mood_history = mood_history[-10:]
        
        # Compute dominant mood from recent history
        from collections import Counter
        recent_moods = [m["mood"] for m in mood_history[-5:]]
        dominant = Counter(recent_moods).most_common(1)[0][0] if recent_moods else "neutral"
        
        # Compute average sentiment
        avg_sentiment = sum(m["sentiment"] for m in mood_history[-5:]) / max(len(mood_history[-5:]), 1)
        
        emotional["mood_history"] = mood_history
        emotional["current_dominant_mood"] = dominant
        emotional["current_sentiment_avg"] = round(avg_sentiment, 3)
        emotional["last_updated"] = timestamp.isoformat()
        
        self.profile_mgr.save_layer("emotional_state", emotional)
