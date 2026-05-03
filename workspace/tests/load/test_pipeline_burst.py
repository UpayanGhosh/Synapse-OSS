"""
Load: burst send. Asserts that 500 concurrent messages are all processed
exactly once with no drops, no duplicates.

Backs the README claim: "zero dropped messages under load."

Design
------
- Constructs FloodGate + TaskQueue + 4-worker pool directly (no FastAPI app).
- Fans out 500 concurrent send() calls via asyncio.gather, each on a unique
  chat_id so the FloodGate produces a 1:1 task per send (no batch coalescing).
- Asserts: no missing message_ids, no duplicates, zero queue-full drops, zero
  dedup drops (all message_ids are unique).
- Bounded by a 60s drain timeout so a hang fails fast rather than hanging CI.
"""

from __future__ import annotations

import asyncio
import collections

import pytest

pytestmark = [pytest.mark.load, pytest.mark.slow]


@pytest.mark.asyncio
async def test_no_dropped_under_burst_500(burst_harness):
    """Fan out 500 concurrent sends; assert exactly-once processing with no drops."""
    sent_ids = [f"msg_{i:04d}" for i in range(500)]

    # Fan out concurrent sends through the gateway pipeline (unique chat_id per send
    # so the FloodGate yields one task per inbound message — required for drop accounting).
    await asyncio.gather(
        *(
            burst_harness.send(mid, chat_id=f"chat_{mid}", text=f"burst payload {mid}")
            for mid in sent_ids
        )
    )

    # Wait for queue to drain (with timeout)
    drained = await burst_harness.wait_for_drain(timeout=60)
    assert drained, (
        f"queue did not drain in 60s (pending={burst_harness.queue.pending_count}, "
        f"flood_buffers={len(burst_harness.flood_gate._buffers)}, "
        f"processed={len(burst_harness.processed_ids)})"
    )

    processed = burst_harness.processed_ids
    counts = collections.Counter(processed)
    missing = set(sent_ids) - set(counts)
    duplicated = [mid for mid, n in counts.items() if n > 1]

    # No drops at any layer
    assert burst_harness.duplicate_drops == 0, (
        f"unexpected dedup drops: {burst_harness.duplicate_drops} "
        "(all 500 message_ids are unique — none should be dedup-rejected)"
    )
    assert burst_harness.full_queue_drops == 0, (
        f"queue rejected {burst_harness.full_queue_drops} tasks under burst — "
        "max_queue_size is too small for the burst (or backpressure is broken)"
    )

    # Exactly-once delivery: every sent id appears exactly once on the processed side
    assert not missing, f"dropped: {sorted(missing)[:20]} (showing first 20 of {len(missing)})"
    assert not duplicated, f"duplicates: {duplicated[:20]} (showing first 20 of {len(duplicated)})"
    assert len(processed) == len(sent_ids), (
        f"processed count mismatch: sent={len(sent_ids)} processed={len(processed)}"
    )
