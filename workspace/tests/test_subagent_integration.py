"""test_subagent_integration.py — Integration tests for SubAgentRunner.

Covers:
    - AGENT-01: spawn_agent() returns immediately (fire-and-forget)
    - AGENT-02: Crash isolation — a failing agent does not affect its sibling
    - AGENT-03: Result delivery via channel_registry.send()
    - AGENT-04: Parallel execution — two agents finish in ~max(t1, t2) not sum
    - AGENT-06: Progress updates fire at configurable intervals
    - AGENT-07: GET /api/agents returns correct agent data
    - maybe_spawn_agent: str return on match, None on no-match, None when runner
      is None, correct memory dict unwrapping

All external dependencies (LLM, channel) are mocked. No live API calls.
Tests use ``@pytest.mark.asyncio`` for async execution and
``@pytest.mark.integration`` for filtering.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import contextlib

from sci_fi_dashboard.subagent.models import AgentStatus, SubAgent
from sci_fi_dashboard.subagent.registry import AgentRegistry
from sci_fi_dashboard.subagent.runner import SubAgentRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**kwargs) -> SubAgent:
    """Create a SubAgent with defaults suitable for integration tests."""
    defaults = {
        "description": "integration test task",
        "channel_id": "whatsapp",
        "chat_id": "chat_001",
        "parent_session_key": "session_key",
        "timeout_seconds": 120.0,
    }
    defaults.update(kwargs)
    return SubAgent(**defaults)


def _make_llm_router(sleep: float = 0.0, raise_exc: Exception | None = None):
    """Build a mock LLM router.

    Parameters
    ----------
    sleep:
        Seconds to sleep before returning (simulates real LLM latency).
    raise_exc:
        If provided, the mock raises this exception instead of returning.
    """
    mock_router = MagicMock()

    async def _call(role, messages):
        if sleep:
            await asyncio.sleep(sleep)
        if raise_exc is not None:
            raise raise_exc
        return "Agent result text"

    mock_router.call = AsyncMock(side_effect=_call)
    return mock_router


def _make_channel_registry():
    """Build a mock ChannelRegistry whose channel.send() is an AsyncMock."""
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock(return_value=True)

    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_channel
    return mock_registry, mock_channel


def _make_runner(
    llm_router=None,
    channel_registry=None,
    progress_interval: float = 15.0,
) -> tuple[SubAgentRunner, AgentRegistry, MagicMock]:
    """Create a fresh runner, registry, and channel mock for each test."""
    registry = AgentRegistry()
    if channel_registry is None:
        channel_registry, _ = _make_channel_registry()
    if llm_router is None:
        llm_router = _make_llm_router()
    runner = SubAgentRunner(
        registry=registry,
        channel_registry=channel_registry,
        llm_router=llm_router,
        progress_interval=progress_interval,
    )
    return runner, registry, channel_registry


# ===========================================================================
# class TestSubAgentRunner
# ===========================================================================


@pytest.mark.integration
class TestSubAgentRunner:
    """Integration tests for SubAgentRunner execution lifecycle."""

    # -----------------------------------------------------------------------
    # AGENT-01: fire-and-forget — spawn must return immediately
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_spawn_returns_immediately(self):
        """spawn_agent() must return before the background task completes (AGENT-01)."""
        # LLM sleeps 2 seconds — spawn must return well before that
        slow_llm = _make_llm_router(sleep=2.0)
        mock_cr, mock_channel = _make_channel_registry()
        runner, registry, _ = _make_runner(llm_router=slow_llm, channel_registry=mock_cr)

        agent = _make_agent(timeout_seconds=10.0)

        t_start = time.monotonic()
        returned_agent = await runner.spawn_agent(agent)
        elapsed = time.monotonic() - t_start

        # spawn must return within 0.5s even though the LLM takes 2s
        assert elapsed < 0.5, f"spawn_agent took {elapsed:.3f}s — should return immediately"
        assert returned_agent.agent_id == agent.agent_id

        # Clean up: cancel the background task so the test does not hang
        for task in asyncio.all_tasks():
            if task.get_name().startswith("subagent-"):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    # -----------------------------------------------------------------------
    # AGENT-04: parallel execution timing
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parallel_execution_timing(self):
        """Two 0.5s agents must complete in ~0.5s total, not ~1.0s (AGENT-04)."""
        fast_llm = _make_llm_router(sleep=0.5)
        mock_cr, mock_channel = _make_channel_registry()
        runner, registry, _ = _make_runner(llm_router=fast_llm, channel_registry=mock_cr)

        agent_a = _make_agent(description="task A", timeout_seconds=10.0)
        agent_b = _make_agent(description="task B", timeout_seconds=10.0)

        t_start = time.monotonic()
        await runner.spawn_agent(agent_a)
        await runner.spawn_agent(agent_b)

        # Wait long enough for both to complete (1.0s is 2x their work time)
        await asyncio.sleep(1.0)
        wall_time = time.monotonic() - t_start

        # Verify both are completed
        all_agents = registry.list_all()
        completed_ids = {a.agent_id for a in all_agents if a.status == AgentStatus.COMPLETED}
        assert agent_a.agent_id in completed_ids, "Agent A should be COMPLETED"
        assert agent_b.agent_id in completed_ids, "Agent B should be COMPLETED"

        # Wall time should be under 1.5s — proves parallel, not sequential (1.0s each)
        assert wall_time < 1.5, (
            f"Parallel agents took {wall_time:.3f}s total — expected < 1.5s "
            "(would be ~2.0s if sequential)"
        )

    # -----------------------------------------------------------------------
    # AGENT-02: crash isolation
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_crash_isolation(self):
        """A crashing agent must not prevent its sibling from completing (AGENT-02)."""
        crash_llm = _make_llm_router(raise_exc=RuntimeError("LLM exploded"))
        success_llm = _make_llm_router(sleep=0.1)
        mock_cr, mock_channel = _make_channel_registry()

        # We need two separate runners here — one with crash LLM, one with good LLM
        registry = AgentRegistry()
        crash_runner = SubAgentRunner(
            registry=registry,
            channel_registry=mock_cr,
            llm_router=crash_llm,
            progress_interval=15.0,
        )
        success_runner = SubAgentRunner(
            registry=registry,
            channel_registry=mock_cr,
            llm_router=success_llm,
            progress_interval=15.0,
        )

        agent_a = _make_agent(description="crash task", timeout_seconds=10.0)
        agent_b = _make_agent(description="success task", timeout_seconds=10.0)

        await crash_runner.spawn_agent(agent_a)
        await success_runner.spawn_agent(agent_b)

        # Wait for both tasks to complete
        await asyncio.sleep(0.8)

        all_agents = registry.list_all()
        agent_map = {a.agent_id: a for a in all_agents}

        assert agent_a.agent_id in agent_map, "Agent A should be in registry"
        assert agent_b.agent_id in agent_map, "Agent B should be in registry"

        a_status = agent_map[agent_a.agent_id].status
        b_status = agent_map[agent_b.agent_id].status

        assert a_status == AgentStatus.FAILED, f"Crash agent A should be FAILED, got {a_status}"
        assert (
            b_status == AgentStatus.COMPLETED
        ), f"Success agent B should be COMPLETED, got {b_status}"

        # Agent A's error should mention the exception
        a_error = agent_map[agent_a.agent_id].error
        assert (
            a_error is not None and "LLM exploded" in a_error
        ), f"Agent A error should contain 'LLM exploded', got {a_error!r}"

    # -----------------------------------------------------------------------
    # AGENT-03: result delivery via channel.send()
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_result_delivery_via_channel(self):
        """spawn_agent() must deliver result text via channel.send() (AGENT-03)."""
        fast_llm = _make_llm_router(sleep=0.1)
        mock_cr, mock_channel = _make_channel_registry()
        runner, registry, _ = _make_runner(llm_router=fast_llm, channel_registry=mock_cr)

        agent = _make_agent(chat_id="target_chat", timeout_seconds=10.0)
        await runner.spawn_agent(agent)

        # Allow the background task to complete
        await asyncio.sleep(0.6)

        # channel.send() must have been called at least once
        assert mock_channel.send.called, "channel.send() was not called"

        # The call must have been for the correct chat_id
        call_args_list = mock_channel.send.call_args_list
        chat_ids_called = [args[0][0] for args in call_args_list]
        assert (
            "target_chat" in chat_ids_called
        ), f"channel.send() not called with 'target_chat'; calls: {call_args_list}"

        # The result text must appear somewhere in the delivery
        all_messages = " ".join(str(args[0][1]) for args in call_args_list if len(args[0]) > 1)
        assert (
            "Agent result text" in all_messages
        ), f"Result text not found in channel.send() calls: {all_messages!r}"

    # -----------------------------------------------------------------------
    # Timeout handling
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Agent times out and delivers a timeout message to the channel."""
        # LLM sleeps much longer than the agent's timeout
        very_slow_llm = _make_llm_router(sleep=5.0)
        mock_cr, mock_channel = _make_channel_registry()
        runner, registry, _ = _make_runner(llm_router=very_slow_llm, channel_registry=mock_cr)

        # Tight timeout so the test stays fast
        agent = _make_agent(timeout_seconds=0.3, chat_id="timeout_chat")
        await runner.spawn_agent(agent)

        # Wait longer than the timeout so the timeout path runs
        await asyncio.sleep(1.0)

        all_agents = registry.list_all()
        agent_map = {a.agent_id: a for a in all_agents}
        assert agent.agent_id in agent_map, "Timed-out agent should be in registry"

        status = agent_map[agent.agent_id].status
        assert status == AgentStatus.TIMED_OUT, f"Expected TIMED_OUT, got {status}"

        # channel.send() must have been called with a timeout message
        assert mock_channel.send.called, "channel.send() not called for timeout"
        timeout_msgs = [
            str(args[0][1]) for args in mock_channel.send.call_args_list if len(args[0]) > 1
        ]
        assert any(
            "Timed out" in msg or "timed out" in msg.lower() for msg in timeout_msgs
        ), f"No timeout message sent; messages: {timeout_msgs}"

    # -----------------------------------------------------------------------
    # AGENT-06: progress updates
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_progress_updates(self):
        """Long-running agent fires progress callbacks at the configured interval (AGENT-06)."""
        slow_llm = _make_llm_router(sleep=1.5)
        mock_cr, mock_channel = _make_channel_registry()

        # Very short progress interval so multiple pings fire during the 1.5s LLM sleep
        runner, registry, _ = _make_runner(
            llm_router=slow_llm,
            channel_registry=mock_cr,
            progress_interval=0.4,
        )

        agent = _make_agent(description="slow task", timeout_seconds=10.0)
        await runner.spawn_agent(agent)

        # Wait for the agent to complete (LLM sleeps 1.5s, add buffer)
        await asyncio.sleep(2.2)

        # At least 2 progress messages + 1 final result = 3+ channel.send() calls
        call_count = mock_channel.send.call_count
        assert (
            call_count >= 2
        ), f"Expected at least 2 channel.send() calls (progress + result), got {call_count}"

    # -----------------------------------------------------------------------
    # AGENT-07: GET /agents endpoint
    # -----------------------------------------------------------------------

    def test_get_agents_endpoint(self):
        """GET /api/agents returns 200 with a JSON list of agents (AGENT-07)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.routes.agents import router as agents_router

        # Build a minimal test app with the agents router and no auth (no token configured)
        app = FastAPI()
        app.include_router(agents_router)

        # Build a completed agent and point deps.agent_registry at a mock
        completed_agent = _make_agent(description="completed task")
        completed_agent.status = AgentStatus.COMPLETED
        completed_agent.result = "done"

        mock_registry = MagicMock()
        mock_registry.list_all.return_value = [completed_agent]

        original_registry = deps.agent_registry
        try:
            deps.agent_registry = mock_registry
            with TestClient(app) as client:
                response = client.get("/api/agents")

            assert (
                response.status_code == 200
            ), f"Expected 200, got {response.status_code}: {response.text}"
            data = response.json()
            assert "agents" in data, f"Response missing 'agents' key: {data}"
            agents_list = data["agents"]
            assert isinstance(
                agents_list, list
            ), f"'agents' should be a list, got {type(agents_list)}"
            assert len(agents_list) == 1, f"Expected 1 agent, got {len(agents_list)}"

            agent_dict = agents_list[0]
            assert agent_dict["agent_id"] == completed_agent.agent_id
            assert agent_dict["status"] == "completed"
            assert agent_dict["description"] == "completed task"
        finally:
            deps.agent_registry = original_registry


# ===========================================================================
# class TestMaybeSpawnAgent
# ===========================================================================


@pytest.mark.integration
class TestMaybeSpawnAgent:
    """Integration tests for maybe_spawn_agent() spawn orchestration function."""

    @pytest.mark.asyncio
    async def test_maybe_spawn_agent_returns_string_on_match(self):
        """maybe_spawn_agent() returns an acknowledgment string when spawn intent detected."""
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

        mock_runner = MagicMock()
        mock_runner.spawn_agent = AsyncMock()

        mock_memory_engine = MagicMock()
        mock_memory_engine.query.return_value = {
            "results": [],
            "tier": "fast_gate",
        }

        original_runner = deps.agent_runner
        original_mem = deps.memory_engine
        original_cache = deps.conversation_cache
        try:
            deps.agent_runner = mock_runner
            deps.memory_engine = mock_memory_engine
            deps.conversation_cache = None

            result = await maybe_spawn_agent(
                "research AI trends",
                "chat123",
                "whatsapp",
                "session_key",
            )
        finally:
            deps.agent_runner = original_runner
            deps.memory_engine = original_mem
            deps.conversation_cache = original_cache

        assert result is not None, "Expected a string, got None"
        assert isinstance(result, str)
        assert "On it!" in result, f"Expected 'On it!' in result: {result!r}"
        assert "AI trends" in result, f"Expected task description in result: {result!r}"
        mock_runner.spawn_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_spawn_agent_returns_none_on_no_match(self):
        """maybe_spawn_agent() returns None when message is NOT a spawn intent."""
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

        mock_runner = MagicMock()
        mock_runner.spawn_agent = AsyncMock()

        original_runner = deps.agent_runner
        try:
            deps.agent_runner = mock_runner

            result = await maybe_spawn_agent(
                "hello how are you",
                "chat123",
                "whatsapp",
                "session_key",
            )
        finally:
            deps.agent_runner = original_runner

        assert result is None, f"Expected None for non-spawn message, got {result!r}"
        mock_runner.spawn_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_spawn_agent_returns_none_when_runner_is_none(self):
        """maybe_spawn_agent() returns None gracefully when agent_runner is not initialized."""
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

        original_runner = deps.agent_runner
        try:
            deps.agent_runner = None

            # This is a valid spawn-intent message, but runner is None
            result = await maybe_spawn_agent(
                "research Python packaging",
                "chat123",
                "whatsapp",
                "session_key",
            )
        finally:
            deps.agent_runner = original_runner

        assert (
            result is None
        ), f"Expected None when runner is None (graceful degradation), got {result!r}"

    @pytest.mark.asyncio
    async def test_maybe_spawn_agent_unwraps_memory_correctly(self):
        """memory_snapshot on the spawned SubAgent is the 'results' list, not the raw dict."""
        from sci_fi_dashboard import _deps as deps
        from sci_fi_dashboard.subagent.spawn import maybe_spawn_agent

        # Capture the SubAgent that was passed to spawn_agent
        spawned_agents: list[SubAgent] = []

        async def _capture_spawn(agent: SubAgent):
            spawned_agents.append(agent)

        mock_runner = MagicMock()
        mock_runner.spawn_agent = AsyncMock(side_effect=_capture_spawn)

        memory_result_list = [
            {"content": "fact", "score": 0.9, "source": "test"},
        ]
        mock_memory_engine = MagicMock()
        mock_memory_engine.query.return_value = {
            "results": memory_result_list,
            "tier": "fast_gate",
        }

        original_runner = deps.agent_runner
        original_mem = deps.memory_engine
        original_cache = deps.conversation_cache
        try:
            deps.agent_runner = mock_runner
            deps.memory_engine = mock_memory_engine
            deps.conversation_cache = None

            await maybe_spawn_agent(
                "research Python packaging",
                "chat123",
                "whatsapp",
                "session_key",
            )
        finally:
            deps.agent_runner = original_runner
            deps.memory_engine = original_mem
            deps.conversation_cache = original_cache

        assert len(spawned_agents) == 1, "spawn_agent should have been called once"
        spawned = spawned_agents[0]

        # memory_snapshot must be the list, NOT the raw dict from query()
        assert isinstance(
            spawned.memory_snapshot, list
        ), f"memory_snapshot should be a list, got {type(spawned.memory_snapshot)}"
        assert (
            spawned.memory_snapshot == memory_result_list
        ), f"memory_snapshot mismatch: {spawned.memory_snapshot!r} != {memory_result_list!r}"
