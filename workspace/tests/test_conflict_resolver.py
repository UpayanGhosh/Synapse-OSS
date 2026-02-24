"""
Test Suite: Conflict Resolution (Unit Tests)
============================================
Tests the ConflictManager class which handles knowledge conflicts
when new facts contradict existing memories.
"""

import pytest
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.conflict_resolver import ConflictManager


class TestConflictManager:
    """Test cases for conflict resolution logic."""

    @pytest.fixture
    def temp_conflicts_file(self):
        """Create a temporary conflicts file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def cm(self, temp_conflicts_file):
        """Create a ConflictManager with temp file."""
        return ConflictManager(conflicts_file=temp_conflicts_file)

    def test_new_fact_returns_new(self, cm):
        """New fact with no existing fact should return NEW."""
        result = cm.check_conflict(
            subject="TestSubject",
            new_fact="A new fact",
            new_confidence=0.5,
            source="Test",
            existing_fact=None,
        )
        assert result == "NEW"

    def test_same_fact_returns_same(self, cm):
        """Identical facts should return SAME."""
        result = cm.check_conflict(
            subject="TestSubject",
            new_fact="Same fact",
            new_confidence=0.5,
            source="Test",
            existing_fact="Same fact",
        )
        assert result == "SAME"

    def test_high_confidence_overwrites_low(self, cm):
        """High confidence new fact should overwrite low confidence existing."""
        result = cm.check_conflict(
            subject="TestSubject",
            new_fact="New fact",
            new_confidence=0.95,
            source="Test",
            existing_fact="Old fact",
            existing_confidence=0.3,
        )
        assert result == "OVERWRITE"

    def test_low_confidence_ignored_when_high_exists(self, cm):
        """Low confidence new fact should be ignored when high confidence exists."""
        result = cm.check_conflict(
            subject="TestSubject",
            new_fact="Low confidence fact",
            new_confidence=0.3,
            source="Test",
            existing_fact="High confidence fact",
            existing_confidence=0.95,
        )
        assert result == "IGNORE"

    def test_similar_confidence_creates_conflict(self, cm):
        """Similar confidence facts should create a conflict."""
        result = cm.check_conflict(
            subject="TestSubject",
            new_fact="Fact A",
            new_confidence=0.6,
            source="Test",
            existing_fact="Fact B",
            existing_confidence=0.6,
        )
        assert result == "CONFLICT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
