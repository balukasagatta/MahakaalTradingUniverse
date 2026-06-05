"""
MTU Terminal — FastAPI Backend v1.0
WebSocket market feed + REST API
VAJRA (Sensex) · SUTRA (Nifty) · PRAGNYA discipline engine
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import asyncio, json, os, sys
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.feed    import router as feed_router
from routes.vajra   import router as vajra_router
from routes.sutra   import router as sutra_router
from routes.pragnya import router as pragnya_router
from routes.auth    import router as auth_router

app = FastAPI(
    title="MTU Terminal API",
    description="Mahakaal Trading Universe — Backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mtutrade.in", "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,    prefix="/api/auth",    tags=["Auth"])
app.include_router(feed_router,    prefix="/api/feed",    tags=["Feed"])
app.include_router(vajra_router,   prefix="/api/vajra",   tags=["VAJRA"])
app.include_router(sutra_router,   prefix="/api/sutra",   tags=["SUTRA"])
app.include_router(pragnya_router, prefix="/api/pragnya", tags=["PRAGNYA"])

@app.get("/api/health")
async def health():
    IST = pytz.timezone("Asia/Kolkata")
    return {
        "status": "ok",
        "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
        "version": "1.0.0",
    }
