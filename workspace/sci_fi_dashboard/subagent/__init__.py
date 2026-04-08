"""subagent — SubAgent lifecycle management package.

Exports:
    SubAgent       — dataclass capturing agent task, status, timing, result
    AgentStatus    — StrEnum of agent lifecycle states
    AgentRegistry  — CRUD manager for spawning and tracking agents
"""

from .models import AgentStatus, SubAgent
from .registry import AgentRegistry

__all__ = ["AgentStatus", "SubAgent", "AgentRegistry"]
