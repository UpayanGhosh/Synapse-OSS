"""
Cron Scheduler — top-of-hour deterministic stagger.

Uses SHA-256 of the job ID to distribute jobs evenly within a window,
preventing all jobs from firing at exactly :00.
"""

from __future__ import annotations

import hashlib


def compute_top_of_hour_stagger(job_id: str, max_stagger_ms: int = 30_000) -> int:
    """Return a deterministic stagger offset in [0, max_stagger_ms).

    The offset is derived from the SHA-256 hash of the job_id so it is
    stable across restarts but uniformly distributed across the window.
    """
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    # Use the first 8 bytes as an unsigned 64-bit integer
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value % max_stagger_ms
