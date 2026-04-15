"""Extended tests for channels/base.py — MsgContext, ReplyPayload, split_message, send_payload.

Fills gaps not covered in test_channels.py:
- MsgContext dataclass validation, session_key, from_channel_message
- ReplyPayload defaults and field population
- BaseChannel.split_message boundary logic
- BaseChannel.send_payload routing (media vs text)
- BaseChannel optional methods defaults (send_media, send_reaction)
"""

import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.base import (
    BaseChannel,
    ChannelMessage,
    MsgContext,
    ReplyPayload,
)
from sci_fi_dashboard.channels.stub import StubChannel

# ===========================================================================
# MsgContext Tests
# ===========================================================================


class TestMsgContext:
    """Tests for MsgContext dataclass."""

    def test_valid_construction(self):
        """MsgContext constructs with required fields."""
        ctx = MsgContext(channel_id="whatsapp", user_id="u1", chat_id="c1", body="hi")
        assert ctx.channel_id == "whatsapp"
        assert ctx.user_id == "u1"
        assert ctx.chat_id == "c1"
        assert ctx.body == "hi"
        assert ctx.chat_type == "direct"
        assert ctx.is_group is False

    def test_empty_channel_id_raises(self):
        """Empty channel_id raises ValueError in __post_init__."""
        with pytest.raises(ValueError, match="channel_id"):
            MsgContext(channel_id="", user_id="u1", chat_id="c1", body="hi")

    def test_empty_user_id_raises(self):
        """Empty user_id raises ValueError in __post_init__."""
        with pytest.raises(ValueError, match="user_id"):
            MsgContext(channel_id="wa", user_id="", chat_id="c1", body="hi")

    def test_empty_chat_id_raises(self):
        """Empty chat_id raises ValueError in __post_init__."""
        with pytest.raises(ValueError, match="chat_id"):
            MsgContext(channel_id="wa", user_id="u1", chat_id="", body="hi")

    def test_whitespace_only_raises(self):
        """Whitespace-only channel_id raises ValueError."""
        with pytest.raises(ValueError, match="channel_id"):
            MsgContext(channel_id="   ", user_id="u1", chat_id="c1", body="hi")

    def test_non_string_raises(self):
        """Non-string channel_id raises ValueError."""
        with pytest.raises(ValueError, match="channel_id"):
            MsgContext(channel_id=123, user_id="u1", chat_id="c1", body="hi")

    def test_session_key_static_method(self):
        """session_key builds canonical 'channel:chatType:targetId' string."""
        key = MsgContext.session_key("whatsapp", "direct", "user123")
        assert key == "whatsapp:direct:user123"

    def test_session_key_group(self):
        """session_key works for group type."""
        key = MsgContext.session_key("telegram", "group", "grp-456")
        assert key == "telegram:group:grp-456"

    def test_from_channel_message(self):
        """from_channel_message converts ChannelMessage to MsgContext correctly."""
        cm = ChannelMessage(
            channel_id="telegram",
            user_id="user99",
            chat_id="chat55",
            text="hello",
            is_group=True,
            message_id="msg1",
            sender_name="Alice",
            raw={"extra": "data"},
        )
        ctx = MsgContext.from_channel_message(cm)
        assert ctx.channel_id == "telegram"
        assert ctx.user_id == "user99"
        assert ctx.chat_id == "chat55"
        assert ctx.body == "hello"
        assert ctx.is_group is True
        assert ctx.chat_type == "group"
        assert ctx.sender_name == "Alice"
        assert ctx.message_sid == "msg1"
        assert ctx.provider == "telegram"
        assert ctx.raw["extra"] == "data"

    def test_from_channel_message_with_overrides(self):
        """from_channel_message applies keyword overrides."""
        cm = ChannelMessage(channel_id="wa", user_id="u1", chat_id="c1", text="hi")
        ctx = MsgContext.from_channel_message(cm, provider="custom", max_chars=500)
        assert ctx.provider == "custom"
        assert ctx.max_chars == 500

    def test_from_channel_message_dm(self):
        """from_channel_message with is_group=False sets chat_type='direct'."""
        cm = ChannelMessage(
            channel_id="slack", user_id="u1", chat_id="c1", text="hi", is_group=False
        )
        ctx = MsgContext.from_channel_message(cm)
        assert ctx.chat_type == "direct"
        assert ctx.is_group is False

    def test_default_field_factories(self):
        """Default list/dict fields use factories (no shared mutable default)."""
        ctx1 = MsgContext(channel_id="wa", user_id="u1", chat_id="c1", body="hi")
        ctx2 = MsgContext(channel_id="wa", user_id="u2", chat_id="c2", body="bye")
        ctx1.media_paths.append("path1")
        assert "path1" not in ctx2.media_paths

    def test_empty_body_allowed(self):
        """Empty body string is allowed (only routing fields validated)."""
        ctx = MsgContext(channel_id="wa", user_id="u1", chat_id="c1", body="")
        assert ctx.body == ""

    def test_timestamp_auto_generated(self):
        """Timestamp defaults to now if not provided."""
        ctx = MsgContext(channel_id="wa", user_id="u1", chat_id="c1", body="hi")
        assert isinstance(ctx.timestamp, datetime)


