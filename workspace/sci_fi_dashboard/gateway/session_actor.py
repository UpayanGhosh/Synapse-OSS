import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 300  # 5 minutes — prevents hung LLM calls from blocking the queue


class SessionActorQueue:
    """Per-actor FIFO: same actor_key serialized, different keys concurrent.

    Uses dict[str, asyncio.Lock] instead of promise-chain.  Each actor_key
    gets its own asyncio.Lock.  Operations on the same key are serialized by
    acquiring the lock.  Operations on different keys run concurrently
    (different locks).  All ops are wrapped in asyncio.wait_for() with a
    configurable timeout to prevent hung calls from permanently blocking
    the queue.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, int] = {}  # actor_key -> count of queued ops
        self._timeout = timeout

    async def run(self, actor_key: str, op: Callable[[], Awaitable[T]]) -> T:
        """Execute *op* serialized per *actor_key*, concurrent across different keys."""
        # Lazily create lock for this actor_key
        if actor_key not in self._locks:
            self._locks[actor_key] = asyncio.Lock()
        lock = self._locks[actor_key]

        self._pending[actor_key] = self._pending.get(actor_key, 0) + 1
        try:
            async with lock:
                return await asyncio.wait_for(op(), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "SessionActorQueue: op for %s timed out after %.1fs",
                actor_key,
                self._timeout,
            )
            raise
        finally:
            self._pending[actor_key] -= 1
            if self._pending[actor_key] <= 0:
                self._pending.pop(actor_key, None)
                self._locks.pop(actor_key, None)

    def get_total_pending_count(self) -> int:
        return sum(self._pending.values())

    def get_pending_count_for_session(self, actor_key: str) -> int:
        return self._pending.get(actor_key, 0)
