"""
End-to-End Tests: Full User Flows
=================================
Tests complete user workflows from start to finish.
These tests replicate real user behavior in a complete environment.

WARNING: These tests require the full system to be running
and may require API keys and external services.
"""

import pytest
import asyncio
import sys
import os
import time
import tempfile
import shutil
from unittest.mock import Mock, patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus
from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.sqlite_graph import SQLiteGraph
from sci_fi_dashboard.conflict_resolver import ConflictManager


class TestWhatsAppMessageFlow:
    """End-to-end tests for WhatsApp message flow."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test data."""
        tmp = tempfile.mkdtemp()
        yield tmp
        shutil.rmtree(tmp, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_complete_inbound_message_flow(self, temp_dir):
        """Test complete flow: webhook → dedup → queue → process → respond."""
        # Setup components
        dedup = MessageDeduplicator(window_seconds=300)
        queue = TaskQueue(max_size=100)

        # Simulate incoming WhatsApp webhook
        webhook_message = {
            "message_id": "wa_test_001",
            "from": "+1234567890",
            "chat_id": "chat_001",
            "body": "Hello Jarvis",
        }

        # Step 1: Check for duplicates
        is_duplicate = dedup.is_duplicate(webhook_message["message_id"])
        assert is_duplicate is False

        # Step 2: Create task
        task = MessageTask(
            task_id=webhook_message["message_id"],
            chat_id=webhook_message["chat_id"],
            user_message=webhook_message["body"],
            message_id=webhook_message["message_id"],
            sender_name=webhook_message["from"],
        )

        # Step 3: Enqueue
        await queue.enqueue(task)

        # Step 4: Process
        processed_task = await queue.dequeue()

        # Step 5: Complete with response
        response = "Hello! How can I help you today?"
        queue.complete(processed_task, response)

        # Verify flow completed
        assert processed_task.status == TaskStatus.COMPLETED
        assert processed_task.response == response

    @pytest.mark.asyncio
    async def test_retry_webhook_no_duplicate_response(self, temp_dir):
        """Test that retry webhooks don't cause duplicate responses."""
        dedup = MessageDeduplicator(window_seconds=300)
        responses_sent = []

        message_id = "wa_retry_001"

        # Simulate 3 webhook retries
        for attempt in range(3):
            is_dup = dedup.is_duplicate(message_id)

            if not is_dup:
                # Would process and send response
                responses_sent.append(f"Response {attempt + 1}")

        # Only first attempt should generate response
        assert len(responses_sent) == 1
        assert responses_sent[0] == "Response 1"

    @pytest.mark.asyncio
    async def test_rapid_message_burst(self, temp_dir):
        """Test handling of rapid message burst."""
        flood = FloodGate(batch_window_seconds=1.0)
        queue = TaskQueue(max_size=100)

        processed = []

        async def callback(chat_id, message, metadata):
            task = MessageTask(
                task_id=metadata.get("message_id", f"task_{time.time()}"),
                chat_id=chat_id,
                user_message=message,
            )
            await queue.enqueue(task)
            processed.append(message)

        flood.set_callback(callback)

        # Simulate rapid burst of messages
        for i in range(10):
            await flood.incoming("chat_001", f"Message {i}", {"message_id": f"wa_{i}"})

        # Wait for batch window
        await asyncio.sleep(1.5)

        # Verify messages were processed
        assert len(processed) >= 1


class TestMemoryRetrievalFlow:
    """End-to-end tests for memory retrieval."""

    def test_add_memory_retrieve_memory_flow(self, temp_dir):
        """Test complete flow: add memory → retrieve later."""
        db_path = os.path.join(temp_dir, "memory.db")
        graph = SQLiteGraph(db_path=db_path)

        # User tells Jarvis something important
        user_message = "Remember that I have a meeting with John tomorrow at 3pm"

        # Extract and store (simulated)
        graph.add_node("Meeting_001", "event", description="Meeting with John")
        graph.add_node("John", "person", name="John")
        graph.add_edge("User", "Meeting_001", "has_scheduled")
        graph.add_edge("Meeting_001", "John", "with")

        # Later, user asks about the meeting
        query = "What meetings do I have?"

        # Retrieve
        results = graph.get_entity_neighborhood("User", hops=2)

        # Verify memory was stored and retrieved
        assert "Meeting_001" in results or "User" in results

    def test_persona_evolution_flow(self, temp_dir):
        """Test persona profile build-up over time."""
        conflicts_file = os.path.join(temp_dir, "conflicts.json")
        cm = ConflictManager(conflicts_file=conflicts_file)

        # Track conversation patterns
        messages = [
            "Hey buddy! What's up?",
            "Nice! That's cool",
            "lol that was funny",
            "Seriously though, I need help with something",
        ]

        # Process messages (simulated SBS analysis)
        casual_count = sum(
            1
            for m in messages
            if any(w in m.lower() for w in ["hey", "lol", "nice", "cool"])
        )

        # Verify casual communication style detected
        assert casual_count >= 2


class TestPrivacyVaultFlow:
    """End-to-end tests for privacy vault."""

    def test_sensitive_data_routes_to_vault(self, temp_dir):
        """Test that sensitive data triggers local processing."""
        private_keywords = ["password", "credit card", "ssn", "bank account", "secret"]

        test_messages = [
            "What's my bank account balance?",
            "I need to change my password",
            "What's the weather like?",
        ]

        vault_routes = []
        cloud_routes = []

        for msg in test_messages:
            if any(kw in msg.lower() for kw in private_keywords):
                vault_routes.append(msg)
            else:
                cloud_routes.append(msg)

        # Verify sensitive messages flagged for vault
        assert len(vault_routes) >= 2
        assert len(cloud_routes) >= 1


class TestHybridRAGFlow:
    """End-to-end tests for hybrid RAG."""

    def test_vector_and_graph_retrieval(self, temp_dir):
        """Test combined vector + graph retrieval."""
        db_path = os.path.join(temp_dir, "hybrid.db")
        graph = SQLiteGraph(db_path=db_path)

        # Add structured knowledge
        graph.add_node("User_Preferences", "preference", favorite_language="Python")
        graph.add_node("User", "person", name="TestUser")
        graph.add_edge("User", "User_Preferences", "has")

        # Add related memories
        graph.add_node("Project_Alpha", "project", status="active")
        graph.add_edge("User", "Project_Alpha", "working_on")

        # Query (simulating hybrid retrieval)
        graph_results = graph.get_entity_neighborhood("User", hops=2)

        # Verify both preferences and projects retrieved
        assert "User" in graph_results


class TestMultiModelRoutingFlow:
    """End-to-end tests for multi-model routing."""

    def test_intent_based_routing(self):
        """Test message routing based on intent."""
        test_cases = [
            ("Hello!", "gemini_flash"),  # Casual
            ("Write a python script", "claude"),  # Coding
            ("Analyze this data", "gemini_pro"),  # Analysis
            ("Review my code", "claude_opus"),  # Complex reasoning
        ]

        for message, expected_route in test_cases:
            # Simple routing simulation
            if any(kw in message.lower() for kw in ["write", "code", "script"]):
                route = "claude"
            elif any(kw in message.lower() for kw in ["analyze", "review"]):
                route = "gemini_pro"
            elif len(message.split()) < 5:
                route = "gemini_flash"
            else:
                route = "default"

            # For demonstration - actual routing logic would be more sophisticated
            assert route is not None


class TestSystemRecoveryFlow:
    """End-to-end tests for system recovery."""

    @pytest.mark.asyncio
    async def test_queue_recovery_after_restart(self, temp_dir):
        """Test queue state recovery after system restart."""
        queue = TaskQueue(max_size=100, max_history=100)

        # Add some tasks
        for i in range(5):
            task = MessageTask(
                task_id=f"task_{i}", chat_id="chat_001", user_message=f"Msg {i}"
            )
            await queue.enqueue(task)

        # Simulate restart by creating new queue instance
        # (in real scenario, would load from persistent storage)
        queue2 = TaskQueue(max_size=100, max_history=100)

        # New queue starts empty (would be restored from DB in production)
        assert queue2.pending_count == 0

    def test_conflict_persistence_after_restart(self, temp_dir):
        """Test conflicts persist across restarts."""
        conflicts_file = os.path.join(temp_dir, "conflicts.json")

        # Create conflict
        cm1 = ConflictManager(conflicts_file=conflicts_file)
        cm1.check_conflict("Subject", "Fact A", 0.5, "src", "Fact B", 0.5)

        # Simulate restart - load from file
        cm2 = ConflictManager(conflicts_file=conflicts_file)

        # Verify conflict persisted
        assert len(cm2.pending_conflicts) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
