"""
MTU Terminal — FastAPI Backend v1.0
Flat file structure — no subfolders
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import pytz

# Import all routers from flat files
from route_feed    import router as feed_router,    startup_feed
from route_auth    import router as auth_router
from route_vajra   import router as vajra_router
from route_sutra   import router as sutra_router
from route_pragnya import router as pragnya_router
from route_broker  import router as broker_router

app = FastAPI(title="MTU Terminal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mtutrade.in", "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,    prefix="/api/auth",    tags=["Auth"])
app.include_router(broker_router,  prefix="/api/auth/broker", tags=["Broker"])
app.include_router(feed_router,    prefix="/api/feed",    tags=["Feed"])
app.include_router(vajra_router,   prefix="/api/vajra",   tags=["VAJRA"])
app.include_router(sutra_router,   prefix="/api/sutra",   tags=["SUTRA"])
app.include_router(pragnya_router, prefix="/api/pragnya", tags=["PRAGNYA"])

@app.on_event("startup")
async def startup():
    await startup_feed()

@app.get("/api/health")
async def health():
    IST = pytz.timezone("Asia/Kolkata")
    return {"status": "ok", "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"), "version": "1.0.0"}
