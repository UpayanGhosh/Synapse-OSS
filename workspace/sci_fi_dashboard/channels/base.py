"""
Base channel primitives — ChannelMessage dataclass and BaseChannel ABC.

All future channel adapters (WhatsApp, Telegram, Discord, Slack) subclass BaseChannel.
Import from the channels package (__init__.py), not from this submodule directly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ChannelMessage:
    """Unified inbound message DTO passed from any channel adapter into the pipeline."""

    channel_id: str
    user_id: str
    chat_id: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)
    is_group: bool = False
    message_id: str = ""
    sender_name: str = ""
    # MUST use field(default_factory=dict) — NOT raw: dict = {} which causes a shared
    # mutable default bug (all instances sharing the same dict object).
    raw: dict = field(default_factory=dict)


class BaseChannel(ABC):
    """
    Abstract base for all channel adapters. Attempting to instantiate BaseChannel
    directly raises TypeError.

    Subclasses must implement all abstract methods and the channel_id property before
    they can be instantiated. The non-abstract lifecycle hooks (start / stop) have
    default no-op bodies that subclasses may override.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Stable string identifier for this channel, e.g. 'whatsapp', 'telegram'."""

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    @abstractmethod
    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """
        Parse a raw inbound payload from the external service into a ChannelMessage.

        Args:
            raw_payload: The raw webhook / event dict from the channel provider.

        Returns:
            A normalised ChannelMessage ready for the pipeline.
        """

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> bool:
        """
        Send a text reply to the given chat.

        Args:
            chat_id: Destination chat / conversation identifier.
            text:    Message body to deliver.

        Returns:
            True on success, False if the delivery failed.
        """

    @abstractmethod
    async def send_typing(self, chat_id: str) -> None:
        """
        Send a "typing…" indicator to the chat if the platform supports it.

        Args:
            chat_id: Target chat / conversation identifier.
        """

    @abstractmethod
    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """
        Mark a specific message as read if the platform supports it.

        Args:
            chat_id:    Chat / conversation identifier.
            message_id: Platform-specific message identifier to mark as read.
        """

    @abstractmethod
    async def health_check(self) -> dict:
        """
        Return a status dict describing the channel's current health.

        Returns:
            A dict with at least {"status": "ok" | "degraded" | "down", ...}.
        """

    # ------------------------------------------------------------------
    # Lifecycle (non-abstract — default no-ops)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the channel adapter (e.g. begin polling, open websocket).

        Called by ChannelRegistry.start_all() via asyncio.create_task().
        Real channel adapters override this with their event loop.
        Default implementation is a no-op — safe for adapters that don't need it.
        """

    async def stop(self) -> None:
        """
        Gracefully shut down the channel adapter.

        Called by ChannelRegistry.stop_all() after the asyncio task is cancelled.
        Default implementation is a no-op — safe for adapters that don't need it.
        """
