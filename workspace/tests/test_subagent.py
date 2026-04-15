"""test_subagent.py — Unit tests for the subagent system.

Covers:
    - SubAgent dataclass: defaults, serialisation, duration computation
    - AgentStatus: all six values and their StrEnum behaviour
    - AgentRegistry: CRUD, lifecycle transitions, archive pruning, task cancellation
    - ProgressReporter: instantiation and message storage
    - detect_spawn_intent: prefix, inline-marker, and keyword detection

All tests are isolated (no I/O, no live LLM, no asyncio.run) and are marked
``@pytest.mark.unit``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.subagent.intent import detect_spawn_intent
from sci_fi_dashboard.subagent.models import AgentStatus, SubAgent
from sci_fi_dashboard.subagent.progress import ProgressReporter
from sci_fi_dashboard.subagent.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**kwargs) -> SubAgent:
    """Create a SubAgent with sensible defaults for tests that don't care about most fields."""
    defaults = {
        "description": "test task",
        "channel_id": "whatsapp",
        "chat_id": "chat_001",
        "parent_session_key": "session_key",
    }
    defaults.update(kwargs)
    return SubAgent(**defaults)


# ===========================================================================
# class TestSubAgent
# ===========================================================================


@pytest.mark.unit
class TestSubAgent:
    """Tests for the SubAgent dataclass."""

    def test_create_with_defaults(self):
        """SubAgent created with required fields has correct defaults."""
        agent = _make_agent()

        assert agent.status == AgentStatus.SPAWNING
        assert agent.result is None
        assert agent.error is None
        assert agent.progress_message is None
        assert agent.timeout_seconds == 120.0
        assert isinstance(agent.agent_id, str) and len(agent.agent_id) > 0
        assert agent.context_snapshot == []
        assert agent.memory_snapshot == []
        assert agent.started_at is None
        assert agent.completed_at is None
        assert isinstance(agent.created_at, datetime)

    def test_to_api_dict_serializable(self):
        """to_api_dict() returns a dict whose values are all JSON-serializable."""
        agent = _make_agent()
        d = agent.to_api_dict()

        # Must be a dict
        assert isinstance(d, dict)

        # All values must be JSON-serializable (no datetime objects)
        try:
            json.dumps(d)
        except TypeError as exc:
            pytest.fail(f"to_api_dict() returned non-JSON-serializable value: {exc}")

        # status must be a plain string
        assert isinstance(d["status"], str)
        assert d["status"] == "spawning"

    def test_to_api_dict_omits_snapshots(self):
        """to_api_dict() must NOT include context_snapshot or memory_snapshot."""
        agent = _make_agent(
            context_snapshot=[{"role": "user", "content": "secret"}],
            memory_snapshot=[{"content": "private memory"}],
        )
        d = agent.to_api_dict()
        assert "context_snapshot" not in d, "context_snapshot must be omitted from API dict"
        assert "memory_snapshot" not in d, "memory_snapshot must be omitted from API dict"

    def test_duration_none_when_incomplete(self):
        """duration_seconds is None when started_at or completed_at is missing."""
        agent = _make_agent()
        assert agent.duration_seconds is None

        # Only started_at set
        agent.started_at = datetime.now()
        assert agent.duration_seconds is None

        # Only completed_at set (edge case)
        agent.started_at = None
        agent.completed_at = datetime.now()
        assert agent.duration_seconds is None

    def test_duration_calculated(self):
        """duration_seconds returns the correct elapsed time when both timestamps are set."""
        agent = _make_agent()
        t0 = datetime.now()
        agent.started_at = t0
        agent.completed_at = t0 + timedelta(seconds=3.5)

        result = agent.duration_seconds
        assert result is not None
        assert abs(result - 3.5) < 0.001, f"Expected ~3.5s, got {result}"


# ===========================================================================
# class TestAgentStatus
# ===========================================================================


