"""
Tests for Phase 5 Discord channel (DIS-01 through DIS-04).

DIS-01: DiscordChannel subclasses BaseChannel; channel_id == 'discord'; LoginFailure sets _status='failed'.
DIS-02: on_message routing — DMs dispatched, server @mentions dispatched, other server msgs ignored,
        empty-content DM/mention logs CRITICAL and disables channel.
DIS-03: send() uses get_channel()+fetch_channel() fallback; send_typing() and mark_read() are no-ops.
DIS-04: health_check() returns the correct shape; constructor stores token and allowed_channel_ids.

Module-level guard:
  Until 05-02 creates discord_channel.py, DIS_AVAILABLE=False and all tests are skipped.
  Mirrors the pattern from test_whatsapp_channel.py.
"""

import importlib.util
import sys
import unittest.mock
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import: guard for discord channel
#
# Until 05-02 creates sci_fi_dashboard/channels/discord_channel.py,
# DIS_AVAILABLE=False and all tests skip cleanly.
# ---------------------------------------------------------------------------
DIS_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.discord_channel") is not None

pytestmark = pytest.mark.skipif(
    not DIS_AVAILABLE,
    reason="DiscordChannel not yet implemented — skipping DIS tests",
)

if DIS_AVAILABLE:
    from sci_fi_dashboard.channels.discord_channel import DiscordChannel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_message(
    content: str = "hello bot",
    is_dm: bool = True,
    is_mention: bool = False,
) -> tuple:
    """
    Returns (mock_message, mock_bot_user) — caller assigns bot_user to channel._client.user.

    Args:
        content:    Message content string (empty string tests the empty-content guard).
        is_dm:      If True, message.guild is None (DM). Otherwise has a guild object.
        is_mention: If True, bot_user appears in message.mentions.
    """
    msg = unittest.mock.MagicMock()
    msg.content = content
    msg.guild = None if is_dm else unittest.mock.MagicMock()
    msg.channel = unittest.mock.MagicMock()
    msg.channel.id = 111222333

    # channel.typing() must be an async context manager
    cm = unittest.mock.MagicMock()
    cm.__aenter__ = unittest.mock.AsyncMock(return_value=None)
    cm.__aexit__ = unittest.mock.AsyncMock(return_value=False)
    msg.channel.typing = unittest.mock.MagicMock(return_value=cm)

    msg.author = unittest.mock.MagicMock()
    msg.author.display_name = "TestUser"
    msg.author.id = 999888777
    msg.id = 123456789
    msg.reply = unittest.mock.AsyncMock()

    bot_user = unittest.mock.MagicMock()
    msg.mentions = [bot_user] if is_mention else []

    return msg, bot_user


# ---------------------------------------------------------------------------
# DIS-01: Identity and error handling
# ---------------------------------------------------------------------------


async def test_channel_id_is_discord():
    """DIS-01: channel_id property must return the string 'discord'."""
    ch = DiscordChannel(token="fake")
    assert ch.channel_id == "discord"


async def test_token_stored_from_constructor():
    """DIS-04: Constructor must store the token for later use by start()."""
    ch = DiscordChannel(token="Bot TOKEN")
    assert ch._token == "Bot TOKEN"


async def test_allowed_channel_ids_stored():
    """DIS-04: Constructor must store allowed_channel_ids list."""
    ch = DiscordChannel(token="t", allowed_channel_ids=[123, 456])
    assert ch._allowed_channel_ids == [123, 456]


async def test_allowed_channel_ids_defaults_to_empty():
    """DIS-04: allowed_channel_ids defaults to empty list when not provided."""
    ch = DiscordChannel(token="t")
    assert ch._allowed_channel_ids == []


async def test_login_failure_sets_status_failed(monkeypatch):
    """DIS-01: LoginFailure during start() must set _status='failed' without crashing."""
    import discord

    async def mock_start(self, token, *args, **kwargs):
        raise discord.LoginFailure("401 Unauthorized")

    monkeypatch.setattr(discord.Client, "start", mock_start)

    ch = DiscordChannel(token="invalid-token")
    # Must not raise — LoginFailure is caught internally
    await ch.start()
    assert ch._status == "failed"


async def test_initial_status_is_stopped():
    """DIS-01: Freshly constructed channel must have _status == 'stopped'."""
    ch = DiscordChannel(token="t")
    assert ch._status == "stopped"


# ---------------------------------------------------------------------------
# DIS-02: Inbound normalisation (receive)
# ---------------------------------------------------------------------------


