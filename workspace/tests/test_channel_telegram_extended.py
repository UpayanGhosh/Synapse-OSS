"""Extended Telegram channel tests — filling gaps not covered in test_telegram_channel.py.

Covers:
- Typing indicator circuit breaker
- Message splitting (_split_message)
- send_voice()
- DM security check in _dispatch
- Sticker and voice handler dispatch
- require_mention=False group behavior
"""

import importlib.util
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEL_AVAILABLE = (
    importlib.util.find_spec("sci_fi_dashboard.channels.telegram") is not None
    and importlib.util.find_spec("telegram") is not None
)

pytestmark = pytest.mark.skipif(not TEL_AVAILABLE, reason="TelegramChannel not available")

if TEL_AVAILABLE:
    from sci_fi_dashboard.channels.security import (
        ChannelSecurityConfig,
        DmPolicy,
        PairingStore,
    )
    from sci_fi_dashboard.channels.telegram import TelegramChannel
    from telegram.error import TelegramError


def _make_mock_update(
    text="hello",
    chat_type="private",
    user_id=99,
    chat_id=12345,
    message_id=1,
    full_name="Test User",
    update_id=None,
):
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.full_name = full_name

    mock_chat = MagicMock()
    mock_chat.id = chat_id
    mock_chat.type = chat_type

    mock_message = MagicMock()
    mock_message.text = text
    mock_message.from_user = mock_user
    mock_message.chat = mock_chat
    mock_message.message_id = message_id
    mock_message.date = None
    mock_message.message_thread_id = None

    mock_update = MagicMock()
    mock_update.message = mock_message
    mock_update.update_id = update_id
    mock_update.to_dict.return_value = {}
    return mock_update


# ===========================================================================
# Typing indicator circuit breaker
# ===========================================================================


