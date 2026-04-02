"""Tests for multiuser/compaction.py helper functions — filling gaps.

Covers:
- strip_tool_result_details()
- split_by_token_share()
- _rewrite_jsonl_sync()
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from sci_fi_dashboard.multiuser.compaction import (
        _rewrite_jsonl_sync,
        split_by_token_share,
        strip_tool_result_details,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(not AVAILABLE, reason="compaction not available")


@_skip
class TestStripToolResultDetails:

    def test_removes_tool_role_messages(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            {"role": "assistant", "content": "ok"},
        ]
        result = strip_tool_result_details(messages)
        assert len(result) == 2
        assert all(m["role"] != "tool" for m in result)

    def test_strips_tool_call_arguments(self):
        messages = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "name": "read_file",
                        "function": {"name": "read_file", "arguments": '{"path": "/foo"}'},
                        "id": "tc1",
                    }
                ],
            }
        ]
        result = strip_tool_result_details(messages)
        assert len(result) == 1
        tc = result[0]["tool_calls"][0]
        assert "name" in tc
        assert "arguments" not in tc
        assert "function" not in tc

    def test_preserves_non_tool_messages(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "system", "content": "you are helpful"},
        ]
        result = strip_tool_result_details(messages)
        assert result == messages

    def test_empty_input(self):
        assert strip_tool_result_details([]) == []


@_skip
class TestSplitByTokenShare:

    def test_single_part(self):
        messages = [{"role": "user", "content": "hello"}]
        result = split_by_token_share(messages, parts=1)
        assert len(result) == 1
        assert result[0] == messages

    def test_two_parts(self):
        messages = [
            {"role": "user", "content": "a" * 100},
            {"role": "assistant", "content": "b" * 100},
            {"role": "user", "content": "c" * 100},
            {"role": "assistant", "content": "d" * 100},
        ]
        result = split_by_token_share(messages, parts=2)
        assert len(result) == 2
        total = sum(len(bucket) for bucket in result)
        assert total == 4

    def test_empty_messages(self):
        result = split_by_token_share([], parts=3)
        assert len(result) == 3
        assert all(bucket == [] for bucket in result)

    def test_fewer_messages_than_parts(self):
        messages = [{"role": "user", "content": "hi"}]
        result = split_by_token_share(messages, parts=5)
        assert len(result) == 5
        total = sum(len(bucket) for bucket in result)
        assert total == 1


@_skip
class TestRewriteJsonlSync:

    def test_basic_rewrite(self, tmp_path):
        path = tmp_path / "test.jsonl"
        lines = [
            {"role": "system", "content": "summary"},
            {"role": "user", "content": "hi"},
        ]
        _rewrite_jsonl_sync(path, lines)

        assert path.exists()
        with open(path) as f:
            read_lines = [json.loads(line) for line in f if line.strip()]
        assert len(read_lines) == 2
        assert read_lines[0]["role"] == "system"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "test.jsonl"
        _rewrite_jsonl_sync(path, [{"role": "user", "content": "hi"}])
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / "test.jsonl"
        path.write_text('{"role":"old","content":"data"}\n')
        _rewrite_jsonl_sync(path, [{"role": "new", "content": "data"}])
        with open(path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0]["role"] == "new"
