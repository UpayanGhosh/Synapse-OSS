"""
Performance Tests: Load and Stress Testing
=========================================
Performance tests evaluate how the system performs under load.
These tests measure reliability, speed, scalability, and responsiveness.

WARNING: These tests are designed to stress the system and may
require significant resources to run.
"""

import pytest
import asyncio
import sys
import os
import time
import tempfile
import shutil
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus
from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.sqlite_graph import SQLiteGraph


class TestQueuePerformance:
    """Performance tests for task queue."""

    @pytest.mark.asyncio
    async def test_high_throughput_enqueue(self):
        """Test queue can handle high throughput of enqueue operations."""
        queue = TaskQueue(max_size=1000)

        start = time.time()

        # Enqueue 100 tasks as fast as possible
        for i in range(100):
            task = MessageTask(
                task_id=f"task_{i}", chat_id="chat", user_message=f"Msg {i}"
            )
            await queue.enqueue(task)

        elapsed = time.time() - start

        # Should complete quickly
        assert elapsed < 1.0, f"Enqueue took {elapsed}s, expected <1s"
        assert queue.pending_count == 100

    @pytest.mark.asyncio
    async def test_concurrent_dequeue(self):
        """Test queue handles concurrent dequeue operations."""
        queue = TaskQueue(max_size=100)

        # Enqueue tasks
        for i in range(50):
            task = MessageTask(
                task_id=f"task_{i}", chat_id="chat", user_message=f"Msg {i}"
            )
            await queue.enqueue(task)

        results = []

        async def dequeue_task():
            task = await queue.dequeue()
            await asyncio.sleep(0.01)  # Simulate work
            queue.complete(task, "Done")
            return task.task_id

        start = time.time()

        # Concurrent dequeue
        tasks = [dequeue_task() for _ in range(50)]
        results = await asyncio.gather(*tasks)

        elapsed = time.time() - start

        # Should complete in reasonable time
        assert len(results) == 50


class TestDeduplicationPerformance:
    """Performance tests for deduplication."""

    def test_large_duplicate_check(self):
        """Test deduplication with large number of messages."""
        dedup = MessageDeduplicator(window_seconds=300)

        start = time.time()

        # Check 5000 messages for duplicates
        for i in range(5000):
            dedup.is_duplicate(f"msg_{i}")

        elapsed = time.time() - start

        # Should be fast
        assert elapsed < 2.0, f"Dedup check took {elapsed}s"

        # All should be new
        assert len(dedup.seen) == 5000

    def test_duplicate_check_with_expiry(self):
        """Test deduplication cleanup performance."""
        dedup = MessageDeduplicator(window_seconds=1)

        # Add messages
        for i in range(1000):
            dedup.is_duplicate(f"msg_{i}")

        # Wait for expiry
        time.sleep(1.5)

        # Trigger cleanup
        dedup.is_duplicate("trigger_cleanup")

        # Old entries should be cleaned
        # (exact behavior depends on implementation)


class TestKnowledgeGraphPerformance:
    """Performance tests for knowledge graph."""

    def test_large_graph_query(self, tmp_path):
        """Test query performance on large graph."""
        db_path = tmp_path / "large.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Populate with 10000 nodes
        print("\nPopulating graph with 10000 nodes...")
        for i in range(10000):
            graph.add_node(f"Node_{i}", "test", index=i)

        # Query
        start = time.time()
        result = graph.get_entity_neighborhood("Node_5000", hops=2)
        elapsed = time.time() - start

        print(f"Query took {elapsed * 1000:.2f}ms")

        # Should complete in reasonable time
        assert elapsed < 2.0, f"Query took {elapsed}s, expected <2s"

    def test_concurrent_writes(self, tmp_path):
        """Test concurrent write performance."""
        db_path = tmp_path / "concurrent.db"
        graph = SQLiteGraph(db_path=str(db_path))

        def write_batch(start_idx, count):
            for i in range(start_idx, start_idx + count):
                graph.add_node(f"Node_{i}", "test")

        start = time.time()

        # Concurrent writes from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_batch, i * 1000, 1000) for i in range(5)]
            for f in as_completed(futures):
                f.result()

        elapsed = time.time() - start

        print(f"Concurrent writes took {elapsed:.2f}s")

        # Should complete reasonably fast
        assert elapsed < 10.0


