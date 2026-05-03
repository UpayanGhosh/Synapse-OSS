"""Load: FloodGate batching. Sustained 100 msg/s for 5s should produce coalesced
batches via the 3s window, with every message represented in some batch and
total count exactly = sent count.

FloodGate API notes (`workspace/sci_fi_dashboard/gateway/flood.py`):
  - Constructor: ``FloodGate(batch_window_seconds: float = 3.0)``
  - Callback wiring: ``flood.set_callback(async_callback)``
  - Ingestion: ``await flood.incoming(chat_id, message, metadata)``
  - Callback signature: ``async callback(chat_id, combined_message, metadata)``
    where ``combined_message`` is the per-chat buffer joined with ``"\\n\\n"``.
  - Debounce semantics: every new ``incoming()`` cancels and restarts the
    flush timer for that chat_id, so a sustained burst will coalesce into
    a single batch that flushes ``batch_window_seconds`` after the LAST
    message. The ``await asyncio.sleep(4.0)`` after the burst guarantees
    the final timer task has completed for a 3s window.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sci_fi_dashboard.gateway.flood import FloodGate  # noqa: E402

pytestmark = [pytest.mark.load, pytest.mark.slow]


@pytest.mark.asyncio
async def test_floodgate_coalesces_without_loss():
    """Sustained 100 msg/s for 5s must coalesce via 3s window with zero loss.

    Total messages sent = 500. After waiting one full window past the last
    send, every message id we sent must appear (exactly once) somewhere
    across the received batches; total reconstructed count must equal sent
    count.
    """
    received_batches: list[list[str]] = []

    async def on_batch(chat_id: str, combined_message: str, metadata: dict) -> None:
        # FloodGate joins per-chat buffered messages with "\n\n".
        # Split it back into the original message ids for accounting.
        received_batches.append(combined_message.split("\n\n"))

    flood = FloodGate(batch_window_seconds=3.0)
    flood.set_callback(on_batch)

    chat_id = "load_chat_floodgate"
    sent: list[str] = []

    # 500 messages at 100 msg/s = 5 seconds of sustained burst.
    for tick in range(500):
        msg_id = f"flood_{tick}"
        sent.append(msg_id)
        await flood.incoming(chat_id, msg_id, {"sender": "loadgen", "tick": tick})
        await asyncio.sleep(0.01)  # 100 msg/s pacing

    # FloodGate uses a debounce-style timer: each new message cancels and
    # restarts the flush task. So we must wait > batch_window_seconds AFTER
    # the last incoming() to allow the final scheduled flush to fire.
    await asyncio.sleep(4.0)

    flat = [m for batch in received_batches for m in batch]

    # Zero loss: every sent message id must appear somewhere in the batches.
    missing = set(sent) - set(flat)
    assert not missing, f"flood gate dropped {len(missing)} messages: {sorted(missing)[:5]}..."

    # Total accounting: reconstructed count must exactly equal what we sent
    # (no duplicates, no drops).
    assert len(flat) == len(sent), (
        f"count mismatch: sent={len(sent)} received={len(flat)} "
        f"(diff={len(flat) - len(sent)})"
    )

    # We must have observed at least one batch flush.
    assert len(received_batches) >= 1, "no batches flushed within the wait window"

    # Sanity: no individual batch can contain more messages than were sent.
    assert all(len(b) <= len(sent) for b in received_batches), (
        f"impossible batch size: max={max(len(b) for b in received_batches)} "
        f"sent={len(sent)}"
    )

    # Coalescing actually happened: with a 3s window and sustained sub-window
    # gaps, we should see far fewer batches than messages. Lower bound is 1
    # (full coalesce); upper bound for a working batcher is well below the
    # sent count — pick a generous ceiling that still proves coalescing.
    assert len(received_batches) < len(sent), (
        f"no coalescing observed: got {len(received_batches)} batches for "
        f"{len(sent)} messages (expected far fewer)"
    )
