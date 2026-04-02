"""
Test Suite: Tool Safety Pipeline
=================================
Tests for the Phase 4 tool safety layer: policy filtering,
before/after hooks, graduated loop detection, and audit logging.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.tool_safety import (
    ToolAuditLogger,
    ToolHookRunner,
    ToolLoopDetector,
    ToolPolicy,
    PolicyStep,
    apply_tool_policy_pipeline,
    build_policy_steps,
)


# ---------------------------------------------------------------------------
# 1. Policy Pipeline Tests
# ---------------------------------------------------------------------------


class TestToolPolicyPipeline:
    """Tests for apply_tool_policy_pipeline."""

    @pytest.mark.unit
    def test_deny_list_removes_tool(self):
        """A tool on the deny list should be filtered out."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "read_file", "owner_only": False},
        ]
        steps = [
            PolicyStep(
                policy=ToolPolicy(deny=["read_file"]),
                label="global",
            ),
        ]

        surviving, log = apply_tool_policy_pipeline(tools, steps, sender_is_owner=True)

        assert surviving == ["web_search"]
        assert len(log) == 1
        assert log[0]["tool"] == "read_file"
        assert log[0]["reason"] == "denied"

    @pytest.mark.unit
    def test_allow_list_keeps_only_listed(self):
        """Only tools on the allow list should survive."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "read_file", "owner_only": False},
            {"name": "write_file", "owner_only": False},
        ]
        steps = [
            PolicyStep(
                policy=ToolPolicy(allow=["web_search", "write_file"]),
                label="global",
            ),
        ]

        surviving, log = apply_tool_policy_pipeline(tools, steps, sender_is_owner=True)

        assert surviving == ["web_search", "write_file"]
        assert len(log) == 1
        assert log[0]["tool"] == "read_file"
        assert log[0]["reason"] == "not_in_allowlist"

    @pytest.mark.unit
    def test_owner_only_non_owner_removed(self):
        """owner_only tools should be removed when sender is not owner."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "write_file", "owner_only": True},
        ]
        steps = [
            PolicyStep(policy=ToolPolicy(), label="sender"),
        ]

        surviving, log = apply_tool_policy_pipeline(
            tools, steps, sender_is_owner=False
        )

        assert surviving == ["web_search"]
        assert log[0]["reason"] == "owner_only"

    @pytest.mark.unit
    def test_owner_only_owner_kept(self):
        """owner_only tools should survive when sender IS the owner."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "write_file", "owner_only": True},
        ]
        steps = [
            PolicyStep(policy=ToolPolicy(), label="sender"),
        ]

        surviving, log = apply_tool_policy_pipeline(
            tools, steps, sender_is_owner=True
        )

        assert surviving == ["web_search", "write_file"]
        assert log == []


# ---------------------------------------------------------------------------
# 2. Hook Runner Tests
# ---------------------------------------------------------------------------


class TestToolHookRunner:
    """Tests for ToolHookRunner before/after hooks."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_before_hook_blocks(self):
        """A before-hook returning 'block' should stop execution."""
        runner = ToolHookRunner()

        async def blocker(name, args, ctx):
            return ("block", None)

        runner.register_before(blocker)

        action, args = await runner.run_before("write_file", {"path": "/etc"}, {})

        assert action == "block"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_before_hook_modifies_args(self):
        """A before-hook can return modified args."""
        runner = ToolHookRunner()

        async def sanitizer(name, args, ctx):
            modified = dict(args)
            modified["sanitized"] = True
            return ("allow", modified)

        runner.register_before(sanitizer)

        action, args = await runner.run_before("read_file", {"path": "/tmp"}, {})

        assert action == "allow"
        assert args["sanitized"] is True
        assert args["path"] == "/tmp"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_after_hook_error_does_not_propagate(self):
        """After-hook exceptions should be logged, not raised."""
        runner = ToolHookRunner()

        async def broken_hook(name, args, result, duration):
            raise RuntimeError("oops")

        runner.register_after(broken_hook)

        # Should not raise
        await runner.run_after("web_search", {}, {"content": "ok"}, 50.0)


# ---------------------------------------------------------------------------
# 3. Loop Detection Tests
# ---------------------------------------------------------------------------


