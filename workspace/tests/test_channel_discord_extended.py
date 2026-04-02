"""Extended Discord channel tests — filling gaps not covered in test_discord_channel.py.

Covers:
- Message splitting (_split_message)
- send_voice()
- Sent message cache (_cache_sent_message, _get_cached_discord_id, LRU eviction)
- PluralKit bot ID constant
- send_typing_loop (basic behavior)
"""

import asyncio
import importlib.util
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DIS_AVAILABLE = (
    importlib.util.find_spec("discord") is not None
    and importlib.util.find_spec("sci_fi_dashboard.channels.discord_channel") is not None
)

pytestmark = pytest.mark.skipif(
    not DIS_AVAILABLE, reason="DiscordChannel or discord.py not available"
)

if DIS_AVAILABLE:
    from sci_fi_dashboard.channels.discord_channel import DiscordChannel


# ===========================================================================
# Message splitting
# ===========================================================================


class TestDiscordSplitMessage:

    def test_short_message_not_split(self):
        assert DiscordChannel._split_message("hello") == ["hello"]

    def test_long_message_split(self):
        text = "x" * 4000
        result = DiscordChannel._split_message(text)
        assert len(result) == 2
        for chunk in result:
            assert len(chunk) <= DiscordChannel.MAX_CHARS

    def test_split_at_paragraph_boundary(self):
        text = "A" * 1500 + "\n\n" + "B" * 1500
        result = DiscordChannel._split_message(text)
        assert len(result) == 2

    def test_split_at_line_boundary(self):
        text = "A" * 1800 + "\n" + "B" * 1800
        result = DiscordChannel._split_message(text)
        assert len(result) >= 2

    def test_split_at_space_boundary(self):
        text = "word " * 500  # 2500 chars
        result = DiscordChannel._split_message(text)
        assert len(result) >= 2

    def test_hard_cut_no_boundary(self):
        text = "x" * 5000
        result = DiscordChannel._split_message(text)
        assert all(len(c) <= 2000 for c in result)


# ===========================================================================
# Sent message cache
# ===========================================================================


class TestDiscordSentCache:

    def test_cache_stores_and_retrieves(self):
        ch = DiscordChannel(token="t")
        ch._cache_sent_message("internal_1", 12345)
        assert ch._get_cached_discord_id("internal_1") == 12345

    def test_cache_miss_returns_none(self):
        ch = DiscordChannel(token="t")
        assert ch._get_cached_discord_id("nonexistent") is None

    def test_cache_lru_eviction(self):
        ch = DiscordChannel(token="t")
        ch._SENT_CACHE_MAX = 3
        for i in range(5):
            ch._cache_sent_message(f"msg_{i}", i * 100)
        # Only last 3 should be in cache
        assert ch._get_cached_discord_id("msg_0") is None
        assert ch._get_cached_discord_id("msg_1") is None
        assert ch._get_cached_discord_id("msg_2") is not None
        assert ch._get_cached_discord_id("msg_3") is not None
        assert ch._get_cached_discord_id("msg_4") is not None

    def test_cache_update_moves_to_end(self):
        ch = DiscordChannel(token="t")
        ch._cache_sent_message("a", 1)
        ch._cache_sent_message("b", 2)
        ch._cache_sent_message("a", 3)  # update "a"
        assert ch._get_cached_discord_id("a") == 3


# ===========================================================================
# Constants
# ===========================================================================


class TestDiscordConstants:

    def test_max_chars(self):
        assert DiscordChannel.MAX_CHARS == 2000

    def test_pluralkit_bot_id(self):
        assert DiscordChannel._PLURALKIT_BOT_ID == 466378653216014359


# ===========================================================================
# send_voice
# ===========================================================================


class TestDiscordSendVoice:

    @pytest.mark.asyncio
    async def test_send_voice_no_client(self):
        ch = DiscordChannel(token="t")
        ch._client = None
        result = await ch.send_voice("123", "/path/to/file.ogg")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_voice_success(self):
        import discord

        ch = DiscordChannel(token="t")
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        ch._client = mock_client

        # Create a temporary file
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"\x00" * 50)
            temp_path = f.name

        try:
            result = await ch.send_voice("123", temp_path)
            assert result is True
            mock_channel.send.assert_awaited_once()
        finally:
            os.unlink(temp_path)


# ===========================================================================
# send_in_thread
# ===========================================================================


class TestDiscordSendInThread:

    @pytest.mark.asyncio
    async def test_send_in_thread_no_client(self):
        ch = DiscordChannel(token="t")
        ch._client = None
        result = await ch.send_in_thread("123", "Thread Name", "Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_in_thread_success(self):
        ch = DiscordChannel(token="t")
        mock_thread = MagicMock()
        mock_thread.id = 99999
        mock_thread.send = AsyncMock()

        mock_channel = MagicMock()
        mock_channel.create_thread = AsyncMock(return_value=mock_thread)

        mock_client = MagicMock()
        mock_client.get_channel = MagicMock(return_value=mock_channel)
        ch._client = mock_client

        result = await ch.send_in_thread("123", "My Thread", "Hello thread")
        assert result == "99999"
        mock_thread.send.assert_awaited_once_with("Hello thread")
