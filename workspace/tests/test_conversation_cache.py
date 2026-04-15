"""Tests for multiuser/conversation_cache.py — ConversationCache LRU with TTL.

Covers:
- get() miss returns None
- put() and get() round-trip
- TTL expiry
- TTL slide on hit
- LRU eviction at max_entries
- append() to cached session
- append() no-op for uncached session
- append() no-op for expired session
- invalidate() removes entry
- __len__ and __contains__
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(not AVAILABLE, reason="conversation_cache not available")


@_skip
class TestConversationCache:

    def test_get_miss_returns_none(self):
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        assert cache.get("nonexistent") is None

    def test_put_and_get_round_trip(self):
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        msgs = [{"role": "user", "content": "hi"}]
        cache.put("key1", msgs)
        result = cache.get("key1")
        assert result == msgs

    def test_put_makes_shallow_copy(self):
        """put() stores a shallow copy — mutations don't leak."""
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        original = [{"role": "user", "content": "hi"}]
        cache.put("key1", original)
        original.append({"role": "assistant", "content": "bye"})
        cached = cache.get("key1")
        assert len(cached) == 1  # not affected by mutation

    def test_ttl_expiry(self):
        """Entry expires after TTL."""
        cache = ConversationCache(max_entries=10, ttl_s=0.01)
        cache.put("key1", [{"role": "user", "content": "hi"}])
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_ttl_slide_on_hit(self):
        """get() slides the TTL forward on a hit."""
        cache = ConversationCache(max_entries=10, ttl_s=0.1)
        cache.put("key1", [{"role": "user", "content": "hi"}])
        time.sleep(0.05)
        # Access should slide TTL
        result = cache.get("key1")
        assert result is not None
        time.sleep(0.05)
        # Should still be alive because TTL was slid
        result2 = cache.get("key1")
        assert result2 is not None

    def test_lru_eviction(self):
        """Oldest entry evicted when exceeding max_entries."""
        cache = ConversationCache(max_entries=3, ttl_s=60.0)
        for i in range(4):
            cache.put(f"key{i}", [{"role": "user", "content": f"msg{i}"}])
        # key0 should be evicted
        assert cache.get("key0") is None
        assert cache.get("key1") is not None
        assert cache.get("key3") is not None

    def test_append_to_cached(self):
        """append() adds a message to an existing cached entry."""
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        cache.put("key1", [{"role": "user", "content": "hi"}])
        cache.append("key1", {"role": "assistant", "content": "hello"})
        result = cache.get("key1")
        assert len(result) == 2
        assert result[1]["role"] == "assistant"

    def test_append_noop_for_uncached(self):
        """append() is a no-op for uncached session key."""
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        cache.append("ghost", {"role": "user", "content": "hi"})
        assert cache.get("ghost") is None

    def test_append_noop_for_expired(self):
        """append() is a no-op for expired session."""
        cache = ConversationCache(max_entries=10, ttl_s=0.01)
        cache.put("key1", [{"role": "user", "content": "hi"}])
        time.sleep(0.02)
        cache.append("key1", {"role": "assistant", "content": "bye"})
        assert cache.get("key1") is None

    def test_invalidate(self):
        """invalidate() removes an entry from the cache."""
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        cache.put("key1", [{"role": "user", "content": "hi"}])
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_invalidate_nonexistent_noop(self):
        """invalidate() on nonexistent key does not raise."""
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        cache.invalidate("ghost")  # should not raise

    def test_len(self):
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        assert len(cache) == 0
        cache.put("a", [])
        cache.put("b", [])
        assert len(cache) == 2

    def test_contains(self):
        cache = ConversationCache(max_entries=10, ttl_s=60.0)
        cache.put("key1", [])
        assert "key1" in cache
        assert "key2" not in cache

    def test_contains_expired_returns_false(self):
        cache = ConversationCache(max_entries=10, ttl_s=0.01)
        cache.put("key1", [])
        time.sleep(0.02)
        assert "key1" not in cache

    def test_min_max_entries(self):
        """max_entries is clamped to at least 1."""
        cache = ConversationCache(max_entries=0, ttl_s=60.0)
        assert cache._max_entries == 1
