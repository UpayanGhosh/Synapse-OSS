"""
Load test fixtures.
====================

Shared fixtures for the workspace/tests/load/ suite.

Marker registration
-------------------
The `load` and `slow` markers are registered in workspace/tests/pytest.ini under
the `markers` section. Both are required by pytestmark in this suite:

  - load: enables filtering with `pytest -m load` to run only burst/throughput tests
  - slow: opt-in via `--run-slow` (see workspace/tests/conftest.py:pytest_collection_modifyitems);
          load tests are auto-skipped without that flag so a normal `pytest` run stays fast.

Design note
-----------
Tests in this suite construct the FloodGate -> TaskQueue -> worker primitives
directly, mirroring the adapter pattern in test_channel_pipeline.py. We do NOT
boot the FastAPI gateway -- the goal is to exercise the queueing primitives
that back the README's "zero dropped messages under load" claim.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue


class BurstHarness:
    """
    Self-contained harness wiring FloodGate -> TaskQueue -> worker pool.

    Mirrors the production adapter (`_make_flood_enqueue` in api_gateway.py) but
    instantiates locally-owned primitives so the test never touches singletons.

    Design contract:
      - send(message_id, chat_id, text): drop-in for the inbound webhook path.
        Each call is independently dedup-checked and pushed through the FloodGate.
      - processed_ids: list of message_ids that emerged from the worker pool.
        Mutations are serialized by an asyncio.Lock so the test can inspect it
        deterministically after wait_for_drain().
      - wait_for_drain(timeout): blocks until the queue is empty AND no flush
        timer is pending in the FloodGate. Returns True iff drained within the
        timeout window.

    Each unique chat_id flushes its own FloodGate buffer, so to verify
    one-message-in / one-message-out accounting we use a unique chat_id per
    send. (Multiple messages on the same chat_id would be coalesced into a
    single batched task, which is correct production behavior but defeats
    drop accounting.)
    """

    def __init__(
        self,
        *,
        max_queue_size: int = 1000,
        batch_window_seconds: float = 0.01,
        dedup_window_seconds: int = 300,
        num_workers: int = 4,
    ) -> None:
        self.queue = TaskQueue(max_size=max_queue_size, max_history=max_queue_size * 2)
        self.flood_gate = FloodGate(batch_window_seconds=batch_window_seconds)
        self.dedup = MessageDeduplicator(window_seconds=dedup_window_seconds)
        self._batch_window = batch_window_seconds
        self._num_workers = num_workers

        self._processed_lock = asyncio.Lock()
        self.processed_ids: list[str] = []
        self.duplicate_drops: int = 0
        self.full_queue_drops: int = 0

        self._workers: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

        self.flood_gate.set_callback(self._on_batch_ready)

    async def _on_batch_ready(
        self, chat_id: str, combined_message: str, metadata: dict[str, Any]
    ) -> None:
        """Adapter mirroring _make_flood_enqueue() in api_gateway.py."""
        task = MessageTask(
            task_id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_message=combined_message,
            message_id=metadata.get("message_id", ""),
            sender_name=metadata.get("sender_name", "load_test"),
            channel_id=metadata.get("channel_id", "stub"),
        )
        try:
            await self.queue.enqueue(task)
        except asyncio.QueueFull:
            # Production wraps enqueue similarly — we count drops rather than swallow silently
            self.full_queue_drops += 1

    async def _worker(self, worker_id: int) -> None:
        """Drain tasks; record their message_id; mark complete on the queue."""
        while not self._stopping.is_set():
            try:
                # Short timeout so the worker can poll the stop flag on idle
                task = await asyncio.wait_for(self.queue.dequeue(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
            try:
                async with self._processed_lock:
                    self.processed_ids.append(task.message_id)
                self.queue.complete(task, result="ok")
            except Exception as exc:  # pragma: no cover — defensive
                self.queue.fail(task, error=str(exc))

    async def start(self) -> None:
        """Spawn the worker pool. Idempotent."""
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self._num_workers)
        ]

    async def stop(self) -> None:
        """Signal workers to exit and await their termination."""
        self._stopping.set()
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except (asyncio.CancelledError, Exception):
                pass
        self._workers = []

    async def send(self, message_id: str, chat_id: str, text: str = "burst") -> None:
        """
        Replicate the inbound webhook path: dedup -> flood.incoming.

        Each send uses a unique chat_id by default so the FloodGate produces a
        1:1 mapping from incoming message to MessageTask (no batch coalescing).
        """
        if self.dedup.is_duplicate(message_id):
            self.duplicate_drops += 1
            return
        await self.flood_gate.incoming(
            chat_id=chat_id,
            message=text,
            metadata={
                "message_id": message_id,
                "sender_name": "load_test",
                "channel_id": "stub",
            },
        )

    async def wait_for_drain(self, timeout: float = 60.0) -> bool:
        """
        Wait for: (a) the FloodGate to flush all buffered batches, and
        (b) the TaskQueue to drain to zero pending tasks.

        Polls every 25ms. Returns True iff fully drained before the timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            flood_buffers_empty = not self.flood_gate._buffers and not self.flood_gate._tasks
            queue_empty = self.queue.pending_count == 0
            if flood_buffers_empty and queue_empty:
                # Give workers one more tick to record the last completion.
                await asyncio.sleep(self._batch_window + 0.05)
                if (
                    not self.flood_gate._buffers
                    and not self.flood_gate._tasks
                    and self.queue.pending_count == 0
                ):
                    return True
            await asyncio.sleep(0.025)
        return False


@pytest.fixture
async def burst_harness():
    """
    Fully wired FloodGate + TaskQueue + worker pool harness.

    Yields a started BurstHarness; tears down workers on exit so background
    tasks don't leak between tests.
    """
    harness = BurstHarness(max_queue_size=1000, batch_window_seconds=0.01, num_workers=4)
    await harness.start()
    try:
        yield harness
    finally:
        await harness.stop()
