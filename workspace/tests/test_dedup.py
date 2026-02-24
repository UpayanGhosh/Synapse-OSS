"""
Test Suite: Message Deduplication (Unit Tests)
==============================================
Tests the MessageDeduplicator class which prevents reprocessing
of duplicate webhook messages within a configurable time window.
"""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.dedup import MessageDeduplicator


class TestMessageDeduplicator:
    """Test cases for message deduplication logic."""

    def test_new_message_not_duplicate(self):
        """First occurrence of a message ID should not be marked as duplicate."""
        dedup = MessageDeduplicator(window_seconds=5)
        result = dedup.is_duplicate("msg_001")
        assert result is False

    def test_same_message_within_window_is_duplicate(self):
        """Same message ID within the window should be flagged as duplicate."""
        dedup = MessageDeduplicator(window_seconds=5)
        dedup.is_duplicate("msg_001")
        result = dedup.is_duplicate("msg_001")
        assert result is True

    def test_different_messages_not_duplicates(self):
        """Different message IDs should not affect each other."""
        dedup = MessageDeduplicator(window_seconds=5)
        dedup.is_duplicate("msg_001")
        result = dedup.is_duplicate("msg_002")
        assert result is False

    def test_empty_message_id_not_duplicate(self):
        """Empty/None message IDs should never be marked as duplicate."""
        dedup = MessageDeduplicator(window_seconds=5)
        assert dedup.is_duplicate("") is False

    def test_expired_message_not_duplicate(self):
        """Message ID outside the window should not be a duplicate."""
        dedup = MessageDeduplicator(window_seconds=1)
        dedup.is_duplicate("msg_001")
        time.sleep(1.5)
        result = dedup.is_duplicate("msg_001")
        assert result is False

    def test_cleanup_happens_on_check(self):
        """Expired entries should be cleaned up during is_duplicate calls."""
        dedup = MessageDeduplicator(window_seconds=1)
        dedup.is_duplicate("msg_001")
        time.sleep(1.5)
        dedup.is_duplicate("msg_002")
        assert "msg_001" not in dedup.seen

    def test_multiple_messages_tracked(self):
        """Multiple different messages should all be tracked correctly."""
        dedup = MessageDeduplicator(window_seconds=5)
        for i in range(50):
            assert dedup.is_duplicate(f"msg_{i}") is False
        for i in range(50):
            assert dedup.is_duplicate(f"msg_{i}") is True

    def test_window_respects_configuration(self):
        """Different window sizes should behave correctly."""
        dedup_short = MessageDeduplicator(window_seconds=1)
        dedup_long = MessageDeduplicator(window_seconds=10)

        dedup_short.is_duplicate("msg_001")
        dedup_long.is_duplicate("msg_001")

        time.sleep(1.5)
        assert dedup_short.is_duplicate("msg_001") is False
        assert dedup_long.is_duplicate("msg_001") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
