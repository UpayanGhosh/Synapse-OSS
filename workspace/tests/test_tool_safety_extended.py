"""
Test Suite: Tool Safety Extended Coverage
==========================================
Gap-filling tests for tool_safety.py not covered in test_tool_safety.py:
- Multi-step policy pipeline interactions
- Multiple before-hooks chaining
- After-hook called with correct timing data
- Loop detector with varying argument hashes
- Audit logger multiple entries and truncation
- build_policy_steps with global allow + channel deny
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.tool_safety import (
    PolicyStep,
    ToolAuditLogger,
    ToolHookRunner,
    ToolLoopDetector,
    ToolPolicy,
    apply_tool_policy_pipeline,
    build_policy_steps,
)

# ---------------------------------------------------------------------------
# Multi-step Policy Pipeline
# ---------------------------------------------------------------------------


class TestPolicyPipelineMultiStep:
    """Tests for multi-step policy pipeline interactions."""

    @pytest.mark.unit
    def test_global_deny_then_channel_allow(self):
        """Global deny should remove tool before channel allow can see it."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "read_file", "owner_only": False},
            {"name": "write_file", "owner_only": False},
        ]
        steps = [
            PolicyStep(
                policy=ToolPolicy(deny=["write_file"]),
                label="global",
            ),
            PolicyStep(
                policy=ToolPolicy(allow=["web_search", "write_file"]),
                label="channel",
            ),
            PolicyStep(policy=ToolPolicy(), label="sender"),
        ]

        surviving, log = apply_tool_policy_pipeline(tools, steps, sender_is_owner=True)
        # write_file denied at global, read_file not in channel allow
        assert "write_file" not in surviving
        assert "read_file" not in surviving
        assert surviving == ["web_search"]

    @pytest.mark.unit
    def test_owner_only_checked_at_every_step(self):
        """owner_only check should happen at each step, not just first."""
        tools = [
            {"name": "admin_tool", "owner_only": True},
            {"name": "public_tool", "owner_only": False},
        ]
        steps = [
            PolicyStep(policy=ToolPolicy(), label="global"),
            PolicyStep(policy=ToolPolicy(), label="channel"),
            PolicyStep(policy=ToolPolicy(), label="sender"),
        ]

        surviving, log = apply_tool_policy_pipeline(tools, steps, sender_is_owner=False)
        # admin_tool should be removed at the first step that checks owner_only
        assert "admin_tool" not in surviving
        assert "public_tool" in surviving
        assert any(entry["reason"] == "owner_only" for entry in log)

    @pytest.mark.unit
    def test_empty_tools_list(self):
        """Empty tools list should produce empty surviving list."""
        steps = [PolicyStep(policy=ToolPolicy(deny=["anything"]), label="global")]
        surviving, log = apply_tool_policy_pipeline([], steps, sender_is_owner=True)
        assert surviving == []
        assert log == []

    @pytest.mark.unit
    def test_empty_steps_list(self):
        """Empty steps list should pass all tools through."""
        tools = [
            {"name": "a", "owner_only": False},
            {"name": "b", "owner_only": False},
        ]
        surviving, log = apply_tool_policy_pipeline(tools, [], sender_is_owner=True)
        assert surviving == ["a", "b"]
        assert log == []

    @pytest.mark.unit
    def test_deny_and_allow_on_same_step(self):
        """When a step has both deny and allow, deny is checked first."""
        tools = [
            {"name": "web_search", "owner_only": False},
            {"name": "read_file", "owner_only": False},
            {"name": "write_file", "owner_only": False},
        ]
        steps = [
            PolicyStep(
                policy=ToolPolicy(
                    deny=["web_search"],
                    allow=["web_search", "read_file"],  # web_search in both
                ),
                label="conflicting",
            ),
        ]

        surviving, log = apply_tool_policy_pipeline(tools, steps, sender_is_owner=True)
        # web_search should be denied (deny checked before allow)
        assert "web_search" not in surviving
        assert "read_file" in surviving
        # write_file not in allowlist
        assert "write_file" not in surviving


