"""
Test Suite: Async Task Queue
===========================
Tests the TaskQueue class which manages message processing tasks
with async operations, status tracking, and history management.

Critical for ensuring no messages are lost and proper processing flow.
"""

import pytest
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus


class TestTaskQueue:
    """Test cases for async task queue operations."""

    @pytest.fixture
    def queue(self):
        """Create a fresh TaskQueue."""
        return TaskQueue(max_size=10, max_history=5)

    @pytest.mark.asyncio
    async def test_enqueue_adds_task(self, queue):
        """Enqueuing a task should add it to active tasks."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)

        assert queue.pending_count == 1
        assert "task_001" in queue._active_tasks

    @pytest.mark.asyncio
    async def test_dequeue_returns_queued_task(self, queue):
        """Dequeuing should return the oldest queued task."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        dequeued_task = await queue.dequeue()

        assert dequeued_task.task_id == "task_001"
        assert dequeued_task.status == TaskStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_complete_moves_to_history(self, queue):
        """Completing a task should move it to history."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        await queue.dequeue()
        queue.complete(task, "Response text")

        assert queue.pending_count == 0
        assert len(queue._task_history) == 1
        assert queue._task_history[0].status == TaskStatus.COMPLETED
        assert queue._task_history[0].response == "Response text"

    @pytest.mark.asyncio
    async def test_fail_moves_to_history(self, queue):
        """Failed tasks should be tracked in history."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        await queue.dequeue()
        queue.fail(task, "Error message")

        assert len(queue._task_history) == 1
        assert queue._task_history[0].status == TaskStatus.FAILED
        assert queue._task_history[0].error == "Error message"

    @pytest.mark.asyncio
    async def test_supersede_marks_task(self, queue):
        """Superseded tasks should be marked appropriately."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        await queue.dequeue()
        queue.supersede(task)

        assert len(queue._task_history) == 1
        assert queue._task_history[0].status == TaskStatus.SUPERSEDED

    @pytest.mark.asyncio
    async def test_queue_respects_max_size(self, queue):
        """Queue should not exceed max_size."""
        # max_size is 10

        for i in range(15):
            task = MessageTask(
                task_id=f"task_{i:03d}", chat_id="chat_001", user_message=f"Message {i}"
            )
            try:
                await queue.enqueue(task)
            except asyncio.QueueFull:
                pass

        # Should have at most 10 pending (some may have failed to enqueue)
        assert queue.pending_count <= 10

    @pytest.mark.asyncio
    async def test_history_respects_max_history(self, queue):
        """History should not exceed max_history."""
        # max_history is 5

        for i in range(10):
            task = MessageTask(
                task_id=f"task_{i:03d}", chat_id="chat_001", user_message=f"Message {i}"
            )
            await queue.enqueue(task)
            await queue.dequeue()
            queue.complete(task, f"Response {i}")

        assert len(queue._task_history) == 5
        assert queue._task_history[0].task_id == "task_005"
        assert queue._task_history[4].task_id == "task_009"

    @pytest.mark.asyncio
    async def test_processing_timestamps_set(self, queue):
        """Processing timestamps should be set on dequeue."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        before_dequeue = datetime.now()
        await queue.dequeue()

        assert task.processing_started is not None
        assert task.processing_started >= before_dequeue

    @pytest.mark.asyncio
    async def test_finished_timestamp_set(self, queue):
        """Finished timestamp should be set on complete."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        await queue.enqueue(task)
        await queue.dequeue()
        before_complete = datetime.now()
        queue.complete(task, "Done")

        assert task.processing_finished is not None
        assert task.processing_finished >= before_complete

    @pytest.mark.asyncio
    async def test_get_stats(self, queue):
        """Stats should report correct pending count."""
        for i in range(3):
            task = MessageTask(
                task_id=f"task_{i:03d}", chat_id="chat_001", user_message=f"Message {i}"
            )
            await queue.enqueue(task)

        stats = queue.get_stats()

        assert stats["pendingSize"] == 3

    @pytest.mark.asyncio
    async def test_task_order_fifo(self, queue):
        """Tasks should be dequeued in FIFO order."""
        tasks = []
        for i in range(5):
            task = MessageTask(
                task_id=f"task_{i:03d}", chat_id="chat_001", user_message=f"Message {i}"
            )
            await queue.enqueue(task)
            tasks.append(task)

        for i, expected_task in enumerate(tasks):
            dequeued = await queue.dequeue()
            assert dequeued.task_id == expected_task.task_id
            queue.complete(dequeued, "Done")


class TestMessageTask:
    """Test cases for MessageTask dataclass."""

    def test_default_status_is_queued(self):
        """New tasks should have QUEUED status by default."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")
        assert task.status == TaskStatus.QUEUED

    def test_default_values(self):
        """Task should have appropriate defaults."""
        task = MessageTask(task_id="task_001", chat_id="chat_001", user_message="Hello")

        assert task.message_id == ""
        assert task.sender_name == ""
        assert task.is_group is False
        assert task.response is None
        assert task.error is None
        assert task.generation == 0
        assert task.processing_time_ms == 0

    def test_task_id_required(self):
        """Task should require task_id and chat_id."""
        with pytest.raises(TypeError):
            MessageTask(chat_id="chat_001", user_message="Hello")

        with pytest.raises(TypeError):
            MessageTask(task_id="task_001", user_message="Hello")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
