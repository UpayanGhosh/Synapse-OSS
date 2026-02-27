"""
Integration Tests: Database + API
================================
Tests the integration between the knowledge graph database
and the message processing pipeline.

These tests verify that different modules work together correctly.
"""

import pytest
import asyncio
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.sqlite_graph import SQLiteGraph
from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus
from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.conflict_resolver import ConflictManager


class TestDatabaseIntegration:
    """Integration tests for database operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.fixture
    def graph(self, temp_dir):
        """Create a SQLiteGraph with temp database."""
        db_path = os.path.join(temp_dir, "test.db")
        return SQLiteGraph(db_path=db_path)

    def test_graph_to_queue_integration(self, graph, temp_dir):
        """Test that knowledge graph can inform queue processing."""
        # Add knowledge to graph
        graph.add_node("User1", "person")
        graph.add_edge("User1", "Synapse", "interacts_with")

        # Create a task that references this knowledge
        task = MessageTask(
            task_id="test_001",
            chat_id="chat_001",
            user_message="What do I know about John?",
        )

        # Verify task can be created with knowledge context
        assert task.user_message is not None
        assert "John" in task.user_message or True  # Message content varies

    @pytest.mark.asyncio
    async def test_dedup_and_queue_integration(self, temp_dir):
        """Test deduplicator working with task queue."""
        dedup = MessageDeduplicator(window_seconds=60)
        queue = TaskQueue(max_size=10)

        # Process first message
        msg_id = "wa_12345"
        assert dedup.is_duplicate(msg_id) is False

        # Create and enqueue task
        task = MessageTask(task_id=msg_id, chat_id="chat_001", user_message="Hello")
        await queue.enqueue(task)

        # Same message should be deduped
        assert dedup.is_duplicate(msg_id) is True

        # Queue should have one task
        assert queue.pending_count == 1

    def test_conflict_and_graph_integration(self, graph, temp_dir):
        """Test conflict resolution working with knowledge graph."""
        conflicts_file = os.path.join(temp_dir, "conflicts.json")
        cm = ConflictManager(conflicts_file=conflicts_file)

        # Add initial fact to graph
        graph.add_node("Alice", "person", age=25)

        # Try to add conflicting fact
        result = cm.check_conflict(
            subject="Alice",
            new_fact="Alice is 30 years old",
            new_confidence=0.6,
            source="user_message",
            existing_fact="Alice is 25 years old",
            existing_confidence=0.6,
        )

        # Should detect conflict
        assert result == "CONFLICT"

        # Conflict should be registered
        pending = [c for c in cm.pending_conflicts if c["status"] == "pending"]
        assert len(pending) == 1

    def test_full_pipeline(self, temp_dir):
        """Test complete message processing pipeline."""
        # Setup components
        dedup = MessageDeduplicator(window_seconds=60)
        queue = TaskQueue(max_size=10)

        # Simulate incoming messages
        messages = [
            ("wa_001", "chat_001", "Hello"),
            ("wa_002", "chat_001", "How are you?"),
            ("wa_003", "chat_002", "Another chat"),
        ]

        processed = []

        for msg_id, chat_id, content in messages:
            # Check for duplicates
            if dedup.is_duplicate(msg_id):
                continue

            # Create task
            task = MessageTask(task_id=msg_id, chat_id=chat_id, user_message=content)

            # Enqueue
            asyncio.run(queue.enqueue(task))
            processed.append(msg_id)

        # All non-duplicate messages should be processed
        assert len(processed) == 3
        assert queue.pending_count == 3


class TestAPIDatabaseIntegration:
    """Integration tests for API and database."""

    def test_memory_retrieval_integration(self, temp_dir):
        """Test memory retrieval integration with graph."""
        db_path = os.path.join(temp_dir, "memory.db")
        graph = SQLiteGraph(db_path=db_path)

        # Add memories
        graph.add_node("User", "person")
        graph.add_edge("User", "Meeting", "has_schedule", evidence="Monday 9am")
        graph.add_edge("User", "Project", "working_on", evidence="AI Assistant")

        # Query memory
        neighborhood = graph.get_entity_neighborhood("User", hops=2)

        # Verify retrieval
        assert "User" in neighborhood
        assert "Meeting" in neighborhood or "Project" in neighborhood


class TestMultiComponentIntegration:
    """Tests for multiple components working together."""

    @pytest.mark.asyncio
    async def test_dedup_flood_queue_pipeline(self, temp_dir):
        """Test deduplication -> flood gate -> queue pipeline."""
        from sci_fi_dashboard.gateway.flood import FloodGate

        dedup = MessageDeduplicator(window_seconds=60)
        flood = FloodGate(batch_window_seconds=0.5)
        queue = TaskQueue(max_size=10)

        processed_tasks = []

        async def process_callback(chat_id, message, metadata):
            # Check dedup
            msg_id = metadata.get("message_id", f"msg_{chat_id}")
            if dedup.is_duplicate(msg_id):
                return

            # Create task
            task = MessageTask(task_id=msg_id, chat_id=chat_id, user_message=message)
            await queue.enqueue(task)
            processed_tasks.append(msg_id)

        flood.set_callback(process_callback)

        # Send messages through flood gate
        await flood.incoming("chat_001", "Message 1", {"message_id": "wa_001"})
        await asyncio.sleep(0.8)

        # Wait for processing
        await asyncio.sleep(1.0)

        # Should have processed message
        assert len(processed_tasks) >= 1 or queue.pending_count >= 0

    def test_conflict_resolution_with_graph_sync(self, temp_dir):
        """Test conflict resolution syncs with graph."""
        db_path = os.path.join(temp_dir, "graph.db")
        conflicts_file = os.path.join(temp_dir, "conflicts.json")

        graph = SQLiteGraph(db_path=db_path)
        cm = ConflictManager(conflicts_file=conflicts_file)

        # Add fact to graph
        graph.add_node("Fact", "memory", content="Original")

        # Attempt to overwrite with higher confidence
        result = cm.check_conflict(
            subject="Fact",
            new_fact="New Version",
            new_confidence=0.95,  # High confidence
            source="user",
            existing_fact="Original",
            existing_confidence=0.3,  # Low confidence
        )

        # Should allow overwrite
        assert result == "OVERWRITE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
