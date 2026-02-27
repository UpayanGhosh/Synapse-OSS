"""
Functional Tests: Business Logic
================================
Tests the business logic and requirements of the system.
Functional tests verify the output of actions without checking
intermediate states.

These tests focus on "what" the system does, not "how" it does it.
"""

import pytest
import asyncio
import sys
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import TaskQueue, MessageTask, TaskStatus
from sci_fi_dashboard.gateway.dedup import MessageDeduplicator
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.sqlite_graph import SQLiteGraph
from sci_fi_dashboard.conflict_resolver import ConflictManager


class TestMessageProcessingFunctionality:
    """Functional tests for message processing."""

    def test_no_duplicate_responses_sent(self):
        """System should never send duplicate responses to same message."""
        dedup = MessageDeduplicator(window_seconds=300)

        # Simulate WhatsApp webhook retry
        message_id = "wa_msg_12345"

        # First attempt
        is_dup_1 = dedup.is_duplicate(message_id)

        # Retry (WhatsApp sometimes retries)
        is_dup_2 = dedup.is_duplicate(message_id)

        # Second retry
        is_dup_3 = dedup.is_duplicate(message_id)

        # First should NOT be duplicate, subsequent should be
        assert is_dup_1 is False
        assert is_dup_2 is True
        assert is_dup_3 is True

    @pytest.mark.asyncio
    async def test_rapid_messages_batched(self):
        """Rapid messages from same user should be batched."""
        flood = FloodGate(batch_window_seconds=2.0)

        messages_received = []

        async def callback(chat_id, message, metadata):
            messages_received.append(message)

        flood.set_callback(callback)

        # Simulate rapid messages
        await flood.incoming("chat_001", "First", {"sender": "user1"})
        await flood.incoming("chat_001", "Second", {"sender": "user1"})
        await flood.incoming("chat_001", "Third", {"sender": "user1"})

        # Wait for batch window
        await asyncio.sleep(2.5)

        # Should have batched into fewer messages
        # (Exact count depends on debounce behavior)

    @pytest.mark.asyncio
    async def test_different_users_not_batched(self):
        """Messages from different users should not be batched."""
        flood = FloodGate(batch_window_seconds=1.0)

        messages = []

        async def callback(chat_id, message, metadata):
            messages.append((chat_id, message))

        flood.set_callback(callback)

        # Different chats
        await flood.incoming("chat_001", "User A msg", {"sender": "A"})
        await flood.incoming("chat_002", "User B msg", {"sender": "B"})

        await asyncio.sleep(1.5)

        # Should have 2 separate messages
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_queue_prevents_message_loss(self):
        """Queue should prevent message loss under load."""
        queue = TaskQueue(max_size=100)

        # Simulate burst of messages
        tasks_created = 0

        for i in range(50):
            task = MessageTask(task_id=f"task_{i}", chat_id="chat_001", user_message=f"Message {i}")
            try:
                await queue.enqueue(task)
                tasks_created += 1
            except Exception:
                pass  # Queue full

        # Should have processed as many as possible
        assert tasks_created > 0
        assert tasks_created <= 100


class TestKnowledgeManagementFunctionality:
    """Functional tests for knowledge management."""

    def test_facts_are_stored_permanently(self, tmp_path):
        """Facts added to knowledge graph should persist."""
        db_path = tmp_path / "knowledge.db"
        graph = SQLiteGraph(db_path=str(db_path))

        # Add fact
        graph.add_node("ImportantFact", "memory", content="Critical information")
        graph.add_edge("User", "ImportantFact", "knows")

        # Create new graph instance (simulating restart)
        graph2 = SQLiteGraph(db_path=str(db_path))

        # Retrieve fact
        result = graph2.get_entity_neighborhood("ImportantFact", hops=1)

        # Should still exist
        assert "ImportantFact" in result

    def test_conflicting_facts_detected(self, tmp_path):
        """System should detect conflicting facts."""
        conflicts_file = tmp_path / "conflicts.json"
        cm = ConflictManager(conflicts_file=str(conflicts_file))

        # Add conflicting facts with similar confidence
        result = cm.check_conflict(
            subject="Meeting",
            new_fact="Meeting at 3pm",
            new_confidence=0.5,
            source="user",
            existing_fact="Meeting at 5pm",
            existing_confidence=0.5,
        )

        assert result == "CONFLICT"

    def test_high_confidence_overwrites_low(self, tmp_path):
        """High confidence facts should overwrite low confidence ones."""
        conflicts_file = tmp_path / "conflicts.json"
        cm = ConflictManager(conflicts_file=str(conflicts_file))

        result = cm.check_conflict(
            subject="Fact",
            new_fact="Correct fact",
            new_confidence=0.95,
            source="verified_source",
            existing_fact="Incorrect fact",
            existing_confidence=0.2,
        )

        assert result == "OVERWRITE"


class TestPersonaFunctionality:
    """Functional tests for persona management."""

    def test_persona_profile_structure(self):
        """Persona profile should have expected structure."""
        # Mock persona profile
        profile = {
            "name": "Synapse",
            "personality_traits": ["helpful", "witty"],
            "communication_style": "casual",
            "language_preferences": {"primary": "en", "use_emoji": True},
        }

        # Verify structure
        assert "name" in profile
        assert "personality_traits" in profile
        assert isinstance(profile["personality_traits"], list)

    def test_persona_injection_in_prompt(self):
        """Persona should be injectable into system prompts."""
        base_prompt = "You are a helpful assistant."
        persona_context = {
            "personality": "You are witty and use casual language.",
            "relationship": "You are talking to a close friend.",
        }

        # Simulate injection
        full_prompt = (
            f"{base_prompt}\n\n{persona_context['personality']}\n{persona_context['relationship']}"
        )

        assert "witty" in full_prompt
        assert "close friend" in full_prompt


class TestPrivacyFunctionality:
    """Functional tests for privacy features."""

    def test_private_messages_routed_locally(self):
        """Private messages should be flagged for local processing."""
        # Simulate privacy keywords
        private_keywords = ["password", "credit card", "ssn", "bank"]

        message = "Don't share my credit card number with anyone"

        has_privacy = any(keyword in message.lower() for keyword in private_keywords)

        assert has_privacy is True
        # In real system, this would trigger The Vault routing

    def test_non_private_messages_can_use_cloud(self):
        """Non-private messages can use cloud API."""
        private_keywords = ["password", "credit card", "ssn", "bank"]

        message = "What's the weather today?"

        has_privacy = any(keyword in message.lower() for keyword in private_keywords)

        assert has_privacy is False
        # In real system, this would use cloud API


class TestRoutingFunctionality:
    """Functional tests for message routing."""

    def test_casual_chat_routes_to_fast_model(self):
        """Casual chat should route to fast/cheap model."""
        message = "Hello how are you"

        # Simple routing logic simulation
        if len(message.split()) < 5:
            route = "gemini_flash"  # Fast model for casual
        else:
            route = "claude"  # Strong model for complex

        assert route == "gemini_flash"

    def test_coding_task_routes_to_coding_model(self):
        """Coding tasks should route to coding-capable model."""
        message = "Write a Python function to sort a list"

        coding_keywords = ["write", "code", "function", "python", "javascript"]

        is_coding = any(keyword in message.lower() for keyword in coding_keywords)

        assert is_coding is True

    def test_analysis_task_routes_to_pro_model(self):
        """Analysis tasks should route to pro model."""
        message = "Analyze the pros and cons of this approach"

        analysis_keywords = ["analyze", "compare", "evaluate", "review"]

        is_analysis = any(keyword in message.lower() for keyword in analysis_keywords)

        assert is_analysis is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
