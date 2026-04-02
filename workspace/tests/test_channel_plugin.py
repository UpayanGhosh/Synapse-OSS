"""Tests for channels/plugin.py — ChannelCapabilities and ChannelPlugin protocol.

Covers:
- ChannelCapabilities default values
- ChannelCapabilities custom values
- ChannelPlugin protocol structural matching
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.plugin import ChannelCapabilities, ChannelPlugin


class TestChannelCapabilities:
    """Tests for ChannelCapabilities dataclass."""

    def test_defaults(self):
        """Default ChannelCapabilities has expected values."""
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
        assert caps.markdown_capable is True
        assert caps.max_message_length == 4000

    def test_custom_values(self):
        """ChannelCapabilities accepts custom values."""
        caps = ChannelCapabilities(
            chat_types=["direct", "group", "channel"],
            polls=True,
            reactions=True,
            threads=True,
            media=True,
            max_message_length=2000,
        )
        assert caps.chat_types == ["direct", "group", "channel"]
        assert caps.polls is True
        assert caps.reactions is True
        assert caps.threads is True
        assert caps.media is True
        assert caps.max_message_length == 2000

    def test_no_shared_mutable_defaults(self):
        """chat_types list uses factory — no shared mutable default."""
        c1 = ChannelCapabilities()
        c2 = ChannelCapabilities()
        c1.chat_types.append("group")
        assert "group" not in c2.chat_types


class TestChannelPlugin:
    """Tests for ChannelPlugin runtime_checkable protocol."""

    def test_protocol_check_valid(self):
        """A class implementing all methods satisfies the protocol."""

        class MyPlugin:
            @property
            def id(self) -> str:
                return "my_plugin"

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

        plugin = MyPlugin()
        assert isinstance(plugin, ChannelPlugin)

    def test_protocol_check_invalid(self):
        """A class missing methods does NOT satisfy the protocol."""

        class NotAPlugin:
            pass

        assert not isinstance(NotAPlugin(), ChannelPlugin)