class TestToolLoopDetector:
    """Tests for ToolLoopDetector graduated escalation."""

    @pytest.mark.unit
    def test_escalation_levels(self):
        """Verify graduated escalation: 1=ok, 3=warn, 5=error, 7=block."""
        detector = ToolLoopDetector()
        args = {"query": "same thing"}

        results = []
        for _ in range(8):
            results.append(detector.record("web_search", args))

        # First two calls are ok
        assert results[0] == "ok"
        assert results[1] == "ok"
        # 3rd call triggers warn
        assert results[2] == "warn"
        # 4th is still warn
        assert results[3] == "warn"
        # 5th triggers error
        assert results[4] == "error"
        # 6th is still error
        assert results[5] == "error"
        # 7th triggers block
        assert results[6] == "block"
        # 8th is still block
        assert results[7] == "block"

    @pytest.mark.unit
    def test_different_call_resets_consecutive(self):
        """A different tool name should reset the consecutive count."""
        detector = ToolLoopDetector()
        same_args = {"q": "test"}

        # Call web_search twice
        assert detector.record("web_search", same_args) == "ok"
        assert detector.record("web_search", same_args) == "ok"

        # Inject a different tool call
        assert detector.record("read_file", {"path": "/tmp"}) == "ok"

        # web_search again -- consecutive count starts fresh
        assert detector.record("web_search", same_args) == "ok"

    @pytest.mark.unit
    def test_warning_messages(self):
        """get_warning_message returns appropriate text for each severity."""
        detector = ToolLoopDetector()

        assert "7+" in detector.get_warning_message("web_search", "block")
        assert "5+" in detector.get_warning_message("web_search", "error")
        assert detector.get_warning_message("web_search", "ok") == ""
        assert detector.get_warning_message("web_search", "warn") == ""

    @pytest.mark.unit
    def test_reset_clears_history(self):
        """reset() should clear all history so next call is ok."""
        detector = ToolLoopDetector()
        args = {"q": "same"}

        for _ in range(5):
            detector.record("web_search", args)

        detector.reset()

        assert detector.record("web_search", args) == "ok"


# ---------------------------------------------------------------------------
# 4. Audit Logger Tests
# ---------------------------------------------------------------------------


class TestToolAuditLogger:
    """Tests for ToolAuditLogger JSONL output."""

    @pytest.mark.unit
    def test_writes_jsonl(self, tmp_path):
        """log_tool_call should write a valid JSONL entry to disk."""
        audit = ToolAuditLogger(audit_dir=str(tmp_path))

        audit.log_tool_call(
            tool_name="web_search",
            args={"query": "hello"},
            result_content="some result",
            is_error=False,
            duration_ms=42.5,
            sender_id="user_123",
            chat_id="chat_456",
        )

        log_file = tmp_path / "tool_audit.jsonl"
        assert log_file.exists()

        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["event"] == "TOOL_CALL"
        assert entry["tool"] == "web_search"
        assert entry["is_error"] is False
        assert entry["duration_ms"] == 42.5
        assert entry["sender"] == "user_123"
        assert entry["chat_id"] == "chat_456"
        assert entry["result_length"] == len("some result")

    @pytest.mark.unit
    def test_no_audit_dir_skips_write(self):
        """When audit_dir is None, log_tool_call should not raise."""
        audit = ToolAuditLogger(audit_dir=None)

        # Should be a no-op, no exception
        audit.log_tool_call(
            tool_name="web_search",
            args={},
            result_content="",
            is_error=False,
            duration_ms=0.0,
            sender_id="",
            chat_id="",
        )


# ---------------------------------------------------------------------------
# 5. Policy Builder Tests
# ---------------------------------------------------------------------------


class TestBuildPolicySteps:
    """Tests for build_policy_steps helper."""

    @pytest.mark.unit
    def test_global_deny_plus_channel_deny(self):
        """Config with global deny + channel deny produces 3 steps."""
        config = {
            "tools": {"deny": ["write_file"]},
            "channels": {
                "whatsapp": {
                    "tools": {"deny": ["read_file"]},
                }
            },
        }

        steps = build_policy_steps(config, channel_id="whatsapp")

        assert len(steps) == 3
        assert steps[0].label == "global"
        assert steps[0].policy.deny == ["write_file"]
        assert steps[1].label == "channel:whatsapp"
        assert steps[1].policy.deny == ["read_file"]
        assert steps[2].label == "sender"

    @pytest.mark.unit
    def test_no_config_produces_sender_only(self):
        """Empty config should still produce the sender step."""
        steps = build_policy_steps({})

        assert len(steps) == 1
        assert steps[0].label == "sender"

    @pytest.mark.unit
    def test_channel_without_tools_skipped(self):
        """Channel present but no tools config -- only global + sender."""
        config = {
            "tools": {"allow": ["web_search"]},
            "channels": {"telegram": {}},
        }

        steps = build_policy_steps(config, channel_id="telegram")

        assert len(steps) == 2
        assert steps[0].label == "global"
        assert steps[1].label == "sender"
