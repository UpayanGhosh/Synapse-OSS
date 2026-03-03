"""
Tests for Phase 5 Slack channel adapter (SLK-01 through SLK-04).

Import guard:
  Until Plan 05-03 creates sci_fi_dashboard/channels/slack.py,
  SLK_AVAILABLE=False and all SlackChannel-dependent tests are skipped.
  Mirrors the pattern from test_whatsapp_channel.py — single guard, clean
  SKIP state, one-line removal when the module ships.

Test coverage:
  SLK-01: channel_id property, health_check(), start() uses connect_async()
  SLK-02: receive() normalizes DM and group events; _dispatch() enqueues ChannelMessage
  SLK-03: send() calls chat_postMessage; send_typing() and mark_read() are no-ops
  SLK-04: token prefix validation at __init__ time; tokens stored on instance
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import: guard for slack channel
#
# Until Plan 05-03 creates sci_fi_dashboard/channels/slack.py,
# SLK_AVAILABLE=False and all tests are skipped.
# ---------------------------------------------------------------------------
SLK_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.slack") is not None

pytestmark = pytest.mark.skipif(
    not SLK_AVAILABLE,
    reason="SlackChannel not yet implemented — skipping SLK tests",
)

if SLK_AVAILABLE:
    from sci_fi_dashboard.channels.slack import SlackChannel, _validate_slack_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(enqueue_fn=None) -> "SlackChannel":
    """Construct SlackChannel with mocked Slack SDK internals."""
    with patch("slack_bolt.async_app.AsyncApp.__init__", return_value=None), patch(
        "slack_sdk.web.async_client.AsyncWebClient.__init__", return_value=None
    ):
        ch = SlackChannel(
            bot_token="xoxb-fake",
            app_token="xapp-fake",
            enqueue_fn=enqueue_fn,
        )
    return ch


# ---------------------------------------------------------------------------
# SLK-04: Token validation (sync tests)
# ---------------------------------------------------------------------------


def test_invalid_bot_token_prefix_raises():
    """SLK-04: Wrong bot_token prefix raises ValueError mentioning 'xoxb-'."""
    with pytest.raises(ValueError, match="xoxb-"):
        _validate_slack_tokens("invalid-token", "xapp-fake")


def test_invalid_app_token_prefix_raises():
    """SLK-04: Wrong app_token prefix raises ValueError mentioning 'xapp-'."""
    with pytest.raises(ValueError, match="xapp-"):
        _validate_slack_tokens("xoxb-fake", "invalid-token")


def test_valid_prefixes_do_not_raise():
    """SLK-04: Correct prefixes do not raise."""
    _validate_slack_tokens("xoxb-valid", "xapp-valid")  # must not raise


def test_tokens_stored_from_constructor():
    """SLK-04: Tokens are stored on the instance after __init__."""
    ch = _make_channel()
    assert ch._bot_token == "xoxb-fake"
    assert ch._app_token == "xapp-fake"


def test_init_raises_for_wrong_bot_token():
    """SLK-04: SlackChannel.__init__ raises ValueError for wrong bot_token prefix."""
    with (
        pytest.raises(ValueError, match="xoxb-"),
        patch("slack_sdk.web.async_client.AsyncWebClient.__init__", return_value=None),
    ):
        SlackChannel(bot_token="bad-token", app_token="xapp-fake")


def test_init_raises_for_wrong_app_token():
    """SLK-04: SlackChannel.__init__ raises ValueError for wrong app_token prefix."""
    with (
        pytest.raises(ValueError, match="xapp-"),
        patch("slack_sdk.web.async_client.AsyncWebClient.__init__", return_value=None),
    ):
        SlackChannel(bot_token="xoxb-fake", app_token="bad-token")


# ---------------------------------------------------------------------------
# SLK-01: Channel identity and health
# ---------------------------------------------------------------------------


def test_channel_id_is_slack():
    """SLK-01: channel_id property returns 'slack'."""
    assert _make_channel().channel_id == "slack"


async def test_health_check_stopped():
    """SLK-01: health_check returns 'down' when status is 'stopped'."""
    ch = _make_channel()
    assert ch._status == "stopped"
    result = await ch.health_check()
    assert result["status"] == "down"
    assert result["channel"] == "slack"
    assert "socket_mode" in result


async def test_health_check_running():
    """SLK-01: health_check returns 'ok' when status is 'running'."""
    ch = _make_channel()
    ch._status = "running"
    result = await ch.health_check()
    assert result["status"] == "ok"
    assert result["channel"] == "slack"


# ---------------------------------------------------------------------------
# SLK-01: start() uses connect_async()
# ---------------------------------------------------------------------------


async def test_start_calls_connect_async():
    """SLK-01: start() must call connect_async() rather than start_async().

    Verifies:
      - connect_async() is awaited exactly once
      - _status is set to 'running' before asyncio.sleep(inf) (the park call)
      - After CancelledError, stop() is called and status reverts to 'stopped'
    """
    connect_async_mock = AsyncMock()
    close_async_mock = AsyncMock()

    mock_handler = MagicMock()
    mock_handler.connect_async = connect_async_mock
    mock_handler.close_async = close_async_mock

    # Capture status at the point asyncio.sleep is first called (after connect_async
    # returns and _status = "running" is set, just before the park sleep).
    status_at_park: list = []

    async def sleep_side_effect(duration):
        # First call is the park sleep (float('inf')) — capture status then raise
        status_at_park.append(ch._status)
        raise asyncio.CancelledError()

    with patch(
        "sci_fi_dashboard.channels.slack.AsyncSocketModeHandler",
        return_value=mock_handler,
    ), patch(
        "sci_fi_dashboard.channels.slack.AsyncApp",
    ) as mock_app_cls:
        # AsyncApp() returns a MagicMock that supports .event decorator
        mock_app_inst = MagicMock()
        mock_app_inst.event = MagicMock(return_value=lambda f: f)
        mock_app_cls.return_value = mock_app_inst

        ch = SlackChannel(bot_token="xoxb-fake", app_token="xapp-fake")

        with (
            patch("asyncio.sleep", side_effect=sleep_side_effect),
            pytest.raises(asyncio.CancelledError),
        ):
            await ch.start()

    # connect_async must have been awaited exactly once
    assert connect_async_mock.await_count == 1
    # _status must have been "running" at the park sleep (before CancelledError)
    assert status_at_park == ["running"]


# ---------------------------------------------------------------------------
# SLK-02: Receive normalization
# ---------------------------------------------------------------------------


async def test_receive_normalizes_dm_event():
    """SLK-02: receive() normalizes a DM event correctly."""
    ch = _make_channel()
    payload = {"user": "U123", "channel": "D456", "text": "hi", "ts": "1234.5"}
    msg = await ch.receive(payload)
    assert msg.channel_id == "slack"
    assert msg.user_id == "U123"
    assert msg.chat_id == "D456"
    assert msg.text == "hi"
    assert msg.is_group is False
    assert msg.message_id == "1234.5"


async def test_receive_normalizes_group_event():
    """SLK-02: receive() normalizes a group/mention event with is_group=True."""
    ch = _make_channel()
    payload = {
        "user": "U789",
        "channel": "C999",
        "text": "hello team",
        "ts": "9999.0",
        "is_group": True,
    }
    msg = await ch.receive(payload)
    assert msg.channel_id == "slack"
    assert msg.is_group is True
    assert msg.text == "hello team"


async def test_receive_handles_missing_fields():
    """SLK-02: receive() uses sensible defaults when fields are absent."""
    ch = _make_channel()
    msg = await ch.receive({})
    assert msg.channel_id == "slack"
    assert msg.user_id == ""
    assert msg.text == ""
    assert msg.is_group is False


# ---------------------------------------------------------------------------
# SLK-02: Dispatch to enqueue_fn
# ---------------------------------------------------------------------------


async def test_dm_event_dispatches_to_enqueue_fn():
    """SLK-02: _dispatch() with is_group=False enqueues a ChannelMessage with correct fields."""
    enqueue_fn = AsyncMock()
    ch = _make_channel(enqueue_fn=enqueue_fn)

    await ch._dispatch(
        {"user": "U1", "channel": "D1", "text": "hello", "ts": "1"},
        is_group=False,
    )

    enqueue_fn.assert_awaited_once()
    channel_msg = enqueue_fn.call_args[0][0]
    assert channel_msg.channel_id == "slack"
    assert channel_msg.text == "hello"
    assert channel_msg.is_group is False
    assert channel_msg.user_id == "U1"


async def test_mention_event_dispatches_to_enqueue_fn():
    """SLK-02: _dispatch() with is_group=True enqueues a ChannelMessage with is_group=True."""
    enqueue_fn = AsyncMock()
    ch = _make_channel(enqueue_fn=enqueue_fn)

    await ch._dispatch(
        {"user": "U2", "channel": "C2", "text": "hey @bot", "ts": "2"},
        is_group=True,
    )

    enqueue_fn.assert_awaited_once()
    channel_msg = enqueue_fn.call_args[0][0]
    assert channel_msg.is_group is True
    assert channel_msg.channel_id == "slack"


async def test_dispatch_no_enqueue_fn_does_not_raise():
    """SLK-02: _dispatch() with no enqueue_fn completes without error."""
    ch = _make_channel(enqueue_fn=None)
    # Should not raise even with no enqueue_fn
    await ch._dispatch({"user": "U1", "channel": "D1", "text": "hi", "ts": "1"}, is_group=False)


# ---------------------------------------------------------------------------
# SLK-03: Outbound send
# ---------------------------------------------------------------------------


async def test_send_calls_chat_post_message():
    """SLK-03: send() calls AsyncWebClient.chat_postMessage with correct args."""
    ch = _make_channel()
    ch._web_client = AsyncMock()
    ch._web_client.chat_postMessage = AsyncMock(return_value={"ok": True})

    result = await ch.send("C12345", "Hello Slack")

    ch._web_client.chat_postMessage.assert_awaited_once_with(channel="C12345", text="Hello Slack")
    assert result is True


async def test_send_returns_false_on_error():
    """SLK-03: send() returns False when chat_postMessage raises an exception."""
    ch = _make_channel()
    ch._web_client = AsyncMock()
    ch._web_client.chat_postMessage = AsyncMock(side_effect=Exception("API error"))

    result = await ch.send("C12345", "Hello Slack")
    assert result is False


# ---------------------------------------------------------------------------
# SLK-03: No-op methods
# ---------------------------------------------------------------------------


async def test_send_typing_is_noop():
    """SLK-03: send_typing() completes without raising — Slack API typing is unreliable."""
    ch = _make_channel()
    await ch.send_typing("C12345")  # must not raise


async def test_mark_read_is_noop():
    """SLK-03: mark_read() completes without raising — Slack bots cannot mark messages read."""
    ch = _make_channel()
    await ch.mark_read("C12345", "ts123")  # must not raise


# ---------------------------------------------------------------------------
# Phase 08-01: Integration tests — enqueue_fn routes via flood.incoming()
# SLK-01, SLK-03
# ---------------------------------------------------------------------------


class TestSlackFloodGateIntegration:
    """
    SLK-01 / SLK-03: Verify that a SlackChannel with a flood.incoming() adapter
    correctly routes ChannelMessage through the adapter without AttributeError.

    These tests use _dispatch() directly (the public normalisation method on
    SlackChannel) to exercise the enqueue_fn contract without needing a live
    Slack socket connection.
    """

    def _make_flood_adapter(self, collected):
        """Returns an async enqueue_fn that captures what the adapter would pass to flood."""

        async def _enqueue(channel_msg):
            collected.append({
                "chat_id": channel_msg.chat_id,
                "text": channel_msg.text,
                "message_id": channel_msg.message_id,
                "sender_name": channel_msg.sender_name,
                "channel_id": "slack",
            })

        return _enqueue

    async def test_slack_dm_reaches_flood_gate(self):
        """SLK-01: Slack DM dispatched via enqueue_fn adapter — not silently dropped."""
        collected = []
        ch = _make_channel(enqueue_fn=self._make_flood_adapter(collected))

        # Build a minimal Slack event matching what _dispatch() expects
        event = {
            "text": "hello slack",
            "user": "U123",
            "channel": "D456",
            "ts": "1234567890.000001",
            "channel_type": "im",
        }
        await ch._dispatch(event, is_group=False)

        assert len(collected) == 1, f"Expected 1 call, got {len(collected)}"
        assert collected[0]["channel_id"] == "slack"
        assert collected[0]["text"] == "hello slack"

    async def test_slack_enqueue_fn_receives_channel_message_shape(self):
        """SLK-03: Adapter receives ChannelMessage with correct fields — no task_id crash."""
        from sci_fi_dashboard.channels.base import ChannelMessage

        received = []

        async def capture(channel_msg):
            received.append(channel_msg)

        ch = _make_channel(enqueue_fn=capture)
        event = {
            "text": "type check",
            "user": "U999",
            "channel": "D001",
            "ts": "9999.0001",
            "channel_type": "im",
        }
        await ch._dispatch(event, is_group=False)

        assert len(received) == 1
        msg = received[0]
        assert isinstance(msg, ChannelMessage)
        assert msg.channel_id == "slack"
        assert hasattr(msg, "chat_id")
        assert hasattr(msg, "message_id")
        assert not hasattr(msg, "task_id"), "ChannelMessage must not have task_id — use adapter"