# ---------------------------------------------------------------------------
# Hook Runner Extended
# ---------------------------------------------------------------------------


class TestToolHookRunnerExtended:
    """Extended tests for hook chaining and ordering."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_before_hooks_chain(self):
        """Multiple before-hooks should chain arg modifications."""
        runner = ToolHookRunner()
        call_order = []

        async def hook_a(name, args, ctx):
            call_order.append("a")
            modified = dict(args)
            modified["from_a"] = True
            return ("allow", modified)

        async def hook_b(name, args, ctx):
            call_order.append("b")
            modified = dict(args)
            modified["from_b"] = True
            # Should see from_a since hook_a ran first
            assert args.get("from_a") is True
            return ("allow", modified)

        runner.register_before(hook_a)
        runner.register_before(hook_b)

        action, args = await runner.run_before("tool", {"original": True}, {})
        assert action == "allow"
        assert args["from_a"] is True
        assert args["from_b"] is True
        assert call_order == ["a", "b"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_second_hook_blocks_after_first_allows(self):
        """If second before-hook blocks, overall action should be block."""
        runner = ToolHookRunner()

        async def allow_hook(name, args, ctx):
            return ("allow", args)

        async def block_hook(name, args, ctx):
            return ("block", None)

        runner.register_before(allow_hook)
        runner.register_before(block_hook)

        action, _ = await runner.run_before("tool", {}, {})
        assert action == "block"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_before_hook_exception_does_not_block(self):
        """Before-hook exception should be logged, not block execution."""
        runner = ToolHookRunner()

        async def broken_hook(name, args, ctx):
            raise RuntimeError("broken")

        runner.register_before(broken_hook)

        action, args = await runner.run_before("tool", {"key": "val"}, {})
        # Should allow despite the error
        assert action == "allow"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_after_hooks_all_called(self):
        """All after-hooks should be called even if one fails."""
        runner = ToolHookRunner()
        calls = []

        async def hook_1(name, args, result, duration):
            calls.append(1)

        async def hook_2(name, args, result, duration):
            raise RuntimeError("fail")

        async def hook_3(name, args, result, duration):
            calls.append(3)

        runner.register_after(hook_1)
        runner.register_after(hook_2)
        runner.register_after(hook_3)

        await runner.run_after("tool", {}, {}, 10.0)
        # hook_1 and hook_3 should have been called; hook_2 failed silently
        assert 1 in calls
        assert 3 in calls

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_hooks_registered(self):
        """With no hooks, run_before should return allow, run_after should be noop."""
        runner = ToolHookRunner()
        action, args = await runner.run_before("tool", {"a": 1}, {})
        assert action == "allow"
        assert args == {"a": 1}

        # Should not raise
        await runner.run_after("tool", {}, {}, 0.0)


# ---------------------------------------------------------------------------
# Loop Detector Extended
# ---------------------------------------------------------------------------


class TestToolLoopDetectorExtended:
    """Extended loop detection tests."""

    @pytest.mark.unit
    def test_different_args_do_not_trigger(self):
        """Same tool with different args should not trigger escalation."""
        detector = ToolLoopDetector()
        results = []
        for i in range(10):
            results.append(detector.record("web_search", {"query": f"different_{i}"}))

        # All should be ok since args differ each time
        assert all(r == "ok" for r in results)

    @pytest.mark.unit
    def test_interleaved_tools_with_same_args(self):
        """Interleaving different tools should break the consecutive count."""
        detector = ToolLoopDetector()
        same_args = {"q": "test"}

        detector.record("tool_a", same_args)
        detector.record("tool_a", same_args)
        detector.record("tool_b", same_args)  # breaks consecutive for tool_a
        result = detector.record("tool_a", same_args)

        assert result == "ok"  # reset after tool_b

    @pytest.mark.unit
    def test_history_accumulates(self):
        """History should grow with each record call."""
        detector = ToolLoopDetector()
        for i in range(5):
            detector.record("tool", {"i": i})
        assert len(detector._history) == 5

    @pytest.mark.unit
    def test_reset_and_restart(self):
        """After reset, consecutive counter should start from scratch."""
        detector = ToolLoopDetector()
        args = {"q": "same"}

        # Get to warn level (3)
        for _ in range(4):
            detector.record("tool", args)

        detector.reset()
        assert len(detector._history) == 0

        # Should start fresh
        assert detector.record("tool", args) == "ok"
        assert detector.record("tool", args) == "ok"


# ---------------------------------------------------------------------------
# Audit Logger Extended
# ---------------------------------------------------------------------------


class TestToolAuditLoggerExtended:
    """Extended audit logger tests."""

    @pytest.mark.unit
    def test_multiple_entries(self, tmp_path):
        """Multiple calls should append multiple JSONL lines."""
        audit = ToolAuditLogger(audit_dir=str(tmp_path))
        for i in range(5):
            audit.log_tool_call(
                tool_name=f"tool_{i}",
                args={},
                result_content="ok",
                is_error=False,
                duration_ms=float(i),
                sender_id="user",
                chat_id="chat",
            )

        log_file = tmp_path / "tool_audit.jsonl"
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5

    @pytest.mark.unit
    def test_args_preview_truncated(self, tmp_path):
        """args_preview should be truncated to 200 chars."""
        audit = ToolAuditLogger(audit_dir=str(tmp_path))
        long_args = {"content": "x" * 500}
        audit.log_tool_call(
            tool_name="tool",
            args=long_args,
            result_content="ok",
            is_error=False,
            duration_ms=1.0,
            sender_id="user",
            chat_id="chat",
        )

        log_file = tmp_path / "tool_audit.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert len(entry["args_preview"]) <= 200

    @pytest.mark.unit
    def test_error_entries_flagged(self, tmp_path):
        """Error tool calls should have is_error=True in audit."""
        audit = ToolAuditLogger(audit_dir=str(tmp_path))
        audit.log_tool_call(
            tool_name="broken",
            args={},
            result_content="error message",
            is_error=True,
            duration_ms=50.0,
            sender_id="user",
            chat_id="chat",
        )

        log_file = tmp_path / "tool_audit.jsonl"
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["is_error"] is True
        assert entry["result_length"] == len("error message")


# ---------------------------------------------------------------------------
# build_policy_steps Extended
# ---------------------------------------------------------------------------


class TestBuildPolicyStepsExtended:
    """Extended build_policy_steps tests."""

    @pytest.mark.unit
    def test_global_allow_with_channel_deny(self):
        """Global allow + channel deny should produce both steps."""
        config = {
            "tools": {"allow": ["web_search", "read_file", "write_file"]},
            "channels": {
                "telegram": {
                    "tools": {"deny": ["write_file"]},
                }
            },
        }

        steps = build_policy_steps(config, channel_id="telegram")
        assert len(steps) == 3
        assert steps[0].label == "global"
        assert steps[0].policy.allow == ["web_search", "read_file", "write_file"]
        assert steps[1].label == "channel:telegram"
        assert steps[1].policy.deny == ["write_file"]

    @pytest.mark.unit
    def test_no_channel_id_skips_channel_step(self):
        """When channel_id is None, channel step should be skipped."""
        config = {
            "tools": {"deny": ["web_search"]},
            "channels": {
                "whatsapp": {"tools": {"deny": ["read_file"]}},
            },
        }

        steps = build_policy_steps(config, channel_id=None)
        assert len(steps) == 2
        assert steps[0].label == "global"
        assert steps[1].label == "sender"

    @pytest.mark.unit
    def test_nonexistent_channel_id(self):
        """Channel ID not in config should skip channel step."""
        config = {
            "tools": {"deny": ["web_search"]},
            "channels": {"whatsapp": {"tools": {"deny": ["read_file"]}}},
        }

        steps = build_policy_steps(config, channel_id="unknown_channel")
        assert len(steps) == 2  # global + sender, no channel
