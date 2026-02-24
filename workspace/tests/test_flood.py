"""
Test Suite: FloodGate Batching
==============================
Tests the FloodGate class which batches rapid-fire messages
from the same user within a configurable time window.

This prevents webhook timeout issues when users send multiple
messages in quick succession.
"""

import pytest
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.flood import FloodGate


class TestFloodGate:
    """Test cases for message batching logic."""

    @pytest.fixture
    def flood_gate(self):
        """Create a FloodGate with 1-second batch window."""
        return FloodGate(batch_window_seconds=1.0)

    @pytest.mark.asyncio
    async def test_single_message_batched(self, flood_gate):
        """Single message should be flushed after window expires."""
        flushed_messages = []

        async def callback(chat_id, message, metadata):
            flushed_messages.append({"chat_id": chat_id, "message": message})

        flood_gate.set_callback(callback)

        await flood_gate.incoming("chat_001", "Hello", {"sender": "user1"})

        # Message should not be flushed immediately
        assert len(flushed_messages) == 0

        # Wait for window to expire
        await asyncio.sleep(1.5)

        # Now message should be flushed
        assert len(flushed_messages) == 1
        assert flushed_messages[0]["message"] == "Hello"

    @pytest.mark.asyncio
    async def test_multiple_messages_batched_together(self, flood_gate):
        """Multiple messages from same user should be combined."""
        flushed_messages = []

        async def callback(chat_id, message, metadata):
            flushed_messages.append(message)

        flood_gate.set_callback(callback)

        # Send 3 messages rapidly
        await flood_gate.incoming("chat_001", "Hello", {"sender": "user1"})
        await flood_gate.incoming("chat_001", "How are you?", {"sender": "user1"})
        await flood_gate.incoming("chat_001", "Reply please", {"sender": "user1"})

        # Wait for window to expire
        await asyncio.sleep(1.5)

        # Should be combined into single message
        assert len(flushed_messages) == 1
        assert "Hello" in flushed_messages[0]
        assert "How are you?" in flushed_messages[0]
        assert "Reply please" in flushed_messages[0]

    @pytest.mark.asyncio
    async def test_different_chats_separate(self, flood_gate):
        """Messages from different chats should not be batched together."""
        flushed_messages = []

        async def callback(chat_id, message, metadata):
            flushed_messages.append({"chat_id": chat_id, "message": message})

        flood_gate.set_callback(callback)

        # Send messages to different chats
        await flood_gate.incoming("chat_001", "Message 1", {"sender": "user1"})
        await flood_gate.incoming("chat_002", "Message 2", {"sender": "user2"})

        # Wait for window to expire
        await asyncio.sleep(1.5)

        # Both messages should be flushed separately
        assert len(flushed_messages) == 2

    @pytest.mark.asyncio
    async def test_debounce_extends_window(self, flood_gate):
        """Additional messages should extend the batch window."""
        flushed_messages = []

        async def callback(chat_id, message, metadata):
            flushed_messages.append(
                {
                    "chat_id": chat_id,
                    "message": message,
                    "time": asyncio.get_event_loop().time(),
                }
            )

        flood_gate.set_callback(callback)

        start_time = asyncio.get_event_loop().time()

        # Send first message
        await flood_gate.incoming("chat_001", "First", {"sender": "user1"})

        # Wait 0.8 seconds (less than 1s window)
        await asyncio.sleep(0.8)

        # Send second message - this should extend the window
        await flood_gate.incoming("chat_001", "Second", {"sender": "user1"})

        # Wait 0.8 seconds (0.8 + 0.8 = 1.6s, but extended window should keep it)
        await asyncio.sleep(0.8)

        # Should not have flushed yet (window extended)
        assert len(flushed_messages) == 0

        # Wait for extended window
        await asyncio.sleep(1.0)

        # Now should have flushed with both messages
        assert len(flushed_messages) == 1

    @pytest.mark.asyncio
    async def test_metadata_updated(self, flood_gate):
        """Latest metadata should be used when flushing."""
        flushed_messages = []

        async def callback(chat_id, message, metadata):
            flushed_messages.append(metadata)

        flood_gate.set_callback(callback)

        await flood_gate.incoming("chat_001", "Message 1", {"count": 1})
        await asyncio.sleep(1.5)

        assert len(flushed_messages) == 1
        assert flushed_messages[0]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty_callback_no_error(self, flood_gate):
        """Should not error if no callback is set."""
        # Should not raise
        await flood_gate.incoming("chat_001", "Hello", {"sender": "user1"})
        await asyncio.sleep(1.5)
        # No assertion - just ensure no exception

    @pytest.mark.asyncio
    async def test_window_respected(self, flood_gate):
        """Different window sizes should work correctly."""
        fast_gate = FloodGate(batch_window_seconds=0.5)

        flushed = []

        async def callback(chat_id, message, metadata):
            flushed.append(message)

        fast_gate.set_callback(callback)

        await fast_gate.incoming("chat_001", "Fast message", {"sender": "user1"})

        # Wait less than window
        await asyncio.sleep(0.3)
        assert len(flushed) == 0

        # Wait for window
        await asyncio.sleep(0.5)
        assert len(flushed) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