# ===========================================================================
# ReplyPayload Tests
# ===========================================================================


class TestReplyPayload:
    """Tests for ReplyPayload dataclass."""

    def test_default_values(self):
        """ReplyPayload has sensible defaults."""
        rp = ReplyPayload()
        assert rp.text == ""
        assert rp.media_url == ""
        assert rp.media_urls == []
        assert rp.reply_to_id == ""
        assert rp.is_reasoning is False
        assert rp.channel_data == {}

    def test_custom_values(self):
        """ReplyPayload accepts custom values."""
        rp = ReplyPayload(
            text="Hello",
            media_url="http://example.com/img.png",
            reply_to_id="msg123",
            is_reasoning=True,
        )
        assert rp.text == "Hello"
        assert rp.media_url == "http://example.com/img.png"
        assert rp.reply_to_id == "msg123"
        assert rp.is_reasoning is True

    def test_no_shared_mutable_defaults(self):
        """media_urls and channel_data use factories."""
        rp1 = ReplyPayload()
        rp2 = ReplyPayload()
        rp1.media_urls.append("url1")
        rp1.channel_data["key"] = "val"
        assert "url1" not in rp2.media_urls
        assert "key" not in rp2.channel_data


# ===========================================================================
# BaseChannel.split_message Tests
# ===========================================================================


class TestSplitMessage:
    """Tests for BaseChannel.split_message class method."""

    def test_short_message_not_split(self):
        """Text that fits within limit is returned as-is."""
        result = StubChannel.split_message("hello", max_chars=100)
        assert result == ["hello"]

    def test_empty_text(self):
        """Empty text returns single empty string."""
        result = StubChannel.split_message("")
        assert result == [""]

    def test_paragraph_boundary_split(self):
        """Split at paragraph boundary (double newline)."""
        text = "Part one.\n\nPart two."
        result = StubChannel.split_message(text, max_chars=15)
        assert len(result) == 2
        assert "Part one." in result[0]
        assert "Part two." in result[1]

    def test_line_boundary_split(self):
        """Split at line boundary when no paragraph boundary within limit."""
        text = "Line one\nLine two\nLine three"
        result = StubChannel.split_message(text, max_chars=15)
        assert len(result) >= 2

    def test_word_boundary_split(self):
        """Split at word boundary when no line boundary within limit."""
        text = "word1 word2 word3 word4 word5"
        result = StubChannel.split_message(text, max_chars=12)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 12 or " " not in chunk

    def test_hard_cut(self):
        """Hard cut when no natural boundary exists."""
        text = "a" * 100
        result = StubChannel.split_message(text, max_chars=30)
        assert len(result) >= 3
        for chunk in result:
            assert len(chunk) <= 30

    def test_default_max_chars_uses_class_attribute(self):
        """When max_chars <= 0, uses cls.MAX_CHARS."""
        text = "short"
        result = StubChannel.split_message(text, max_chars=0)
        assert result == ["short"]

    def test_exact_limit_not_split(self):
        """Text exactly at limit is not split."""
        text = "a" * 4000
        result = BaseChannel.split_message(text, max_chars=4000)
        assert result == [text]


# ===========================================================================
# BaseChannel.send_payload Tests
# ===========================================================================


class TestSendPayload:
    """Tests for BaseChannel.send_payload routing."""

    @pytest.mark.asyncio
    async def test_send_payload_text_only(self):
        """send_payload with no media_url calls send()."""
        stub = StubChannel("test")
        payload = ReplyPayload(text="Hello world")
        result = await stub.send_payload("chat1", payload)
        assert result is True
        assert stub.sent_messages == [("chat1", "Hello world")]

    @pytest.mark.asyncio
    async def test_send_payload_with_media_calls_send_media(self):
        """send_payload with media_url calls send_media()."""
        stub = StubChannel("test")
        stub.send_media = AsyncMock(return_value=True)
        payload = ReplyPayload(text="Caption", media_url="http://example.com/img.png")
        result = await stub.send_payload("chat1", payload)
        assert result is True
        stub.send_media.assert_awaited_once_with(
            "chat1", media_url="http://example.com/img.png", caption="Caption"
        )

    @pytest.mark.asyncio
    async def test_send_media_default_returns_false(self):
        """BaseChannel.send_media default returns False."""
        stub = StubChannel("test")
        result = await stub.send_media("chat1", "http://url", "image", "cap")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_reaction_default_returns_false(self):
        """BaseChannel.send_reaction default returns False."""
        stub = StubChannel("test")
        result = await stub.send_reaction("chat1", "msg1", "thumbsup")
        assert result is False


# ===========================================================================
# BaseChannel lifecycle defaults
# ===========================================================================


class TestBaseChannelLifecycle:
    """Test default start/stop implementations."""

    @pytest.mark.asyncio
    async def test_start_default_is_noop(self):
        """Default start() completes without error."""
        stub = StubChannel("test")
        # StubChannel overrides start, but the base class default is a no-op
        # Test that calling start works
        await stub.start()
        assert stub._started is True

    @pytest.mark.asyncio
    async def test_stop_default_is_noop(self):
        """Default stop() completes without error."""
        stub = StubChannel("test")
        await stub.stop()
        assert stub._started is False
