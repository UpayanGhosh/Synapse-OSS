"""Session management endpoints — reads from multiuser/SessionStore (file-based)."""

import logging
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from sci_fi_dashboard.middleware import _require_gateway_auth
from sci_fi_dashboard.style_policy import get_current_style_policy

logger = logging.getLogger(__name__)
router = APIRouter()


def _target_from_session_key(session_key: str, fallback: str = "the_creator") -> str:
    parts = str(session_key or "").split(":")
    if len(parts) >= 2 and parts[0] in {"cli", "agent"} and parts[1]:
        return parts[1]
    return fallback


def _load_style_profile_for_target(target: str) -> dict:
    from sci_fi_dashboard import _deps as deps

    sbs = deps.get_sbs_for_target(target)
    profile_mgr = getattr(sbs, "profile_mgr", None)
    load_layer = getattr(profile_mgr, "load_layer", None)
    if not callable(load_layer):
        return {}
    profile: dict = {}
    for layer in ("linguistic", "interaction"):
        try:
            loaded = load_layer(layer)
        except Exception:
            loaded = {}
        if isinstance(loaded, dict):
            profile[layer] = loaded
    return profile


@router.get("/api/sessions/{session_key}/style", dependencies=[Depends(_require_gateway_auth)])
async def get_session_style(session_key: str):
    """Return the current runtime style policy for a conversation session."""
    target = _target_from_session_key(session_key)
    policy = get_current_style_policy(session_key, _load_style_profile_for_target(target))
    return policy.as_dict()


@router.get("/api/sessions", dependencies=[Depends(_require_gateway_auth)])
async def get_sessions():
    """Return all conversation sessions from disk store for all agents.

    Scans each agent's SessionStore (file-based JSON at
    ~/.synapse/state/agents/<agent_id>/sessions/sessions.json) and returns
    a combined list sorted by updatedAt descending.
    """
    from synapse_config import SynapseConfig

    from sci_fi_dashboard import _deps as deps
    from sci_fi_dashboard.multiuser.session_store import SessionStore

    cfg = SynapseConfig.load()
    data_root: Path = cfg.data_root
    results = []

    for agent_id in deps.sbs_registry:
        try:
            store = SessionStore(agent_id=agent_id, data_root=data_root)
            sessions = await store.load()
            for key, entry in sessions.items():
                # updated_at is a float (Unix epoch) — convert to ISO string for JSON
                from datetime import datetime

                updated_iso = (
                    datetime.fromtimestamp(entry.updated_at, tz=UTC).isoformat()
                    if entry.updated_at
                    else None
                )
                results.append(
                    {
                        "sessionKey": key,
                        "agentId": agent_id,
                        "sessionId": entry.session_id,
                        "updatedAt": updated_iso,
                        "updatedAtEpoch": entry.updated_at,  # raw float for sorting
                        "compactionCount": entry.compaction_count,
                    }
                )
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

    from sci_fi_dashboard import _deps as deps
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import archive_transcript, transcript_path

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