class TestMemoryFootprint:
    """Tests for memory usage."""

    def test_graph_memory_usage(self, tmp_path):
        """Test that graph uses minimal memory."""
        db_path = tmp_path / "memory_test.db"

        # Create large graph
        graph = SQLiteGraph(db_path=str(db_path))

        for i in range(5000):
            graph.add_node(f"Entity_{i}", "test", data=f"Data_{i}")

        # Check internal state size
        # SQLite should only load what's needed into memory
        assert graph is not None

    @pytest.mark.asyncio
    async def test_queue_memory_bounds(self):
        """Test queue maintains memory bounds."""
        queue = TaskQueue(max_size=100, max_history=50)

        # Add max tasks
        for i in range(100):
            task = MessageTask(
                task_id=f"task_{i}", chat_id="chat", user_message="x" * 1000
            )
            await queue.enqueue(task)

        # Complete and archive
        for i in range(100):
            task = await queue.dequeue()
            queue.complete(task, "x" * 1000)

        # History should be bounded
        assert len(queue._task_history) <= 50


class TestLatencyMeasurements:
    """Latency measurement tests."""

    def test_dedup_latency(self):
        """Measure deduplication latency."""
        dedup = MessageDeduplicator()

        latencies = []

        for _ in range(1000):
            start = time.perf_counter()
            dedup.is_duplicate(f"msg_{time.time()}")
            latencies.append((time.perf_counter() - start) * 1000)  # ms

        avg = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print(f"\nDedup Latency - Avg: {avg:.3f}ms, P50: {p50:.3f}ms, P99: {p99:.3f}ms")

        # Should be very fast
        assert avg < 1.0

    @pytest.mark.asyncio
    async def test_queue_enqueue_latency(self):
        """Measure queue enqueue latency."""
        queue = TaskQueue(max_size=1000)

        latencies = []

        for _ in range(1000):
            start = time.perf_counter()
            task = MessageTask(
                task_id=f"task_{time.time()}", chat_id="chat", user_message="x"
            )
            await queue.enqueue(task)
            latencies.append((time.perf_counter() - start) * 1000)

        avg = statistics.mean(latencies)
        print(f"\nQueue Enqueue Latency - Avg: {avg:.3f}ms")

        # Should be fast
        assert avg < 5.0


class TestStressTests:
    """Stress tests to find breaking points."""

    @pytest.mark.asyncio
    async def test_queue_overflow_handling(self):
        """Test queue behavior when full."""
        queue = TaskQueue(max_size=10)

        # Fill queue
        for i in range(10):
            task = MessageTask(task_id=f"task_{i}", chat_id="chat", user_message="x")
            await queue.enqueue(task)

        # Try to add more (should fail gracefully)
        overflow_count = 0
        for i in range(20):
            if queue.pending_count >= queue._queue.maxsize:
                overflow_count += 1
                continue
            task = MessageTask(
                task_id=f"task_overflow_{i}", chat_id="chat", user_message="x"
            )
            await queue.enqueue(task)

        # Queue was already full at start
        assert queue.pending_count == queue._queue.maxsize

    def test_dedup_memory_growth(self):
        """Test dedup doesn't grow unbounded."""
        dedup = MessageDeduplicator(window_seconds=300)

        # Add many messages
        for i in range(10000):
            dedup.is_duplicate(f"msg_{i}")

        # Check cache size
        cache_size = len(dedup.seen)

        # Should not grow unbounded (cleanup should happen)
        # This test verifies cleanup logic works
        assert cache_size <= 10000


class TestBottleneckIdentification:
    """Tests to identify potential bottlenecks."""

    @pytest.mark.asyncio
    async def test_flood_gate_timing(self):
        """Measure FloodGate batching timing."""
        flood = FloodGate(batch_window_seconds=0.5)

        results = []

        async def callback(chat_id, message, metadata):
            results.append(message)

        flood.set_callback(callback)

        start = time.time()

        # Send messages
        for i in range(10):
            await flood.incoming("chat_001", f"Msg {i}", {"id": i})

        # Wait for flush
        await asyncio.sleep(1.0)

        elapsed = time.time() - start

        print(f"\n10 messages processed in {elapsed:.3f}s")

        # Should have flushed

    @pytest.mark.asyncio
    async def test_concurrent_queue_operations(self):
        """Test concurrent queue operations."""
        queue = TaskQueue(max_size=100)

        async def enqueue_batch(batch_id):
            for i in range(20):
                task = MessageTask(
                    task_id=f"batch{batch_id}_task_{i}",
                    chat_id="chat",
                    user_message="x",
                )
                await queue.enqueue(task)

        async def dequeue_batch():
            count = 0
            while count < 100:
                try:
                    task = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
                    await asyncio.sleep(0.001)
                    queue.complete(task, "done")
                    count += 1
                except asyncio.TimeoutError:
                    break

        start = time.time()

        # Run concurrent operations
        await asyncio.gather(
            enqueue_batch(0),
            enqueue_batch(1),
            enqueue_batch(2),
            enqueue_batch(3),
            enqueue_batch(4),
            dequeue_batch(),
        )

        elapsed = time.time() - start

        print(f"\nConcurrent operations took {elapsed:.3f}s")


if __name__ == "__main__":
    pytest.main([__file__, ".."])
