"""Health and status endpoints."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.db import get_db_connection
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


@router.get("/memory_health", dependencies=[Depends(_require_gateway_auth)])
async def memory_health() -> dict[str, Any]:
    """Ingestion pipeline health probe.

    Queries ingest_failures for the most recent success and failure timestamps,
    plus the last time a document and KG triple were added. Also counts pending
    session messages not yet ingested.

    Auth-gated: exception messages can contain file paths or partial content.
    """
    from synapse_config import SynapseConfig  # noqa: PLC0415

    cfg = SynapseConfig.load()

    conn = get_db_connection()
    try:
        def _scalar(sql: str, params: tuple = ()) -> str | None:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else None

        last_doc_added_at = _scalar("SELECT MAX(created_at) FROM documents")
        last_kg_extraction_at = _scalar("SELECT MAX(created_at) FROM entity_links")
        last_ingest_completed_at = _scalar(
            "SELECT MAX(created_at) FROM ingest_failures WHERE phase = 'completed'"
        )
        last_ingest_failure_at = _scalar(
            "SELECT MAX(created_at) FROM ingest_failures WHERE phase IN ('load','vector','kg')"
        )

        rows = conn.execute(
            """
            SELECT created_at, session_key, phase, exception_type, exception_msg
              FROM ingest_failures
             WHERE phase != 'completed'
             ORDER BY created_at DESC
             LIMIT 10
            """
        ).fetchall()
        recent_failures = [
            {
                "created_at": r[0],
                "session_key": r[1],
                "phase": r[2],
                "exception_type": r[3],
                "exception_msg": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()

    # Count pending session messages: lines in *.jsonl files under agents/*/sessions/
    # that are NOT *.deleted.* files.
    pending_count = 0
    agents_root = cfg.data_root / "state" / "agents"
    if agents_root.exists():
        for jsonl_file in agents_root.glob("*/sessions/*.jsonl"):
            # Skip archived (deleted) transcripts
            if ".deleted." in jsonl_file.name:
                continue
            try:
                pending_count += sum(1 for _ in jsonl_file.open(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    return {
        "last_doc_added_at": last_doc_added_at,
        "last_kg_extraction_at": last_kg_extraction_at,
        "last_ingest_completed_at": last_ingest_completed_at,
        "last_ingest_failure_at": last_ingest_failure_at,
        "pending_session_message_count": pending_count,
        "recent_failures": recent_failures,
    }
