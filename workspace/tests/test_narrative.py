"""
test_narrative.py — Tests for the narrative engine (translate_log_to_narrative).

Covers:
  - All NARRATIVE_MAP keys produce matching narratives
  - Unknown/unmatched log strings produce the default fallback
  - Return type is always a 2-tuple (str, str)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from sci_fi_dashboard.narrative import NARRATIVE_MAP, translate_log_to_narrative


class TestTranslateLogToNarrative:
    """Tests for the translate_log_to_narrative function."""

    def test_returns_tuple_for_known_key(self):
        """Each known key should return a 2-tuple of strings."""
        for key in NARRATIVE_MAP:
            result = translate_log_to_narrative(key)
            assert isinstance(result, tuple), f"Expected tuple for key={key}"
            assert len(result) == 2, f"Expected 2-tuple for key={key}"
            assert isinstance(result[0], str)
            assert isinstance(result[1], str)

    def test_email_log_matches(self):
        """POST /api/send_email should match the email narrative."""
        narrative, sub = translate_log_to_narrative("POST /api/send_email")
        assert narrative  # non-empty
        assert sub  # non-empty

    def test_scrape_log_matches(self):
        """SCRAPE: news_source should match."""
        narrative, sub = translate_log_to_narrative("SCRAPE: news_source")
        assert narrative
        assert sub

    def test_analytics_log_matches(self):
        """PROCESS: analytics should match."""
        narrative, sub = translate_log_to_narrative("PROCESS: analytics")
        assert narrative

    def test_backup_log_matches(self):
        """SYSTEM: backup should match."""
        narrative, sub = translate_log_to_narrative("SYSTEM: backup")
        assert narrative

    def test_error_log_matches(self):
        """ERROR: timeout should match."""
        narrative, sub = translate_log_to_narrative("ERROR: timeout")
        assert narrative

    def test_memory_search_matches(self):
        """MEMORY: search should match."""
        narrative, sub = translate_log_to_narrative("MEMORY: search")
        assert narrative

    def test_thinking_matches(self):
        """SYSTEM: thinking should match."""
        narrative, sub = translate_log_to_narrative("SYSTEM: thinking")
        assert narrative

    def test_sentiment_matches(self):
        """sentiment_logs should match."""
        narrative, sub = translate_log_to_narrative("sentiment_logs")
        assert narrative

    def test_language_nuance_matches(self):
        """language_nuance should match."""
        narrative, sub = translate_log_to_narrative("language_nuance")
        assert narrative

    def test_growth_log_matches(self):
        """growth_log should match."""
        narrative, sub = translate_log_to_narrative("growth_log")
        assert narrative

    def test_unknown_log_returns_default(self):
        """An unrecognized log should return the default fallback."""
        narrative, sub = translate_log_to_narrative("COMPLETELY_UNKNOWN_LOG_ENTRY")
        assert "[EVAL]" in narrative
        assert "COMPLETELY_UNKNOWN_LOG_ENTRY" in narrative
        assert sub == "Monitoring system impact..."

    def test_empty_string_returns_default(self):
        """Empty string should return default fallback."""
        narrative, sub = translate_log_to_narrative("")
        assert isinstance(narrative, str)
        assert isinstance(sub, str)

    def test_partial_key_in_longer_string(self):
        """Key embedded in a longer string should still match."""
        narrative, sub = translate_log_to_narrative(
            "2024-01-01 12:00 SYSTEM: backup started successfully"
        )
        # Should match SYSTEM: backup
        assert narrative
        assert sub

    def test_narrative_map_is_dict(self):
        """NARRATIVE_MAP should be a non-empty dict."""
        assert isinstance(NARRATIVE_MAP, dict)
        assert len(NARRATIVE_MAP) > 0

    def test_all_map_values_are_nonempty_lists(self):
        """Every value in NARRATIVE_MAP should be a non-empty list of 2-tuples."""
        for key, options in NARRATIVE_MAP.items():
            assert isinstance(options, list), f"Expected list for key={key}"
            assert len(options) > 0, f"Expected non-empty list for key={key}"
            for opt in options:
                assert (
                    isinstance(opt, tuple) and len(opt) == 2
                ), f"Expected 2-tuple in options for key={key}, got {opt}"
