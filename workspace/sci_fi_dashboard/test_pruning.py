import sys
import os
import time
import tempfile

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sci_fi_dashboard.conflict_resolver import ConflictManager


def test_pruning_limits_pending_conflicts():
    """Conflict pruning should keep at most 20 pending conflicts."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        test_file = tmp.name

    try:
        cm = ConflictManager(test_file)

        # Add 25 conflicts (limit is 20)
        for i in range(25):
            cm.check_conflict(
                subject=f"Topic {i}",
                new_fact=f"Fact A{i}",
                new_confidence=0.5,
                source="Test",
                existing_fact=f"Fact B{i}",
                existing_confidence=0.5,
            )
            time.sleep(0.01)  # Ensure timestamps differ slightly

        # Verify count
        pending_count = len([c for c in cm.pending_conflicts if c["status"] == "pending"])
        assert pending_count <= 20, f"Expected <= 20 pending, got {pending_count}"
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)


def test_pruning_keeps_newest():
    """Pruning should discard oldest and keep newest conflicts."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        test_file = tmp.name

    try:
        cm = ConflictManager(test_file)

        for i in range(25):
            cm.check_conflict(
                subject=f"Topic {i}",
                new_fact=f"Fact A{i}",
                new_confidence=0.5,
                source="Test",
                existing_fact=f"Fact B{i}",
                existing_confidence=0.5,
            )
            time.sleep(0.01)

        pending_subjects = [
            c["subject"] for c in cm.pending_conflicts if c["status"] == "pending"
        ]

        # Oldest should have been pruned, newest should remain
        assert "Topic 0" not in pending_subjects
        assert "Topic 24" in pending_subjects
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
