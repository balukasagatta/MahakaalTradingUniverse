"""
Feed WebSocket route — browser connects here for live market data
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feed_manager import feed_manager

router = APIRouter()

@router.on_event("startup")
async def start_feed():
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
                # Send heartbeat
                await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, Exception):
        feed_manager.remove_client(q)

@router.get("/snapshot")
async def get_snapshot():
    """Latest market snapshot — for initial page load"""
    return {"status": "ok", "data": feed_manager.latest}
