"""Extended tests for channels/registry.py — alias resolution, metadata, and lifecycle gaps.

Fills gaps not covered in test_channels.py:
- Alias resolution via get() (e.g. "wa" -> whatsapp)
- get_meta() and list_meta() for ChannelCapabilities
- start_all/stop_all task lifecycle details
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.channels.base import BaseChannel
from sci_fi_dashboard.channels.plugin import ChannelCapabilities
from sci_fi_dashboard.channels.registry import ChannelRegistry
from sci_fi_dashboard.channels.stub import StubChannel


# ===========================================================================
# Alias resolution via get()
# ===========================================================================


class TestRegistryAliasResolution:
    """ChannelRegistry.get() resolves aliases via ids.resolve_channel_id()."""

    def test_get_by_alias(self):
        """get('wa') returns the whatsapp channel."""
        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)
        assert reg.get("wa") is stub

    def test_get_by_alias_telegram(self):
        """get('tg') returns the telegram channel."""
        reg = ChannelRegistry()
        stub = StubChannel("telegram")
        reg.register(stub)
        assert reg.get("tg") is stub

    def test_get_canonical_still_works(self):
        """get() with canonical ID still works after alias resolution."""
        reg = ChannelRegistry()
        stub = StubChannel("discord")
        reg.register(stub)
        assert reg.get("discord") is stub

    def test_get_unknown_alias_returns_none(self):
        """get() with unresolvable ID returns None."""
        reg = ChannelRegistry()
        assert reg.get("nonexistent") is None

    def test_get_falls_back_to_raw_id(self):
        """get() falls back to the raw channel_id if alias resolution misses."""
        reg = ChannelRegistry()
        stub = StubChannel("custom_channel")
        reg.register(stub)
        # "custom_channel" is not in CHANNEL_ALIASES, but it's the raw registered ID
        assert reg.get("custom_channel") is stub


# ===========================================================================
# Metadata
# ===========================================================================


class TestRegistryMetadata:
    """Tests for get_meta() and list_meta()."""

    def test_get_meta_returns_none_for_unregistered(self):
        """get_meta on unregistered channel returns None."""
        reg = ChannelRegistry()
        assert reg.get_meta("whatsapp") is None

    def test_get_meta_returns_none_without_capabilities(self):
        """get_meta returns None when channel has no capabilities attribute."""
        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)
        # StubChannel has no capabilities attr by default
        assert reg.get_meta("whatsapp") is None

    def test_get_meta_returns_capabilities(self):
        """get_meta returns ChannelCapabilities when channel exposes it."""
        reg = ChannelRegistry()
        stub = StubChannel("slack")
        caps = ChannelCapabilities(threads=True, reactions=True, max_message_length=3000)
        stub.capabilities = caps
        reg.register(stub)
        result = reg.get_meta("slack")
        assert result is caps
        assert result.threads is True
        assert result.reactions is True

    def test_get_meta_resolves_alias(self):
        """get_meta resolves aliases before lookup."""
        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        caps = ChannelCapabilities(media=True)
        stub.capabilities = caps
        reg.register(stub)
        assert reg.get_meta("wa") is caps

    def test_list_meta_empty(self):
        """list_meta returns empty dict when no channels have capabilities."""
        reg = ChannelRegistry()
        reg.register(StubChannel("a"))
        reg.register(StubChannel("b"))
        assert reg.list_meta() == {}

    def test_list_meta_returns_all_with_capabilities(self):
        """list_meta returns only channels that expose capabilities."""
        reg = ChannelRegistry()
        s1 = StubChannel("alpha")
        s2 = StubChannel("beta")
        s3 = StubChannel("gamma")
        s1.capabilities = ChannelCapabilities(polls=True)
        s3.capabilities = ChannelCapabilities(edit=True)
        reg.register(s1)
        reg.register(s2)
        reg.register(s3)
        meta = reg.list_meta()
        assert "alpha" in meta
        assert "gamma" in meta
        assert "beta" not in meta
        assert meta["alpha"].polls is True
        assert meta["gamma"].edit is True


# ===========================================================================
# Lifecycle edge cases
# ===========================================================================


class TestRegistryLifecycle:
    """Tests for start_all/stop_all edge cases."""

    @pytest.mark.asyncio
    async def test_stop_all_calls_stop_on_each_channel(self):
        """stop_all() calls stop() on each registered channel."""
        reg = ChannelRegistry()
        s1 = StubChannel("a")
        s2 = StubChannel("b")
        reg.register(s1)
        reg.register(s2)
        await reg.start_all()
        await asyncio.sleep(0)
        await reg.stop_all()
        assert s1._started is False
        assert s2._started is False

    @pytest.mark.asyncio
    async def test_start_all_with_no_channels(self):
        """start_all with no channels is a no-op."""
        reg = ChannelRegistry()
        await reg.start_all()  # should not raise

    @pytest.mark.asyncio
    async def test_stop_all_with_no_channels(self):
        """stop_all with no channels is a no-op."""
        reg = ChannelRegistry()
        await reg.stop_all()  # should not raise

    @pytest.mark.asyncio
    async def test_stop_all_clears_tasks(self):
        """stop_all clears the internal tasks dict."""
        reg = ChannelRegistry()
        reg.register(StubChannel("x"))
        await reg.start_all()
        await asyncio.sleep(0)
        await reg.stop_all()
        assert len(reg._tasks) == 0
