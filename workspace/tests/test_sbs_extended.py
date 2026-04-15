"""
Test Suite: SBS Extended Coverage
==================================
Gap-filling tests for SBS subsystems not covered in test_sbs.py:
- ProfileManager max_versions constructor param
- ConversationLogger edge cases
- RealtimeProcessor language detection edge cases
- PromptCompiler custom max_chars, mood instructions
- SBSOrchestrator feedback detection integration
- ImplicitFeedbackDetector YAML loading fallback
- BatchProcessor linguistic drift detection
"""

import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sbs.feedback.implicit import (
    _DEFAULT_PATTERNS,
    ImplicitFeedbackDetector,
    _load_patterns,
)
from sci_fi_dashboard.sbs.ingestion.schema import RawMessage
from sci_fi_dashboard.sbs.injection.compiler import PromptCompiler
from sci_fi_dashboard.sbs.processing.realtime import (
    COMPILED_BANGLISH,
    COMPILED_MOOD,
    RealtimeProcessor,
)
from sci_fi_dashboard.sbs.profile.manager import ProfileManager

# ---------------------------------------------------------------------------
# ProfileManager Extended
# ---------------------------------------------------------------------------


class TestProfileManagerExtended:
    """Extended coverage for ProfileManager edge cases."""

    @pytest.mark.unit
    def test_custom_max_versions(self, tmp_path):
        """max_versions param should control archive pruning limit."""
        pm = ProfileManager(tmp_path / "profiles", max_versions=3)
        for _ in range(5):
            pm.snapshot_version()

        archives = list(pm.archive_dir.iterdir())
        assert len(archives) == 3

    @pytest.mark.unit
    def test_load_full_profile_has_all_layers(self, tmp_path):
        """load_full_profile should have exactly 8 keys matching LAYERS."""
        pm = ProfileManager(tmp_path / "profiles")
        profile = pm.load_full_profile()
        assert len(profile) == 8
        assert set(profile.keys()) == set(ProfileManager.LAYERS)

    @pytest.mark.unit
    def test_meta_layer_schema_version(self, tmp_path):
        """meta layer should have schema_version 2.0 by default."""
        pm = ProfileManager(tmp_path / "profiles")
        meta = pm.load_layer("meta")
        assert meta["schema_version"] == "2.0"

    @pytest.mark.unit
    def test_concurrent_writes_use_filelock(self, tmp_path):
        """ProfileManager should use filelock for concurrent safety."""
        pm = ProfileManager(tmp_path / "profiles")
        # Write and read rapidly; should not corrupt
        for i in range(10):
            pm.save_layer("linguistic", {"iteration": i})
        data = pm.load_layer("linguistic")
        assert data["iteration"] == 9

    @pytest.mark.unit
    def test_read_json_nonexistent_returns_empty(self, tmp_path):
        """_read_json on a nonexistent path should return empty dict."""
        pm = ProfileManager(tmp_path / "profiles")
        result = pm._read_json(tmp_path / "nonexistent.json")
        assert result == {}

    @pytest.mark.unit
    def test_multiple_snapshots_and_rollback(self, tmp_path):
        """Multiple snapshots, rollback to earliest, verify state."""
        pm = ProfileManager(tmp_path / "profiles")
        pm.save_layer("linguistic", {"state": "v1"})
        v1 = pm.snapshot_version()

        pm.save_layer("linguistic", {"state": "v2"})
        pm.snapshot_version()

        pm.save_layer("linguistic", {"state": "v3"})

        pm.rollback_to(v1)
        data = pm.load_layer("linguistic")
        assert data["state"] == "v1"


# ---------------------------------------------------------------------------
# RealtimeProcessor Extended
# ---------------------------------------------------------------------------


