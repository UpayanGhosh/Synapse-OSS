"""conversation_cache.py — LRU cache for parsed conversation message lists.

Avoids repeated JSONL disk reads within a configurable TTL.  Thread-safe
for single-threaded asyncio — all mutations happen on the event-loop thread
under the GIL.

Usage::

    cache = ConversationCache(max_entries=100, ttl_s=60.0)
    msgs = cache.get(session_key)
    if msgs is None:
        msgs = await load_messages(transcript_path)
        cache.put(session_key, msgs)

Wire into ``context_assembler.assemble_context()`` via the optional
``conversation_cache`` parameter.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    messages: list[dict]
    expires_at: float  # time.monotonic() deadline


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class ConversationCache:
    """LRU cache for parsed conversation message lists.

    Args:
        max_entries: Maximum number of session keys to cache.  When exceeded
                     the least-recently-used entry is evicted.
        ttl_s:       Time-to-live in seconds.  On ``get()`` hits the TTL is
                     **slid** forward — frequently accessed sessions stay warm.
    """

    def __init__(self, max_entries: int = 100, ttl_s: float = 60.0) -> None:
        self._max_entries = max(max_entries, 1)
        self._ttl_s = ttl_s
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, session_key: str) -> list[dict] | None:
        """Return cached messages for *session_key*, or ``None`` on miss.

        On hit the TTL is slid forward and the entry is promoted to
        most-recently-used.
        """
        entry = self._store.get(session_key)
        if entry is None:
            return None

        if time.monotonic() > entry.expires_at:
            # Expired — evict and treat as miss.
            self._store.pop(session_key, None)
            return None

        # Slide TTL and promote to MRU.
        entry.expires_at = time.monotonic() + self._ttl_s
        self._store.move_to_end(session_key)
        return entry.messages

    def put(self, session_key: str, messages: list[dict]) -> None:
        """Store *messages* under *session_key*, evicting LRU if over capacity."""
        self._store[session_key] = _CacheEntry(
            messages=list(messages),  # shallow copy to avoid mutation leaks
            expires_at=time.monotonic() + self._ttl_s,
        )
        self._store.move_to_end(session_key)
        self._evict()

    def append(self, session_key: str, message: dict) -> None:
        """Append a single message to the cached list for *session_key*.

        No-op if *session_key* is not currently cached (avoids partial state).
        Does **not** reset the TTL — the original expiry stands.
        """
        entry = self._store.get(session_key)
        if entry is None:
            return

        if time.monotonic() > entry.expires_at:
            self._store.pop(session_key, None)
            return

        entry.messages.append(message)

    def invalidate(self, session_key: str) -> None:
        """Remove *session_key* from the cache.

        Should be called after compaction so the next ``get()`` re-reads
        the compacted transcript from disk.
        """
        self._store.pop(session_key, None)

    # ------------------------------------------------------------------
    # Introspection (useful for tests)
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, session_key: str) -> bool:
        entry = self._store.get(session_key)
        if entry is None:
            return False
        if time.monotonic() > entry.expires_at:
            self._store.pop(session_key, None)
            return False
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict(self) -> None:
        """Evict oldest entries until the store is within capacity."""
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
