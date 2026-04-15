"""Persona management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import _require_gateway_auth, validate_api_key
from sci_fi_dashboard.retriever import get_db_stats

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/persona/rebuild")
async def rebuild_personas(request: Request):
    """Rebuild all persona profiles using SBS."""
    validate_api_key(request)
    try:
        for sbs in deps.sbs_registry.values():
            sbs.force_batch(full_rebuild=True)
        return {"status": "rebuilt", "personas": list(deps.sbs_registry.keys())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/persona/status", dependencies=[Depends(_require_gateway_auth)])
def persona_status():
    """Show current persona profile stats from SBS."""
    stats = {pid: sbs.get_profile_summary() for pid, sbs in deps.sbs_registry.items()}
    db = get_db_stats()
    return {"profiles": stats, "memory_db": db}


@router.get("/sbs/status", dependencies=[Depends(_require_gateway_auth)])
def sbs_status():
    """Show live SBS stats for sci-fi dashboard."""
    stats = {pid: sbs.get_profile_summary() for pid, sbs in deps.sbs_registry.items()}
    return {"profiles": stats}
