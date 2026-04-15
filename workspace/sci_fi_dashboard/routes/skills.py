"""Skill inventory endpoint.

GET /skills — return all loaded skills with their metadata.

Response shape::

    {
        "skills": [
            {"name": str, "description": str, "version": str, "author": str},
            ...
        ],
        "count": int
    }

When the skill system has not been initialised (e.g. during bare startup
without a skills directory), returns count=0 with a status hint.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

router = APIRouter(tags=["skills"])
logger = logging.getLogger(__name__)


@router.get("/skills")
async def list_skills():
    """Return all loaded skills with metadata.

    Reads from the module-level ``skill_registry`` singleton in
    ``sci_fi_dashboard._deps``. If the registry has not been initialised yet
    (attribute absent or None), returns an empty response with a status hint
    rather than raising a 500.
    """
    from sci_fi_dashboard import _deps as deps

    registry = getattr(deps, "skill_registry", None)

    if registry is None:
        return {"skills": [], "count": 0, "status": "skill_system_not_initialized"}

    manifests = registry.list_skills()
    return {
        "skills": [
            {
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "author": m.author,
            }
            for m in manifests
        ],
        "count": len(manifests),
    }
