"""
Auth — JWT-based login per product
Default credentials:
  vajra_admin / vajra123   → VAJRA
  sutra_admin / sutra123   → SUTRA
  tark_admin  / tark123    → TARK
  mtu_admin   / mahakaal123 → all
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json, os, hashlib, secrets
from datetime import datetime, timedelta
import pytz

router = APIRouter()
IST = pytz.timezone("Asia/Kolkata")

USERS_PATH = os.path.expanduser("~/mahakaal/mtu_users.json")
SESSIONS: dict = {}

DEFAULT_USERS = {
    "vajra_admin":  {"password": hashlib.sha256(b"vajra123").hexdigest(),   "products": ["VAJRA"]},
    "sutra_admin":  {"password": hashlib.sha256(b"sutra123").hexdigest(),   "products": ["SUTRA"]},
    "tark_admin":   {"password": hashlib.sha256(b"tark123").hexdigest(),    "products": ["TARK"]},
    "mtu_admin":    {"password": hashlib.sha256(b"mahakaal123").hexdigest(),"products": ["VAJRA","SUTRA","TARK"]},
}

def _load_users():
    if os.path.exists(USERS_PATH):
        return json.load(open(USERS_PATH))
    json.dump(DEFAULT_USERS, open(USERS_PATH, "w"), indent=2)
    return DEFAULT_USERS

class LoginRequest(BaseModel):
    username: str
    password: str
    product:  str

@router.post("/login")
async def login(req: LoginRequest):
    users   = _load_users()
    user    = users.get(req.username)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if user["password"] != hashlib.sha256(req.password.encode()).hexdigest():
        raise HTTPException(401, "Invalid credentials")
    if req.product.upper() not in user["products"]:
        raise HTTPException(403, f"No access to {req.product}")
    token   = secrets.token_hex(32)
    expires = datetime.now(IST) + timedelta(hours=12)
    SESSIONS[token] = {"username": req.username, "products": user["products"], "expires": expires}
    return {"token": token, "username": req.username, "products": user["products"], "expires": expires.isoformat()}

@router.post("/logout")
async def logout(token: str):
    SESSIONS.pop(token, None)
    return {"status": "ok"}

@router.get("/verify")
async def verify(token: str):
    session = SESSIONS.get(token)
    if not session or datetime.now(IST) > session["expires"]:
        SESSIONS.pop(token, None)
        raise HTTPException(401, "Invalid or expired token")
    return {"status": "ok", "username": session["username"], "products": session["products"]}

def require_auth(token: str) -> dict:
    session = SESSIONS.get(token)
    if not session or datetime.now(IST) > session["expires"]:
        raise HTTPException(401, "Unauthorized")
    return session