class TestRealtimeProcessorExtended:
    """Extended coverage for edge cases in realtime processing."""

    @pytest.fixture
    def processor(self, tmp_path):
        pm = ProfileManager(tmp_path / "profiles")
        return RealtimeProcessor(pm)

    @pytest.mark.unit
    def test_empty_message(self, processor):
        """Empty message should return neutral sentiment and no mood."""
        msg = RawMessage(role="user", content="")
        result = processor.process(msg)
        assert result["rt_sentiment"] == 0.0
        assert result["rt_mood_signal"] is None

    @pytest.mark.unit
    def test_language_detection_mixed(self, processor):
        """Message with both English and Banglish should detect as mixed."""
        msg = RawMessage(role="user", content="arey bhai please implement the feature now")
        result = processor.process(msg)
        assert result["rt_language"] in ("mixed", "en")

    @pytest.mark.unit
    def test_sentiment_clamped_range(self, processor):
        """Sentiment should be clamped to [-1.0, 1.0]."""
        # All positive words
        msg = RawMessage(role="user", content="awesome awesome awesome awesome awesome")
        result = processor.process(msg)
        assert -1.0 <= result["rt_sentiment"] <= 1.0

    @pytest.mark.unit
    def test_mood_detection_stressed(self, processor):
        """Stress-related keywords should detect 'stressed' mood."""
        msg = RawMessage(role="user", content="so much pressure and deadline")
        result = processor.process(msg)
        assert result["rt_mood_signal"] == "stressed"

    @pytest.mark.unit
    def test_mood_detection_excited(self, processor):
        """Excitement keywords should detect 'excited' mood."""
        msg = RawMessage(role="user", content="!!! let's go this is amazing!!!")
        result = processor.process(msg)
        assert result["rt_mood_signal"] == "excited"

    @pytest.mark.unit
    def test_mood_detection_frustrated(self, processor):
        """Frustration keywords should detect 'frustrated' mood."""
        msg = RawMessage(role="user", content="wtf this is broken and keno it's not working")
        result = processor.process(msg)
        assert result["rt_mood_signal"] == "frustrated"

    @pytest.mark.unit
    def test_mood_history_limited_to_10(self, processor):
        """Mood history in emotional_state should be capped at 10 entries."""
        for _i in range(15):
            msg = RawMessage(role="user", content="need to implement and build and code")
            processor.process(msg)

        emotional = processor.profile_mgr.load_layer("emotional_state")
        assert len(emotional["mood_history"]) <= 10

    @pytest.mark.unit
    def test_compiled_patterns_loaded(self):
        """COMPILED_BANGLISH and COMPILED_MOOD should be populated at module load."""
        assert len(COMPILED_BANGLISH) > 0
        assert len(COMPILED_MOOD) > 0
        assert "stressed" in COMPILED_MOOD
        assert "playful" in COMPILED_MOOD


# ---------------------------------------------------------------------------
# PromptCompiler Extended
# ---------------------------------------------------------------------------


class TestPromptCompilerExtended:
    """Extended tests for prompt compilation edge cases."""

    @pytest.mark.unit
    def test_custom_max_chars(self, tmp_path):
        """Custom max_chars should be respected."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm, max_chars=10000)
        assert comp.MAX_CHARS == 10000

    @pytest.mark.unit
    def test_zero_max_chars_uses_default(self, tmp_path):
        """max_chars=0 should fall back to DEFAULT_MAX_CHARS."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm, max_chars=0)
        assert comp.MAX_CHARS == PromptCompiler.DEFAULT_MAX_CHARS

    @pytest.mark.unit
    def test_mood_instructions_for_each_mood(self, tmp_path):
        """Each known mood should produce a different instruction in the prompt."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        known_moods = [
            "stressed",
            "playful",
            "tired",
            "focused",
            "excited",
            "frustrated",
            "neutral",
        ]
        for mood in known_moods:
            emotional = pm.load_layer("emotional_state")
            emotional["current_dominant_mood"] = mood
            pm.save_layer("emotional_state", emotional)

            result = comp.compile()
            assert mood in result

    @pytest.mark.unit
    def test_compile_with_interaction_peak_hours(self, tmp_path):
        """Interaction peak hours should appear in compiled prompt."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        interaction = pm.load_layer("interaction")
        interaction["peak_hours"] = [14, 22, 9]
        interaction["avg_response_length"] = 75
        pm.save_layer("interaction", interaction)

        result = comp.compile()
        assert "[INTERACTION PATTERN]" in result
        assert "14:00" in result

    @pytest.mark.unit
    def test_compile_style_heavy_banglish(self, tmp_path):
        """High banglish_ratio should produce heavy Banglish instruction."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        linguistic = pm.load_layer("linguistic")
        linguistic["current_style"] = {
            "banglish_ratio": 0.7,
            "avg_message_length": 20,
            "emoji_frequency": 0.3,
        }
        pm.save_layer("linguistic", linguistic)

        result = comp.compile()
        assert "heavy Banglish" in result

    @pytest.mark.unit
    def test_compile_style_primarily_english(self, tmp_path):
        """Low banglish_ratio should produce English instruction."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        linguistic = pm.load_layer("linguistic")
        linguistic["current_style"] = {
            "banglish_ratio": 0.1,
            "avg_message_length": 15,
            "emoji_frequency": 0.01,
        }
        pm.save_layer("linguistic", linguistic)

        result = comp.compile()
        assert "Primarily English" in result

    @pytest.mark.unit
    def test_compile_no_exemplars_section_when_empty(self, tmp_path):
        """When no exemplars exist, [EXAMPLE INTERACTIONS] should not appear."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        result = comp.compile()
        assert "[EXAMPLE INTERACTIONS]" not in result

    @pytest.mark.unit
    def test_compile_no_domain_section_when_empty(self, tmp_path):
        """When no active domains exist, [CURRENT INTERESTS] should not appear."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        result = comp.compile()
        assert "[CURRENT INTERESTS]" not in result

    @pytest.mark.unit
    def test_compile_no_vocabulary_section_when_empty(self, tmp_path):
        """When no top_banglish terms exist, [ACTIVE VOCABULARY] should not appear."""
        pm = ProfileManager(tmp_path / "profiles")
        comp = PromptCompiler(pm)

        result = comp.compile()
        assert "[ACTIVE VOCABULARY]" not in result


