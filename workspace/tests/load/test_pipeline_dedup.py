"""Load: dedup correctness under burst.

Sends 1000 messages where 50% are exact-id repeats; asserts every duplicate is
rejected, every unique is allowed. Exercises ``MessageDeduplicator.is_duplicate``
under concurrent ``asyncio.gather`` fan-out so we catch any TTL-window or
shared-state regression that lets a duplicate slip through (or a unique get
falsely rejected) when many checks race in the same event-loop tick.

PRODUCT_ISSUES.md issue 6.3 — load-time dedup test (slice 2 of 3).
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Mirror the sys.path convention used by workspace/tests/test_dedup.py so this
# file can be discovered from the workspace/ root regardless of how pytest is
# launched (load tests live one directory deeper than the unit tests).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sci_fi_dashboard.gateway.dedup import MessageDeduplicator  # noqa: E402

pytestmark = [pytest.mark.load, pytest.mark.slow]


# ---- Test parameters --------------------------------------------------------
# 500 unique IDs, duplicated once -> 1000 total checks, 500 expected accepts
# and 500 expected rejects.
_UNIQUE_COUNT: int = 500

# Window comfortably larger than the test runtime so periodic cleanup
# (60s sweep cadence inside MessageDeduplicator) can never evict an
# in-flight ID and pollute the accept/reject assertion.
_TTL_SECONDS: int = 600


@pytest.mark.asyncio
async def test_dedup_under_burst() -> None:
    """1000-call burst: 500 unique + 500 duplicates, fully concurrent.

    Asserts:
      * exactly 500 calls return "accepted" (first-sighting)
      * exactly 500 calls return "rejected" (duplicate hit)
      * the accepted set equals the original unique-id set
      * the dedup's internal hits/misses counters match
    """

    dedup = MessageDeduplicator(window_seconds=_TTL_SECONDS)

    async def check_and_record(message_id: str) -> bool:
        """Return True iff the message was accepted (first sighting).

        ``MessageDeduplicator.is_duplicate`` is synchronous; wrapping it in an
        ``async def`` lets ``asyncio.gather`` fan out the calls so the test
        actually exercises concurrent scheduling rather than a sequential
        for-loop dressed up as async.
        """
        # Yield to the event loop before each check so gather() actually
        # interleaves the coroutines instead of running them top-to-bottom.
        await asyncio.sleep(0)
        is_dup = dedup.is_duplicate(message_id)
        return not is_dup  # accepted == not-a-duplicate

    # Build 500 unique msg_ids, then duplicate the list -> 1000 calls total.
    unique_ids = [f"dup_msg_{i}" for i in range(_UNIQUE_COUNT)]
    burst = unique_ids + unique_ids
    assert len(burst) == 2 * _UNIQUE_COUNT

    # Concurrent fan-out — order of resolution is non-deterministic which is
    # exactly what we want to stress.
    results = await asyncio.gather(*(check_and_record(mid) for mid in burst))

    accepted = [mid for mid, ok in zip(burst, results) if ok is True]
    rejected = [mid for mid, ok in zip(burst, results) if ok is False]

    # Exactly half accepted, half rejected.
    assert len(accepted) == _UNIQUE_COUNT, (
        f"expected {_UNIQUE_COUNT} accepts under burst, got {len(accepted)}"
    )
    assert len(rejected) == _UNIQUE_COUNT, (
        f"expected {_UNIQUE_COUNT} rejects under burst, got {len(rejected)}"
    )

    # Every unique id must appear exactly once in the accepted set — no id
    # was double-counted as "first-sighting", no id was lost.
    assert set(accepted) == set(unique_ids), (
        "accepted set diverged from the unique-id set: "
        f"missing={set(unique_ids) - set(accepted)} "
        f"extra={set(accepted) - set(unique_ids)}"
    )
    assert len(set(accepted)) == _UNIQUE_COUNT, (
        "duplicate id slipped into the accepted set"
    )

    # Internal counters should mirror the external observation.
    assert dedup.misses == _UNIQUE_COUNT, (
        f"expected misses={_UNIQUE_COUNT}, got {dedup.misses}"
    )
    assert dedup.hits == _UNIQUE_COUNT, (
        f"expected hits={_UNIQUE_COUNT}, got {dedup.hits}"
    )
    assert dedup.hit_rate() == pytest.approx(0.5)
