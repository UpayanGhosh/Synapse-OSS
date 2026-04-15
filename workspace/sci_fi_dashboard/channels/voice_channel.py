"""
channels/voice_channel.py — VoiceChannel adapter for real-time voice sessions.

VoiceChannel is a thin BaseChannel subclass that represents the voice
WebSocket path. Unlike text channels (WhatsApp, Telegram), the voice channel
does NOT use the standard receive/send adapter pattern:

  - Inbound audio arrives as raw binary WebSocket frames, handled directly by
    GatewayWebSocket._handle_voice_audio(). The ``receive()`` method therefore
    raises NotImplementedError to document this intentionally.
  - Outbound TTS audio is streamed back as binary frames inside
    _stream_tts_to_ws(). The ``send()`` method returns True immediately
    because actual delivery is handled by the WS layer.
  - Typing indicators and read receipts are not meaningful for voice sessions.
  - ``health_check()`` returns a static ok dict — the channel is stateless.

This adapter exists primarily so that VoiceChannel can be registered with
ChannelRegistry under channel_id="voice", allowing the rest of the pipeline
(e.g. channels.status WS method) to report it.
"""

from __future__ import annotations

import logging

from .base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)


class VoiceChannel(BaseChannel):
    """BaseChannel adapter for the real-time voice WebSocket path.

    All six abstract methods are implemented as required by BaseChannel.
    Most are no-ops or stubs — real audio I/O is managed by GatewayWebSocket.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        """Stable identifier used throughout the gateway and channel registry."""
        return "voice"

    # ------------------------------------------------------------------
    # Core I/O
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """Not applicable — voice input arrives as binary WebSocket frames.

        Raises
        ------
        NotImplementedError
            Always. Callers should use GatewayWebSocket._handle_voice_audio()
            for inbound audio processing.
        """
        raise NotImplementedError(
            "VoiceChannel receives audio via WebSocket binary frames, not raw_payload. "
            "Use GatewayWebSocket._handle_voice_audio() for inbound audio."
        )

    async def send(self, chat_id: str, text: str) -> bool:
        """No-op send — TTS delivery is handled by _stream_tts_to_ws().

        Returns True to indicate the message was accepted (delivery is
        asynchronous and managed by the WebSocket layer).
        """
        return True

    async def send_typing(self, chat_id: str) -> None:
        """No-op — voice channel does not simulate typing indicators."""

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """No-op — voice channel does not simulate read receipts."""

    async def health_check(self) -> dict:
        """Return a static ok response — voice channel is stateless."""
        return {"status": "ok", "channel": "voice"}

    # ------------------------------------------------------------------
    # Lifecycle (inherits no-op defaults from BaseChannel)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """No-op — voice channel has no background polling loop."""

    async def stop(self) -> None:
        """No-op — voice channel has no resources to release."""
