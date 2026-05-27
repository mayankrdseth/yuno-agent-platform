from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.broadcast import subscribe, unsubscribe

router = APIRouter(tags=["monitor"])


@router.websocket("/ws/monitor")
async def monitor_ws(websocket: WebSocket):
    await websocket.accept()
    queue = subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        unsubscribe(queue)