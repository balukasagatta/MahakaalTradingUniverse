"""
MTU VAJRA — Broker OAuth v2
Each user brings their own broker API app credentials
Credentials encrypted with AES-256 before storage
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx, json, os, base64, hashlib, secrets
from datetime import datetime
from cryptography.fernet import Fernet
import pytz

router = APIRouter()
IST = pytz.timezone("Asia/Kolkata")

# ── Encryption key — generated once, stored in env.vars ───────────────────────
def _get_fernet():
    # Load from env.vars file directly
    env_path = os.path.expanduser("~/mahakaal/env.vars")
    key = os.environ.get("MTU_ENCRYPT_KEY")
    if not key and os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("MTU_ENCRYPT_KEY="):
                key = line.strip().split("=",1)[1].strip().strip('"')
                break
    if not key:
        raise RuntimeError("MTU_ENCRYPT_KEY not set in env.vars")
    return Fernet(key.encode() if isinstance(key, str) else key)

def _encrypt(text: str) -> str:
    return _get_fernet().encrypt(text.encode()).decode()

def _decrypt(text: str) -> str:
    return _get_fernet().decrypt(text.encode()).decode()

# ── Storage ────────────────────────────────────────────────────────────────────
CREDS_PATH  = os.path.expanduser("~/mahakaal/user_broker_creds.json")
TOKENS_PATH = os.path.expanduser("~/mahakaal/user_tokens.json")

def _load_creds() -> dict:
    if os.path.exists(CREDS_PATH):
        return json.load(open(CREDS_PATH))
    return {}

def _save_creds(data: dict):
    json.dump(data, open(CREDS_PATH, "w"), indent=2)

def _load_tokens() -> dict:
    if os.path.exists(TOKENS_PATH):
        return json.load(open(TOKENS_PATH))
    return {}

def _save_tokens(data: dict):
    json.dump(data, open(TOKENS_PATH, "w"), indent=2)

# ── Auth helper ────────────────────────────────────────────────────────────────
def _get_user(request: Request) -> str:
    from route_auth import verify_token
    token = request.cookies.get("mtu_token")
    if not token:
        auth = request.headers.get("authorization","")
        if auth.startswith("Bearer "): token = auth[7:]
    if not token: raise HTTPException(401, "Not authenticated")
    return verify_token(token)["sub"]

# ── Broker redirect configs ────────────────────────────────────────────────────
BROKER_CFG = {
    "upstox": {
        "auth_url":   "https://api.upstox.com/v2/login/authorization/dialog",
        "token_url":  "https://api.upstox.com/v2/login/authorization/token",
        "redirect":   "https://mtutrade.in/api/auth/broker/upstox/callback",
    },
    "dhan": {
        "auth_url":   "https://api.dhan.co/oauth2/authorize",
        "token_url":  "https://api.dhan.co/oauth2/token",
        "redirect":   "https://mtutrade.in/api/auth/broker/dhan/callback",
    },
    "fyers": {
        "auth_url":   "https://api-t1.fyers.in/api/v3/generate-authcode",
        "token_url":  "https://api-t1.fyers.in/api/v3/validate-authcode",
        "redirect":   "https://mtutrade.in/api/auth/broker/fyers/callback",
    },
    "zerodha": {
        "auth_url":   "https://kite.zerodha.com/connect/login",
        "token_url":  "https://api.kite.trade/session/token",
        "redirect":   "https://mtutrade.in/api/auth/broker/zerodha/callback",
    },
}

# ── Save user broker credentials ───────────────────────────────────────────────
@router.post("/save-creds")
async def save_broker_creds(request: Request):
    email = _get_user(request)
    data  = await request.json()
    broker = data.get("broker","").lower()
    if broker not in BROKER_CFG:
        raise HTTPException(400, f"Unknown broker: {broker}")
    creds = _load_creds()
    if email not in creds: creds[email] = {}
    # Encrypt sensitive fields
    creds[email][broker] = {
        "user_id":    data.get("user_id","").strip(),
        "api_key":    _encrypt(data.get("api_key","").strip()),
        "api_secret": _encrypt(data.get("api_secret","").strip()) if data.get("api_secret") else "",
        "saved_at":   datetime.now(IST).isoformat(),
    }
    _save_creds(creds)
    return {"status": "ok", "broker": broker}

# ── Connect — redirect to broker OAuth ────────────────────────────────────────
@router.get("/connect/{broker}")
async def broker_connect(broker: str, request: Request, token: str = None):
    # Accept token via query param for browser redirects
    if token:
        from route_auth import verify_token
        try:
            payload = verify_token(token)
            email = payload["sub"]
        except:
            raise HTTPException(401, "Invalid token.")
    else:
        email = _get_user(request)
    broker = broker.lower()
    if broker not in BROKER_CFG:
        raise HTTPException(400, f"Unknown broker: {broker}")
    creds = _load_creds()
    user_creds = creds.get(email,{}).get(broker)
    if not user_creds:
        raise HTTPException(400, "Save broker credentials first")
    api_key = _decrypt(user_creds["api_key"])
    cfg = BROKER_CFG[broker]
    # Build OAuth URL
    state = base64.urlsafe_b64encode(email.encode()).decode()
    if broker == "upstox":
        url = f"{cfg['auth_url']}?response_type=code&client_id={api_key}&redirect_uri={cfg['redirect']}&state={state}"
    elif broker == "dhan":
        url = f"{cfg['auth_url']}?client_id={api_key}&redirect_uri={cfg['redirect']}&response_type=code&state={state}"
    elif broker == "fyers":
        app_hash = hashlib.sha256(f"{api_key}:{_decrypt(user_creds['api_secret'])}".encode()).hexdigest()
        url = f"{cfg['auth_url']}?client_id={api_key}-100&redirect_uri={cfg['redirect']}&response_type=code&state={state}&appHash={app_hash}"
    elif broker == "zerodha":
        url = f"{cfg['auth_url']}?v=3&api_key={api_key}&redirect_uri={cfg['redirect']}&state={state}"
    return RedirectResponse(url)

# ── Callbacks ─────────────────────────────────────────────────────────────────
def _decode_state(state: str) -> str:
    try: return base64.urlsafe_b64decode(state.encode()).decode()
    except: return state

def _store_token(email: str, broker: str, token: str):
    tokens = _load_tokens()
    if email not in tokens: tokens[email] = {}
    tokens[email][broker] = {
        "access_token": token,
        "connected_at": datetime.now(IST).isoformat(),
    }
    _save_tokens(tokens)

@router.get("/upstox/callback")
async def upstox_callback(code: str=None, state: str=None, error: str=None):
    if error or not code:
        return RedirectResponse(f"/vajra/?broker_error=upstox")
    email = _decode_state(state or "")
    creds = _load_creds().get(email,{}).get("upstox",{})
    api_key = _decrypt(creds.get("api_key",""))
    api_secret = _decrypt(creds.get("api_secret",""))
    async with httpx.AsyncClient() as c:
        r = await c.post(BROKER_CFG["upstox"]["token_url"], data={
            "code": code, "client_id": api_key, "client_secret": api_secret,
            "redirect_uri": BROKER_CFG["upstox"]["redirect"], "grant_type": "authorization_code",
        }, headers={"Content-Type":"application/x-www-form-urlencoded"})
    data = r.json()
    if "access_token" not in data:
        return RedirectResponse(f"/vajra/?broker_error=upstox&reason=token_failed")
    _store_token(email, "upstox", data["access_token"])
    return RedirectResponse(f"/vajra/?broker_success=upstox")

@router.get("/dhan/callback")
async def dhan_callback(code: str=None, state: str=None, error: str=None):
    if error or not code:
        return RedirectResponse(f"/vajra/?broker_error=dhan")
    email = _decode_state(state or "")
    creds = _load_creds().get(email,{}).get("dhan",{})
    api_key = _decrypt(creds.get("api_key",""))
    api_secret = _decrypt(creds.get("api_secret",""))
    async with httpx.AsyncClient() as c:
        r = await c.post(BROKER_CFG["dhan"]["token_url"], json={
            "code": code, "client_id": api_key, "client_secret": api_secret,
            "redirect_uri": BROKER_CFG["dhan"]["redirect"], "grant_type": "authorization_code",
        })
    data = r.json()
    token = data.get("access_token") or data.get("accessToken")
    if not token:
        return RedirectResponse(f"/vajra/?broker_error=dhan&reason=token_failed")
    _store_token(email, "dhan", token)
    return RedirectResponse(f"/vajra/?broker_success=dhan")

@router.get("/fyers/callback")
async def fyers_callback(auth_code: str=None, state: str=None, error: str=None):
    if error or not auth_code:
        return RedirectResponse(f"/vajra/?broker_error=fyers")
    email = _decode_state(state or "")
    creds = _load_creds().get(email,{}).get("fyers",{})
    api_key = _decrypt(creds.get("api_key",""))
    api_secret = _decrypt(creds.get("api_secret",""))
    app_hash = hashlib.sha256(f"{api_key}:{api_secret}".encode()).hexdigest()
    async with httpx.AsyncClient() as c:
        r = await c.post(BROKER_CFG["fyers"]["token_url"], json={
            "grant_type": "authorization_code", "appIdHash": app_hash, "code": auth_code,
        })
    data = r.json()
    token = data.get("access_token")
    if not token:
        return RedirectResponse(f"/vajra/?broker_error=fyers&reason=token_failed")
    _store_token(email, "fyers", token)
    return RedirectResponse(f"/vajra/?broker_success=fyers")

@router.get("/zerodha/callback")
async def zerodha_callback(status: str=None, request_token: str=None, state: str=None):
    if status != "success" or not request_token:
        return RedirectResponse(f"/vajra/?broker_error=zerodha")
    email = _decode_state(state or "")
    creds = _load_creds().get(email,{}).get("zerodha",{})
    api_key = _decrypt(creds.get("api_key",""))
    api_secret = _decrypt(creds.get("api_secret",""))
    checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    async with httpx.AsyncClient() as c:
        r = await c.post(BROKER_CFG["zerodha"]["token_url"],
            data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
            headers={"X-Kite-Version": "3"})
    data = r.json()
    token = data.get("data",{}).get("access_token")
    if not token:
        return RedirectResponse(f"/vajra/?broker_error=zerodha&reason=token_failed")
    _store_token(email, "zerodha", token)
    return RedirectResponse(f"/vajra/?broker_success=zerodha")

# ── Get user's connected brokers ───────────────────────────────────────────────
@router.get("/my-brokers")
async def my_brokers(request: Request):
    email = _get_user(request)
    tokens = _load_tokens().get(email,{})
    creds  = _load_creds().get(email,{})
    return {
        "brokers": {
            broker: {
                "connected":    data.get("status") != "expired",
                "expired":      data.get("status") == "expired",
                "connected_at": data.get("connected_at",""),
                "user_id":      creds.get(broker,{}).get("user_id",""),
            }
            for broker, data in tokens.items()
        }
    }

@router.delete("/my-brokers/{broker}")
async def disconnect_broker(broker: str, request: Request):
    email = _get_user(request)
    tokens = _load_tokens()
    if email in tokens and broker in tokens[email]:
        del tokens[email][broker]
        _save_tokens(tokens)
    return {"status": "ok"}

# ── Get active token for API calls ─────────────────────────────────────────────
def get_active_token(email: str, broker: str) -> str:
    tokens = _load_tokens()
    return tokens.get(email,{}).get(broker,{}).get("access_token","")
