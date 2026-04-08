"""Session management endpoints — reads from multiuser/SessionStore (file-based)."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from sci_fi_dashboard.middleware import _require_gateway_auth

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sessions", dependencies=[Depends(_require_gateway_auth)])
async def get_sessions():
    """Return all conversation sessions from disk store for all agents.

    Scans each agent's SessionStore (file-based JSON at
    ~/.synapse/state/agents/<agent_id>/sessions/sessions.json) and returns
    a combined list sorted by updatedAt descending.
    """
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard import _deps as deps

    cfg = SynapseConfig.load()
    data_root: Path = cfg.data_root
    results = []

    for agent_id in deps.sbs_registry:
        try:
            store = SessionStore(agent_id=agent_id, data_root=data_root)
            sessions = await store.load()
            for key, entry in sessions.items():
                # updated_at is a float (Unix epoch) — convert to ISO string for JSON
                from datetime import datetime, timezone
                updated_iso = (
                    datetime.fromtimestamp(entry.updated_at, tz=timezone.utc).isoformat()
                    if entry.updated_at else None
                )
                results.append({
                    "sessionKey": key,
                    "agentId": agent_id,
                    "sessionId": entry.session_id,
                    "updatedAt": updated_iso,
                    "updatedAtEpoch": entry.updated_at,  # raw float for sorting
                    "compactionCount": entry.compaction_count,
                })
        except Exception as exc:
            logger.warning("Failed to load sessions for agent %s: %s", agent_id, exc)

    # Sort by float epoch (not string) to avoid TypeError on mixed types
    return sorted(results, key=lambda x: x.get("updatedAtEpoch") or 0, reverse=True)


@router.post(
    "/api/sessions/{session_key}/reset",
    dependencies=[Depends(_require_gateway_auth)],
)
async def reset_session(session_key: str):
    """Clear conversation history for a session.

    Archives the existing transcript (renames to .deleted.<epoch_ms>) and
    invalidates the conversation cache entry. The next message will start
    a fresh transcript.
    """
    from synapse_config import SynapseConfig
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import transcript_path, archive_transcript
    from sci_fi_dashboard import _deps as deps

    cfg = SynapseConfig.load()
    data_root: Path = cfg.data_root

    # Find which agent owns this session key
    for agent_id in deps.sbs_registry:
        store = SessionStore(agent_id=agent_id, data_root=data_root)
        entry = await store.get(session_key)
        if entry is not None:
            # Archive the transcript file
            t_path = transcript_path(entry, data_root, agent_id)
            if t_path.exists():
                await archive_transcript(t_path)

            # CRITICAL: delete() then update() to rotate session_id.
            # store.update() alone CANNOT change session_id — _merge_entry() preserves
            # it once set. delete() removes the entry so update() creates a fresh UUID.
            await store.delete(session_key)
            await store.update(session_key, {"compaction_count": 0})

            # Invalidate cache so next message loads fresh
            deps.conversation_cache.invalidate(session_key)

            return {
                "status": "reset",
                "sessionKey": session_key,
                "agentId": agent_id,
            }

    raise HTTPException(status_code=404, detail=f"Session not found: {session_key}")
