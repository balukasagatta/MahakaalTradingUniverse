"""
Feed WebSocket route — live market data to browser
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from feed_manager import feed_manager
import asyncio

router = APIRouter()

async def startup_feed():
    feed_manager.start()

@router.websocket("/ws")
async def feed_ws(websocket: WebSocket):
    await websocket.accept()
    q = feed_manager.add_client()
    try:
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json(data)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        feed_manager.remove_client(q)

@router.get("/snapshot")
async def get_snapshot():
    return {"status": "ok", "data": feed_manager.latest}
