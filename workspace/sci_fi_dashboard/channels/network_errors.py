"""
Network error classification for channel adapters.

Separates pre-connect errors (safe to retry for sends — message was never
transmitted) from broader recoverable errors (safe to retry for polling —
polling is idempotent).

Used by telegram.py send(), whatsapp.py send(), and polling_watchdog.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error name sets
# ---------------------------------------------------------------------------

PRE_CONNECT_ERRNO: frozenset[str] = frozenset(
    {
        "ECONNREFUSED",
        "ENOTFOUND",
        "EAI_AGAIN",
        "ENETUNREACH",
        "EHOSTUNREACH",
        "ConnectionRefusedError",
        "gaierror",
    }
)

RECOVERABLE_ERRNO: frozenset[str] = PRE_CONNECT_ERRNO | frozenset(
    {
        "ECONNRESET",
        "ETIMEDOUT",
        "ConnectionResetError",
        "TimeoutError",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_safe_to_retry_send(exc: Exception) -> bool:
    """Only pre-connect errors are safe for send retry.

    A pre-connect error means the TCP connection was never established, so the
    remote side never received any data.  It is safe to retry the send without
    risk of duplicate delivery.

    Args:
        exc: The exception raised during the send attempt.

    Returns:
        True if the error occurred before the connection was established.
    """
    tag = _classify_exception(exc)
    return tag in PRE_CONNECT_ERRNO


def is_recoverable_poll_error(exc: Exception) -> bool:
    """Broader set -- polling is idempotent.

    Polling (long-poll or getUpdates) can safely be retried for any transient
    network failure because no side-effects occur from re-fetching updates.

    Args:
        exc: The exception raised during polling.

    Returns:
        True if the error is transient and the poll can be retried.
    """
    tag = _classify_exception(exc)
    return tag in RECOVERABLE_ERRNO


def _classify_exception(exc: Exception) -> str:
    """Extract a classification string from an exception.

    Checks, in order:
      1. The exception type name (e.g. ``ConnectionRefusedError``).
      2. An ``errno`` attribute (POSIX style, e.g. ``ECONNREFUSED``).
      3. A string ``errno`` attribute (Node-style error codes forwarded via
         bridge HTTP responses).
      4. The nested ``__cause__`` chain (same checks, one level deep).

    Returns:
        A string matching one of the names in ``PRE_CONNECT_ERRNO`` or
        ``RECOVERABLE_ERRNO``, or an empty string if no match is found.
    """
    tag = _match_single(exc)
    if tag:
        return tag

    # Walk the __cause__ chain (one level)
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        tag = _match_single(cause)
        if tag:
            return tag

    # Also check __context__ (implicit chaining)
    ctx = getattr(exc, "__context__", None)
    if ctx is not None and ctx is not cause:
        tag = _match_single(ctx)
        if tag:
            return tag

    return ""


def _match_single(exc: BaseException) -> str:
    """Classify a single exception (no chaining)."""
    # 1. Type name
    type_name = type(exc).__name__
    all_known = PRE_CONNECT_ERRNO | RECOVERABLE_ERRNO
    if type_name in all_known:
        return type_name

    # 2. errno attribute (int or str)
    errno_val = getattr(exc, "errno", None)
    if errno_val is not None:
        errno_str = str(errno_val)
        if errno_str in all_known:
            return errno_str

    # 3. String representation (last resort — look for known tokens)
    exc_str = str(exc)
    for token in all_known:
        if token in exc_str:
            return token

    return ""
