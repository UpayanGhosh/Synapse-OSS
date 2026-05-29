"""
OutboundTracker — self-echo prevention ring buffer (Phase 14 ACL-01, ACL-02).

Port of OpenClaw's rememberRecentOutboundMessage pattern.

Design:
  - Raw outbound text NEVER stored — only sha256(text.encode())[:16] hex
  - Ring buffer: deque(maxlen=window_size) — O(1) append, automatic eviction
  - TTL: entries older than ttl_s are ignored by is_echo() (not actively evicted)
  - Thread model: asyncio single-threaded, no lock needed

Integration:
  - WhatsAppChannel.send() calls record(chat_id, text) after 200 OK
  - routes/whatsapp.py::unified_webhook calls is_echo(chat_id, text) before dedup
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass

from sci_fi_dashboard.observability import get_child_logger

_log = get_child_logger("gateway.echo")

_HASH_LEN = 16  # 64 bits — more than sufficient for a 20-entry window


@dataclass
class OutboundEntry:
    """One recorded outbound message fingerprint — never stores raw content."""

    chat_id: str
    text_hash: str  # sha256(text)[:16] hex
    timestamp: float  # time.monotonic() at record time


class OutboundTracker:
    """Ring buffer of last-N outbound fingerprints for self-echo detection.

    Args:
        window_size: Max entries to keep (default 20, matching OpenClaw).
        ttl_s:       Seconds after which a record is considered expired (default 60s).
    """

    def __init__(self, window_size: int = 20, ttl_s: float = 60.0) -> None:
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {window_size}")
        if ttl_s <= 0:
            raise ValueError(f"ttl_s must be > 0, got {ttl_s}")
        self._buf: deque[OutboundEntry] = deque(maxlen=window_size)
        self._ttl = ttl_s

    def __len__(self) -> int:
        return len(self._buf)

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_HASH_LEN]

    def record(self, chat_id: str, text: str) -> None:
        """Record an outbound fingerprint. Call ONLY after successful send (HTTP 200)."""
        self._buf.append(
            OutboundEntry(
                chat_id=chat_id,
                text_hash=self._fingerprint(text),
                timestamp=time.monotonic(),
            )
        )

    def is_echo(self, chat_id: str, text: str) -> bool:
        """Return True iff (chat_id, text) matches a recent outbound within TTL."""
        h = self._fingerprint(text)
        now = time.monotonic()
        return any(
            e.chat_id == chat_id and e.text_hash == h and (now - e.timestamp) < self._ttl
            for e in self._buf
        )