class TestTypingCircuitBreaker:
    """Tests for typing indicator circuit breaker."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_activates_after_5_failures(self):
        ch = TelegramChannel(token="x")
        ch._app = MagicMock(bot=AsyncMock())
        ch._app.bot.send_chat_action = AsyncMock(side_effect=TelegramError("rate limited"))

        # 5 failures should trigger suspension
        for _ in range(5):
            await ch.send_typing("123")

        assert ch._consecutive_typing_failures >= 5
        assert ch._typing_suspended_until > time.time()

    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_while_suspended(self):
        ch = TelegramChannel(token="x")
        ch._app = MagicMock(bot=AsyncMock())
        ch._typing_suspended_until = time.time() + 300
        ch._app.bot.send_chat_action = AsyncMock()

        await ch.send_typing("123")
        # send_chat_action should NOT have been called
        ch._app.bot.send_chat_action.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_typing_resets_counter(self):
        ch = TelegramChannel(token="x")
        ch._app = MagicMock(bot=AsyncMock())
        ch._app.bot.send_chat_action = AsyncMock()
        ch._consecutive_typing_failures = 3

        await ch.send_typing("123")
        assert ch._consecutive_typing_failures == 0


# ===========================================================================
# Message splitting
# ===========================================================================


class TestTelegramSplitMessage:

    def test_short_message_not_split(self):
        ch = TelegramChannel(token="x")
        assert ch._split_message("hi") == ["hi"]

    def test_long_message_split(self):
        ch = TelegramChannel(token="x")
        text = "x" * 8000
        result = ch._split_message(text)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= TelegramChannel.MAX_CHARS

    def test_split_at_paragraph_boundary(self):
        ch = TelegramChannel(token="x")
        text = "A" * 4000 + "\n\n" + "B" * 4000
        result = ch._split_message(text)
        assert len(result) == 2


# ===========================================================================
# send_voice
# ===========================================================================


class TestTelegramSendVoice:

    @pytest.mark.asyncio
    async def test_send_voice_success(self, tmp_path):
        ch = TelegramChannel(token="x")
        ch._app = MagicMock(bot=AsyncMock())
        ch._app.bot.send_voice = AsyncMock()

        voice_file = tmp_path / "test.ogg"
        voice_file.write_bytes(b"\x00" * 100)

        result = await ch.send_voice("123", str(voice_file))
        assert result is True
        ch._app.bot.send_voice.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_voice_no_app(self):
        ch = TelegramChannel(token="x")
        result = await ch.send_voice("123", "/fake/path.ogg")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_voice_error_returns_false(self, tmp_path):
        ch = TelegramChannel(token="x")
        ch._app = MagicMock(bot=AsyncMock())
        ch._app.bot.send_voice = AsyncMock(side_effect=TelegramError("file too big"))

        voice_file = tmp_path / "test.ogg"
        voice_file.write_bytes(b"\x00" * 100)

        result = await ch.send_voice("123", str(voice_file))
        assert result is False


# ===========================================================================
# DM security in _dispatch
# ===========================================================================


class TestTelegramDmSecurity:

    @pytest.mark.asyncio
    async def test_dispatch_blocks_dm_when_not_allowed(self, tmp_path):
        """DM from non-allowed sender is blocked in pairing mode."""
        store = PairingStore("telegram", data_root=tmp_path)
        await store.load()

        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.ALLOWLIST, allow_from=["999"])
        enqueue_fn = AsyncMock()
        ch = TelegramChannel(
            token="x",
            enqueue_fn=enqueue_fn,
            security_config=cfg,
            pairing_store=store,
        )

        mock_update = _make_mock_update(text="blocked", chat_type="private", user_id=123)
        await ch._dispatch(mock_update)

        enqueue_fn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dispatch_allows_dm_when_allowed(self, tmp_path):
        """DM from allowed sender passes through."""
        store = PairingStore("telegram", data_root=tmp_path)
        await store.load()

        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.ALLOWLIST, allow_from=["99"])
        enqueue_fn = AsyncMock()
        ch = TelegramChannel(
            token="x",
            enqueue_fn=enqueue_fn,
            security_config=cfg,
            pairing_store=store,
        )

        mock_update = _make_mock_update(text="allowed", chat_type="private", user_id=99)
        await ch._dispatch(mock_update)

        enqueue_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_skips_security_for_groups(self, tmp_path):
        """Security check is skipped for group messages."""
        store = PairingStore("telegram", data_root=tmp_path)
        await store.load()

        cfg = ChannelSecurityConfig(dm_policy=DmPolicy.DISABLED)  # would block all DMs
        enqueue_fn = AsyncMock()
        ch = TelegramChannel(
            token="x",
            enqueue_fn=enqueue_fn,
            security_config=cfg,
            pairing_store=store,
        )

        mock_update = _make_mock_update(text="group msg", chat_type="supergroup", user_id=123)
        await ch._dispatch(mock_update)

        enqueue_fn.assert_awaited_once()


# ===========================================================================
# require_mention=False group behavior
# ===========================================================================


class TestRequireMentionFalse:

    @pytest.mark.asyncio
    async def test_group_message_without_mention_dispatched(self):
        """When require_mention=False, group messages without mention are dispatched."""
        enqueue_fn = AsyncMock()
        ch = TelegramChannel(token="x", enqueue_fn=enqueue_fn, require_mention=False)

        mock_update = _make_mock_update(text="no mention here", chat_type="supergroup")
        mock_context = MagicMock()
        mock_context.bot.username = "botname"

        await ch._on_group_message(mock_update, mock_context)
        enqueue_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_slash_command_bypasses_mention_gate(self):
        """Slash commands always bypass mention gating."""
        enqueue_fn = AsyncMock()
        ch = TelegramChannel(token="x", enqueue_fn=enqueue_fn, require_mention=True)

        mock_update = _make_mock_update(text="/start", chat_type="group")
        mock_context = MagicMock()
        mock_context.bot.username = "botname"

        await ch._on_group_message(mock_update, mock_context)
        enqueue_fn.assert_awaited_once()
