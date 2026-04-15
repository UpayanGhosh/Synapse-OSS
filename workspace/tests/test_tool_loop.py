"""test_tool_loop.py — Tests for ToolLoopDetector.

Covers:
- OK level for normal tool usage
- WARNING at 10 identical calls
- CRITICAL at 20 identical calls
- ToolLoopError raised at 30 (global circuit breaker)
- Ping-pong pattern detected
- Different args = different signatures
- Window size respected
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from sci_fi_dashboard.multiuser.tool_loop_detector import (
        CRITICAL_THRESHOLD,
        GLOBAL_CIRCUIT_BREAKER,
        WARNING_THRESHOLD,
        ToolLoopDetector,
        ToolLoopError,
        ToolLoopLevel,
        _signature,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="sci_fi_dashboard/multiuser not yet available",
)


class TestToolLoopDetector:
    """Tests for ToolLoopDetector severity levels."""

    @_skip
    def test_ok_for_normal_usage(self):
        """A few diverse tool calls remain at OK level."""
        d = ToolLoopDetector(window_size=50)
        for i in range(5):
            level = d.record(f"tool_{i}", {"arg": i})
            assert level == ToolLoopLevel.OK

    @_skip
    def test_warning_at_10_identical_calls(self):
        """10 identical calls trigger WARNING level."""
        d = ToolLoopDetector(window_size=50)
        for _i in range(WARNING_THRESHOLD - 1):
            level = d.record("read_file", {"path": "/foo"})
            assert level == ToolLoopLevel.OK

        # The 10th call should trigger WARNING.
        level = d.record("read_file", {"path": "/foo"})
        assert level == ToolLoopLevel.WARNING

    @_skip
    def test_critical_at_20_identical_calls(self):
        """20 identical calls trigger CRITICAL level."""
        d = ToolLoopDetector(window_size=50)
        for _i in range(CRITICAL_THRESHOLD - 1):
            level = d.record("read_file", {"path": "/foo"})
        # All before 20 should be OK or WARNING.
        assert level == ToolLoopLevel.WARNING

        # The 20th call should trigger CRITICAL.
        level = d.record("read_file", {"path": "/foo"})
        assert level == ToolLoopLevel.CRITICAL

    @_skip
    def test_tool_loop_error_at_30(self):
        """30 total tool calls within window raises ToolLoopError."""
        d = ToolLoopDetector(window_size=50)
        # Use different tool names to avoid hitting CRITICAL before 30.
        for i in range(GLOBAL_CIRCUIT_BREAKER - 1):
            d.record(f"tool_{i}", {"idx": i})

        with pytest.raises(ToolLoopError):
            d.record("tool_final", {"idx": 999})

    @_skip
    def test_ping_pong_detected(self):
        """Alternating A-B-A-B pattern triggers WARNING."""
        d = ToolLoopDetector(window_size=50)
        for _ in range(2):
            d.record("tool_a", {"x": 1})
            d.record("tool_b", {"y": 2})

        # After A-B-A-B (4 calls), the next A should detect ping-pong.
        # But the detection happens on the 4th call which completes the pattern.
        # Let's check: at the 4th call (B), the tail is A-B-A-B.
        # Actually let's re-test more carefully:
        d2 = ToolLoopDetector(window_size=50)
        levels = []
        for _ in range(3):
            levels.append(d2.record("tool_a", {"x": 1}))
            levels.append(d2.record("tool_b", {"y": 2}))

        # At some point after 4 alternating calls, WARNING should appear.
        assert ToolLoopLevel.WARNING in levels

    @_skip
    def test_different_args_different_signatures(self):
        """Same tool name with different args produces different signatures."""
        sig1 = _signature("read_file", {"path": "/foo"})
        sig2 = _signature("read_file", {"path": "/bar"})
        assert sig1 != sig2

        # Different args should not accumulate toward the same threshold.
        d = ToolLoopDetector(window_size=50)
        for i in range(WARNING_THRESHOLD + 5):
            level = d.record("read_file", {"path": f"/file_{i}"})
            assert level == ToolLoopLevel.OK

    @_skip
    def test_same_args_same_signature(self):
        """Same tool name + same args = same signature regardless of dict order."""
        sig1 = _signature("tool", {"a": 1, "b": 2})
        sig2 = _signature("tool", {"b": 2, "a": 1})
        assert sig1 == sig2

    @_skip
    def test_window_size_respected(self):
        """Old entries beyond window_size are evicted, preventing false positives."""
        d = ToolLoopDetector(window_size=15)

        # Record 9 identical calls.
        for _ in range(9):
            d.record("old_tool", {"x": 1})

        # Fill the rest of the window with different calls to push old ones out.
        for i in range(10):
            d.record(f"new_tool_{i}", {"i": i})

        # Now record 'old_tool' again — should be OK because the old entries
        # were evicted.
        level = d.record("old_tool", {"x": 1})
        assert level == ToolLoopLevel.OK

    @_skip
    def test_get_injection_message_at_warning(self):
        """get_injection_message returns a string at WARNING level."""
        d = ToolLoopDetector(window_size=50)
        for _ in range(WARNING_THRESHOLD):
            d.record("read_file", {"path": "/foo"})

        msg = d.get_injection_message()
        assert msg is not None
        assert "tool loop" in msg.lower() or "Potential" in msg

    @_skip
    def test_get_injection_message_none_at_ok(self):
        """get_injection_message returns None at OK level."""
        d = ToolLoopDetector(window_size=50)
        d.record("tool_a", {"x": 1})
        msg = d.get_injection_message()
        assert msg is None

    @_skip
    def test_get_injection_message_none_at_critical(self):
        """get_injection_message returns None at CRITICAL level (only WARNING)."""
        d = ToolLoopDetector(window_size=50)
        for _ in range(CRITICAL_THRESHOLD):
            d.record("tool_a", {"x": 1})
        msg = d.get_injection_message()
        assert msg is None


class TestToolLoopLevel:
    """Tests for ToolLoopLevel enum."""

    @_skip
    def test_str_values(self):
        """ToolLoopLevel values match expected strings."""
        assert ToolLoopLevel.OK == "ok"
        assert ToolLoopLevel.WARNING == "warning"
        assert ToolLoopLevel.CRITICAL == "critical"

    @_skip
    def test_is_str_enum(self):
        """ToolLoopLevel members are strings."""
        assert isinstance(ToolLoopLevel.OK, str)
