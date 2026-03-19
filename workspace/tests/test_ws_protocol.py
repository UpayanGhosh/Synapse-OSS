"""
Tests for ws_protocol.py — WebSocket frame serialization/deserialization.

Covers:
  - parse_frame with valid req JSON returns RequestFrame
  - parse_frame with invalid JSON returns None
  - parse_frame with non-req type returns None
  - make_response creates correct dict structure
  - make_event creates correct dict structure
  - make_error creates correct dict structure
  - Error constants are defined
"""

import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.gateway.ws_protocol import (
        AGENT_TIMEOUT,
        INVALID_REQUEST,
        NOT_LINKED,
        NOT_PAIRED,
        UNAVAILABLE,
        RequestFrame,
        make_error,
        make_event,
        make_response,
        parse_frame,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="gateway/ws_protocol.py not yet available",
)


class TestParseFrame:
    """parse_frame() — JSON -> RequestFrame deserialization."""

    @_skip
    def test_valid_req_frame(self):
        """Valid req JSON returns a RequestFrame."""
        raw = '{"type": "req", "id": "r1", "method": "chat.send", "params": {"text": "hi"}}'
        frame = parse_frame(raw)
        assert isinstance(frame, RequestFrame)
        assert frame.type == "req"
        assert frame.id == "r1"
        assert frame.method == "chat.send"
        assert frame.params == {"text": "hi"}

    @_skip
    def test_valid_req_no_params(self):
        """Valid req JSON without params gets empty dict."""
        raw = '{"type": "req", "id": "r2", "method": "sessions.list"}'
        frame = parse_frame(raw)
        assert isinstance(frame, RequestFrame)
        assert frame.params == {}

    @_skip
    def test_invalid_json_returns_none(self):
        """Malformed JSON returns None."""
        assert parse_frame("not-json{{{") is None

    @_skip
    def test_non_req_type_returns_none(self):
        """A frame with type != 'req' returns None."""
        raw = '{"type": "connect", "id": "c1", "method": "init"}'
        assert parse_frame(raw) is None

    @_skip
    def test_event_type_returns_none(self):
        """An event frame returns None (only req frames are parsed)."""
        raw = '{"type": "event", "event": "tick", "seq": 1}'
        assert parse_frame(raw) is None

    @_skip
    def test_missing_id_returns_none(self):
        """A req frame without 'id' returns None."""
        raw = '{"type": "req", "method": "chat.send"}'
        assert parse_frame(raw) is None

    @_skip
    def test_missing_method_returns_none(self):
        """A req frame without 'method' returns None."""
        raw = '{"type": "req", "id": "r3"}'
        assert parse_frame(raw) is None

    @_skip
    def test_non_dict_json_returns_none(self):
        """A JSON array returns None."""
        assert parse_frame("[1, 2, 3]") is None

    @_skip
    def test_none_input_returns_none(self):
        """None input returns None."""
        assert parse_frame(None) is None


class TestMakeResponse:
    """make_response() — build response dict."""

    @_skip
    def test_success_response(self):
        resp = make_response("r1", ok=True, payload={"result": "ok"})
        assert resp["type"] == "res"
        assert resp["id"] == "r1"
        assert resp["ok"] is True
        assert resp["payload"] == {"result": "ok"}
        assert "error" not in resp

    @_skip
    def test_error_response(self):
        err = {"code": "FAIL", "message": "something broke"}
        resp = make_response("r2", ok=False, error=err)
        assert resp["type"] == "res"
        assert resp["id"] == "r2"
        assert resp["ok"] is False
        assert resp["error"] == err
        assert "payload" not in resp

    @_skip
    def test_bare_response_no_payload_no_error(self):
        resp = make_response("r3", ok=True)
        assert resp["type"] == "res"
        assert resp["ok"] is True
        assert "payload" not in resp
        assert "error" not in resp


class TestMakeEvent:
    """make_event() — build event dict."""

    @_skip
    def test_tick_event(self):
        evt = make_event("tick", payload={"ts": 1234.5}, seq=7)
        assert evt["type"] == "event"
        assert evt["event"] == "tick"
        assert evt["payload"] == {"ts": 1234.5}
        assert evt["seq"] == 7

    @_skip
    def test_event_no_payload(self):
        evt = make_event("presence", seq=0)
        assert evt["type"] == "event"
        assert evt["event"] == "presence"
        assert "payload" not in evt


class TestMakeError:
    """make_error() — build structured error dict."""

    @_skip
    def test_basic_error(self):
        err = make_error("NOT_LINKED", "Channel not linked")
        assert err["code"] == "NOT_LINKED"
        assert err["message"] == "Channel not linked"
        assert err["retryable"] is False
        assert "details" not in err

    @_skip
    def test_retryable_error_with_details(self):
        err = make_error(
            "AGENT_TIMEOUT",
            "LLM timed out",
            retryable=True,
            details={"timeout_ms": 30000},
        )
        assert err["retryable"] is True
        assert err["details"] == {"timeout_ms": 30000}


class TestErrorConstants:
    """Error code constants are defined and non-empty."""

    @_skip
    def test_constants_defined(self):
        assert NOT_LINKED == "NOT_LINKED"
        assert NOT_PAIRED == "NOT_PAIRED"
        assert AGENT_TIMEOUT == "AGENT_TIMEOUT"
        assert INVALID_REQUEST == "INVALID_REQUEST"
        assert UNAVAILABLE == "UNAVAILABLE"

    @_skip
    def test_constants_are_strings(self):
        for const in (NOT_LINKED, NOT_PAIRED, AGENT_TIMEOUT, INVALID_REQUEST, UNAVAILABLE):
            assert isinstance(const, str)
            assert len(const) > 0
