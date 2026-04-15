"""WhatsApp and channel webhook endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.channels.base import ChannelMessage
from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Channel Abstraction Layer Routes
# ---------------------------------------------------------------------------


@router.post("/channels/{channel_id}/webhook")
async def unified_webhook(channel_id: str, request: Request):
    """
    CHAN-04: Unified inbound webhook for all channels.
    Validates channel is registered, normalizes payload to ChannelMessage,
    feeds FloodGate pipeline with channel_id in metadata.
    """
    channel = deps.channel_registry.get(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not registered")

    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    # Handle non-message event types from WhatsApp bridge (delivery, typing, reactions)
    event_type = raw.get("type", "message")
    if event_type in ("message_status", "typing_indicator", "reaction"):
        logger.debug("[gateway] WhatsApp event type=%s chat=%s", event_type, raw.get("chat_id", ""))
        # Future: broadcast via WebSocket, update delivery tracking DB, etc.
        return {"status": "accepted", "event_type": event_type}

    msg: ChannelMessage | None = await channel.receive(raw)

    if msg is None:
        return {"status": "skipped", "reason": "blocked_or_filtered", "accepted": True}

    # H-09: Generate UUID fallback if message_id is empty/None
    effective_msg_id = msg.message_id or raw.get("message_id", "") or str(uuid.uuid4())
    if deps.dedup.is_duplicate(effective_msg_id):
        return {"status": "skipped", "reason": "duplicate", "accepted": True}

    await deps.flood.incoming(
        chat_id=msg.chat_id,
        message=msg.text,
        metadata={
            "message_id": msg.message_id,
            "sender_name": msg.sender_name,
            "channel_id": msg.channel_id,  # CRITICAL: must be in metadata for on_batch_ready
        },
    )
    return {"status": "queued", "accepted": True, "task_queue_depth": deps.task_queue.pending_count}


@router.post("/whatsapp/enqueue")
async def whatsapp_enqueue_shim(request: Request):
    """
    CHAN-05: Backwards-compatible shim. Delegates to unified_webhook with channel_id='whatsapp'.
    Existing webhook configurations do NOT need to change.
    """
    return await unified_webhook("whatsapp", request)


# ---------------------------------------------------------------------------
# QR code proxy
# ---------------------------------------------------------------------------


@router.get("/qr", dependencies=[Depends(deps._require_gateway_auth)])
async def get_qr():
    """
    WA-07: Proxy the QR code from the Baileys bridge for WhatsApp authentication.
    Returns {"qr": "<qr_string>"} on success.
    Returns 503 if WhatsApp channel not registered, bridge not running, or already authenticated.
    """
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        raise HTTPException(status_code=503, detail="WhatsApp channel not registered")
    qr = await wa_channel.get_qr()
    if qr is None:
        raise HTTPException(
            status_code=503,
            detail="QR not available — bridge may be down or already authenticated",
        )
    return {"qr": qr}


# ---------------------------------------------------------------------------
# WhatsApp session management + monitoring routes
# ---------------------------------------------------------------------------


@router.get("/channels/whatsapp/status", dependencies=[Depends(deps._require_gateway_auth)])
async def whatsapp_status():
    """Return enhanced WhatsApp connection status with auth age and uptime."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        raise HTTPException(status_code=503, detail="WhatsApp channel not registered")
    return await wa_channel.get_status()


@router.post("/channels/whatsapp/logout", dependencies=[Depends(deps._require_gateway_auth)])
async def whatsapp_logout():
    """Deregister linked device and wipe WhatsApp session."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        raise HTTPException(status_code=503, detail="WhatsApp channel not registered")
    ok = await wa_channel.logout()
    if not ok:
        raise HTTPException(status_code=503, detail="Logout failed — bridge may be down")
    return {"ok": True, "message": "Logged out and session cleared"}


@router.post("/channels/whatsapp/relink", dependencies=[Depends(deps._require_gateway_auth)])
async def whatsapp_relink():
    """Force fresh QR cycle — wipe creds and restart Baileys socket."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        raise HTTPException(status_code=503, detail="WhatsApp channel not registered")
    ok = await wa_channel.relink()
    if not ok:
        raise HTTPException(status_code=503, detail="Relink failed — bridge may be down")
    return {"ok": True, "message": "Restarting socket — poll GET /qr for new QR"}


@router.post("/channels/whatsapp/connection-state")
async def whatsapp_connection_state(request: Request):
    """
    Receive connection state change webhook from the Baileys bridge.
    Updates WhatsAppChannel internal state and triggers retry queue flush on reconnect.
    """
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel):
        return {"ok": False, "detail": "WhatsApp channel not registered"}
    payload = await request.json()
    wa_channel.update_connection_state(payload)
    return {"ok": True}


# ---------------------------------------------------------------------------
# WhatsApp retry queue routes
# ---------------------------------------------------------------------------


@router.get("/channels/whatsapp/retry-queue", dependencies=[Depends(deps._require_gateway_auth)])
async def whatsapp_retry_queue_list():
    """List pending entries in the WhatsApp message retry queue."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel) or wa_channel._retry_queue is None:
        return {"entries": []}
    return {"entries": await wa_channel._retry_queue.list_pending()}


@router.post(
    "/channels/whatsapp/retry-queue/flush", dependencies=[Depends(deps._require_gateway_auth)]
)
async def whatsapp_retry_queue_flush():
    """Force immediate retry of all pending messages in the queue."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel) or wa_channel._retry_queue is None:
        raise HTTPException(status_code=503, detail="Retry queue not available")
    flushed = await wa_channel._retry_queue.flush()
    return {"ok": True, "flushed": flushed}


@router.delete(
    "/channels/whatsapp/retry-queue/{entry_id}",
    dependencies=[Depends(deps._require_gateway_auth)],
)
async def whatsapp_retry_queue_delete(entry_id: int):
    """Remove a specific entry from the retry queue."""
    wa_channel = deps.channel_registry.get("whatsapp")
    if not isinstance(wa_channel, WhatsAppChannel) or wa_channel._retry_queue is None:
        raise HTTPException(status_code=503, detail="Retry queue not available")
    ok = await wa_channel._retry_queue.delete(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# WhatsApp job status + loop test
# ---------------------------------------------------------------------------


@router.get("/whatsapp/jobs/{message_id}")
def whatsapp_job_status(message_id: str):
    row = deps.get_inbound_message(message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


@router.post("/whatsapp/loop-test")
async def whatsapp_loop_test(payload: deps.WhatsAppLoopTestRequest, request: Request):
    """
    Validate outbound loop path from Python -> WhatsApp bridge.
    Phase 4 will implement Baileys bridge. Currently returns 501.
    Uses --dry-run by default to avoid sending real messages.
    """
    deps.validate_bridge_token(request)

    target = deps.normalize_phone(payload.target)
    if not target:
        raise HTTPException(status_code=400, detail="target is required")

    raise HTTPException(
        status_code=501,
        detail="WhatsApp send via CLI not available — Phase 4 will implement Baileys bridge",
    )
