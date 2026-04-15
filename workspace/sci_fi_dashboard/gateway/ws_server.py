"""
ws_server.py -- WebSocket control-plane handler for the Synapse gateway.

GatewayWebSocket is constructed inside the FastAPI lifespan() after all
singletons are initialized, and stored on ``app.state.gateway_ws``.
The ``/ws`` endpoint reads from ``app.state`` to access it (wired in
Subtask 7).

Protocol:
  1. Client sends a ``connect`` frame as the very first message.
  2. Server validates optional SYNAPSE_GATEWAY_TOKEN.
  3. Server replies with a ``hello-ok`` response.
  4. A background tick loop sends heartbeat events every 30 s.
  5. Subsequent ``req`` frames are dispatched to method handlers.
     voice.* JSON methods are routed to dedicated voice handlers before
     reaching _dispatch().
  6. Binary frames are treated as voice audio (WAV bytes from mic).
  7. On disconnect the tick task is cancelled and any active voice session
     is torn down.

Each connection gets its own monotonic ``seq`` counter for events.

Voice protocol additions
------------------------
  voice.start     — open a VoiceSession for this connection
  voice.stop      — close the VoiceSession, cancel any active TTS
  voice.barge_in  — cancel active TTS while keeping the session open

Binary frames (bytes)
  Client → Server:  WAV audio blob (<=5 MiB)
  Server → Client:  MP3/OGG TTS audio blob, followed by voice.tts_done event

Events emitted by this server
  voice.transcription  {"text": "..."}   — transcript of user audio
  voice.tts_done       {}                — TTS stream finished
  voice.error          {"code": "...", "message": "..."}
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import time
import uuid
from pathlib import Path

from starlette.websockets import WebSocket, WebSocketDisconnect

from .voice_session import VoiceSession
from .ws_protocol import (
    INVALID_REQUEST,
    UNAVAILABLE,
    make_error,
    make_event,
    make_response,
    parse_frame,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_INTERVAL_S: int = 30
CONNECT_TIMEOUT_S: float = 10.0

SUPPORTED_METHODS: list[str] = [
    "chat.send",
    "channels.status",
    "models.list",
    "sessions.list",
    "sessions.reset",
    "voice.start",
    "voice.stop",
    "voice.barge_in",
]

SUPPORTED_EVENTS: list[str] = [
    "tick",
    "agent",
    "presence",
    "voice.transcription",
    "voice.tts_done",
    "voice.error",
]

SERVER_VERSION: str = "1.0.0"
MAX_PAYLOAD_BYTES: int = 1_048_576  # 1 MiB
MAX_VOICE_FRAME_BYTES: int = 5 * 1024 * 1024  # 5 MiB — ~30s of 16kHz PCM16 WAV


# ---------------------------------------------------------------------------
# GatewayWebSocket
# ---------------------------------------------------------------------------


class GatewayWebSocket:
    """WebSocket control-plane handler.

    Constructed inside ``lifespan()`` after all singletons are ready, and
    stored on ``app.state.gateway_ws``.  The ``/ws`` endpoint reads from
    ``app.state`` to access this instance.
    """

    def __init__(
        self,
        config=None,
        task_queue=None,
        channel_registry=None,
        models_catalog_path: str | Path | None = None,
    ) -> None:
        self._config = config
        self._task_queue = task_queue
        self._channel_registry = channel_registry
        self._models_catalog_path = Path(models_catalog_path) if models_catalog_path else None
        self._gateway_token: str | None = os.environ.get("SYNAPSE_GATEWAY_TOKEN")
        # Maps conn_id -> VoiceSession for active voice connections
        self._voice_sessions: dict[str, VoiceSession] = {}

    # ------------------------------------------------------------------
    # Main connection handler
    # ------------------------------------------------------------------

    async def handle(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and run the frame loop."""
        await websocket.accept()
        conn_id = str(uuid.uuid4())
        seq: list[int] = [0]  # mutable container for per-connection counter

        try:
            # ---- 1. Wait for first frame -- must be "connect" --------
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=CONNECT_TIMEOUT_S)
            except TimeoutError:
                logger.warning("WS %s: connect timeout after %.0fs", conn_id, CONNECT_TIMEOUT_S)
                await websocket.close(code=4000, reason="Connect timeout")
                return

            try:
                frame = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                await websocket.close(code=4000, reason="Invalid JSON")
                return

            if not isinstance(frame, dict) or frame.get("type") != "connect":
                await websocket.close(code=4000, reason="First frame must be connect")
                return

            # ---- 2. Validate auth token if SYNAPSE_GATEWAY_TOKEN set -
            if self._gateway_token:
                params = frame.get("params", {})
                auth = params.get("auth", {}) if isinstance(params, dict) else {}
                token = auth.get("token", "") if isinstance(auth, dict) else ""
                if not hmac.compare_digest(token, self._gateway_token):
                    logger.warning("WS %s: invalid gateway token", conn_id)
                    await websocket.close(code=4001, reason="Invalid token")
                    return

            # ---- 3. Send HelloOk response ----------------------------
            hello = make_response(
                request_id=frame.get("id", "connect"),
                ok=True,
                payload={
                    "type": "hello-ok",
                    "protocol": 1,
                    "server": {
                        "version": SERVER_VERSION,
                        "connId": conn_id,
                    },
                    "features": {
                        "methods": list(SUPPORTED_METHODS),
                        "events": list(SUPPORTED_EVENTS),
                    },
                    "policy": {
                        "maxPayload": MAX_PAYLOAD_BYTES,
                        "maxVoiceFrame": MAX_VOICE_FRAME_BYTES,
                        "tickIntervalMs": TICK_INTERVAL_S * 1000,
                    },
                },
            )
            await websocket.send_json(hello)
            logger.info("WS %s: connected", conn_id)

            # ---- 4. Start tick loop in background --------------------
            tick_task = asyncio.create_task(self._tick_loop(websocket, seq, conn_id))

            # ---- 5. Handle subsequent frames (text JSON or binary audio) ----
            try:
                while True:
                    message = await websocket.receive()

                    # Client disconnected cleanly
                    if message.get("type") == "websocket.disconnect":
                        logger.info("WS %s: client disconnected (clean)", conn_id)
                        break

                    # Binary frame — treat as voice audio
                    if message.get("bytes"):
                        audio_bytes: bytes = message["bytes"]
                        if len(audio_bytes) > MAX_VOICE_FRAME_BYTES:
                            seq[0] += 1
                            await websocket.send_json(
                                make_event(
                                    "voice.error",
                                    {
                                        "code": "frame_too_large",
                                        "message": (
                                            f"Audio frame exceeds {MAX_VOICE_FRAME_BYTES // (1024 * 1024)} MiB limit"
                                        ),
                                    },
                                    seq[0],
                                )
                            )
                            logger.warning(
                                "WS %s: binary frame %d bytes > limit %d, rejected",
                                conn_id,
                                len(audio_bytes),
                                MAX_VOICE_FRAME_BYTES,
                            )
                            continue
                        await self._handle_voice_audio(websocket, audio_bytes, conn_id, seq)
                        continue

                    # Text frame — JSON dispatch
                    raw_text = message.get("text", "")
                    if not raw_text:
                        continue

                    if len(raw_text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                        logger.warning(
                            "WS %s: payload exceeds %d bytes, closing",
                            conn_id,
                            MAX_PAYLOAD_BYTES,
                        )
                        await websocket.close(code=4002, reason="Payload exceeds max size")
                        return

                    req = parse_frame(raw_text)
                    if req is None:
                        # Silently ignore non-req frames (e.g. pong, unknown)
                        continue

                    seq[0] += 1

                    # Route voice.* methods BEFORE _dispatch() to keep them
                    # separate from the standard JSON RPC path.
                    method = req.method if hasattr(req, "method") else req.get("method", "")
                    if isinstance(method, str) and method.startswith("voice."):
                        response = await self._dispatch_voice(websocket, conn_id, req, seq)
                        await websocket.send_json(response)
                        continue

                    # Standard method dispatch (chat.send, channels.status, etc.)
                    response = await self._dispatch(req)
                    await websocket.send_json(response)

            except WebSocketDisconnect:
                logger.info("WS %s: client disconnected", conn_id)
            finally:
                tick_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tick_task

                # Clean up any active voice session on disconnect
                voice_session = self._voice_sessions.pop(conn_id, None)
                if voice_session:
                    voice_session.request_cancel()
                    if voice_session.active_tts_task and not voice_session.active_tts_task.done():
                        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                            await asyncio.wait_for(voice_session.active_tts_task, timeout=1.0)
                    logger.info("WS %s: voice session cleaned up on disconnect", conn_id)

        except Exception:
            logger.exception("WS %s: unhandled error", conn_id)
            # Attempt graceful close; ignore if already closed
            with contextlib.suppress(Exception):
                await websocket.close(code=4000, reason="Internal error")

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    async def _tick_loop(
        self,
        websocket: WebSocket,
        seq_ref: list[int],
        conn_id: str,
    ) -> None:
        """Send ``tick`` events every TICK_INTERVAL_S seconds."""
        try:
            while True:
                await asyncio.sleep(TICK_INTERVAL_S)
                seq_ref[0] += 1
                event = make_event(
                    event="tick",
                    payload={"ts": time.time()},
                    seq=seq_ref[0],
                )
                await websocket.send_json(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("WS %s: tick loop ended", conn_id)

    # ------------------------------------------------------------------
    # Voice method routing
    # ------------------------------------------------------------------

    async def _dispatch_voice(
        self,
        websocket: WebSocket,
        conn_id: str,
        req,
        seq: list[int],
    ) -> dict:
        """Route a voice.* JSON method to its dedicated handler.

        This is called from the main receive loop BEFORE _dispatch() so that
        voice methods never touch the standard chat/channel handler table.
        """
        # Support both RequestFrame dataclass (from parse_frame) and plain dict
        method = req.method if hasattr(req, "method") else req.get("method", "")
        request_id = req.id if hasattr(req, "id") else req.get("id", "")

        try:
            if method == "voice.start":
                return await self._handle_voice_start(websocket, conn_id, req)
            elif method == "voice.stop":
                return await self._handle_voice_stop(websocket, conn_id, req)
            elif method == "voice.barge_in":
                return await self._handle_voice_barge_in(websocket, conn_id, req)
            else:
                return make_response(
                    request_id,
                    ok=False,
                    error=make_error(INVALID_REQUEST, f"Unknown voice method: {method}"),
                )
        except Exception as exc:
            logger.exception("WS %s: voice dispatch error for method %s", conn_id, method)
            return make_response(
                request_id,
                ok=False,
                error=make_error(UNAVAILABLE, str(exc), retryable=True),
            )

    # ------------------------------------------------------------------
    # Voice method handlers
    # ------------------------------------------------------------------

    async def _handle_voice_start(self, websocket: WebSocket, conn_id: str, req) -> dict:
        """Create a VoiceSession for this connection.

        Idempotent — if a session already exists it is replaced with a fresh one
        (the old TTS task is cancelled first).
        """
        request_id = req.id if hasattr(req, "id") else req.get("id", "")

        # Cancel any pre-existing session for this conn
        existing = self._voice_sessions.get(conn_id)
        if existing:
            existing.request_cancel()

        session = VoiceSession(conn_id=conn_id)
        self._voice_sessions[conn_id] = session
        logger.info("WS %s: voice session started", conn_id)
        return make_response(request_id, ok=True, payload={"status": "voice_session_active"})

    async def _handle_voice_stop(self, websocket: WebSocket, conn_id: str, req) -> dict:
        """Tear down the VoiceSession and cancel any active TTS task."""
        request_id = req.id if hasattr(req, "id") else req.get("id", "")

        session = self._voice_sessions.pop(conn_id, None)
        if session:
            session.request_cancel()
            if session.active_tts_task and not session.active_tts_task.done():
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(session.active_tts_task, timeout=1.0)
        logger.info("WS %s: voice session stopped", conn_id)
        return make_response(request_id, ok=True, payload={"status": "voice_session_ended"})

    async def _handle_voice_barge_in(self, websocket: WebSocket, conn_id: str, req) -> dict:
        """Cancel the active TTS stream without ending the voice session.

        The session stays open so the user can immediately speak again after
        interrupting the AI.
        """
        request_id = req.id if hasattr(req, "id") else req.get("id", "")

        session = self._voice_sessions.get(conn_id)
        if session:
            session.request_cancel()
            logger.info(
                "WS %s: barge-in requested (is_ai_speaking=%s)", conn_id, session.is_ai_speaking
            )
        return make_response(request_id, ok=True, payload={"status": "barge_in_acknowledged"})

    # ------------------------------------------------------------------
    # Voice audio handler (binary frames)
    # ------------------------------------------------------------------

    async def _handle_voice_audio(
        self,
        websocket: WebSocket,
        wav_bytes: bytes,
        conn_id: str,
        seq: list[int],
    ) -> None:
        """Process a binary WAV frame from the client microphone.

        Pipeline:
          1. Retrieve VoiceSession (abort if no session — voice.start required).
          2. Cancel any currently-streaming TTS (barge-in implicit in new audio).
          3. Transcribe audio via Groq Whisper.
          4. Emit voice.transcription event.
          5. Route through persona_chat() as a text message.
          6. Start TTS streaming as a background asyncio.Task.
        """
        from ..media.audio_transcriber import transcribe_bytes  # local to avoid circular

        session = self._voice_sessions.get(conn_id)
        if session is None:
            logger.warning(
                "WS %s: binary audio frame received but no voice session active — "
                "client must send voice.start first",
                conn_id,
            )
            return

        # Implicitly cancel any running TTS before processing new audio
        if session.active_tts_task is not None and not session.active_tts_task.done():
            session.request_cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(session.active_tts_task, timeout=1.0)
        session.reset_cancel()

        # --- Transcribe ---
        text = await transcribe_bytes(wav_bytes)
        if not text:
            seq[0] += 1
            await websocket.send_json(
                make_event(
                    "voice.error",
                    {"code": "transcription_failed", "message": "Could not transcribe audio"},
                    seq[0],
                )
            )
            logger.warning("WS %s: transcription returned empty string", conn_id)
            return

        # --- Emit transcription event ---
        seq[0] += 1
        await websocket.send_json(make_event("voice.transcription", {"text": text}, seq[0]))
        logger.info("WS %s: transcribed %d chars", conn_id, len(text))

        # --- Route through persona pipeline ---
        try:
            from sci_fi_dashboard.chat_pipeline import persona_chat  # lazy import
            from sci_fi_dashboard.schemas import ChatRequest  # lazy import

            request = ChatRequest(message=text, user_id="the_creator")
            result = await persona_chat(request, target="the_creator")
            reply_text: str = result.get("reply", "")
        except Exception as exc:
            logger.error("WS %s: persona_chat error: %s", conn_id, exc)
            seq[0] += 1
            await websocket.send_json(
                make_event(
                    "voice.error",
                    {"code": "pipeline_error", "message": "Failed to generate reply"},
                    seq[0],
                )
            )
            return

        if not reply_text:
            logger.warning("WS %s: persona_chat returned empty reply", conn_id)
            return

        # --- Stream TTS as background task ---
        tts_task = asyncio.create_task(self._stream_tts_to_ws(websocket, reply_text, session, seq))
        session.active_tts_task = tts_task

    # ------------------------------------------------------------------
    # TTS streaming
    # ------------------------------------------------------------------

    async def _stream_tts_to_ws(
        self,
        websocket: WebSocket,
        text: str,
        session: VoiceSession,
        seq: list[int],
    ) -> None:
        """Stream TTS audio to the WebSocket client as a single binary frame.

        Uses the buffered pattern (Research Pitfall 7): all edge-tts audio
        chunks are collected before sending. This ensures the client receives
        a complete, seekable audio blob rather than a stream of tiny chunks.

        The cancel_event is checked after each chunk — if set (barge-in or
        voice.stop), the loop exits early and nothing is sent.
        """
        session.is_ai_speaking = True
        session.cancel_event.clear()  # fresh start for this utterance

        # Resolve TTS voice from config (falls back to a sensible default)
        voice: str = "en-US-AriaNeural"
        if self._config is not None:
            tts_cfg = (
                self._config.get("tts", {})
                if isinstance(self._config, dict)
                else getattr(self._config, "tts", {}) or {}
            )
            voice = tts_cfg.get("voice", voice) if isinstance(tts_cfg, dict) else voice

        try:
            import edge_tts  # lazy import — optional dependency

            communicate = edge_tts.Communicate(text, voice)
            full_audio = bytearray()

            async for chunk in communicate.stream():
                if session.cancel_event.is_set():
                    logger.info(
                        "WS %s: TTS cancelled mid-stream after %d bytes",
                        session.conn_id,
                        len(full_audio),
                    )
                    return  # Do NOT send partial audio

                if chunk.get("type") == "audio":
                    full_audio.extend(chunk["data"])

            # Only send if not cancelled and we have audio
            if not session.cancel_event.is_set() and full_audio:
                await websocket.send_bytes(bytes(full_audio))
                seq[0] += 1
                await websocket.send_json(make_event("voice.tts_done", {}, seq[0]))
                logger.info(
                    "WS %s: TTS done — sent %d audio bytes", session.conn_id, len(full_audio)
                )

        except asyncio.CancelledError:
            logger.info("WS %s: TTS task cancelled (asyncio)", session.conn_id)
            raise  # Re-raise so asyncio can clean up the task properly
        except ImportError:
            logger.error(
                "WS %s: edge_tts not installed — install with: pip install edge-tts",
                session.conn_id,
            )
        except Exception as exc:
            logger.error("WS %s: TTS stream error: %s", session.conn_id, exc)
        finally:
            session.is_ai_speaking = False
            session.active_tts_task = None

    # ------------------------------------------------------------------
    # Method dispatch (standard JSON RPC — voice.* never reaches here)
    # ------------------------------------------------------------------

    async def _dispatch(self, frame) -> dict:
        """Route a RequestFrame to the appropriate handler."""
        method = frame.method
        request_id = frame.id
        params = frame.params

        handlers = {
            "chat.send": self._handle_chat_send,
            "channels.status": self._handle_channels_status,
            "models.list": self._handle_models_list,
            "sessions.list": self._handle_sessions_list,
            "sessions.reset": self._handle_sessions_reset,
        }

        handler = handlers.get(method)
        if handler is None:
            return make_response(
                request_id,
                ok=False,
                error=make_error(INVALID_REQUEST, f"Unknown method: {method}"),
            )

        try:
            result = await handler(params)
            return make_response(request_id, ok=True, payload=result)
        except Exception as exc:
            logger.exception("WS dispatch error for method %s", method)
            return make_response(
                request_id,
                ok=False,
                error=make_error(UNAVAILABLE, str(exc), retryable=True),
            )

    # ------------------------------------------------------------------
    # Method handlers
    # ------------------------------------------------------------------

    async def _handle_chat_send(self, params: dict) -> dict:
        """Enqueue a chat message via the existing TaskQueue.

        Expected params:
            chat_id (str): Target chat identifier.
            text (str): Message body.
            sender_name (str, optional): Display name.
            channel_id (str, optional): Channel identifier.
        """
        if self._task_queue is None:
            raise RuntimeError("TaskQueue not available")

        from .queue import MessageTask  # local import to avoid circular deps

        chat_id = params.get("chat_id", "")
        text = params.get("text", "")
        if not chat_id or not text:
            raise ValueError("chat_id and text are required")

        task = MessageTask(
            task_id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_message=text,
            sender_name=params.get("sender_name", ""),
            channel_id=params.get("channel_id", "websocket"),
            session_key=params.get("session_key", ""),
        )
        await self._task_queue.enqueue(task)

        return {"task_id": task.task_id, "status": "queued"}

    async def _handle_channels_status(self, params: dict) -> dict:
        """Return status of all registered channel adapters."""
        if self._channel_registry is None:
            return {"channels": []}

        channel_ids = self._channel_registry.list_ids()
        channels = []
        for cid in channel_ids:
            channels.append({"id": cid, "status": "registered"})

        return {"channels": channels}

    async def _handle_models_list(self, params: dict) -> dict:
        """Return models from the catalog file or config model_mappings."""
        # Try reading from the models_catalog.json file first
        if self._models_catalog_path and self._models_catalog_path.exists():
            try:
                content = self._models_catalog_path.read_text(encoding="utf-8")
                catalog = json.loads(content)
                return {"catalog": catalog}
            except (OSError, json.JSONDecodeError):
                logger.debug("Failed to read models_catalog.json")

        # Fall back to config model_mappings
        if self._config is not None and hasattr(self._config, "model_mappings"):
            mappings = self._config.model_mappings or {}
            models = []
            for role, mapping in mappings.items():
                if isinstance(mapping, dict):
                    models.append(
                        {
                            "role": role,
                            "model": mapping.get("model", ""),
                            "fallback": mapping.get("fallback"),
                        }
                    )
            return {"models": models}

        return {"models": []}

    async def _handle_sessions_list(self, params: dict) -> dict:
        """Return queue stats as a minimal session list (placeholder)."""
        if self._task_queue is not None:
            return {"sessions": [], "queue": self._task_queue.get_stats()}
        return {"sessions": []}

    async def _handle_sessions_reset(self, params: dict) -> dict:
        """Reset session state (placeholder -- session management is future work)."""
        return {"ok": True}
