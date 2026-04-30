"""Chat and OpenAI-compatible completion endpoints."""

import logging
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import validate_api_key
from sci_fi_dashboard.observability import mint_run_id
from sci_fi_dashboard.pipeline_helpers import process_direct_persona_chat
from sci_fi_dashboard.schemas import ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", dependencies=[Depends(deps._check_rate_limit)])
@router.post("/v1/chat/completions", dependencies=[Depends(deps._check_rate_limit)])
async def chat_webhook(request: Request):
    run_id = mint_run_id()
    deps.validate_api_key(request)
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "reason": "invalid_json"}

    messages = body.get("messages", [])
    if not messages:
        if "message" in body:
            user_msg = body["message"]
        else:
            return {"status": "error", "reason": "no_messages"}
    else:
        user_msg = None
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break

    if not user_msg:
        return {"status": "skipped", "reason": "no_user_message"}

    chat_id = (
        body.get("chat_id")
        or body.get("from")
        or body.get("user")
        or request.headers.get("X-Chat-Id", "")
        or body.get("user_id", "")
    )
    message_id = body.get("message_id", str(uuid.uuid4()))
    sender_name = body.get("sender_name", chat_id)
    is_from_me = body.get("fromMe", False)

    if is_from_me:
        return {"status": "skipped", "reason": "own_message"}

    if not str(user_msg).strip():
        return {"status": "skipped", "reason": "empty"}

    if deps.dedup.is_duplicate(message_id):
        # We pretend it queued but do not actually queue
        return {"status": "skipped", "reason": "duplicate", "accepted": True}

    await deps.flood.incoming(
        chat_id=chat_id,
        message=user_msg,
        metadata={
            "message_id": message_id,
            "sender_name": sender_name,
            "run_id": run_id,
        },
    )

    return {
        "status": "queued",
        "accepted": True,
        "task_queue_depth": deps.task_queue.pending_count,
    }


# --- Persona Chat Endpoints (dynamically registered from personas.yaml) ---


def _make_persona_handler(persona_id: str):
    async def handler(
        request: ChatRequest, background_tasks: BackgroundTasks, http_request: Request
    ):
        mint_run_id()
        deps._check_rate_limit(http_request)  # H-04: rate limit persona chat
        validate_api_key(http_request)
        override_role = http_request.headers.get("X-Synapse-Model-Role", "").strip()
        if override_role and _parity_role_override_enabled():
            return await _run_with_parity_role_override(
                request, persona_id, background_tasks, override_role
            )
        return await process_direct_persona_chat(request, persona_id, background_tasks)

    handler.__name__ = f"chat_{persona_id}"
    return handler


def _parity_role_override_enabled() -> bool:
    return os.environ.get("SYNAPSE_PARITY_ALLOW_ROLE_HEADER", "").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _run_with_parity_role_override(
    request: ChatRequest,
    persona_id: str,
    background_tasks: BackgroundTasks,
    override_role: str,
):
    mappings = getattr(deps._synapse_cfg, "model_mappings", {}) or {}
    if override_role not in mappings:
        return {
            "status": "error",
            "reason": "unknown_model_role",
            "role": override_role,
            "available_roles": sorted(mappings),
        }

    from sci_fi_dashboard.tool_features import (
        clear_model_override,
        get_model_override,
        set_model_override,
    )

    chat_id = request.user_id or "default"
    previous = get_model_override(chat_id)
    set_model_override(chat_id, override_role)
    try:
        return await process_direct_persona_chat(request, persona_id, background_tasks)
    finally:
        if previous:
            set_model_override(chat_id, previous)
        else:
            clear_model_override(chat_id)


# Register persona-specific routes
for _p in deps.PERSONAS_CONFIG.get("personas", []):
    pid = _p.get("id")
    if pid:
        handler = _make_persona_handler(pid)
        router.add_api_route(
            f"/chat/{pid}",
            handler,
            methods=["POST"],
            summary=_p.get("description", f"Chat as {pid}"),
            dependencies=[
                Depends(validate_api_key),
                Depends(deps._check_rate_limit),
            ],
        )
