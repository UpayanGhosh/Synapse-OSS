"""
Tests for SessionActorQueue — per-actor FIFO serialization.

Covers:
  - Two ops with same key run sequentially (ordering verified via asyncio.Event)
  - Two ops with different keys run concurrently
  - Timeout raises asyncio.TimeoutError
  - get_total_pending_count returns correct value
  - get_pending_count_for_session returns correct value per key
  - Lock cleanup after all ops complete (no memory leak)
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.gateway.session_actor import SessionActorQueue

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.asyncio

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="gateway/session_actor.py not yet available",
)


class TestSessionActorQueue:
    """SessionActorQueue unit tests."""

    @_skip
    async def test_same_key_sequential(self):
        """Two ops with the same actor_key execute sequentially, not overlapping."""
        q = SessionActorQueue()
        order: list[str] = []
        gate = asyncio.Event()

        async def op_a():
            order.append("a_start")
            gate.set()  # signal that op_a has started
            await asyncio.sleep(0.05)
            order.append("a_end")
            return "a"

        async def op_b():
            order.append("b_start")
            order.append("b_end")
            return "b"

        # Launch both concurrently with the SAME key
        task_a = asyncio.create_task(q.run("key1", op_a))
        await gate.wait()  # wait until op_a has started
        task_b = asyncio.create_task(q.run("key1", op_b))

        results = await asyncio.gather(task_a, task_b)
        assert results == ["a", "b"]

        # op_a must finish before op_b starts (sequential)
        assert order.index("a_end") < order.index("b_start")

    @_skip
    async def test_different_keys_concurrent(self):
        """Two ops with different keys run concurrently."""
        q = SessionActorQueue()
        started: list[str] = []
        both_started = asyncio.Event()

        async def op_x():
            started.append("x")
            if len(started) >= 2:
                both_started.set()
            # Wait a bit for both to start
            await asyncio.sleep(0.05)
            if len(started) >= 2:
                both_started.set()
            return "x"

        async def op_y():
            started.append("y")
            if len(started) >= 2:
                both_started.set()
            await asyncio.sleep(0.05)
            if len(started) >= 2:
                both_started.set()
            return "y"

        task_x = asyncio.create_task(q.run("key_x", op_x))
        task_y = asyncio.create_task(q.run("key_y", op_y))

        # Wait for both to signal they started (with timeout)
        try:
            await asyncio.wait_for(both_started.wait(), timeout=2.0)
            concurrent = True
        except TimeoutError:
            concurrent = False

        await asyncio.gather(task_x, task_y)
        assert concurrent, "Ops with different keys should run concurrently"

    @_skip
    async def test_timeout_raises(self):
        """Op that exceeds the timeout raises asyncio.TimeoutError."""
        q = SessionActorQueue(timeout=0.05)

        async def slow_op():
            await asyncio.sleep(10)  # will be cancelled by timeout
            return "never"

        with pytest.raises(asyncio.TimeoutError):
            await q.run("slow_key", slow_op)

    @_skip
    async def test_get_total_pending_count(self):
        """get_total_pending_count returns correct value while ops are pending."""
        q = SessionActorQueue()
        gate = asyncio.Event()

        async def blocking_op():
            await gate.wait()
            return "done"

        # Start 2 ops that will block
        t1 = asyncio.create_task(q.run("k1", blocking_op))
        t2 = asyncio.create_task(q.run("k2", blocking_op))
        await asyncio.sleep(0.01)  # let tasks start

        assert q.get_total_pending_count() == 2

        gate.set()
        await asyncio.gather(t1, t2)
        assert q.get_total_pending_count() == 0

    @_skip
    async def test_get_pending_count_for_session(self):
        """get_pending_count_for_session returns per-key count."""
        q = SessionActorQueue()
        gate = asyncio.Event()

        async def blocking_op():
            await gate.wait()
            return "done"

        t1 = asyncio.create_task(q.run("sess_a", blocking_op))
        t2 = asyncio.create_task(q.run("sess_a", blocking_op))
        t3 = asyncio.create_task(q.run("sess_b", blocking_op))
        await asyncio.sleep(0.01)

        assert q.get_pending_count_for_session("sess_a") == 2
        assert q.get_pending_count_for_session("sess_b") == 1
        assert q.get_pending_count_for_session("nonexistent") == 0

        gate.set()
        await asyncio.gather(t1, t2, t3)

    @_skip
    async def test_lock_cleanup_after_completion(self):
        """Locks are cleaned up after all ops for a key complete — no memory leak."""
        q = SessionActorQueue()

        async def fast_op():
            return 42

        await q.run("temp_key", fast_op)

        # After completion, the lock and pending entry should be removed
        assert "temp_key" not in q._locks
        assert "temp_key" not in q._pending
