"""Phase 16 test fixture: cycling /health response mock for BridgeHealthPoller tests.

Usage:
    from tests.fixtures.bridge_health_transport import make_mock_transport, SUCCESS_HEALTH_JSON
    transport = make_mock_transport([
        SUCCESS_HEALTH_JSON,
        {"status_code": 500, "body": "Internal Error"},
        "timeout",
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        r = await client.get("http://127.0.0.1:5010/health")
"""

from __future__ import annotations

import json
from typing import Any

import httpx

SUCCESS_HEALTH_JSON: dict[str, Any] = {
    "status": "ok",
    "connectionState": "connected",
    "pid": 12345,
    "connectedSince": "2026-04-23T09:00:00.000Z",
    "authTimestamp": "2026-03-15T18:20:33.000Z",
    "uptimeSeconds": 3600,
    "restartCount": 0,
    "lastDisconnectReason": None,
    "last_inbound_at": "2026-04-23T09:05:12.000Z",
    "last_outbound_at": "2026-04-23T09:05:15.000Z",
    "uptime_ms": 3600000,
    "bridge_version": "1.0.0",
}

AUTH_EXPIRED_RESPONSE: dict[str, Any] = {"status_code": 401, "body": '{"error":"auth_expired"}'}
SERVER_ERROR_RESPONSE: dict[str, Any] = {"status_code": 500, "body": '{"error":"internal"}'}


def make_mock_transport(responses: list[Any]) -> httpx.MockTransport:
    """Return a cycling httpx.MockTransport.

    Each entry in `responses` is one of:
      - dict with "status_code" + "body" (raw response)
      - dict shaped like /health JSON (auto-wrapped to 200 + JSON body)
      - str "timeout" → raises httpx.ReadTimeout
      - str "connect_error" → raises httpx.ConnectError

    Responses cycle: after the last one, the next request uses responses[0] again.
    """
    idx = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        entry = responses[idx["i"] % len(responses)]
        idx["i"] += 1
        if isinstance(entry, str):
            if entry == "timeout":
                raise httpx.ReadTimeout("simulated timeout", request=request)
            if entry == "connect_error":
                raise httpx.ConnectError("simulated connect error", request=request)
            raise ValueError(f"unknown string response directive: {entry}")
        if isinstance(entry, dict) and "status_code" in entry:
            return httpx.Response(status_code=entry["status_code"], content=entry.get("body", ""))
        # Treat dict without status_code as a /health JSON payload
        return httpx.Response(status_code=200, content=json.dumps(entry).encode("utf-8"))

    return httpx.MockTransport(handler)
