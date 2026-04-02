"""
Tests for network error classification (Phase 5).

Verifies that exceptions are correctly classified as pre-connect (safe to retry
send), recoverable for polling, or generic (not retryable).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.channels.network_errors import (
    is_recoverable_poll_error,
    is_safe_to_retry_send,
    _classify_exception,
)


# ---------------------------------------------------------------------------
# is_safe_to_retry_send — only pre-connect errors
# ---------------------------------------------------------------------------


class TestSafeToRetrySend:
    """Pre-connect errors are safe to retry because the message was never sent."""

    def test_connection_refused_is_safe(self):
        """ConnectionRefusedError is a pre-connect failure — safe to retry."""
        exc = ConnectionRefusedError("Connection refused")
        assert is_safe_to_retry_send(exc) is True

    def test_connection_reset_is_not_safe(self):
        """ConnectionResetError means data may have been sent — NOT safe to retry."""
        exc = ConnectionResetError("Connection reset by peer")
        assert is_safe_to_retry_send(exc) is False

    def test_timeout_is_not_safe(self):
        """TimeoutError could occur mid-send — NOT safe to retry."""
        exc = TimeoutError("timed out")
        assert is_safe_to_retry_send(exc) is False

    def test_generic_exception_is_not_safe(self):
        """A generic Exception is never safe to retry."""
        exc = Exception("something went wrong")
        assert is_safe_to_retry_send(exc) is False

    def test_oserror_with_econnrefused_string(self):
        """OSError whose string mentions ECONNREFUSED should be safe."""
        exc = OSError("ECONNREFUSED: connection refused")
        assert is_safe_to_retry_send(exc) is True

    def test_oserror_with_enetunreach_string(self):
        """OSError whose string mentions ENETUNREACH should be safe."""
        exc = OSError("ENETUNREACH: network unreachable")
        assert is_safe_to_retry_send(exc) is True


# ---------------------------------------------------------------------------
# is_recoverable_poll_error — broader set
# ---------------------------------------------------------------------------


class TestRecoverablePollError:
    """Polling is idempotent, so a broader set of errors can be retried."""

    def test_connection_refused_recoverable(self):
        """ConnectionRefusedError is recoverable for polling."""
        exc = ConnectionRefusedError("Connection refused")
        assert is_recoverable_poll_error(exc) is True

    def test_connection_reset_recoverable(self):
        """ConnectionResetError is recoverable for polling (not for send)."""
        exc = ConnectionResetError("Connection reset")
        assert is_recoverable_poll_error(exc) is True

    def test_timeout_recoverable(self):
        """TimeoutError is recoverable for polling."""
        exc = TimeoutError("timed out")
        assert is_recoverable_poll_error(exc) is True

    def test_generic_exception_not_recoverable(self):
        """A generic Exception is NOT recoverable."""
        exc = Exception("fatal error")
        assert is_recoverable_poll_error(exc) is False

    def test_value_error_not_recoverable(self):
        """ValueError is not a network error — not recoverable."""
        exc = ValueError("bad value")
        assert is_recoverable_poll_error(exc) is False

    def test_oserror_with_etimedout_string(self):
        """OSError with ETIMEDOUT in the message is recoverable."""
        exc = OSError("ETIMEDOUT: connection timed out")
        assert is_recoverable_poll_error(exc) is True


# ---------------------------------------------------------------------------
# Nested exception classification
# ---------------------------------------------------------------------------


class TestNestedExceptionClassification:
    """_classify_exception should walk __cause__ and __context__ chains."""

    def test_nested_cause_connection_refused(self):
        """Exception wrapping a ConnectionRefusedError should classify correctly."""
        inner = ConnectionRefusedError("inner")
        outer = RuntimeError("wrapper")
        outer.__cause__ = inner
        assert _classify_exception(outer) == "ConnectionRefusedError"

    def test_nested_context_connection_reset(self):
        """Exception with __context__ (implicit chaining) should also work."""
        inner = ConnectionResetError("inner")
        outer = RuntimeError("wrapper")
        outer.__context__ = inner
        assert _classify_exception(outer) == "ConnectionResetError"

    def test_no_nesting_returns_empty(self):
        """A plain Exception with no chaining returns empty string."""
        exc = Exception("plain")
        assert _classify_exception(exc) == ""

    def test_gaierror_classified(self):
        """socket.gaierror is a subclass of OSError — should match by string."""
        import socket
        exc = socket.gaierror("Name or service not known")
        assert _classify_exception(exc) == "gaierror"

    def test_econnrefused_in_errno_attr(self):
        """OSError with string 'ECONNREFUSED' in message should classify."""
        exc = OSError("ECONNREFUSED")
        result = _classify_exception(exc)
        assert result == "ECONNREFUSED"