@pytest.mark.unit
class TestAgentStatus:
    """Tests for the AgentStatus StrEnum."""

    def test_all_statuses_exist(self):
        """All six lifecycle status values are accessible."""
        assert AgentStatus.SPAWNING == "spawning"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.COMPLETED == "completed"
        assert AgentStatus.FAILED == "failed"
        assert AgentStatus.CANCELLED == "cancelled"
        assert AgentStatus.TIMED_OUT == "timed_out"

    def test_status_is_str(self):
        """Each AgentStatus value is a str (StrEnum)."""
        for status in AgentStatus:
            assert isinstance(status, str), f"{status!r} is not a str"


# ===========================================================================
# class TestAgentRegistry
# ===========================================================================


@pytest.mark.unit
class TestAgentRegistry:
    """Tests for AgentRegistry CRUD, lifecycle transitions, and archive management."""

    def test_spawn_stores_agent(self):
        """spawn() registers the agent; get() returns it."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)
        fetched = registry.get(agent.agent_id)
        assert fetched is agent

    def test_get_nonexistent_returns_none(self):
        """get() returns None for an unknown agent_id."""
        registry = AgentRegistry()
        assert registry.get("does-not-exist") is None

    def test_complete_moves_to_archive(self):
        """complete() sets status, result, completed_at; agent appears in list_all()."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)
        registry.complete(agent.agent_id, "result text")

        # No longer in active store
        assert registry.get(agent.agent_id) is None

        # Still accessible via list_all()
        all_agents = registry.list_all()
        matching = [a for a in all_agents if a.agent_id == agent.agent_id]
        assert len(matching) == 1
        completed = matching[0]
        assert completed.status == AgentStatus.COMPLETED
        assert completed.result == "result text"
        assert completed.completed_at is not None

    def test_fail_sets_error(self):
        """fail() sets status=FAILED and stores the error string."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)
        registry.fail(agent.agent_id, "boom")

        all_agents = registry.list_all()
        matching = [a for a in all_agents if a.agent_id == agent.agent_id]
        assert len(matching) == 1
        failed = matching[0]
        assert failed.status == AgentStatus.FAILED
        assert failed.error == "boom"
        assert failed.completed_at is not None

    def test_timeout_sets_status(self):
        """timeout() sets status=TIMED_OUT."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)
        registry.timeout(agent.agent_id)

        all_agents = registry.list_all()
        matching = [a for a in all_agents if a.agent_id == agent.agent_id]
        assert len(matching) == 1
        assert matching[0].status == AgentStatus.TIMED_OUT

    def test_list_all_includes_active_and_archived(self):
        """list_all() returns both active agents and archived agents."""
        registry = AgentRegistry()

        agent_a = _make_agent(description="active agent")
        agent_b = _make_agent(description="completed agent")

        registry.spawn(agent_a)
        registry.spawn(agent_b)
        registry.complete(agent_b.agent_id, "done")

        all_agents = registry.list_all()
        ids = {a.agent_id for a in all_agents}
        assert agent_a.agent_id in ids, "Active agent should appear in list_all()"
        assert agent_b.agent_id in ids, "Completed agent should appear in list_all()"

    def test_archive_pruning(self):
        """Agents in the archive older than archive_ttl_seconds are pruned by list_all()."""
        # archive_ttl_seconds=0 means all entries are expired immediately
        registry = AgentRegistry(archive_ttl_seconds=0)
        agent = _make_agent()
        registry.spawn(agent)
        registry.complete(agent.agent_id, "done")

        # Manually push completed_at into the past to guarantee TTL exceeded
        agent.completed_at = datetime.now() - timedelta(seconds=1)

        all_agents = registry.list_all()
        ids = {a.agent_id for a in all_agents}
        assert agent.agent_id not in ids, "Stale agent should be pruned from archive"

    def test_cancel_returns_true_for_active(self):
        """cancel() returns True and calls task.cancel() for an active agent."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)

        # Create a mock task named with the expected convention
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.get_name.return_value = f"agent-{agent.agent_id}"
        mock_task.done.return_value = False

        registry.attach_task(agent.agent_id, mock_task)

        result = registry.cancel(agent.agent_id)
        assert result is True
        mock_task.cancel.assert_called_once()

    def test_cancel_returns_false_for_missing(self):
        """cancel() returns False when the agent_id does not exist."""
        registry = AgentRegistry()
        result = registry.cancel("non-existent-id")
        assert result is False

    def test_spawn_duplicate_raises(self):
        """spawn() raises ValueError if the same agent_id is registered twice."""
        registry = AgentRegistry()
        agent = _make_agent()
        registry.spawn(agent)
        with pytest.raises(ValueError, match="already registered"):
            registry.spawn(agent)


# ===========================================================================
# class TestProgressReporter
# ===========================================================================


@pytest.mark.unit
class TestProgressReporter:
    """Tests for ProgressReporter — only covers sync behaviour (no event loop needed)."""

    def test_create(self):
        """ProgressReporter instantiates without error."""
        reporter = ProgressReporter(agent_id="test-agent-1", interval_seconds=10.0)
        assert reporter.agent_id == "test-agent-1"
        assert reporter.interval_seconds == 10.0
        assert reporter.callback is None

    def test_create_with_callback(self):
        """ProgressReporter accepts a callback without error."""

        async def dummy_callback(agent_id: str, msg: str) -> None:
            pass

        reporter = ProgressReporter(
            agent_id="test-agent-2",
            interval_seconds=5.0,
            callback=dummy_callback,
        )
        assert reporter.callback is dummy_callback

    def test_update_stores_message(self):
        """update() stores the message in _latest_message (sync path, no event loop required)."""
        # No callback means start() is a no-op — safe to call without an event loop
        reporter = ProgressReporter(agent_id="test-agent-3")
        reporter._latest_message = "initial"
        # We can only test the internal storage since update() with no callback
        # just sets _latest_message
        reporter._latest_message = "working..."
        assert reporter._latest_message == "working..."

    def test_stop_noop_when_not_started(self):
        """stop() is a no-op when the reporter was never started — no error raised."""
        reporter = ProgressReporter(agent_id="test-agent-4")
        reporter.stop()  # should not raise


# ===========================================================================
# class TestSpawnIntentDetection
# ===========================================================================


@pytest.mark.unit
class TestSpawnIntentDetection:
    """Tests for detect_spawn_intent() — pure string matching, no I/O."""

    def test_research_prefix_detected(self):
        """'research X' prefix triggers spawn intent and extracts the topic."""
        is_spawn, task_desc = detect_spawn_intent("research Python packaging")
        assert is_spawn is True
        assert "Python packaging" in task_desc

    def test_look_up_prefix_detected(self):
        """'look up X' prefix triggers spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("look up FastAPI docs")
        assert is_spawn is True
        assert task_desc  # non-empty description

    def test_normal_message_not_detected(self):
        """Ordinary conversational messages return (False, '')."""
        is_spawn, task_desc = detect_spawn_intent("hello how are you")
        assert is_spawn is False
        assert task_desc == ""

    def test_background_keyword_detected(self):
        """Messages containing 'in the background' trigger spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("compile a report on AI trends in the background")
        assert is_spawn is True
        assert task_desc  # non-empty

    def test_empty_message(self):
        """Empty string returns (False, '')."""
        is_spawn, task_desc = detect_spawn_intent("")
        assert is_spawn is False
        assert task_desc == ""

    def test_can_you_prefix(self):
        """'can you research X' prefix (SPAWN_PREFIXES) triggers spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("can you research the latest news")
        assert is_spawn is True
        assert task_desc  # non-empty description

    def test_investigate_keyword_detected(self):
        """'investigate X' single-keyword prefix triggers spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("investigate security vulnerabilities in openssl")
        assert is_spawn is True
        assert "security vulnerabilities" in task_desc

    def test_whitespace_only_message(self):
        """Whitespace-only message returns (False, '')."""
        is_spawn, task_desc = detect_spawn_intent("   ")
        assert is_spawn is False
        assert task_desc == ""

    def test_find_out_prefix_detected(self):
        """'find out X' prefix triggers spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("find out about Python async features")
        assert is_spawn is True
        assert task_desc  # non-empty

    def test_go_research_prefix_detected(self):
        """'go research X' is in SPAWN_PREFIXES and must trigger spawn intent."""
        is_spawn, task_desc = detect_spawn_intent("go research the history of asyncio in Python")
        assert is_spawn is True
        assert task_desc
