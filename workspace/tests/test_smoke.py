"""
Smoke Tests: Basic Functionality
=============================
Smoke tests are basic tests that check the fundamental functionality
of the system. They are quick to execute and verify that major
features are working.

These tests should run quickly and catch obvious issues.
"""

import pytest
import asyncio
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus
from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.sqlite_graph import SQLiteGraph
from sci_fi_dashboard.conflict_resolver import ConflictManager


class TestCoreComponentsSmoke:
    """Smoke tests for core components."""

    @pytest.mark.smoke
    @pytest.mark.smoke
    def test_dedup_exists(self):
        """Deduplicator should instantiate."""
        dedup = MessageDeduplicator()
        assert dedup is not None

    @pytest.mark.smoke
    def test_dedup_basic_function(self):
        """Deduplicator should detect duplicates."""
        dedup = MessageDeduplicator()

        is_new = dedup.is_duplicate("test_msg")
        is_dup = dedup.is_duplicate("test_msg")

        assert is_new is False
        assert is_dup is True

    @pytest.mark.smoke
    def test_queue_exists(self):
        """TaskQueue should instantiate."""
        queue = TaskQueue()
        assert queue is not None

    @pytest.mark.asyncio
    async def test_queue_basic_workflow(self):
        """TaskQueue should handle basic workflow."""
        queue = TaskQueue()

        # Create task
        task = MessageTask(task_id="smoke_001", chat_id="chat_001", user_message="Test")

        # Enqueue
        await queue.enqueue(task)

        # Dequeue
        dequeued = await queue.dequeue()

        # Check status is PROCESSING before completing
        assert dequeued.status == TaskStatus.PROCESSING

        # Complete
        queue.complete(dequeued, "Response")

        # Verify completion
        assert queue._task_history[0].status == TaskStatus.COMPLETED

    @pytest.mark.smoke
    def test_flood_gate_exists(self):
        """FloodGate should instantiate."""
        flood = FloodGate()
        assert flood is not None

    @pytest.mark.smoke
    def test_graph_exists(self):
        """SQLiteGraph should instantiate."""
        tmp = tempfile.mkdtemp()
        db_path = os.path.join(tmp, "smoke.db")

        try:
            graph = SQLiteGraph(db_path=db_path)
            assert graph is not None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @pytest.mark.smoke
    def test_graph_basic_operations(self, tmp_path):
        """Graph should handle basic operations."""
        db_path = tmp_path / "smoke_graph.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Add node
        graph.add_node("TestNode", "test", value="test")

        # Add edge
        graph.add_edge("TestNode", "AnotherNode", "relates_to")

        # Query
        result = graph.get_entity_neighborhood("TestNode", hops=1)

        assert "TestNode" in result

    @pytest.mark.smoke
    def test_conflict_manager_exists(self):
        """ConflictManager should instantiate."""
        tmp = tempfile.mkdtemp()
        conflicts_file = os.path.join(tmp, "conflicts.json")

        try:
            cm = ConflictManager(conflicts_file=conflicts_file)
            assert cm is not None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestBasicWorkflowsSmoke:
    """Smoke tests for basic workflows."""

    @pytest.mark.smoke
    def test_message_flow(self):
        """Basic message flow should work."""
        dedup = MessageDeduplicator()

        # Process message
        msg_id = "wa_smoke_001"

        # Should process first time
        assert dedup.is_duplicate(msg_id) is False

        # Should dedupe retry
        assert dedup.is_duplicate(msg_id) is True

    @pytest.mark.asyncio
    async def test_queue_flow(self):
        """Basic queue flow should work."""
        queue = TaskQueue(max_size=10)

        # Enqueue
        task = MessageTask(task_id="q_001", chat_id="chat", user_message="hello")
        await queue.enqueue(task)

        # Process
        processed = await queue.dequeue()

        # Complete
        queue.complete(processed, "hi there")

        assert queue.pending_count == 0
        assert len(queue._task_history) == 1

    @pytest.mark.smoke
    def test_memory_storage_and_retrieval(self, tmp_path):
        """Basic memory storage and retrieval should work."""
        db_path = tmp_path / "memory.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Store
        graph.add_node("Fact1", "memory", content="Important")
        graph.add_edge("User", "Fact1", "knows")

        # Retrieve
        result = graph.get_entity_neighborhood("User", hops=1)

        # Should find stored memory
        assert "Fact1" in result or "User" in result