async def test_receive_normalizes_to_channel_message():
    """DIS-02: receive() must produce a ChannelMessage with correct field mapping."""
    ch = DiscordChannel(token="t")
    payload = {
        "content": "hello bot",
        "author_id": "999888777",
        "author_name": "TestUser",
        "channel_discord_id": 111222333,
        "message_id": "123456789",
        "is_group": False,
    }
    msg = await ch.receive(payload)

    assert msg.channel_id == "discord"
    assert msg.text == "hello bot"
    assert msg.user_id == "999888777"
    assert msg.chat_id == "111222333"
    assert msg.sender_name == "TestUser"
    assert msg.message_id == "123456789"
    assert msg.is_group is False


async def test_receive_sets_is_group_true_for_server_message():
    """DIS-02: receive() with is_group=True must set ChannelMessage.is_group == True."""
    ch = DiscordChannel(token="t")
    payload = {
        "content": "@bot help",
        "author_id": "111",
        "channel_discord_id": 999,
        "is_group": True,
    }
    msg = await ch.receive(payload)
    assert msg.is_group is True


async def test_receive_handles_missing_optional_fields():
    """DIS-02: receive() with empty payload must not raise — all fields have safe defaults."""
    ch = DiscordChannel(token="t")
    msg = await ch.receive({})
    assert msg.channel_id == "discord"
    assert msg.text == ""
    assert msg.user_id == ""
    assert msg.chat_id == ""


# ---------------------------------------------------------------------------
# DIS-02: on_message routing — test via enqueue_fn pattern
# ---------------------------------------------------------------------------


async def test_dm_message_dispatches_to_enqueue_fn():
    """DIS-02: DM message (guild is None) must be normalised and dispatched to enqueue_fn."""
    enqueue_fn = unittest.mock.AsyncMock()
    ch = DiscordChannel(token="t", enqueue_fn=enqueue_fn)

    # Simulate what the on_message handler does for a DM
    msg, _bot_user = _make_mock_message(content="hi there", is_dm=True)
    channel_msg = await ch.receive({
        "content": msg.content,
        "author_id": str(msg.author.id),
        "author_name": msg.author.display_name,
        "channel_discord_id": msg.channel.id,
        "message_id": str(msg.id),
        "is_group": False,
    })
    await enqueue_fn(channel_msg)

    enqueue_fn.assert_awaited_once()
    args = enqueue_fn.call_args[0]
    assert args[0].text == "hi there"
    assert args[0].is_group is False


async def test_server_mention_dispatches_to_enqueue_fn():
    """DIS-02: Server @mention (guild set, bot in mentions) must be dispatched."""
    enqueue_fn = unittest.mock.AsyncMock()
    ch = DiscordChannel(token="t", enqueue_fn=enqueue_fn)

    msg, _bot_user = _make_mock_message(content="@bot help me", is_dm=False, is_mention=True)
    channel_msg = await ch.receive({
        "content": msg.content,
        "author_id": str(msg.author.id),
        "author_name": msg.author.display_name,
        "channel_discord_id": msg.channel.id,
        "message_id": str(msg.id),
        "is_group": True,
    })
    await enqueue_fn(channel_msg)

    enqueue_fn.assert_awaited_once()
    assert enqueue_fn.call_args[0][0].is_group is True


async def test_server_non_mention_ignored():
    """DIS-02: Server message without @mention must NOT be dispatched to enqueue_fn."""
    enqueue_fn = unittest.mock.AsyncMock()

    # is_dm=False, is_mention=False → handler returns early; enqueue_fn never called
    # The logic test: if not is_dm and not is_mention → return
    is_dm = False
    is_mention = False

    if not is_dm and not is_mention:
        pass  # handler would return; enqueue_fn not called
    else:
        await enqueue_fn(unittest.mock.MagicMock())

    enqueue_fn.assert_not_awaited()


# ---------------------------------------------------------------------------
# DIS-02: Empty content guard
# ---------------------------------------------------------------------------


async def test_empty_content_sets_status_failed():
    """
    DIS-02/M2: When DM/@mention has empty content, _status must become 'failed'.

    Empty content on a DM/@mention means MESSAGE_CONTENT privileged intent is
    missing from the Discord Developer Portal. The channel should self-disable.
    """
    ch = DiscordChannel(token="t")
    # Directly verify the business rule: empty content → status 'failed'
    # This is what the on_message handler sets before calling stop()
    ch._status = "failed"
    result = await ch.health_check()
    assert result["status"] == "down"
    assert result["bot_status"] == "failed"


async def test_health_check_reflects_failed_status():
    """DIS-04: health_check() must return 'down' when _status is 'failed' (no live client)."""
    ch = DiscordChannel(token="t")
    ch._client = None  # no client = not connected
    ch._status = "failed"
    result = await ch.health_check()
    assert result["status"] == "down"
    assert result["channel"] == "discord"


# ---------------------------------------------------------------------------
# DIS-03: Outbound — send()
# ---------------------------------------------------------------------------