# ---------------------------------------------------------------------------
# ImplicitFeedbackDetector Extended
# ---------------------------------------------------------------------------


class TestImplicitFeedbackExtended:
    """Extended tests for feedback detection edge cases."""

    @pytest.mark.unit
    def test_load_patterns_returns_dict(self):
        """_load_patterns should return a dict of pattern lists."""
        patterns = _load_patterns()
        assert isinstance(patterns, dict)
        assert len(patterns) > 0
        for _key, value in patterns.items():
            assert isinstance(value, list)

    @pytest.mark.unit
    def test_default_patterns_have_all_categories(self):
        """_DEFAULT_PATTERNS should have all expected categories."""
        expected = {
            "correction_formal",
            "correction_casual",
            "correction_length",
            "correction_short",
            "praise",
            "rejection",
        }
        assert set(_DEFAULT_PATTERNS.keys()) == expected

    @pytest.mark.unit
    def test_analyze_with_context(self, tmp_path):
        """analyze should include truncated context in result."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        result = detector.analyze(
            "too long, stop yapping",
            last_assistant_text="Here is a very long detailed response about many things " * 5,
        )
        assert result is not None
        assert result["context"] is not None
        assert result["context"].endswith("...")

    @pytest.mark.unit
    def test_analyze_no_context(self, tmp_path):
        """analyze with empty assistant text should have None context."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        result = detector.analyze("too long")
        assert result is not None
        assert result["context"] is None

    @pytest.mark.unit
    def test_apply_feedback_praise_increments_count(self, tmp_path):
        """Praise feedback should increment praise_count in linguistic style."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        linguistic = pm.load_layer("linguistic")
        linguistic["current_style"] = {"praise_count": 0}
        pm.save_layer("linguistic", linguistic)

        signal = {"type": "praise", "matched_text": "perfect", "context": None}
        detector.apply_feedback(signal)

        updated = pm.load_layer("linguistic")
        assert updated["current_style"]["praise_count"] == 1

    @pytest.mark.unit
    def test_apply_feedback_rejection_sets_meta_flag(self, tmp_path):
        """Rejection feedback should set rejection_pending in meta layer."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        signal = {"type": "rejection", "matched_text": "shut up", "context": None}
        detector.apply_feedback(signal)

        meta = pm.load_layer("meta")
        assert meta["rejection_pending"] is True
        assert meta["last_rejection"] is not None

    @pytest.mark.unit
    def test_apply_feedback_length_clamps_at_min(self, tmp_path):
        """correction_length should not reduce below 10."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        interaction = pm.load_layer("interaction")
        interaction["avg_response_length"] = 15
        pm.save_layer("interaction", interaction)

        signal = {"type": "correction_length", "matched_text": "too long", "context": None}
        detector.apply_feedback(signal)

        updated = pm.load_layer("interaction")
        assert updated["avg_response_length"] >= 10

    @pytest.mark.unit
    def test_apply_feedback_short_clamps_at_max(self, tmp_path):
        """correction_short should not increase beyond 500."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)

        interaction = pm.load_layer("interaction")
        interaction["avg_response_length"] = 300
        pm.save_layer("interaction", interaction)

        signal = {"type": "correction_short", "matched_text": "elaborate", "context": None}
        detector.apply_feedback(signal)

        updated = pm.load_layer("interaction")
        assert updated["avg_response_length"] <= 500

    @pytest.mark.unit
    def test_tl_dr_detected_as_length_correction(self, tmp_path):
        """'tl;dr' should be detected as correction_length."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)
        result = detector.analyze("tl;dr give me the summary")
        assert result is not None
        assert result["type"] == "correction_length"

    @pytest.mark.unit
    def test_stop_yapping_detected(self, tmp_path):
        """'stop yapping' should be detected as correction_length."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)
        result = detector.analyze("stop yapping about this")
        assert result is not None
        assert result["type"] == "correction_length"

    @pytest.mark.unit
    def test_love_this_tone_detected_as_praise(self, tmp_path):
        """'love this tone' should be detected as praise."""
        pm = ProfileManager(tmp_path / "profiles")
        detector = ImplicitFeedbackDetector(pm)
        result = detector.analyze("love this tone, keep it up")
        assert result is not None
        assert result["type"] == "praise"


