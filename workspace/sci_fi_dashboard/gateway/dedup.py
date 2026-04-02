import time


class MessageDeduplicator:
    """Simple TTLCache to avoid reprocessing same messageid if webhook is retried."""

    _CLEANUP_INTERVAL: float = 60.0  # seconds between cleanup sweeps

    def __init__(self, window_seconds: int = 300):
        self.window = window_seconds
        self.seen: dict[str, float] = {}
        self._last_cleanup: float = 0.0

    def is_duplicate(self, message_id: str) -> bool:
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
            return True

        self.seen[message_id] = now
        return False
