"""Health and status endpoints."""

import logging

from fastapi import APIRouter, Depends

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import _require_gateway_auth
from sci_fi_dashboard.retriever import get_db_stats

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def root():
    return {"status": "online", "soul": "operational", "version": "v2.0"}


@router.get("/health")
async def health():
    # M-19: Redacted health endpoint — no internal paths, model names, or DB locations
    # H-08: Use cached config instead of calling SynapseConfig.load() repeatedly
    channels_health: dict[str, bool] = {}
    for cid in deps.channel_registry.list_ids():
        ch = deps.channel_registry.get(cid)
        if ch is not None:
            try:
                ch_health = await ch.health_check()
                channels_health[cid] = ch_health.get("status") == "ok"
            except Exception:
                channels_health[cid] = False

    # H-08: Use module-level cached config (_synapse_cfg) instead of 5x SynapseConfig.load()
    _cached_mappings = deps._synapse_cfg.model_mappings
    all_roles_configured = all(
        _cached_mappings.get(r, {}).get("model") for r in ("casual", "code", "analysis", "review")
    )

    overall = "ok" if all_roles_configured else "degraded"
    return {
        "status": overall,
        "graph_ok": deps.brain.number_of_nodes() > 0,
        "toxic_model_loaded": deps.toxic_scorer.is_loaded(),
        "memory_ok": bool(get_db_stats()),
        "pending_conflicts": len(
            [c for c in deps.conflicts.pending_conflicts if c["status"] == "pending"]
        ),
        "llm_configured": all_roles_configured,
        "channels": channels_health,
    }


@router.get("/gateway/status", dependencies=[Depends(_require_gateway_auth)])
async def gateway_status():
    return {
        "queue": deps.task_queue.get_stats(),
        "workers": deps.app.state.worker.num_workers if hasattr(deps.app.state, "worker") else 0,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }
