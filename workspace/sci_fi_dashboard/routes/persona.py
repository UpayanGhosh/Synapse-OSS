"""Persona management endpoints."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import _require_gateway_auth, validate_api_key
from sci_fi_dashboard.retriever import get_db_stats

logger = logging.getLogger(__name__)
router = APIRouter()

# Canonical SBS profile layers (mirrors ProfileManager.LAYERS).
# Hard-coded so PATCH validation does not depend on any SBS instance being
# resolvable for the requested user.
LAYERS: frozenset[str] = frozenset(
    {
        "core_identity",
        "linguistic",
        "emotional_state",
        "domain",
        "interaction",
        "vocabulary",
        "exemplars",
        "meta",
    }
)


def _resolve_sbs(user: str):
    """Return the SBSOrchestrator registered for ``user`` or None.

    ``deps.sbs_registry`` is a ``dict[persona_id -> SBSOrchestrator]``
    populated from ``personas.yaml`` (default keys: ``the_creator``,
    ``the_partner``).  Falls back to None when the persona id is unknown
    so the caller can raise a 404.
    """
    return getattr(deps, "sbs_registry", {}).get(user)


class ProfileOverride(BaseModel):
    """Body schema for PATCH /persona/profile/{user}/{layer}."""

    value: Any  # Layer payload — every layer except ``meta`` is a JSON object.
    reason: str | None = None


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
    """Show live SBS stats for Synapse dashboard."""
    stats = {pid: sbs.get_profile_summary() for pid, sbs in deps.sbs_registry.items()}
    return {"profiles": stats}


@router.get(
    "/persona/profile/{user}",
    summary="Read live SBS profile",
    dependencies=[Depends(_require_gateway_auth)],
)
async def get_profile(user: str):
    """Return all 8 SBS profile layers for ``user`` plus rebuild metadata.

    The response shape is::

        {
          "user": "the_creator",
          "layers": {<layer_name>: <layer_dict>, ...},
          "last_rebuild_at": "2025-04-01T12:34:00",  # from meta.last_batch_run
          "profile_version": 7
        }
    """
    sbs = _resolve_sbs(user)
    if sbs is None:
        known = sorted(getattr(deps, "sbs_registry", {}).keys())
        raise HTTPException(
            status_code=404,
            detail=f"unknown user: {user}; known personas: {known}",
        )
    try:
        full = sbs.profile_mgr.load_full_profile()
    except Exception as exc:  # pragma: no cover — defensive: corrupt JSON, IO error
        logger.exception("Failed to load profile for %s", user)
        raise HTTPException(status_code=500, detail=f"profile read failed: {exc}") from None

    meta = full.get("meta", {}) if isinstance(full, dict) else {}
    return {
        "user": user,
        "layers": full,
        "last_rebuild_at": meta.get("last_batch_run"),
        "profile_version": meta.get("current_version", 0),
    }


@router.patch(
    "/persona/profile/{user}/{layer}",
    summary="Override one SBS profile layer",
    dependencies=[Depends(_require_gateway_auth)],
)
async def patch_profile(user: str, layer: str, body: ProfileOverride):
    """Replace a single profile layer and append an audit-trail entry to ``meta``.

    Notes:
        * ``core_identity`` is immutable in ``ProfileManager.save_layer`` and
          this endpoint refuses it up-front with a 403 to give a clearer error
          than the underlying ``PermissionError``.
        * The override entry is appended to ``meta.overrides`` so the audit
          log persists across restarts alongside the profile itself.
    """
    if layer not in LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown layer: {layer}; allowed: {sorted(LAYERS)}",
        )
    if layer == "core_identity":
        raise HTTPException(
            status_code=403,
            detail="core_identity is immutable; manual edit only",
        )
    if not isinstance(body.value, dict):
        # Every non-core layer is a JSON object on disk; reject scalar/array
        # payloads early to avoid silently corrupting the layer file.
        raise HTTPException(
            status_code=400,
            detail=f"value must be a JSON object for layer '{layer}'",
        )

    sbs = _resolve_sbs(user)
    if sbs is None:
        known = sorted(getattr(deps, "sbs_registry", {}).keys())
        raise HTTPException(
            status_code=404,
            detail=f"unknown user: {user}; known personas: {known}",
        )

    try:
        # 1. Persist the new layer payload.
        sbs.profile_mgr.save_layer(layer, body.value)

        # 2. Append an audit-trail entry to meta.overrides.
        meta = sbs.profile_mgr.load_layer("meta")
        overrides = meta.get("overrides")
        if not isinstance(overrides, list):
            overrides = []
        overrides.append(
            {
                "layer": layer,
                "reason": body.reason or "user override",
                "at": datetime.now().isoformat(),
            }
        )
        # Cap audit log to the most recent 200 entries to keep meta.json bounded.
        meta["overrides"] = overrides[-200:]
        sbs.profile_mgr.save_layer("meta", meta)
    except PermissionError as exc:
        # Defensive — should not fire because we already 403 on core_identity above.
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("Failed to override profile layer %s for %s", layer, user)
        raise HTTPException(status_code=500, detail=f"profile write failed: {exc}") from None

    return {"ok": True, "user": user, "layer": layer}
