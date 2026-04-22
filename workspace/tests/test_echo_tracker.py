"""Phase 14 Wave 0 -- failing stubs for ACL-01, ACL-02.

Tests for OutboundTracker (ring-buffer of last-N sent messages, used to
drop self-echoes at the inbound webhook before FloodGate).
Imports from sci_fi_dashboard.gateway.echo_tracker which is installed in
Wave 1 (Plan 03). pytest.importorskip skips the whole module until then.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.importorskip(
    "sci_fi_dashboard.gateway.echo_tracker",
    reason="Phase 14 echo_tracker module not yet installed (Wave 1)",
)

from sci_fi_dashboard.gateway.echo_tracker import (  # noqa: E402
    OutboundEntry,
    OutboundTracker,
)


# ---------------------------------------------------------------------------
# ACL-01: ring-buffer records
# ---------------------------------------------------------------------------


class TestOutboundTracker:
    """ACL-01: OutboundTracker ring-buffer record behaviour."""

    def test_outbound_tracker_record(self):
        """Recording a single message yields len == 1."""
        tracker = OutboundTracker()
        tracker.record("chat_a", "hello")
        assert len(tracker) == 1

    def test_outbound_window_eviction(self):
        """Oldest entry is evicted when window_size is exceeded."""
        tracker = OutboundTracker(window_size=5)
        for i in range(6):
            tracker.record(f"chat_{i}", f"msg_{i}")
        # Only the last 5 should remain
        assert len(tracker) == 5
        # The very first message (chat_0/msg_0) must be gone
        assert tracker.is_echo("chat_0", "msg_0") is False
        # The most recent message (chat_5/msg_5) must still be present
        assert tracker.is_echo("chat_5", "msg_5") is True

    def test_outbound_record_stores_hash_not_raw(self):
        """Record stores a truncated SHA-256 hash, never the raw text."""
        tracker = OutboundTracker()
        sensitive = "my-credit-card-4111-1111-1111-1111"
        tracker.record("chat_a", sensitive)
        entry: OutboundEntry = list(tracker._buf)[0]
        # The full PAN and any partial fragment must not appear in the hash
        assert "4111-1111-1111-1111" not in entry.text_hash
        assert "4111" not in entry.text_hash

    def test_outbound_record_multiple_chats_independent(self):
        """Each chat_id is tracked independently; a third chat never matches."""
        tracker = OutboundTracker()
        tracker.record("chat_a", "hi")
        tracker.record("chat_b", "hi")
        assert tracker.is_echo("chat_a", "hi") is True
        assert tracker.is_echo("chat_b", "hi") is True
        assert tracker.is_echo("chat_c", "hi") is False


# ---------------------------------------------------------------------------
# ACL-02: match semantics + TTL
# ---------------------------------------------------------------------------


class TestIsEcho:
    """ACL-02: is_echo match semantics, chat isolation, and TTL expiry."""

    def test_outbound_is_echo_match(self):
        """is_echo returns True for a message that was just recorded."""
        tracker = OutboundTracker()
        tracker.record("chat_a", "hello")
        assert tracker.is_echo("chat_a", "hello") is True

    def test_outbound_is_echo_different_chat(self):
        """is_echo returns False when the chat_id does not match."""
        tracker = OutboundTracker()
        tracker.record("chat_a", "hello")
        assert tracker.is_echo("chat_b", "hello") is False

    def test_outbound_is_echo_different_text(self):
        """is_echo returns False when the text does not match."""
        tracker = OutboundTracker()
        tracker.record("chat_a", "hello")
        assert tracker.is_echo("chat_a", "goodbye") is False

    def test_outbound_ttl_expiry(self):
        """An entry older than ttl_s is treated as expired and not an echo."""
        tracker = OutboundTracker(ttl_s=60.0)
        with patch("sci_fi_dashboard.gateway.echo_tracker.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            tracker.record("chat_a", "hello")

            # Within TTL — should be an echo
            mock_time.monotonic.return_value = 1000.0
            assert tracker.is_echo("chat_a", "hello") is True

            # Beyond TTL — must not be an echo
            mock_time.monotonic.return_value = 1061.0
            assert tracker.is_echo("chat_a", "hello") is False

    def test_outbound_tracker_hash_collision_resistant(self):
        """Querying an unrecorded string from a large pool returns False."""
        import random
        import string

        rng = random.Random(42)

        def rand_str(n: int = 32) -> str:
            return "".join(rng.choices(string.ascii_letters + string.digits, k=n))

        tracker = OutboundTracker(window_size=2000)
        recorded = set()
        for _ in range(1000):
            s = rand_str()
            recorded.add(s)
            tracker.record("chat_x", s)

        # Pick a string that was definitely never recorded
        probe = rand_str(64)
        while probe in recorded:
            probe = rand_str(64)

        assert tracker.is_echo("chat_x", probe) is False


# ---------------------------------------------------------------------------
# ACL-02 integration seam — xfail stubs (wired in Plan 03)
# ---------------------------------------------------------------------------


class TestEchoWebhook:
    """ACL-02 integration seam: echo filtering at the inbound webhook layer."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Webhook integration wired in Plan 03", strict=False)
    async def test_echo_dropped_in_webhook(self):
        """Echoed messages must be silently dropped before reaching FloodGate."""
        pytest.fail("Plan 03 must implement real webhook integration")

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Webhook integration wired in Plan 03", strict=False)
    async def test_non_echo_passes_through(self):
        """Non-echo messages must continue through the pipeline unchanged."""
        pytest.fail("Plan 03 must implement real webhook integration")
