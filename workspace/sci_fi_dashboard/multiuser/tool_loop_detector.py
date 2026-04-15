"""tool_loop_detector.py — Detect and break runaway tool-calling loops.

Monitors tool invocations within a sliding window and raises at three
severity levels:

    OK       — normal usage
    WARNING  — 10 identical calls or ping-pong pattern detected; injects a
               diagnostic message into the conversation
    CRITICAL — 20 identical calls; caller should abort the tool loop
    (global)  — 30 total tool calls within the window triggers ToolLoopError

Detection strategies:
    1. **generic_repeat** — same (tool_name, args_signature) appears N times
    2. **ping_pong** — alternating A-B-A-B pattern (4+ consecutive alternations)
    3. **global_circuit_breaker** — total tool calls within window exceeds 30
"""

from __future__ import annotations

import hashlib
import json
import logging
from enum import StrEnum

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WARNING_THRESHOLD: int = 10
CRITICAL_THRESHOLD: int = 20
GLOBAL_CIRCUIT_BREAKER: int = 30

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ToolLoopLevel(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class ToolLoopError(Exception):
    """Raised when the global circuit breaker trips (30 total calls in window)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signature(tool_name: str, tool_args: dict) -> str:
    """Return a SHA-256 hex digest of (tool_name, sorted JSON args)."""
    canonical = json.dumps({"name": tool_name, "args": tool_args}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class ToolLoopDetector:
    """Sliding-window tool-loop detector.

    Args:
        window_size: Maximum number of recent invocations to track.  Older
                     entries are evicted FIFO when the window fills.
    """

    def __init__(self, window_size: int = 50) -> None:
        self._window_size = max(window_size, 1)
        # Each entry: (tool_name, args_signature)
        self._history: list[tuple[str, str]] = []
        self._last_level: ToolLoopLevel = ToolLoopLevel.OK

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, tool_name: str, tool_args: dict) -> ToolLoopLevel:
        """Record a tool invocation and return the current severity level.

        Raises:
            ToolLoopError: When the global circuit breaker threshold (30) is
                           reached within the current window.
        """
        sig = _signature(tool_name, tool_args)
        self._history.append((tool_name, sig))

        # Evict oldest entries beyond window size.
        if len(self._history) > self._window_size:
            self._history = self._history[-self._window_size :]

        # --- Global circuit breaker ---
        if len(self._history) >= GLOBAL_CIRCUIT_BREAKER:
            raise ToolLoopError(
                f"Global circuit breaker tripped: {len(self._history)} tool calls "
                f"within a window of {self._window_size}"
            )

        # --- Generic repeat detection ---
        sig_count = sum(1 for _, s in self._history if s == sig)
        if sig_count >= CRITICAL_THRESHOLD:
            self._last_level = ToolLoopLevel.CRITICAL
            logger.warning(
                "ToolLoopDetector: CRITICAL — %s called %d times (sig=%s…)",
                tool_name,
                sig_count,
                sig[:12],
            )
            return ToolLoopLevel.CRITICAL

        if sig_count >= WARNING_THRESHOLD:
            self._last_level = ToolLoopLevel.WARNING
            logger.info(
                "ToolLoopDetector: WARNING — %s called %d times (sig=%s…)",
                tool_name,
                sig_count,
                sig[:12],
            )
            return ToolLoopLevel.WARNING

        # --- Ping-pong detection (A-B-A-B pattern, 4+ alternations) ---
        if self._detect_ping_pong():
            self._last_level = ToolLoopLevel.WARNING
            logger.info("ToolLoopDetector: WARNING — ping-pong pattern detected")
            return ToolLoopLevel.WARNING

        self._last_level = ToolLoopLevel.OK
        return ToolLoopLevel.OK

    def get_injection_message(self) -> str | None:
        """Return a diagnostic message suitable for injecting into the conversation.

        Returns ``None`` unless the last ``record()`` call returned WARNING.
        """
        if self._last_level != ToolLoopLevel.WARNING:
            return None

        # Build a readable summary of the most-repeated signatures.
        from collections import Counter

        counts = Counter(name for name, _ in self._history)
        top = counts.most_common(3)
        parts = [f"{name} ({n}x)" for name, n in top]
        return (
            "[System] Potential tool loop detected. "
            f"Recent tool call distribution: {', '.join(parts)}. "
            "Consider whether the current approach is making progress or cycling."
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _detect_ping_pong(self) -> bool:
        """Return ``True`` if the tail of history shows an A-B-A-B pattern.

        Requires at least 4 entries forming alternating pairs.
        """
        if len(self._history) < 4:
            return False

        tail = self._history[-8:]  # check last 8 entries max
        if len(tail) < 4:
            return False

        # Check if the last 4+ entries alternate between exactly 2 signatures.
        sigs = [s for _, s in tail]
        if len(set(sigs[-4:])) != 2:
            return False

        # Verify strict alternation in the last 4 entries.
        for i in range(len(sigs) - 4, len(sigs) - 2):
            if sigs[i] != sigs[i + 2]:
                return False
            if sigs[i] == sigs[i + 1]:
                return False

        return True
