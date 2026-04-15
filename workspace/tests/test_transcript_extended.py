"""Extended tests for multiuser/transcript.py — repair, transcript_path, archive.

Fills gaps not covered in test_multiuser.py:
- RepairReport dataclass
- repair_orphaned_tool_pairs logic
- repair_all_transcripts batch repair
- transcript_path construction
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from sci_fi_dashboard.multiuser.session_store import SessionEntry
    from sci_fi_dashboard.multiuser.transcript import (
        RepairReport,
        repair_all_transcripts,
        repair_orphaned_tool_pairs,
        transcript_path,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(not AVAILABLE, reason="multiuser not available")


@_skip
class TestRepairReport:

    def test_default_values(self):
        r = RepairReport()
        assert r.orphaned_tool_results_removed == 0
        assert r.orphaned_tool_calls_removed == 0
        assert r.total_messages_before == 0
        assert r.total_messages_after == 0

    def test_repairs_made_property(self):
        r = RepairReport(orphaned_tool_results_removed=2, orphaned_tool_calls_removed=1)
        assert r.repairs_made == 3


@_skip
class TestRepairOrphanedToolPairs:

    def test_no_repair_needed(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        repaired, report = repair_orphaned_tool_pairs(messages)
        assert repaired == messages
        assert report.repairs_made == 0

    def test_orphaned_tool_result_removed(self):
        """tool_result without matching tool_use is removed."""
        messages = [
            {"role": "tool", "tool_call_id": "orphan123", "content": "result"},
            {"role": "user", "content": "hi"},
        ]
        repaired, report = repair_orphaned_tool_pairs(messages)
        assert report.orphaned_tool_results_removed == 1
        assert len(repaired) == 1
        assert repaired[0]["role"] == "user"

    def test_matched_tool_result_kept(self):
        """tool_result with matching tool_use is kept."""
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "name": "read_file"}],
            },
            {"role": "tool", "tool_call_id": "tc1", "content": "file content"},
            {"role": "user", "content": "thanks"},
        ]
        repaired, report = repair_orphaned_tool_pairs(messages)
        assert report.repairs_made == 0
        assert len(repaired) == 3

    def test_empty_messages(self):
        repaired, report = repair_orphaned_tool_pairs([])
        assert repaired == []
        assert report.repairs_made == 0

    def test_report_counts(self):
        messages = [
            {"role": "tool", "tool_call_id": "orphan1", "content": "r1"},
            {"role": "tool", "tool_call_id": "orphan2", "content": "r2"},
            {"role": "user", "content": "hi"},
        ]
        repaired, report = repair_orphaned_tool_pairs(messages)
        assert report.total_messages_before == 3
        assert report.total_messages_after == 1
        assert report.orphaned_tool_results_removed == 2


@_skip
class TestRepairAllTranscripts:

    def test_repairs_files_in_directory(self, tmp_path):
        """repair_all_transcripts finds and repairs JSONL files."""
        # Create a JSONL file with an orphaned tool result
        jsonl = tmp_path / "session1.jsonl"
        lines = [
            {"role": "tool", "tool_call_id": "orphan1", "content": "result"},
            {"role": "user", "content": "hi"},
        ]
        jsonl.write_text("\n".join(json.dumps(item) for item in lines) + "\n")

        count = repair_all_transcripts(tmp_path)
        assert count == 1

        # Verify the file was rewritten
        repaired_lines = []
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if line:
                    repaired_lines.append(json.loads(line))
        assert len(repaired_lines) == 1
        assert repaired_lines[0]["role"] == "user"

    def test_no_repair_needed(self, tmp_path):
        """Files without orphaned pairs are not rewritten."""
        jsonl = tmp_path / "clean.jsonl"
        lines = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        jsonl.write_text("\n".join(json.dumps(item) for item in lines) + "\n")

        count = repair_all_transcripts(tmp_path)
        assert count == 0

    def test_nonexistent_dir(self):
        """Nonexistent directory returns 0."""
        from pathlib import Path

        count = repair_all_transcripts(Path("/nonexistent/dir/12345"))
        assert count == 0


@_skip
class TestTranscriptPath:

    def test_correct_path_construction(self, tmp_path):
        entry = SessionEntry(session_id="abc-123", updated_at=time.time())
        path = transcript_path(entry, tmp_path, "jarvis")
        expected = tmp_path / "state" / "agents" / "jarvis" / "sessions" / "abc-123.jsonl"
        assert path == expected