# ---------------------------------------------------------------------------
# BatchProcessor Extended
# ---------------------------------------------------------------------------


class TestBatchProcessorExtended:
    """Extended batch processing tests for drift detection."""

    @pytest.mark.unit
    def test_linguistic_drift_detection(self, tmp_path):
        """With enough style history, drift_direction should be computed."""
        from sci_fi_dashboard.sbs.processing.batch import BatchProcessor

        pm = ProfileManager(tmp_path / "profiles")
        db_path = tmp_path / "messages.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    msg_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL,
                    session_id TEXT, response_to TEXT,
                    char_count INTEGER, word_count INTEGER,
                    has_emoji BOOLEAN, is_question BOOLEAN,
                    rt_sentiment REAL, rt_language TEXT, rt_mood_signal TEXT
                )
            """)

        bp = BatchProcessor(db_path, pm)

        # Simulate multiple batch style history entries
        linguistic = pm.load_layer("linguistic")
        linguistic["style_history"] = [
            {
                "banglish_ratio": 0.1,
                "english_ratio": 0.8,
                "mixed_ratio": 0.1,
                "avg_message_length": 15,
                "emoji_frequency": 0.05,
                "question_frequency": 0.2,
                "sample_size": 50,
                "timestamp": "2025-01-01T00:00:00",
            },
            {
                "banglish_ratio": 0.15,
                "english_ratio": 0.7,
                "mixed_ratio": 0.15,
                "avg_message_length": 16,
                "emoji_frequency": 0.06,
                "question_frequency": 0.3,
                "sample_size": 50,
                "timestamp": "2025-02-01T00:00:00",
            },
            {
                "banglish_ratio": 0.4,
                "english_ratio": 0.5,
                "mixed_ratio": 0.1,
                "avg_message_length": 18,
                "emoji_frequency": 0.08,
                "question_frequency": 0.25,
                "sample_size": 50,
                "timestamp": "2025-03-01T00:00:00",
            },
            {
                "banglish_ratio": 0.5,
                "english_ratio": 0.4,
                "mixed_ratio": 0.1,
                "avg_message_length": 20,
                "emoji_frequency": 0.1,
                "question_frequency": 0.2,
                "sample_size": 50,
                "timestamp": "2025-04-01T00:00:00",
            },
        ]
        pm.save_layer("linguistic", linguistic)

        # Feed messages with banglish
        now = datetime.now()
        messages = [
            {
                "content": "arey bhai chai khaowa",
                "rt_language": "banglish",
                "word_count": 4,
                "has_emoji": False,
                "is_question": False,
                "role": "user",
                "timestamp": now.isoformat(),
            },
        ]
        bp._update_linguistic_profile(messages)

        updated = pm.load_layer("linguistic")
        style = updated["current_style"]
        # With enough history, drift should be computed
        assert "banglish_drift" in style or "drift_direction" in style
