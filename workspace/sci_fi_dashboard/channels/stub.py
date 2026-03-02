"""
StubChannel — minimal concrete BaseChannel implementation for testing and pattern validation.

Does not connect to any external service. Useful as:
  - A template showing how to implement BaseChannel
  - A drop-in channel during unit and integration tests
  - A smoke test that the ChannelRegistry lifecycle works end-to-end

asyncio.create_task() wraps start() — returning immediately is correct for stubs.
Real channels (Telegram, Discord) put their polling loop inside start().
"""

from .base import BaseChannel, ChannelMessage


class StubChannel(BaseChannel):
    """
    Minimal channel for testing and pattern validation.
    Does not connect to any external service.

    asyncio.create_task() wraps start() — returning immediately is correct for stubs.
    Real polling channels would loop inside start():
        while True: await asyncio.sleep(1)
    """

    def __init__(self, channel_id: str = "stub") -> None:
        self._channel_id = channel_id
        # Records (chat_id, text) tuples for each send() call — inspect in tests.
        self.sent_messages: list[tuple[str, str]] = []
        self._started: bool = False

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return self._channel_id

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """Parse a stub payload into a ChannelMessage. All fields have sensible defaults."""
        return ChannelMessage(
            channel_id=self._channel_id,
            user_id=raw_payload.get("user_id", "stub_user"),
            chat_id=raw_payload.get("chat_id", "stub_chat"),
            text=raw_payload.get("text", ""),
            message_id=raw_payload.get("message_id", ""),
            sender_name=raw_payload.get("sender_name", "Stub User"),
            raw=raw_payload,
        )

    async def send(self, chat_id: str, text: str) -> bool:
        """Record the outbound message in sent_messages and return True."""
        self.sent_messages.append((chat_id, text))
        return True

    async def send_typing(self, chat_id: str) -> None:
        """No-op — stub does not simulate typing indicators."""

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """No-op — stub does not simulate read receipts."""

    async def health_check(self) -> dict:
        """Return a static ok response with current started state."""
        return {"status": "ok", "channel": self._channel_id, "started": self._started}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark as started and return immediately (no polling loop)."""
        self._started = True
        # Real channels would keep the event loop busy here, e.g.:
        #   while True:
        #       events = await self._poll()
        #       for event in events:
        #           await self._dispatch(event)

    async def stop(self) -> None:
        """Mark as stopped."""
        self._started = False
