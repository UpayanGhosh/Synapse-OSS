"""
SubAgentRunner — isolated asyncio execution engine for sub-agents.

Responsibilities
----------------
- Spawn each sub-agent as an independent asyncio.Task (AGENT-04: parallel).
- Provide a hard try/except crash boundary so any agent failure is contained
  and never propagates to the parent conversation (AGENT-02: isolation).
- Wrap execution in asyncio.wait_for with the agent's timeout_seconds (AGENT-06).
- Deliver results via the same channel_registry.send() path used by the parent
  (AGENT-03: result delivery).
- Pass only a frozen memory_snapshot (plain list[dict]) to the agent — never a
  reference to the live MemoryEngine (AGENT-05: scoped context).
- Fire periodic progress callbacks via ProgressReporter for long-running agents
  (AGENT-06: progress updates).

Usage::

    runner = SubAgentRunner(
        registry=agent_registry,
        channel_registry=channel_registry,
        llm_router=llm_router,
        progress_interval=15.0,
    )
    agent = await runner.spawn_agent(agent)  # returns immediately
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .progress import ProgressReporter

if TYPE_CHECKING:
    from .models import SubAgent
    from .registry import AgentRegistry
    from ..channels.registry import ChannelRegistry
    from ..llm_router import SynapseLLMRouter

logger = logging.getLogger(__name__)

# GC anchor — prevents agent execution tasks from being garbage-collected while
# they are still running (same pattern as pipeline_helpers._background_tasks).
_agent_tasks: set[asyncio.Task] = set()


class SubAgentRunner:
    """Execution engine that spawns and manages sub-agent asyncio tasks.

    Parameters
    ----------
    registry:
        AgentRegistry that tracks the lifecycle of all sub-agents.
    channel_registry:
        ChannelRegistry used to retrieve the output channel for result delivery.
    llm_router:
        SynapseLLMRouter instance for LLM inference inside the agent.
    progress_interval:
        Seconds between automatic progress updates sent to the user (default 15 s).
    """

    def __init__(
        self,
        registry: "AgentRegistry",
        channel_registry: "ChannelRegistry",
        llm_router: "SynapseLLMRouter",
        progress_interval: float = 15.0,
    ) -> None:
        self.registry = registry
        self.channel_registry = channel_registry
        self.llm_router = llm_router
        self.progress_interval = progress_interval

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def spawn_agent(self, agent: "SubAgent") -> "SubAgent":
        """Register and start an agent as an independent asyncio task.

        This method returns immediately after the task is created.  The caller
        receives the registered agent object so it can inspect status or
        agent_id without blocking on the result.

        Parameters
        ----------
        agent:
            Fully populated SubAgent dataclass (from models.py).  Its
            *context_snapshot* and *memory_snapshot* must already be frozen
            copies — this method does not snapshot anything.

        Returns
        -------
        SubAgent
            The registered agent (same object, now with SPAWNING status set by
            registry.spawn()).
        """
        # Register the agent and transition to SPAWNING status.
        agent = self.registry.spawn(agent)

        # Create an isolated asyncio.Task for this agent.
        task = asyncio.create_task(
            self._run_agent(agent),
            name=f"subagent-{agent.agent_id}",
        )

        # Attach the task to the registry (transitions to RUNNING, stores ref).
        self.registry.attach_task(agent.agent_id, task)

        # GC anchor: keep a strong reference so the event loop doesn't discard
        # the task before it finishes.
        _agent_tasks.add(task)
        task.add_done_callback(_agent_tasks.discard)

        logger.info(
            "Spawned sub-agent %s | description=%r | timeout=%.1fs",
            agent.agent_id,
            agent.description[:80],
            agent.timeout_seconds,
        )
        return agent

    # ------------------------------------------------------------------
    # Internal execution pipeline
    # ------------------------------------------------------------------

    async def _run_agent(self, agent: "SubAgent") -> None:
        """Top-level crash isolation boundary for a single agent execution.

        Any non-cancellation exception raised inside ``_execute()`` is caught
        here, logged, recorded in the registry, and converted to a user-facing
        error message that is delivered via the normal channel path.  The
        parent conversation loop is never affected.
        """
        try:
            result = await asyncio.wait_for(
                self._execute(agent),
                timeout=agent.timeout_seconds,
            )
            self.registry.complete(agent.agent_id, result)
            await self._deliver_result(agent, result)

        except asyncio.TimeoutError:
            logger.warning(
                "Sub-agent %s timed out after %.1fs",
                agent.agent_id,
                agent.timeout_seconds,
            )
            self.registry.timeout(agent.agent_id)
            await self._deliver_result(
                agent,
                f"[Timed out after {agent.timeout_seconds}s] "
                "I wasn't able to finish this task in time.",
            )

        except asyncio.CancelledError:
            # Re-raise per asyncio contract — cancellation must propagate.
            logger.info("Sub-agent %s was cancelled", agent.agent_id)
            raise

        except Exception as exc:  # noqa: BLE001
            logger.exception("Sub-agent %s failed with an unhandled exception", agent.agent_id)
            self.registry.fail(agent.agent_id, str(exc))
            await self._deliver_result(
                agent,
                f"[Error] I encountered a problem: {exc}",
            )

        finally:
            # Nothing to clean up here — ProgressReporter is stopped inside
            # _execute's own finally block so it is cancelled even on timeout.
            pass

    async def _execute(self, agent: "SubAgent") -> str:
        """Run the actual agent work: build prompt, call LLM, return result.

        The agent only sees ``context_snapshot`` and ``memory_snapshot``
        (plain list[dict]).  It never holds a reference to the live
        MemoryEngine — read-only isolation per AGENT-05.

        A ProgressReporter is started here and stopped in the finally block
        regardless of whether the LLM call succeeds or fails.
        """
        reporter = ProgressReporter(
            agent_id=agent.agent_id,
            interval_seconds=self.progress_interval,
            callback=lambda aid, msg: self._send_progress(agent, msg),
        )
        reporter.start()

        try:
            messages = self._build_messages(agent)
            result = await self.llm_router.call("analysis", messages)
            return result

        finally:
            reporter.stop()

    def _build_messages(self, agent: "SubAgent") -> list[dict]:
        """Assemble the messages list sent to the LLM.

        Message structure:
        1. System prompt — role + task description.
        2. (Optional) Conversation context snapshot — last N turns.
        3. (Optional) Memory snapshot — relevant memories for the task.
        4. Final user message — the task description the agent must complete.
        """
        system_prompt = (
            "You are a sub-agent of Synapse. "
            f"Your task: {agent.description}. "
            "Work efficiently and return a clear, complete answer."
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Include frozen conversation context if available.
        if agent.context_snapshot:
            formatted_context = self._format_snapshot(agent.context_snapshot)
            messages.append(
                {
                    "role": "user",
                    "content": f"Here is the relevant conversation context:\n{formatted_context}",
                }
            )

        # Include frozen memory snapshot if available.
        if agent.memory_snapshot:
            formatted_memories = self._format_snapshot(agent.memory_snapshot)
            messages.append(
                {
                    "role": "user",
                    "content": f"Here are relevant memories:\n{formatted_memories}",
                }
            )

        # Final instruction — the concrete task to complete.
        messages.append({"role": "user", "content": agent.description})

        return messages

    @staticmethod
    def _format_snapshot(snapshot: list[dict]) -> str:
        """Convert a list-of-dict snapshot into a readable text block.

        Each dict is rendered as ``key: value`` pairs separated by blank lines.
        Falls back to repr() for non-dict items.
        """
        parts: list[str] = []
        for item in snapshot:
            if isinstance(item, dict):
                lines = [f"{k}: {v}" for k, v in item.items()]
                parts.append("\n".join(lines))
            else:
                parts.append(repr(item))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Delivery helpers
    # ------------------------------------------------------------------

    async def _deliver_result(self, agent: "SubAgent", text: str) -> None:
        """Send the agent's final result to the user via the channel.

        Delivery failures are swallowed so they never propagate back into
        ``_run_agent`` and affect error accounting.
        """
        try:
            channel = self.channel_registry.get(agent.channel_id)
            if channel is None:
                logger.warning(
                    "Cannot deliver result for agent %s — channel %r not found",
                    agent.agent_id,
                    agent.channel_id,
                )
                return

            formatted = f"[Agent complete] {agent.description}\n\n{text}"
            await channel.send(agent.chat_id, formatted)

        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to deliver result for agent %s to channel %r",
                agent.agent_id,
                agent.channel_id,
            )

    async def _send_progress(self, agent: "SubAgent", message: str) -> None:
        """Send an intermediate progress update to the user.

        Progress delivery failures are always swallowed — a failed progress
        ping must never abort the agent's actual work.
        """
        try:
            channel = self.channel_registry.get(agent.channel_id)
            if channel is None:
                return

            progress_text = f"[Still working on: {agent.description}] {message}"
            await channel.send(agent.chat_id, progress_text)

            # Persist the latest progress message on the agent dataclass so
            # callers (e.g. status API endpoints) can inspect it.
            agent.progress_message = message

        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to send progress for agent %s to channel %r",
                agent.agent_id,
                agent.channel_id,
            )