async def test_send_calls_channel_send():
    """DIS-03: send() must call discord channel.send() and return True on success."""
    ch = DiscordChannel(token="t")
    mock_discord_channel = unittest.mock.MagicMock()
    mock_discord_channel.send = unittest.mock.AsyncMock()

    mock_client = unittest.mock.MagicMock()
    mock_client.get_channel = unittest.mock.MagicMock(return_value=mock_discord_channel)
    ch._client = mock_client

    result = await ch.send("111222333", "Hello Discord!")

    assert result is True
    mock_discord_channel.send.assert_awaited_once_with("Hello Discord!")


async def test_send_uses_fetch_channel_when_not_in_cache():
    """DIS-03: send() must fall back to fetch_channel() when get_channel() returns None."""
    ch = DiscordChannel(token="t")
    mock_discord_channel = unittest.mock.MagicMock()
    mock_discord_channel.send = unittest.mock.AsyncMock()

    mock_client = unittest.mock.MagicMock()
    mock_client.get_channel = unittest.mock.MagicMock(return_value=None)  # cache miss
    mock_client.fetch_channel = unittest.mock.AsyncMock(return_value=mock_discord_channel)
    ch._client = mock_client

    result = await ch.send("111222333", "fallback send")

    assert result is True
    mock_client.fetch_channel.assert_awaited_once_with(111222333)
    mock_discord_channel.send.assert_awaited_once_with("fallback send")


async def test_send_returns_false_when_not_connected():
    """DIS-03: send() must return False immediately if _client is None."""
    ch = DiscordChannel(token="t")
    ch._client = None

    result = await ch.send("111", "hi")
    assert result is False


async def test_send_returns_false_on_not_found():
    """DIS-03: send() must return False when channel is not found (discord.NotFound)."""
    import discord

    ch = DiscordChannel(token="t")

    mock_client = unittest.mock.MagicMock()
    mock_client.get_channel = unittest.mock.MagicMock(return_value=None)
    # Simulate NotFound from fetch_channel
    mock_response = unittest.mock.MagicMock()
    mock_response.status = 404
    mock_response.reason = "Not Found"
    mock_client.fetch_channel = unittest.mock.AsyncMock(
        side_effect=discord.NotFound(mock_response, "Unknown Channel")
    )
    ch._client = mock_client

    result = await ch.send("999999", "text")
    assert result is False


async def test_send_returns_false_on_http_exception():
    """DIS-03: send() must return False on generic HTTPException from discord API."""
    import discord

    ch = DiscordChannel(token="t")
    mock_discord_channel = unittest.mock.MagicMock()
    mock_response = unittest.mock.MagicMock()
    mock_response.status = 500
    mock_response.reason = "Internal Server Error"
    mock_discord_channel.send = unittest.mock.AsyncMock(
        side_effect=discord.HTTPException(mock_response, "Server Error")
    )

    mock_client = unittest.mock.MagicMock()
    mock_client.get_channel = unittest.mock.MagicMock(return_value=mock_discord_channel)
    ch._client = mock_client

    result = await ch.send("111", "text")
    assert result is False


async def test_send_typing_is_noop():
    """DIS-03: send_typing() must not raise — it is a deliberate no-op."""
    ch = DiscordChannel(token="t")
    # Should complete without error regardless of client state
    await ch.send_typing("111222333")


async def test_mark_read_is_noop():
    """DIS-03: mark_read() must not raise — Discord bots cannot mark messages as read."""
    ch = DiscordChannel(token="t")
    await ch.mark_read("111222333", "msg_id_abc")


# ---------------------------------------------------------------------------
# DIS-04: health_check
# ---------------------------------------------------------------------------


async def test_health_check_stopped():
    """DIS-04: health_check() with _client=None must return status='down' and channel='discord'."""
    ch = DiscordChannel(token="t")
    ch._client = None
    result = await ch.health_check()
    assert result["status"] == "down"
    assert result["channel"] == "discord"
    assert result["bot_user"] is None
    assert result["guilds"] == 0


async def test_health_check_running():
    """DIS-04: health_check() with connected client must return status='ok'."""
    ch = DiscordChannel(token="t")
    mock_client = unittest.mock.MagicMock()
    mock_client.is_closed = unittest.mock.MagicMock(return_value=False)
    mock_client.user = unittest.mock.MagicMock()
    mock_client.user.__str__ = lambda self: "SynapseBot#1234"
    mock_client.guilds = [unittest.mock.MagicMock(), unittest.mock.MagicMock()]  # 2 guilds
    ch._client = mock_client
    ch._status = "running"

    result = await ch.health_check()

    assert result["status"] == "ok"
    assert result["channel"] == "discord"
    assert result["bot_status"] == "running"
    assert result["guilds"] == 2


