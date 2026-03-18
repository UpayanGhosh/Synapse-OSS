"""
ws_protocol.py -- Typed frame protocol for the WebSocket control plane.

Defines Python dataclasses for the four wire frame types from the integration
blueprint (Section 11.1): RequestFrame, ResponseFrame, EventFrame, and
ConnectParams / HelloOk handshake shapes.

Also provides helper functions for parsing inbound frames and building
outbound response/event dicts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

NOT_LINKED: str = "NOT_LINKED"
NOT_PAIRED: str = "NOT_PAIRED"
AGENT_TIMEOUT: str = "AGENT_TIMEOUT"
INVALID_REQUEST: str = "INVALID_REQUEST"
UNAVAILABLE: str = "UNAVAILABLE"

# ---------------------------------------------------------------------------
# Wire frame dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RequestFrame:
    """Inbound request from a WebSocket client (type="req")."""

    type: str  # always "req"
    id: str
    method: str
    params: dict = field(default_factory=dict)


@dataclass
class ResponseFrame:
    """Outbound response to a client request (type="res")."""

    type: str  # always "res"
    id: str
    ok: bool
    payload: dict | None = None
    error: dict | None = None


@dataclass
class EventFrame:
    """Server-pushed event (type="event")."""

    type: str  # always "event"
    event: str
    payload: dict = field(default_factory=dict)
    seq: int = 0
    state_version: int | None = None


@dataclass
class ErrorShape:
    """Structured error object embedded in ResponseFrame.error."""

    code: str
    message: str
    details: dict | None = None
    retryable: bool = False
    retry_after_ms: int | None = None


@dataclass
class ConnectParams:
    """Parameters sent inside the initial 'connect' frame."""

    min_protocol: int = 1
    max_protocol: int = 1
    client: dict = field(default_factory=dict)
    auth: dict = field(default_factory=dict)


@dataclass
class HelloOk:
    """Payload of the server's response to a successful 'connect' handshake."""

    protocol: int = 1
    server: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    policy: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def parse_frame(raw: str) -> RequestFrame | None:
    """Parse a raw JSON string into a RequestFrame.

    Returns None if the JSON is malformed or the ``type`` field is not
    ``"req"``.  Connect frames (``type="connect"``) are handled separately
    in the server handshake logic and are intentionally *not* returned here.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.debug("parse_frame: invalid JSON")
        return None

    if not isinstance(data, dict):
        return None

    frame_type = data.get("type")
    if frame_type != "req":
        return None

    frame_id = data.get("id", "")
    method = data.get("method", "")
    if not frame_id or not method:
        return None

    return RequestFrame(
        type="req",
        id=str(frame_id),
        method=str(method),
        params=data.get("params", {}),
    )


def make_response(
    request_id: str,
    ok: bool,
    payload: dict | None = None,
    error: dict | None = None,
) -> dict:
    """Build a response dict ready for ``websocket.send_json()``."""
    resp: dict = {
        "type": "res",
        "id": request_id,
        "ok": ok,
    }
    if payload is not None:
        resp["payload"] = payload
    if error is not None:
        resp["error"] = error
    return resp


def make_event(
    event: str,
    payload: dict | None = None,
    seq: int = 0,
) -> dict:
    """Build an event dict ready for ``websocket.send_json()``."""
    evt: dict = {
        "type": "event",
        "event": event,
        "seq": seq,
    }
    if payload is not None:
        evt["payload"] = payload
    return evt


def make_error(
    code: str,
    message: str,
    retryable: bool = False,
    details: dict | None = None,
) -> dict:
    """Build a structured error dict for embedding in a ResponseFrame."""
    err: dict = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details is not None:
        err["details"] = details
    return err
