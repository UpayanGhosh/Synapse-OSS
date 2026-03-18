"""
Tests for MsgContext, ReplyPayload, ChannelCapabilities, and ChannelPlugin.

Covers:
  - MsgContext.session_key() format
  - MsgContext.from_channel_message() bridge
  - MsgContext.__post_init__ validation (empty channel_id, user_id, chat_id)
  - ReplyPayload construction with defaults
  - ChannelCapabilities construction with defaults
  - ChannelPlugin runtime_checkable
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import: RED phase guard
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.channels.base import ChannelMessage, MsgContext, ReplyPayload
    from sci_fi_dashboard.channels.plugin import ChannelCapabilities, ChannelPlugin

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="channels/ subpackage not yet available",
)


class TestMsgContext:
    """MsgContext dataclass — session_key, from_channel_message, validation."""

    @_skip
    def test_session_key_format(self):
        """session_key('telegram', 'group', '-100123') returns 'telegram:group:-100123'."""
        result = MsgContext.session_key("telegram", "group", "-100123")
        assert result == "telegram:group:-100123"

    @_skip
    def test_session_key_direct(self):
        """session_key for a direct chat."""
        result = MsgContext.session_key("whatsapp", "direct", "+1234567890")
        assert result == "whatsapp:direct:+1234567890"

    @_skip
    def test_from_channel_message(self):
        """from_channel_message() bridges ChannelMessage fields into MsgContext."""
        cm = ChannelMessage(
            channel_id="telegram",
            user_id="u42",
            chat_id="c99",
            text="hello world",
            message_id="m001",
            sender_name="Alice",
            is_group=True,
        )
        ctx = MsgContext.from_channel_message(cm)
        assert ctx.channel_id == "telegram"
        assert ctx.user_id == "u42"
        assert ctx.chat_id == "c99"
        assert ctx.body == "hello world"
        assert ctx.message_sid == "m001"
        assert ctx.sender_name == "Alice"
        assert ctx.is_group is True
        assert ctx.chat_type == "group"
        assert ctx.provider == "telegram"

    @_skip
    def test_from_channel_message_overrides(self):
        """from_channel_message() accepts keyword overrides."""
        cm = ChannelMessage(
            channel_id="wa",
            user_id="u1",
            chat_id="c1",
            text="hi",
        )
        ctx = MsgContext.from_channel_message(cm, provider="custom", was_mentioned=True)
        assert ctx.provider == "custom"
        assert ctx.was_mentioned is True

    @_skip
    def test_post_init_empty_channel_id_raises(self):
        """__post_init__ raises ValueError for empty channel_id."""
        with pytest.raises(ValueError, match="channel_id"):
            MsgContext(channel_id="", user_id="u", chat_id="c", body="t")

    @_skip
    def test_post_init_whitespace_channel_id_raises(self):
        """__post_init__ raises ValueError for whitespace-only channel_id."""
        with pytest.raises(ValueError, match="channel_id"):
            MsgContext(channel_id="   ", user_id="u", chat_id="c", body="t")

    @_skip
    def test_post_init_empty_user_id_raises(self):
        """__post_init__ raises ValueError for empty user_id."""
        with pytest.raises(ValueError, match="user_id"):
            MsgContext(channel_id="wa", user_id="", chat_id="c", body="t")

    @_skip
    def test_post_init_empty_chat_id_raises(self):
        """__post_init__ raises ValueError for empty chat_id."""
        with pytest.raises(ValueError, match="chat_id"):
            MsgContext(channel_id="wa", user_id="u", chat_id="", body="t")

    @_skip
    def test_valid_construction(self):
        """MsgContext with valid fields constructs without error."""
        ctx = MsgContext(channel_id="wa", user_id="u", chat_id="c", body="test")
        assert ctx.channel_id == "wa"
        assert ctx.body == "test"
        assert ctx.chat_type == "direct"
        assert ctx.is_group is False


class TestReplyPayload:
    """ReplyPayload construction with defaults."""

    @_skip
    def test_defaults(self):
        rp = ReplyPayload()
        assert rp.text == ""
        assert rp.media_url == ""
        assert rp.media_urls == []
        assert rp.reply_to_id == ""
        assert rp.is_reasoning is False
        assert rp.channel_data == {}

    @_skip
    def test_with_values(self):
        rp = ReplyPayload(text="hi", media_url="http://example.com/img.png")
        assert rp.text == "hi"
        assert rp.media_url == "http://example.com/img.png"

    @_skip
    def test_no_shared_mutable_default(self):
        rp1 = ReplyPayload()
        rp2 = ReplyPayload()
        rp1.channel_data["key"] = "val"
        assert "key" not in rp2.channel_data


class TestChannelCapabilities:
    """ChannelCapabilities construction with defaults."""

    @_skip
    def test_defaults(self):
        caps = ChannelCapabilities()
        assert caps.chat_types == ["direct"]
        assert caps.polls is False
        assert caps.reactions is False
        assert caps.edit is False
        assert caps.unsend is False
        assert caps.reply is False
        assert caps.effects is False
        assert caps.group_management is False
        assert caps.threads is False
        assert caps.media is False
        assert caps.native_commands is False
        assert caps.block_streaming is False

    @_skip
    def test_custom_values(self):
        caps = ChannelCapabilities(
            chat_types=["direct", "group"],
            media=True,
            reply=True,
        )
        assert caps.chat_types == ["direct", "group"]
        assert caps.media is True
        assert caps.reply is True


class TestChannelPlugin:
    """ChannelPlugin runtime_checkable Protocol."""

    @_skip
    def test_runtime_checkable(self):
        """A class implementing all ChannelPlugin methods is recognized."""

        class FakePlugin:
            @property
            def id(self) -> str:
                return "fake"

            @property
            def capabilities(self) -> ChannelCapabilities:
                return ChannelCapabilities()

            async def start_account(self, account_id: str) -> None:
                pass

            async def stop_account(self, account_id: str) -> None:
                pass

            async def send_text(self, to: str, text: str) -> dict:
                return {}

            async def send_media(self, to: str, media_url: str) -> dict:
                return {}

        assert isinstance(FakePlugin(), ChannelPlugin)

    @_skip
    def test_non_conforming_class_not_instance(self):
        """A class missing methods is NOT a ChannelPlugin instance."""

        class NotAPlugin:
            pass

        assert not isinstance(NotAPlugin(), ChannelPlugin)
