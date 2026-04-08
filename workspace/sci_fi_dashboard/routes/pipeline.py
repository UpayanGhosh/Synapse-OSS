"""
routes/pipeline.py — SSE endpoint for real-time pipeline event streaming.

GET  /pipeline/events  →  text/event-stream
GET  /pipeline/state   →  JSON snapshot for dashboard cold-start
POST /pipeline/send    →  Dashboard chat endpoint (no token required — local dev only)
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.pipeline_emitter import get_emitter

router = APIRouter()


@router.get("/pipeline/events")
async def pipeline_events():
    """Server-Sent Events stream for real-time pipeline visualization."""
    emitter = get_emitter()
    queue = emitter.subscribe()

    async def event_stream():
        try:
            # Initial handshake event
            yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield msg
                except asyncio.TimeoutError:
                    # SSE keep-alive comment (not parsed by EventSource)
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            emitter.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/pipeline/state")
async def pipeline_state():
    """Snapshot of current system state for dashboard initialization."""
    try:
        queue_stats = deps.task_queue.get_stats() if hasattr(deps, "task_queue") else {}
    except Exception:
        queue_stats = {}

    try:
        # Use configured default persona (falls back to "the_creator")
        from synapse_config import SynapseConfig
        _default_target = SynapseConfig.load().session.get("default_persona", "the_creator")
        sbs_summary = deps.get_sbs_for_target(_default_target).get_profile_summary()
    except Exception:
        sbs_summary = {}

    return JSONResponse({
        "status": "online",
        "queue": queue_stats,
        "sbs_profile": sbs_summary,
    })


@router.post("/pipeline/send")
async def pipeline_send(body: dict, background_tasks: BackgroundTasks):
    """
    Dashboard chat endpoint — no auth token required (local dev only).
    Calls persona_chat() directly so all emit() events fire to the SSE stream.
    """
    from sci_fi_dashboard.schemas import ChatRequest

    message = (body.get("message") or "").strip()
    # Use configured default persona (falls back to "the_creator")
    try:
        from synapse_config import SynapseConfig
        _default_target = SynapseConfig.load().session.get("default_persona", "the_creator")
    except Exception:
        _default_target = "the_creator"
    target = body.get("target", _default_target)
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    req = ChatRequest(message=message)
    try:
        reply = await deps.persona_chat(req, target, background_tasks)
        # persona_chat returns a string or a dict with 'reply'
        if isinstance(reply, dict):
            text = reply.get("reply") or reply.get("response") or str(reply)
        else:
            text = str(reply)
    except Exception as exc:
        text = f"[error] {exc}"

    return JSONResponse({"reply": text, "target": target})