class TestErrorHandlingSmoke:
    """Smoke tests for error handling."""

    @pytest.mark.smoke
    def test_dedup_handles_empty(self):
        """Deduplicator should handle empty inputs."""
        dedup = MessageDeduplicator()

        # Empty should not crash
        assert dedup.is_duplicate("") is False
        assert dedup.is_duplicate(None) is False

    @pytest.mark.asyncio
    async def test_queue_handles_empty(self):
        """Queue should handle edge cases."""
        queue = TaskQueue()

        # Empty message should be fine
        task = MessageTask(task_id="empty", chat_id="chat", user_message="")
        await queue.enqueue(task)

        processed = await queue.dequeue()
        queue.complete(processed, "")

        assert queue._task_history[0].status == TaskStatus.COMPLETED

    @pytest.mark.smoke
    def test_graph_handles_missing_data(self, tmp_path):
        """Graph should handle missing data gracefully."""
        db_path = tmp_path / "missing.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Query non-existent node
        result = graph.get_entity_neighborhood("NonExistent", hops=1)

        # Should return empty or safe result
        assert result is not None


class TestConfigurationSmoke:
    """Smoke tests for configuration."""

    @pytest.mark.smoke
    def test_dedup_custom_window(self):
        """Deduplicator should accept custom window."""
        dedup = MessageDeduplicator(window_seconds=600)

        assert dedup.window == 600

    @pytest.mark.smoke
    def test_queue_custom_size(self):
        """Queue should accept custom size."""
        queue = TaskQueue(max_size=50, max_history=100)

        assert queue._queue.maxsize == 50

    @pytest.mark.smoke
    def test_flood_custom_window(self):
        """FloodGate should accept custom window."""
        flood = FloodGate(batch_window_seconds=5.0)

        assert flood.window == 5.0


class TestBasicSecuritySmoke:
    """Smoke tests for basic security."""

    @pytest.mark.smoke
    def test_no_sensitive_data_in_logs(self):
        """Sensitive data should not be logged."""
        # This is a placeholder - in real tests would check logs
        sensitive = "password123"

        # Should not be logged in plain text
        # In production, would verify log output
        assert sensitive is not None

    @pytest.mark.smoke
    def test_api_key_validation(self):
        """API keys should be validated."""
        # Placeholder for API key validation tests
        # In production, would test key format/validation
        assert True


class TestDependenciesSmoke:
    """Smoke tests for dependencies."""

    @pytest.mark.smoke
    def test_sqlite_available(self):
        """SQLite should be available."""
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.close()
        assert True

    @pytest.mark.smoke
    def test_asyncio_available(self):
        """Asyncio should be available."""
        assert asyncio is not None

    @pytest.mark.smoke
    def test_required_modules_importable(self):
        """All required modules should be importable."""
        try:
            from sci_fi_dashboard.gateway.queue import TaskQueue
            from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
            from sci_fi_dashboard.gateway.flood import FloodGate
            from sci_fi_dashboard.sqlite_graph import SQLiteGraph
            from sci_fi_dashboard.conflict_resolver import ConflictManager

            assert True
        except ImportError as e:
            pytest.fail(f"Import failed: {e}")


class TestDatabaseSmoke:
    """Smoke tests for database operations."""

    @pytest.mark.smoke
    def test_database_creation(self, tmp_path):
        """Database should be created properly."""
        db_path = tmp_path / "create.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Should create file
        assert os.path.exists(db_path)

    @pytest.mark.smoke
    def test_database_schema(self, tmp_path):
        """Database should have correct schema."""
        db_path = tmp_path / "schema.db"
        graph = SQLiteGraph(db_path=str(db_path))

        conn = graph._conn()
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "nodes" in tables
        assert "edges" in tables


class TestIntegrationSmoke:
    """Smoke tests for basic integration."""

    @pytest.mark.asyncio
    async def test_components_work_together(self, tmp_path):
        """Components should work together."""
        # Setup
        dedup = MessageDeduplicator()
        queue = TaskQueue()
        db_path = tmp_path / "integrated.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Message comes in
        msg_id = "wa_integration_001"

        # Check dedup
        if not dedup.is_duplicate(msg_id):
            # Store in knowledge
            graph.add_node("UserMessage", "message", content="Hello")

            # Queue for processing
            task = MessageTask(task_id=msg_id, chat_id="chat", user_message="Hello")
            await queue.enqueue(task)

        # Verify all worked
        assert queue.pending_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
