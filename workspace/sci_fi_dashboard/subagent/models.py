"""subagent/models.py — SubAgent dataclass and AgentStatus enum.

Defines the core data contracts for the subagent system. This module has
NO heavy dependencies — it must remain import-safe for circular-free wiring
across the gateway and route modules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AgentStatus(StrEnum):
    """Lifecycle states for a SubAgent task."""

    SPAWNING = "spawning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SubAgent:
    """
    Captures the full lifecycle of a background agent task.

    Fields mirror the MessageTask pattern from gateway/queue.py, extended with
    subagent-specific fields: context/memory snapshots, progress updates, timeout.

    The ``context_snapshot`` and ``memory_snapshot`` fields hold frozen copies
    of the parent conversation state and are treated as read-only after creation.
    """

    # Identity
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""

    # Lifecycle state
    status: AgentStatus = AgentStatus.SPAWNING

    # Origin — used to deliver results back to the spawning conversation
    channel_id: str = "default"
    chat_id: str = ""
    parent_session_key: str = ""

    # Frozen context injected at spawn time (read-only from this point forward)
    context_snapshot: list[dict] = field(default_factory=list)
    memory_snapshot: list[dict] = field(default_factory=list)

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Output
    result: str | None = None
    error: str | None = None
    progress_message: str | None = None

    # Execution config
    timeout_seconds: float = 120.0

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def duration_seconds(self) -> float | None:
        """Return elapsed seconds between started_at and completed_at, or None."""
        if self.started_at is not None and self.completed_at is not None:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_api_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this agent.

        All datetime fields are converted to ISO-8601 strings. The status enum
        is returned as its string value. Snapshot lists are omitted from the
        API response to avoid leaking conversation history over the wire.
        """
        return {
            "agent_id": self.agent_id,
            "description": self.description,
            "status": str(self.status),
            "channel_id": self.channel_id,
            "chat_id": self.chat_id,
            "parent_session_key": self.parent_session_key,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (self.completed_at.isoformat() if self.completed_at else None),
            "duration_seconds": self.duration_seconds,
            "result": self.result,
            "error": self.error,
            "progress_message": self.progress_message,
            "timeout_seconds": self.timeout_seconds,
        }
