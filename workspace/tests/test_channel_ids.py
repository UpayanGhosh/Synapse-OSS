"""Tests for channels/ids.py — canonical IDs, aliases, and validation.

Covers:
- CHANNEL_ORDER tuple contents
- CHANNEL_ALIASES mappings
- resolve_channel_id() alias resolution
- is_valid_channel_id() validation
- ChannelId type completeness
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.ids import (
    CHANNEL_ALIASES,
    CHANNEL_ORDER,
    ChannelId,
    is_valid_channel_id,
    resolve_channel_id,
)


class TestChannelOrder:
    """Tests for CHANNEL_ORDER tuple."""

    def test_contains_core_channels(self):
        """All core channels are in CHANNEL_ORDER."""
        for ch in ("whatsapp", "telegram", "discord", "slack", "cli", "websocket"):
            assert ch in CHANNEL_ORDER

    def test_is_tuple(self):
        """CHANNEL_ORDER is a tuple (immutable)."""
        assert isinstance(CHANNEL_ORDER, tuple)

    def test_no_duplicates(self):
        """No duplicate entries in CHANNEL_ORDER."""
        assert len(CHANNEL_ORDER) == len(set(CHANNEL_ORDER))


class TestChannelAliases:
    """Tests for CHANNEL_ALIASES mapping."""

    def test_wa_alias(self):
        assert CHANNEL_ALIASES["wa"] == "whatsapp"

    def test_tg_alias(self):
        assert CHANNEL_ALIASES["tg"] == "telegram"

    def test_dc_alias(self):
        assert CHANNEL_ALIASES["dc"] == "discord"

    def test_ws_alias(self):
        assert CHANNEL_ALIASES["ws"] == "websocket"

    def test_web_alias(self):
        assert CHANNEL_ALIASES["web"] == "websocket"


class TestResolveChannelId:
    """Tests for resolve_channel_id()."""

    def test_alias_resolved(self):
        """Known alias resolves to canonical ID."""
        assert resolve_channel_id("wa") == "whatsapp"
        assert resolve_channel_id("tg") == "telegram"
        assert resolve_channel_id("dc") == "discord"

    def test_canonical_id_returned_as_is(self):
        """Canonical ID passes through unchanged."""
        assert resolve_channel_id("whatsapp") == "whatsapp"
        assert resolve_channel_id("telegram") == "telegram"

    def test_case_insensitive(self):
        """Resolution is case-insensitive."""
        assert resolve_channel_id("WA") == "whatsapp"
        assert resolve_channel_id("Telegram") == "telegram"
        assert resolve_channel_id("DISCORD") == "discord"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert resolve_channel_id("  wa  ") == "whatsapp"
        assert resolve_channel_id("\ttelegram\n") == "telegram"

    def test_unknown_returned_lowered(self):
        """Unknown channel ID returned as lowercase."""
        assert resolve_channel_id("myCustomChannel") == "mycustomchannel"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert resolve_channel_id("") == ""


class TestIsValidChannelId:
    """Tests for is_valid_channel_id()."""

    def test_valid_canonical_ids(self):
        """All canonical IDs are valid."""
        for ch in CHANNEL_ORDER:
            assert is_valid_channel_id(ch) is True

    def test_valid_aliases(self):
        """Known aliases are valid."""
        assert is_valid_channel_id("wa") is True
        assert is_valid_channel_id("tg") is True
        assert is_valid_channel_id("dc") is True

    def test_case_insensitive_valid(self):
        """Validation is case-insensitive."""
        assert is_valid_channel_id("WhatsApp") is True
        assert is_valid_channel_id("SLACK") is True

    def test_unknown_invalid(self):
        """Unknown channel IDs are not valid."""
        assert is_valid_channel_id("unknown_channel") is False
        assert is_valid_channel_id("sms") is False

    def test_empty_string_invalid(self):
        """Empty string is not valid."""
        assert is_valid_channel_id("") is False
