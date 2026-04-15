"""subagent/registry.py — AgentRegistry lifecycle manager.

Mirrors the ChannelRegistry pattern from channels/registry.py:
  - dict-based store for active agents
  - set-based GC anchor for asyncio.Task references
  - explicit lifecycle transitions: spawn → running → completed/failed/timed_out

Archive TTL is 1 hour by default. Stale archive entries are pruned lazily
on every list_all() call — no background task needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from .models import AgentStatus, SubAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Singleton-style registry for SubAgent instances.

    Usage inside FastAPI lifespan (same pattern as ChannelRegistry):

        agent_registry = AgentRegistry()
        deps.agent_registry = agent_registry

    Spawning a new agent:

        agent = SubAgent(description="summarise thread", channel_id="whatsapp", ...)
        agent_registry.spawn(agent)
        task = asyncio.create_task(run_agent(agent))
        agent_registry.attach_task(agent.agent_id, task)
    """

    def __init__(self, archive_ttl_seconds: float = 3600.0) -> None:
        self._agents: dict[str, SubAgent] = {}
        # GC anchor — prevents asyncio from garbage-collecting running tasks.
        # Per pipeline_helpers.py pattern: add task, register discard callback.
        self._task_refs: set[asyncio.Task] = set()
        self._archive: list[SubAgent] = []
        self._archive_ttl_seconds = archive_ttl_seconds

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def spawn(self, agent: SubAgent) -> SubAgent:
        """Register a new agent and return it.

        The agent starts in SPAWNING status. Call attach_task() once the
        asyncio.Task has been created to transition to RUNNING.

        Args:
            agent: A SubAgent instance (typically freshly constructed).

        Returns:
            The same agent instance (allows chaining).

        Raises:
            ValueError: If an agent with the same agent_id is already registered.
        """
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent '{agent.agent_id}' already registered")
        self._agents[agent.agent_id] = agent
        logger.info("[AgentRegistry] Spawned agent %s: %s", agent.agent_id, agent.description)
        return agent

    def attach_task(self, agent_id: str, task: asyncio.Task) -> None:
        """Anchor the asyncio.Task and transition agent to RUNNING.

        The task is added to _task_refs (GC anchor) and a done callback is
        registered to remove it automatically when the task finishes.

        Args:
            agent_id: ID of the agent that owns this task.
            task: The asyncio.Task running the agent coroutine.
        """
        self._task_refs.add(task)
        task.add_done_callback(self._task_refs.discard)

        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("[AgentRegistry] attach_task: agent %s not found", agent_id)
            return

        agent.status = AgentStatus.RUNNING
        agent.started_at = datetime.now()
        logger.debug("[AgentRegistry] Agent %s transitioned to RUNNING", agent_id)

    def get(self, agent_id: str) -> SubAgent | None:
        """Return the active agent for the given ID, or None if not found.

        Note: Does NOT search the archive. Use list_all() to include archived agents.
        """
        return self._agents.get(agent_id)

    def cancel(self, agent_id: str) -> bool:
        """Cancel a running agent task.

        Cancels the asyncio.Task (if found in _task_refs), sets agent status to
        CANCELLED, and archives the agent.

        Args:
            agent_id: ID of the agent to cancel.

        Returns:
            True if the agent was found and cancelled, False otherwise.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("[AgentRegistry] cancel: agent %s not found", agent_id)
            return False

        # Cancel the underlying asyncio.Task if we can find it.
        # _task_refs is a set — we cannot look up by agent_id directly, so we
        # cancel any task whose name matches the convention "agent-<id>".
        for task in list(self._task_refs):
            if task.get_name() == f"agent-{agent_id}":
                task.cancel()
                logger.info("[AgentRegistry] Cancelled task for agent %s", agent_id)
                break

        agent.status = AgentStatus.CANCELLED
        agent.completed_at = datetime.now()
        self._archive_agent(agent_id)
        logger.info("[AgentRegistry] Agent %s cancelled", agent_id)
        return True

    # ------------------------------------------------------------------
    # Terminal transitions
    # ------------------------------------------------------------------

    def complete(self, agent_id: str, result: str) -> None:
        """Mark agent as COMPLETED with the given result text and archive it.

        Args:
            agent_id: ID of the agent that finished successfully.
            result: The agent's final text output.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("[AgentRegistry] complete: agent %s not found", agent_id)
            return

        agent.status = AgentStatus.COMPLETED
        agent.result = result
        agent.completed_at = datetime.now()
        self._archive_agent(agent_id)
        logger.info(
            "[AgentRegistry] Agent %s completed (%.1fs)",
            agent_id,
            agent.duration_seconds or 0.0,
        )

    def fail(self, agent_id: str, error: str) -> None:
        """Mark agent as FAILED with the given error message and archive it.

        Args:
            agent_id: ID of the agent that encountered an error.
            error: Human-readable error description.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("[AgentRegistry] fail: agent %s not found", agent_id)
            return

        agent.status = AgentStatus.FAILED
        agent.error = error
        agent.completed_at = datetime.now()
        self._archive_agent(agent_id)
        logger.warning("[AgentRegistry] Agent %s failed: %s", agent_id, error)

    def timeout(self, agent_id: str) -> None:
        """Mark agent as TIMED_OUT and archive it.

        Args:
            agent_id: ID of the agent that exceeded its timeout_seconds limit.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            logger.warning("[AgentRegistry] timeout: agent %s not found", agent_id)
            return

        agent.status = AgentStatus.TIMED_OUT
        agent.completed_at = datetime.now()
        self._archive_agent(agent_id)
        logger.warning("[AgentRegistry] Agent %s timed out", agent_id)

    # ------------------------------------------------------------------
    # Listing + pruning
    # ------------------------------------------------------------------

    def list_all(self) -> list[SubAgent]:
        """Return active agents plus recently archived agents.

        Prunes archive entries older than _archive_ttl_seconds before building
        the result. This is a lazy GC approach — no background task required.

        Returns:
            List of SubAgent instances ordered by created_at descending
            (active first, then archived).
        """
        self._prune_archive()
        active = list(self._agents.values())
        return active + list(self._archive)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _archive_agent(self, agent_id: str) -> None:
        """Move an agent from _agents to _archive and clean up task refs.

        Internal method — only called by the terminal transition methods
        (complete, fail, timeout, cancel).
        """
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            return
        self._archive.append(agent)
        logger.debug("[AgentRegistry] Agent %s archived", agent_id)

    def _prune_archive(self) -> None:
        """Remove archive entries older than _archive_ttl_seconds."""
        cutoff = datetime.now() - timedelta(seconds=self._archive_ttl_seconds)
        before = len(self._archive)
        self._archive = [a for a in self._archive if (a.completed_at or a.created_at) > cutoff]
        pruned = before - len(self._archive)
        if pruned:
            logger.debug("[AgentRegistry] Pruned %d stale archive entries", pruned)
