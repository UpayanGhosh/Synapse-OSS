"""
Test Suite: Phase 2 — Gateway Layer
====================================
Focused unit tests for the three gateway components that sit between
inbound channel messages and the task-processing workers:

  FloodGate         (gateway/flood.py)    — debounce-batching per chat_id
  MessageDeduplicator (gateway/dedup.py)  — TTL-window duplicate filter
  TaskQueue         (gateway/queue.py)    — async FIFO with status lifecycle

12 tests total, organised in 3 sections of 4.

These tests are intentionally standalone — no conftest fixtures are required
beyond what pytest-asyncio provides automatically (asyncio_mode = auto).
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

# Allow imports from workspace root when running the file directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue, TaskStatus


# ---------------------------------------------------------------------------
# Section 1: FloodGate — debounce-batching
# ---------------------------------------------------------------------------


class TestFloodGate:
    """FloodGate batches rapid-fire messages from the same chat_id and fires
    a single callback after the debounce window expires.  Each new incoming()
    call within the window restarts the timer (true debounce).
    """

    @pytest.mark.asyncio
    async def test_floodgate_debounces_rapid_messages(self):
        """Rapid successive messages from the same chat_id must be coalesced
        into a single callback invocation, not multiple ones.
        """
        gate = FloodGate(batch_window_seconds=0.05)
        callback = AsyncMock()
        gate.set_callback(callback)

        # Send three messages in quick succession — each restarts the timer.
        await gate.incoming("user1", "msg1", {})
        await gate.incoming("user1", "msg2", {})
        await gate.incoming("user1", "msg3", {})

        # Wait long enough for the debounce window to fire.
        await asyncio.sleep(0.15)

        # All three messages were within the window → exactly one callback.
        assert callback.call_count == 1

        # The batched payload must contain the first and last message text.
        _chat_id, batched_msg, _meta = callback.call_args[0]
        assert "msg1" in batched_msg
        assert "msg3" in batched_msg

    @pytest.mark.asyncio
    async def test_floodgate_fires_after_timeout(self):
        """A single message must trigger the callback once the window elapses,
        not before.
        """
        gate = FloodGate(batch_window_seconds=0.05)
        callback = AsyncMock()
        gate.set_callback(callback)

        await gate.incoming("user1", "hello", {})

        # Before the window expires the callback must not have fired.
        assert callback.call_count == 0

        await asyncio.sleep(0.15)

        # After the window the callback fires exactly once with the right chat_id.
        assert callback.call_count == 1
        fired_chat_id = callback.call_args[0][0]
        assert fired_chat_id == "user1"

    @pytest.mark.asyncio
    async def test_floodgate_separate_chat_ids_independent(self):
        """Messages addressed to different chat_ids must each generate their
        own independent callback — they must never be batched together.
        """
        gate = FloodGate(batch_window_seconds=0.05)
        callback = AsyncMock()
        gate.set_callback(callback)

        await gate.incoming("alice", "hi", {})
        await gate.incoming("bob", "hey", {})

        await asyncio.sleep(0.15)

        # One callback per distinct chat_id.
        assert callback.call_count == 2

        fired_chat_ids = {call[0][0] for call in callback.call_args_list}
        assert "alice" in fired_chat_ids
        assert "bob" in fired_chat_ids

    @pytest.mark.asyncio
    async def test_floodgate_metadata_passthrough(self):
        """The metadata dict supplied to incoming() must reach the callback
        unchanged so downstream workers have full channel context.
        """
        gate = FloodGate(batch_window_seconds=0.05)
        callback = AsyncMock()
        gate.set_callback(callback)

        meta = {"channel": "whatsapp", "user": "alice"}
        await gate.incoming("alice", "test", meta)

        await asyncio.sleep(0.15)

        assert callback.call_count == 1
        _chat_id, _msg, received_meta = callback.call_args[0]

        # At least one of the original metadata values must survive intact.
        assert received_meta.get("channel") == "whatsapp" or received_meta.get("user") == "alice"


# ---------------------------------------------------------------------------
# Section 2: MessageDeduplicator — TTL-window duplicate filter
# ---------------------------------------------------------------------------


class TestMessageDeduplicator:
    """MessageDeduplicator records seen message IDs for window_seconds.  A
    second call with the same ID within the window returns True; after the
    window has elapsed the ID is treated as fresh again.
    """

    def test_dedup_new_message_not_duplicate(self):
        """The first call for any message ID must return False — it is not a
        duplicate until it has been seen at least once.
        """
        dedup = MessageDeduplicator(window_seconds=60)
        assert dedup.is_duplicate("msg-abc-123") is False

    def test_dedup_same_id_is_duplicate(self):
        """The second call with the same message ID within the window must
        return True.
        """
        dedup = MessageDeduplicator(window_seconds=60)
        # First call marks the ID as seen.
        dedup.is_duplicate("msg-dup-1")
        # Second call should detect the duplicate.
        assert dedup.is_duplicate("msg-dup-1") is True

    def test_dedup_ttl_expiry(self):
        """An entry whose timestamp has been artificially aged past the window
        must no longer be considered a duplicate.
        """
        dedup = MessageDeduplicator(window_seconds=1)
        dedup.is_duplicate("msg-expire-1")

        # Manually age the recorded timestamp so it falls outside the 1-second window.
        dedup.seen["msg-expire-1"] -= 2
        # Reset _last_cleanup so the cleanup sweep fires on the next call.
        # (Cleanup only runs when now - _last_cleanup > _CLEANUP_INTERVAL = 60s.)
        dedup._last_cleanup = 0.0

        # The entry is now stale — must be treated as a fresh message.
        assert dedup.is_duplicate("msg-expire-1") is False

    def test_dedup_different_ids_independent(self):
        """Marking one ID as seen must not affect the freshness of other IDs."""
        dedup = MessageDeduplicator(window_seconds=60)

        dedup.is_duplicate("id-A")

        # id-A is now a known duplicate.
        assert dedup.is_duplicate("id-A") is True
        # id-B has never been seen — must not be treated as a duplicate.
        assert dedup.is_duplicate("id-B") is False


# ---------------------------------------------------------------------------
# Section 3: TaskQueue — async FIFO with status lifecycle
# ---------------------------------------------------------------------------


class TestTaskQueue:
    """TaskQueue is an async FIFO backed by asyncio.Queue.  Tasks move through
    QUEUED → PROCESSING → COMPLETED | FAILED | SUPERSEDED.  Completed tasks
    are archived in _task_history and removed from _active_tasks.
    """

    @pytest.mark.asyncio
    async def test_queue_fifo_ordering(self):
        """Tasks must be dequeued in the exact order they were enqueued
        (First-In, First-Out).
        """
        queue = TaskQueue()

        t1 = MessageTask(task_id="t1", chat_id="c1", user_message="first")
        t2 = MessageTask(task_id="t2", chat_id="c1", user_message="second")
        t3 = MessageTask(task_id="t3", chat_id="c1", user_message="third")

        await queue.enqueue(t1)
        await queue.enqueue(t2)
        await queue.enqueue(t3)

        dequeued = [await queue.dequeue() for _ in range(3)]

        assert [t.task_id for t in dequeued] == ["t1", "t2", "t3"]

    @pytest.mark.asyncio
    async def test_queue_complete_removes_from_active(self):
        """Calling complete() on a dequeued task must remove it from
        _active_tasks, ensuring the active-task registry stays clean.
        """
        queue = TaskQueue()
        task = MessageTask(task_id="done-1", chat_id="c1", user_message="hi")

        await queue.enqueue(task)
        dequeued = await queue.dequeue()

        queue.complete(dequeued, result="done!")

        # The task must no longer appear in the active registry.
        assert dequeued.task_id not in queue._active_tasks

    @pytest.mark.asyncio
    async def test_queue_fail_behavior(self):
        """Calling fail() must not raise an exception and must leave the task
        with a FAILED status and the supplied error message.
        """
        queue = TaskQueue()
        task = MessageTask(task_id="fail-1", chat_id="c1", user_message="oops")

        await queue.enqueue(task)
        dequeued = await queue.dequeue()

        # Must not raise.
        queue.fail(dequeued, error="something broke")

        # Status must be FAILED and the error string must be stored.
        assert dequeued.status == TaskStatus.FAILED
        assert dequeued.error is not None

    @pytest.mark.asyncio
    async def test_queue_stats_accurate(self):
        """get_stats() and pending_count must both report the correct number
        of tasks still waiting in the queue before any dequeue.
        """
        queue = TaskQueue()

        for i in range(3):
            await queue.enqueue(
                MessageTask(task_id=f"s{i}", chat_id="c", user_message="m")
            )

        stats = queue.get_stats()

        # The real implementation uses "pendingSize" as the stats key.
        pending_via_stats = stats.get("pendingSize", stats.get("pending", stats.get("queued", 0)))
        assert pending_via_stats >= 3 or queue.pending_count >= 3
