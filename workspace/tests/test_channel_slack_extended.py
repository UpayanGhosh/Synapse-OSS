"""Extended Slack channel tests — filling gaps in test_slack_channel.py.

Covers:
- Thread tracking (_track_thread, _is_active_thread, eviction, expiry)
- Message splitting (_split_message) for long messages
- send() with thread_ts routing
- _dispatch() thread context propagation
"""

import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importlib.util

SLK_AVAILABLE = (
    importlib.util.find_spec("slack_bolt") is not None
    and importlib.util.find_spec("sci_fi_dashboard.channels.slack") is not None
)

pytestmark = pytest.mark.skipif(
    not SLK_AVAILABLE, reason="SlackChannel or slack_bolt not available"
)

if SLK_AVAILABLE:
    from sci_fi_dashboard.channels.slack import SlackChannel


def _make_channel(enqueue_fn=None):
    with (
        patch("slack_bolt.async_app.AsyncApp.__init__", return_value=None),
        patch("slack_sdk.web.async_client.AsyncWebClient.__init__", return_value=None),
    ):
        ch = SlackChannel(bot_token="xoxb-fake", app_token="xapp-fake", enqueue_fn=enqueue_fn)
    return ch


# ===========================================================================
# Thread tracking
# ===========================================================================


class TestSlackThreadTracking:
    """Tests for thread participation tracking."""

    def test_track_thread_stores_timestamp(self):
        ch = _make_channel()
        ch._track_thread("1234.5678")
        assert "1234.5678" in ch._active_threads

    def test_is_active_thread_true_for_recent(self):
        ch = _make_channel()
        ch._track_thread("1234.5678")
        assert ch._is_active_thread("1234.5678") is True

    def test_is_active_thread_false_for_unknown(self):
        ch = _make_channel()
        assert ch._is_active_thread("unknown") is False

    def test_is_active_thread_false_for_expired(self):
        ch = _make_channel()
        ch._active_threads["old_thread"] = time.monotonic() - (SlackChannel._THREAD_TTL_SECS + 1)
        assert ch._is_active_thread("old_thread") is False
        # Expired entry should be lazily removed
        assert "old_thread" not in ch._active_threads

    def test_track_thread_evicts_oldest_at_max(self):
        ch = _make_channel()
        ch._MAX_ACTIVE_THREADS = 3
        for i in range(4):
            ch._track_thread(f"thread_{i}")
            time.sleep(0.001)

        assert len(ch._active_threads) <= 3
        # The oldest (thread_0) should have been evicted
        assert "thread_3" in ch._active_threads


# ===========================================================================
# Message splitting
# ===========================================================================


class TestSlackSplitMessage:
    """Tests for SlackChannel._split_message static method."""

    def test_short_message_not_split(self):
        result = SlackChannel._split_message("hello")
        assert result == ["hello"]

    def test_long_message_split_at_paragraph(self):
        text = "A" * 2500 + "\n\n" + "B" * 2500
        result = SlackChannel._split_message(text)
        assert len(result) == 2

    def test_hard_cut_no_boundaries(self):
        text = "x" * 6000
        result = SlackChannel._split_message(text)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= SlackChannel.MAX_CHARS


# ===========================================================================
# send() with thread routing
# ===========================================================================


class TestSlackSendThread:
    """Tests for send() thread_ts resolution."""

    @pytest.mark.asyncio
    async def test_send_with_explicit_thread_ts(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        ch._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})

        result = await ch.send("C123", "hi", thread_ts="1234.5678")
        assert result is True
        ch._web_client.chat_postMessage.assert_awaited_once_with(
            channel="C123", text="hi", thread_ts="1234.5678"
        )

    @pytest.mark.asyncio
    async def test_send_uses_last_known_thread(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        ch._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})
        ch._last_thread_ts["C123"] = "auto_thread"

        result = await ch.send("C123", "hi")
        assert result is True
        ch._web_client.chat_postMessage.assert_awaited_once_with(
            channel="C123", text="hi", thread_ts="auto_thread"
        )

    @pytest.mark.asyncio
    async def test_send_no_thread_when_none_known(self):
        ch = _make_channel()
        ch._web_client = AsyncMock()
        ch._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})

        result = await ch.send("C123", "hi")
        assert result is True
        ch._web_client.chat_postMessage.assert_awaited_once_with(channel="C123", text="hi")


# ===========================================================================
# _dispatch thread propagation
# ===========================================================================


class TestSlackDispatchThread:
    """Tests for _dispatch() thread context."""

    @pytest.mark.asyncio
    async def test_dispatch_records_thread_ts(self):
        enqueue_fn = AsyncMock()
        ch = _make_channel(enqueue_fn=enqueue_fn)

        event = {
            "user": "U1",
            "channel": "C1",
            "text": "reply",
            "ts": "1111.2222",
            "thread_ts": "1111.0000",
        }
        await ch._dispatch(event, is_group=True)

        # thread_ts should be recorded
        assert ch._last_thread_ts["C1"] == "1111.0000"

    @pytest.mark.asyncio
    async def test_dispatch_thread_ts_in_raw(self):
        enqueue_fn = AsyncMock()
        ch = _make_channel(enqueue_fn=enqueue_fn)

        event = {
            "user": "U1",
            "channel": "C1",
            "text": "threaded",
            "ts": "2222.3333",
            "thread_ts": "2222.0000",
        }
        await ch._dispatch(event, is_group=False)

        msg = enqueue_fn.call_args[0][0]
        assert msg.raw.get("message_thread_id") == "2222.0000"

    @pytest.mark.asyncio
    async def test_dispatch_no_thread_ts(self):
        enqueue_fn = AsyncMock()
        ch = _make_channel(enqueue_fn=enqueue_fn)

        event = {
            "user": "U1",
            "channel": "C1",
            "text": "no thread",
            "ts": "3333.0000",
        }
        await ch._dispatch(event, is_group=False)

        msg = enqueue_fn.call_args[0][0]
        assert "message_thread_id" not in msg.raw
