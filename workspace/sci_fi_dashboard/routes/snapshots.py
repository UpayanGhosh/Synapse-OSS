"""GET /snapshots — list all Zone 2 snapshots with metadata."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import _require_gateway_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["snapshots"])


@router.get("/snapshots", dependencies=[Depends(_require_gateway_auth)])
async def list_snapshots():
    """Return all snapshots sorted newest-first.

    Requires gateway_token auth via existing middleware (T-02-05).
    Returns an empty list when no snapshots exist yet.
    """
    if deps.snapshot_engine is None:
        raise HTTPException(status_code=503, detail="Snapshot engine not initialized")

    snapshots = deps.snapshot_engine.list_snapshots()
    return [
        {
            "id": s.id,
            "timestamp": s.timestamp,
            "description": s.description,
            "change_type": s.change_type,
            "zone2_paths": list(s.zone2_paths),
            "pre_snapshot_id": s.pre_snapshot_id,
        }
        for s in snapshots
    ]
