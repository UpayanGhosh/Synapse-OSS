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
  6. On disconnect the tick task is cancelled.

Each connection gets its own monotonic ``seq`` counter for events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from starlette.websockets import WebSocket, WebSocketDisconnect

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
]

SUPPORTED_EVENTS: list[str] = [
    "tick",
    "agent",
    "presence",
]

SERVER_VERSION: str = "1.0.0"
MAX_PAYLOAD_BYTES: int = 1_048_576  # 1 MiB


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
        self._models_catalog_path = (
            Path(models_catalog_path) if models_catalog_path else None
        )
        self._gateway_token: str | None = os.environ.get("SYNAPSE_GATEWAY_TOKEN")

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
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=CONNECT_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                logger.warning("WS %s: connect timeout after %.0fs", conn_id, CONNECT_TIMEOUT_S)
                await websocket.close(code=4000, reason="Connect timeout")
                return

            try:
                frame = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                await websocket.close(code=4000, reason="Invalid JSON")
                return

            if not isinstance(frame, dict) or frame.get("type") != "connect":
                await websocket.close(
                    code=4000, reason="First frame must be connect"
                )
                return

            # ---- 2. Validate auth token if SYNAPSE_GATEWAY_TOKEN set -
            if self._gateway_token:
                params = frame.get("params", {})
                auth = params.get("auth", {}) if isinstance(params, dict) else {}
                token = auth.get("token", "") if isinstance(auth, dict) else ""
                if token != self._gateway_token:
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
                        "tickIntervalMs": TICK_INTERVAL_S * 1000,
                    },
                },
            )
            await websocket.send_json(hello)
            logger.info("WS %s: connected", conn_id)

            # ---- 4. Start tick loop in background --------------------
            tick_task = asyncio.create_task(
                self._tick_loop(websocket, seq, conn_id)
            )

            # ---- 5. Handle subsequent req frames ---------------------
            try:
                while True:
                    raw = await websocket.receive_text()
                    req = parse_frame(raw)
                    if req is None:
                        # Silently ignore non-req frames (e.g. pong, unknown)
                        continue

                    seq[0] += 1
                    response = await self._dispatch(req)
                    await websocket.send_json(response)

            except WebSocketDisconnect:
                logger.info("WS %s: client disconnected", conn_id)
            finally:
                tick_task.cancel()
                try:
                    await tick_task
                except asyncio.CancelledError:
                    pass

        except Exception:
            logger.exception("WS %s: unhandled error", conn_id)
            # Attempt graceful close; ignore if already closed
            try:
                await websocket.close(code=4000, reason="Internal error")
            except Exception:
                pass

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
    # Method dispatch
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
                    models.append({
                        "role": role,
                        "model": mapping.get("model", ""),
                        "fallback": mapping.get("fallback"),
                    })
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
