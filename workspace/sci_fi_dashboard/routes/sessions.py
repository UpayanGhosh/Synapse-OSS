"""Session management endpoints."""
import logging
import sqlite3

from fastapi import APIRouter, Depends

from sci_fi_dashboard.db import DB_PATH
from sci_fi_dashboard.middleware import _require_gateway_auth

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sessions", dependencies=[Depends(_require_gateway_auth)])
def get_sessions():
    """
    SESS-02: Return session token usage matching Synapse sessions list schema.
    Returns last 100 sessions, most recent first.
    Graceful degradation: returns [] if sessions table absent or DB unreadable.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT session_id, model, input_tokens, output_tokens, total_tokens, created_at "
                "FROM sessions ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [
            {
                "sessionId": r["session_id"],
                "model": r["model"],
                "inputTokens": r["input_tokens"],
                "outputTokens": r["output_tokens"],
                "totalTokens": r["total_tokens"],
                "contextTokens": 1048576,
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    except Exception:
        return []
