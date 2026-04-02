"""WebSocket gateway endpoint."""
from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    gw = websocket.app.state.gateway_ws
    if gw:
        await gw.handle(websocket)
    else:
        await websocket.close(code=4000, reason="Gateway not ready")