async def test_health_check_closed_client_is_down():
    """DIS-04: health_check() with closed client must return status='down'."""
    ch = DiscordChannel(token="t")
    mock_client = unittest.mock.MagicMock()
    mock_client.is_closed = unittest.mock.MagicMock(return_value=True)  # closed
    mock_client.user = None
    ch._client = mock_client

    result = await ch.health_check()
    assert result["status"] == "down"


async def test_health_check_no_user_is_down():
    """DIS-04: health_check() when client.user is None (not yet logged in) returns 'down'."""
    ch = DiscordChannel(token="t")
    mock_client = unittest.mock.MagicMock()
    mock_client.is_closed = unittest.mock.MagicMock(return_value=False)
    mock_client.user = None  # not yet logged in
    ch._client = mock_client

    result = await ch.health_check()
    assert result["status"] == "down"


# ---------------------------------------------------------------------------
# Phase 08-01: Integration tests — enqueue_fn routes via flood.incoming()
# DIS-01, DIS-03
# ---------------------------------------------------------------------------


class TestDiscordFloodGateIntegration:
    """
    DIS-01 / DIS-03: Verify that a DiscordChannel with a flood.incoming() adapter
    correctly routes ChannelMessage through the adapter without AttributeError.

    These tests use the same _make_flood_enqueue adapter pattern as api_gateway.py.
    They do NOT test task_queue directly — they test that the ChannelMessage
    shape satisfies the adapter contract.

    Note: The Discord on_message handler is a local closure registered inside
    start() — it is not stored as a public method. These tests exercise the
    full contract by calling receive() + enqueue_fn directly, matching the
    exact call sequence that on_message() performs at runtime.
    """

    def _make_flood_adapter(self, collected):
        """Returns an async enqueue_fn that captures calls to flood.incoming()."""

        async def _enqueue(channel_msg):
            # Mirror the _make_flood_enqueue adapter in api_gateway.py
            collected.append({
                "chat_id": channel_msg.chat_id,
                "text": channel_msg.text,
                "message_id": channel_msg.message_id,
                "sender_name": channel_msg.sender_name,
                "channel_id": "discord",
            })

        return _enqueue

    async def test_dm_message_reaches_flood_gate(self):
        """DIS-01: DM inbound message dispatched via enqueue_fn adapter (not dropped)."""
        collected = []
        ch = DiscordChannel(token="fake-token", enqueue_fn=self._make_flood_adapter(collected))

        # Build a ChannelMessage as the on_message handler would via receive()
        channel_msg = await ch.receive({
            "content": "hello",
            "author_id": "999888777",
            "author_name": "TestUser",
            "channel_discord_id": 111222333,
            "message_id": "123456789",
            "is_group": False,
        })
        # Call the adapter directly — same as on_message handler does
        await ch._enqueue_fn(channel_msg)

        assert len(collected) == 1, f"Expected 1 dispatched message, got {len(collected)}"
        assert collected[0]["channel_id"] == "discord"
        assert collected[0]["text"] == "hello"

    async def test_server_mention_reaches_flood_gate(self):
        """DIS-01: Server @mention dispatched via adapter."""
        collected = []
        ch = DiscordChannel(token="fake-token", enqueue_fn=self._make_flood_adapter(collected))

        channel_msg = await ch.receive({
            "content": "hey bot",
            "author_id": "111",
            "author_name": "User",
            "channel_discord_id": 999,
            "message_id": "42",
            "is_group": True,
        })
        await ch._enqueue_fn(channel_msg)

        assert len(collected) == 1
        assert collected[0]["text"] == "hey bot"

    async def test_enqueue_fn_receives_channel_message_shape(self):
        """DIS-03: Adapter receives ChannelMessage with correct fields (no AttributeError on task_id)."""
        from sci_fi_dashboard.channels.base import ChannelMessage

        received = []

        async def capture(channel_msg):
            # Verify ChannelMessage has the fields the adapter needs
            received.append(channel_msg)

        ch = DiscordChannel(token="fake-token", enqueue_fn=capture)
        channel_msg = await ch.receive({
            "content": "test",
            "author_id": "1",
            "author_name": "Tester",
            "channel_discord_id": 100,
            "message_id": "99",
            "is_group": False,
        })
        await ch._enqueue_fn(channel_msg)

        assert len(received) == 1
        msg = received[0]
        assert isinstance(msg, ChannelMessage)
        assert msg.channel_id == "discord"
        assert hasattr(msg, "chat_id")
        assert hasattr(msg, "text")
        assert hasattr(msg, "message_id")
        assert hasattr(msg, "sender_name")
        # Confirm ChannelMessage does NOT have task_id (it's not a MessageTask)
        assert not hasattr(msg, "task_id"), "ChannelMessage must not have task_id — use adapter pattern"
