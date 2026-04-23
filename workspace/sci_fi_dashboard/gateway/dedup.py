"""Phase 16 BRIDGE-04 — webhook idempotency dedup with hit/miss telemetry.

Minimal TTLCache of message_ids. 300s default window. Periodic cleanup every 60s.

Phase 16 additions:
  - self.hits (int): number of duplicate-hits seen (operator signal for broken retry loop)
  - self.misses (int): number of first-sightings seen
  - hit_rate computed at read time as hits / (hits + misses) when total > 0

Existing callers (routes/whatsapp.py:81) are unaffected — counters are purely additive.
"""

from __future__ import annotations

import time


class MessageDeduplicator:
    """Simple TTLCache to avoid reprocessing the same message_id on webhook retries.

    Attributes:
        window (int): TTL in seconds before an entry is evicted from the cache
        seen (dict[str, float]): message_id -> first-seen monotonic-ish timestamp
        hits (int): Phase 16 BRIDGE-04 — count of is_duplicate calls that found a hit
        misses (int): Phase 16 BRIDGE-04 — count of is_duplicate calls that were first-seen
    """

    _CLEANUP_INTERVAL: float = 60.0  # seconds between cleanup sweeps

    def __init__(self, window_seconds: int = 300):
        self.window = window_seconds
        self.seen: dict[str, float] = {}
        self._last_cleanup: float = 0.0
        # Phase 16 BRIDGE-04: operator-visible counters
        self.hits: int = 0
        self.misses: int = 0

    def is_duplicate(self, message_id: str) -> bool:
        """Return True iff message_id was seen within window.

        Empty / falsy message_id returns False WITHOUT incrementing counters
        (preserved behavior from H-09 UUID-fallback path in routes/whatsapp.py).
        """
        if not message_id:
            return False

        now = time.time()

        # Periodic cleanup instead of every call (L-14)
        if now - self._last_cleanup > self._CLEANUP_INTERVAL:
            expired = [k for k, v in self.seen.items() if now - v > self.window]
            for k in expired:
                del self.seen[k]
            self._last_cleanup = now

        if message_id in self.seen:
            self.hits += 1
            return True

        self.seen[message_id] = now
        self.misses += 1
        return False

    def hit_rate(self) -> float:
        """Return duplicates / total as float in [0, 1]. 0.0 when no samples."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
