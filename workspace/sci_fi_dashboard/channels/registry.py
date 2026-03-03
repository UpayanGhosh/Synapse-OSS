"""
ChannelRegistry — manages channel adapter lifecycle within a FastAPI lifespan.

All channels must be registered before start_all() is called from the lifespan hook.
Uses asyncio.create_task() exclusively — NEVER asyncio.run() — because uvicorn already
owns the event loop and calling asyncio.run() inside an existing loop raises RuntimeError.
"""

import asyncio

from .base import BaseChannel


class ChannelRegistry:
    """
    Singleton-style registry for channel adapters.

    Usage inside FastAPI lifespan:

        registry = ChannelRegistry()
        registry.register(WhatsAppChannel(...))
        registry.register(TelegramChannel(...))

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await registry.start_all()
            yield
            await registry.stop_all()
    """

    def __init__(self) -> None:
        self._channels: dict[str, BaseChannel] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, channel: BaseChannel) -> None:
        """
        Register a channel adapter.

        Args:
            channel: A concrete BaseChannel subclass instance.

        Raises:
            ValueError: If a channel with the same channel_id is already registered.
        """
        cid = channel.channel_id
        if cid in self._channels:
            raise ValueError(f"Channel '{cid}' already registered")
        self._channels[cid] = channel

    def get(self, channel_id: str) -> BaseChannel | None:
        """
        Return the channel adapter for the given id, or None if not registered.

        Args:
            channel_id: The stable string identifier used during register().

        Returns:
            The BaseChannel instance or None.
        """
        return self._channels.get(channel_id)

    def list_ids(self) -> list[str]:
        """Return a list of all registered channel IDs (insertion order)."""
        return list(self._channels.keys())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """
        Start all registered channels as asyncio tasks within the current event loop.

        MUST be called from inside an async context (e.g. FastAPI lifespan).
        Uses asyncio.create_task() — NEVER asyncio.run() — uvicorn already owns the
        event loop. Calling asyncio.run() inside an existing loop raises RuntimeError.

        Each channel's start() coroutine is wrapped in a named task so it appears
        in asyncio debug output and can be cancelled individually.
        """
        for cid, channel in self._channels.items():
            task = asyncio.create_task(channel.start(), name=f"channel-{cid}")
            self._tasks[cid] = task
            print(f"[CHANNELS] Started channel: {cid}")

    async def stop_all(self) -> None:
        """
        Cancel all channel tasks and call stop() on each channel.

        Cancels tasks first, then gathers them to consume CancelledError, then calls
        stop() on each adapter for any additional cleanup (closing connections, flushing
        state). Mirrors the pattern used in api_gateway.py lifespan shutdown.
        """
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        for cid, channel in self._channels.items():
            await channel.stop()
            print(f"[CHANNELS] Stopped channel: {cid}")
