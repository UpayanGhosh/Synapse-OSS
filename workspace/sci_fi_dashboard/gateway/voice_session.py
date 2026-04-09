"""
gateway/voice_session.py — Per-connection voice session state machine.

A VoiceSession is created when a WebSocket client sends ``voice.start`` and
destroyed when it sends ``voice.stop`` (or disconnects). It tracks the active
TTS asyncio.Task and exposes a cancellation event so that barge-in can
interrupt streaming audio mid-flight without cascading cancellation errors.

Lifecycle:
    voice.start  →  VoiceSession created (is_ai_speaking=False)
    binary frame →  _handle_voice_audio() sets active_tts_task
    voice.barge_in → request_cancel() sets cancel_event + cancels TTS task
    TTS done     →  reset_cancel() clears state
    voice.stop   →  request_cancel() + session removed from dict
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VoiceSession:
    """Per-connection voice session state.

    Attributes
    ----------
    conn_id:
        The UUID string identifying the WebSocket connection. Used only for
        logging — the dict key in GatewayWebSocket._voice_sessions is also
        conn_id, but having it on the dataclass simplifies log messages.
    active_tts_task:
        The asyncio.Task currently streaming TTS audio to the client, or None
        if the AI is not speaking.
    cancel_event:
        Set when barge-in or voice.stop requests cancellation. Checked inside
        _stream_tts_to_ws() to break out of the edge-tts streaming loop early.
    is_ai_speaking:
        True while _stream_tts_to_ws() is running, False otherwise. Read by
        callers to decide whether barge-in is meaningful.
    """

    conn_id: str
    active_tts_task: asyncio.Task | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    is_ai_speaking: bool = False

    def request_cancel(self) -> None:
        """Signal cancellation and cancel the active TTS task if present.

        The cancel_event is set unconditionally so that _stream_tts_to_ws()
        exits its streaming loop on the next chunk iteration.

        The TTS task is cancelled via task.cancel() — asyncio will raise
        CancelledError inside the task. asyncio.shield() is intentionally NOT
        used here because we *want* the task to stop; shield() would only
        matter if we needed to await it from within a cancellation handler,
        which we do not do here.
        """
        self.cancel_event.set()
        if self.active_tts_task is not None and not self.active_tts_task.done():
            self.active_tts_task.cancel()
            logger.debug("VoiceSession %s: TTS task cancel requested", self.conn_id)

    def reset_cancel(self) -> None:
        """Clear cancellation state after TTS has finished or been cancelled.

        Called at the start of each new TTS stream so the cancel_event is
        fresh. Also called after barge-in handling completes.
        """
        self.cancel_event.clear()
        self.active_tts_task = None
        self.is_ai_speaking = False
        logger.debug("VoiceSession %s: cancel state reset", self.conn_id)
