"""
test_conflict_resolver_gaps.py — Gap-fill tests for conflict_resolver.py

Existing test_conflict_resolver.py covers basic check_conflict scenarios.
This file adds:
  - register_conflict and conflict persistence
  - prune_conflicts (max 20 pending)
  - get_morning_briefing_questions
  - resolve() method
  - save/load round-trip
  - Edge cases: empty file, corrupt file
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.conflict_resolver import ConflictManager


@pytest.fixture
def temp_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def cm(temp_file):
    return ConflictManager(conflicts_file=temp_file)


class TestRegisterConflict:
    def test_registers_and_saves(self, cm, temp_file):
        cm.register_conflict("Coffee", "I hate coffee", "Chat", "I love coffee")
        assert len(cm.pending_conflicts) == 1
        c = cm.pending_conflicts[0]
        assert c["subject"] == "Coffee"
        assert c["option_a"]["fact"] == "I love coffee"
        assert c["option_b"]["fact"] == "I hate coffee"
        assert c["status"] == "pending"

        # Verify persisted to file
        with open(temp_file) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_conflict_has_id(self, cm):
        cm.register_conflict("Topic", "new", "src", "old")
        assert cm.pending_conflicts[0]["id"]

    def test_conflict_has_timestamp(self, cm):
        cm.register_conflict("Topic", "new", "src", "old")
        assert "timestamp" in cm.pending_conflicts[0]


class TestPruneConflicts:
    def test_prune_keeps_max_20(self, cm):
        # Add 25 conflicts
        for i in range(25):
            cm.pending_conflicts.append(
                {
                    "id": f"id-{i}",
                    "subject": f"subject-{i}",
                    "timestamp": float(i),
                    "option_a": {"fact": "a", "source": "Memory"},
                    "option_b": {"fact": "b", "source": "Chat"},
                    "status": "pending",
                }
            )
        cm.prune_conflicts(max_conflicts=20)
        pending = [c for c in cm.pending_conflicts if c["status"] == "pending"]
        assert len(pending) <= 20

    def test_prune_keeps_newest(self, cm):
        for i in range(25):
            cm.pending_conflicts.append(
                {
                    "id": f"id-{i}",
                    "subject": f"subject-{i}",
                    "timestamp": float(i),
                    "option_a": {"fact": "a", "source": "Memory"},
                    "option_b": {"fact": "b", "source": "Chat"},
                    "status": "pending",
                }
            )
        cm.prune_conflicts(max_conflicts=5)
        pending = [c for c in cm.pending_conflicts if c["status"] == "pending"]
        timestamps = [c["timestamp"] for c in pending]
        # Should keep the newest 5
        assert max(timestamps) == 24.0

    def test_prune_preserves_resolved(self, cm):
        cm.pending_conflicts = [
            {
                "id": "r1",
                "subject": "x",
                "timestamp": 1.0,
                "option_a": {},
                "option_b": {},
                "status": "resolved",
            },
        ]
        for i in range(25):
            cm.pending_conflicts.append(
                {
                    "id": f"id-{i}",
                    "subject": f"s-{i}",
                    "timestamp": float(i + 10),
                    "option_a": {},
                    "option_b": {},
                    "status": "pending",
                }
            )
        cm.prune_conflicts(max_conflicts=5)
        resolved = [c for c in cm.pending_conflicts if c["status"] == "resolved"]
        assert len(resolved) == 1


class TestMorningBriefing:
    def test_empty_when_no_conflicts(self, cm):
        assert cm.get_morning_briefing_questions() == []

    def test_generates_questions(self, cm):
        cm.register_conflict("Coffee", "I hate coffee", "Chat", "I love coffee")
        questions = cm.get_morning_briefing_questions()
        assert len(questions) == 1
        assert "Coffee" in questions[0]
        assert "I love coffee" in questions[0]
        assert "I hate coffee" in questions[0]

    def test_skips_resolved(self, cm):
        cm.register_conflict("Topic", "new", "Chat", "old")
        cm.pending_conflicts[0]["status"] = "resolved"
        assert cm.get_morning_briefing_questions() == []


class TestResolve:
    def test_resolve_option_a(self, cm):
        cm.register_conflict("Topic", "new_fact", "Chat", "old_fact")
        conflict_id = cm.pending_conflicts[0]["id"]
        result = cm.resolve(conflict_id, "A")
        assert "Kept Option A" in result
        assert cm.pending_conflicts[0]["status"] == "resolved"
        assert cm.pending_conflicts[0]["resolution"] == "A"

    def test_resolve_option_b(self, cm):
        cm.register_conflict("Topic", "new", "Chat", "old")
        conflict_id = cm.pending_conflicts[0]["id"]
        result = cm.resolve(conflict_id, "B")
        assert "Option B" in result

    def test_resolve_nonexistent(self, cm):
        result = cm.resolve("nonexistent-id", "A")
        assert "not found" in result


class TestLoadSaveRoundTrip:
    def test_load_empty_file(self, temp_file):
        with open(temp_file, "w") as f:
            f.write("")
        cm = ConflictManager(conflicts_file=temp_file)
        assert cm.pending_conflicts == []

    def test_load_corrupt_file(self, temp_file):
        with open(temp_file, "w") as f:
            f.write("not json {{{")
        cm = ConflictManager(conflicts_file=temp_file)
        assert cm.pending_conflicts == []

    def test_save_and_reload(self, temp_file):
        cm1 = ConflictManager(conflicts_file=temp_file)
        cm1.register_conflict("X", "new", "src", "old")
        cm1.save_conflicts()

        cm2 = ConflictManager(conflicts_file=temp_file)
        assert len(cm2.pending_conflicts) == 1
        assert cm2.pending_conflicts[0]["subject"] == "X"

    def test_nonexistent_file_starts_empty(self):
        cm = ConflictManager(conflicts_file="/tmp/nonexistent_synapse_test_file.json")
        assert cm.pending_conflicts == []
        # Cleanup
        if os.path.exists("/tmp/nonexistent_synapse_test_file.json"):
            os.remove("/tmp/nonexistent_synapse_test_file.json")
