"""
Base channel primitives — ChannelMessage dataclass and BaseChannel ABC.

All future channel adapters (WhatsApp, Telegram, Discord, Slack) subclass BaseChannel.
Import from the channels package (__init__.py), not from this submodule directly.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .security import ChannelSecurityConfig

logger = logging.getLogger(__name__)


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


@dataclass
class MsgContext:
    """Canonical inbound message — superset of ChannelMessage fields."""

    # Core routing (required)
    channel_id: str
    user_id: str
    chat_id: str
    body: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Identity
    sender_name: str = ""
    sender_id: str = ""
    sender_username: str = ""
    sender_e164: str = ""

    # Message IDs
    message_sid: str = ""
    reply_to_id: str = ""

    # Session
    session_key_str: str = ""
    account_id: str = ""
    parent_session_key: str = ""

    # Chat context
    chat_type: str = "direct"  # "direct" | "group" | "channel" | "thread"
    provider: str = ""  # "whatsapp" | "telegram" | ...
    is_group: bool = False
    group_subject: str = ""
    was_mentioned: bool = False

    # Media
    media_path: str = ""
    media_url: str = ""
    media_type: str = ""
    media_paths: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)

    # Reply context
    reply_to_body: str = ""
    reply_to_sender: str = ""

    # Thread
    message_thread_id: str = ""
    thread_label: str = ""

    # Commands
    command_authorized: bool = False
    command_body: str = ""

    # Body variants
    body_for_agent: str = ""
    raw_body: str = ""

    # Transcript
    transcript: str = ""

    # Provenance
    max_chars: int = 4000

    # Raw payload passthrough
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("channel_id", "user_id", "chat_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"MsgContext.{field_name} must be a non-empty string, "
                    f"got {value!r}"
                )

    @staticmethod
    def session_key(channel: str, chat_type: str, target_id: str) -> str:
        """Build canonical session key: '<channel>:<chatType>:<targetId>'."""
        return f"{channel}:{chat_type}:{target_id}"

    @classmethod
    def from_channel_message(cls, cm: ChannelMessage, **overrides) -> MsgContext:
        """Convert a ChannelMessage to MsgContext, filling defaults."""
        base: dict = {
            "channel_id": cm.channel_id,
            "user_id": cm.user_id,
            "chat_id": cm.chat_id,
            "body": cm.text,
            "timestamp": cm.timestamp,
            "sender_name": cm.sender_name,
            "message_sid": cm.message_id,
            "is_group": cm.is_group,
            "chat_type": "group" if cm.is_group else "direct",
            "provider": cm.channel_id,
            "raw": cm.raw,
        }
        base.update(overrides)
        return cls(**base)


@dataclass
class ReplyPayload:
    """Outbound reply shape returned by the agent pipeline."""

    text: str = ""
    media_url: str = ""
    media_urls: list[str] = field(default_factory=list)
    reply_to_id: str = ""
    is_reasoning: bool = False
    channel_data: dict = field(default_factory=dict)


class BaseChannel(ABC):
    """
    Abstract base for all channel adapters. Attempting to instantiate BaseChannel
    directly raises TypeError.

    Subclasses must implement all abstract methods and the channel_id property before
    they can be instantiated. The non-abstract lifecycle hooks (start / stop) have
    default no-op bodies that subclasses may override.
    """

    # Safe default — subclasses should override to match their platform limit.
    MAX_CHARS: int = 4000

    # Optional security configuration — set by subclass __init__ when provided.
    # Defaults to None (no access control), so existing channels work unchanged.
    security_config: ChannelSecurityConfig | None = None

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

    async def start(self) -> None:  # noqa: B027
        """
        Start the channel adapter (e.g. begin polling, open websocket).

        Called by ChannelRegistry.start_all() via asyncio.create_task().
        Real channel adapters override this with their event loop.
        Default implementation is a no-op — safe for adapters that don't need it.
        """
        ...  # default no-op; subclasses may override

    async def stop(self) -> None:  # noqa: B027
        """
        Gracefully shut down the channel adapter.

        Called by ChannelRegistry.stop_all() after the asyncio task is cancelled.
        Default implementation is a no-op — safe for adapters that don't need it.
        """
        ...  # default no-op; subclasses may override

    # ------------------------------------------------------------------
    # Optional capabilities (non-abstract — not all channels support these)
    # ------------------------------------------------------------------

    async def send_media(  # noqa: B027
        self,
        chat_id: str,
        media_url: str,
        media_type: str = "image",
        caption: str = "",
    ) -> bool:
        """
        Send a media message (image/video/audio/document) to the given chat.

        Default returns False — override in channels that support media.
        """
        return False

    async def send_reaction(  # noqa: B027
        self,
        chat_id: str,
        message_id: str,
        emoji: str,
    ) -> bool:
        """
        Send an emoji reaction to a specific message.

        Default returns False — override in channels that support reactions.
        """
        return False

    async def send_payload(self, chat_id: str, payload: ReplyPayload) -> bool:
        """Route a ReplyPayload to send_media() or send() based on media_url presence.

        Default covers the common case; channels may override for richer behaviour.
        """
        if payload.media_url:
            return await self.send_media(
                chat_id,
                media_url=payload.media_url,
                caption=payload.text,
            )
        return await self.send(chat_id, payload.text)

    # ------------------------------------------------------------------
    # Message splitting
    # ------------------------------------------------------------------

    @classmethod
    def split_message(cls, text: str, max_chars: int = 0) -> list[str]:
        """Split *text* into chunks that each fit within *max_chars*.

        Strategy (in priority order):
        1. paragraph boundary (``\\n\\n``)
        2. line boundary (``\\n``)
        3. word boundary (`` ``)
        4. hard cut

        If *max_chars* <= 0, ``cls.MAX_CHARS`` is used.
        A message that already fits is returned as ``[text]``.
        """
        limit = max_chars if max_chars > 0 else cls.MAX_CHARS
        if not text or len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            # Try split points in priority order
            cut = -1
            for sep in ("\n\n", "\n", " "):
                idx = remaining.rfind(sep, 0, limit)
                if idx > 0:
                    cut = idx
                    break

            if cut <= 0:
                # Hard cut — no natural boundary found
                cut = limit

            chunk = remaining[:cut].rstrip()
            if chunk:
                chunks.append(chunk)

            # Skip past the separator(s) we split on
            remaining = remaining[cut:].lstrip("\n").lstrip(" ") if cut < len(remaining) else ""

        return chunks if chunks else [text]
