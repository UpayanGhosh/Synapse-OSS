"""routes/agents.py — SubAgent inspection and control endpoints.

Follows the sessions.py pattern: lazy singleton access via _deps to avoid
circular imports at module load time.

Routes:
    GET  /api/agents               — list all active + recently archived agents
    GET  /api/agents/{agent_id}    — single agent detail, or 404
    POST /api/agents/{agent_id}/cancel — cancel a running agent, or 404
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from sci_fi_dashboard.middleware import _require_gateway_auth

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/agents", dependencies=[Depends(_require_gateway_auth)])
async def list_agents():
    """Return all active and recently completed agents.

    Combines active agents (status: spawning/running) with archived agents
    (completed/failed/cancelled/timed_out within the last hour). Stale archive
    entries are pruned lazily during this call.
    """
    from sci_fi_dashboard import _deps as deps

    registry = deps.agent_registry
    if registry is None:
        return {"agents": []}
    return {"agents": [agent.to_api_dict() for agent in registry.list_all()]}


@router.get("/api/agents/{agent_id}", dependencies=[Depends(_require_gateway_auth)])
async def get_agent(agent_id: str):
    """Return detail for a single agent by ID.

    Searches both active agents and the archive. Returns 404 if the agent
    is not found (or has been pruned from the archive).
    """
    from sci_fi_dashboard import _deps as deps

    registry = deps.agent_registry
    if registry is not None:
        # Check active agents first (fast path)
        agent = registry.get(agent_id)
        if agent is not None:
            return agent.to_api_dict()
        # Fall back to archive scan
        for archived in registry._archive:
            if archived.agent_id == agent_id:
                return archived.to_api_dict()

    raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")


@router.post(
    "/api/agents/{agent_id}/cancel",
    dependencies=[Depends(_require_gateway_auth)],
)
async def cancel_agent(agent_id: str):
    """Cancel a running agent by ID.

    Returns 200 on success, 404 if the agent is not found or already terminal.
    """
    from sci_fi_dashboard import _deps as deps

    registry = deps.agent_registry
    if registry is not None and registry.cancel(agent_id):
        logger.info("[agents] Agent %s cancelled via API", agent_id)
        return {"status": "cancelled", "agent_id": agent_id}

    raise HTTPException(
        status_code=404,
        detail=f"Agent not found or not cancellable: {agent_id}",
    )
