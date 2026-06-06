"""
MTU Terminal — Auth v2
Secure email/password auth with bcrypt, JWT, rate limiting
"""
from fastapi import APIRouter, HTTPException, Request, Response, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
import bcrypt, jwt, json, os, time, secrets
from datetime import datetime, timedelta
from collections import defaultdict
import pytz

router = APIRouter()
IST = pytz.timezone("Asia/Kolkata")

# ── Config ────────────────────────────────────────────────────────────────────
def _load_jwt_secret():
    secret = os.environ.get("MTU_JWT_SECRET")
    if not secret:
        env_path = os.path.expanduser("~/mahakaal/env.vars")
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("MTU_JWT_SECRET="):
                    secret = line.strip().split("=",1)[1].strip().strip('"')
                    break
    if not secret:
        secret = secrets.token_hex(32)
    return secret
JWT_SECRET = _load_jwt_secret()
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = 12
USERS_PATH   = os.path.expanduser("~/mahakaal/mtu_users.json")

# Rate limiting — in memory (resets on restart, fine for now)
_failed_attempts = defaultdict(list)  # email -> [timestamp, ...]
MAX_ATTEMPTS  = 5
LOCKOUT_SECS  = 900  # 15 min

# ── User store ─────────────────────────────────────────────────────────────────
def _load_users() -> dict:
    if os.path.exists(USERS_PATH):
        return json.load(open(USERS_PATH))
    # Create default admin on first run
    default = {
        "balu@mtutrade.in": {
            "name":     "Balu",
            "password": bcrypt.hashpw(b"mahakaal123", bcrypt.gensalt()).decode(),
            "products": ["VAJRA", "SUTRA", "TARK"],
            "active":   True,
            "created":  datetime.now(IST).isoformat(),
        }
    }
    _save_users(default)
    return default

def _save_users(users: dict):
    json.dump(users, open(USERS_PATH, "w"), indent=2)

# ── Rate limit check ───────────────────────────────────────────────────────────
def _check_rate_limit(email: str):
    now = time.time()
    attempts = [t for t in _failed_attempts[email] if now - t < LOCKOUT_SECS]
    _failed_attempts[email] = attempts
    if len(attempts) >= MAX_ATTEMPTS:
        remaining = int(LOCKOUT_SECS - (now - attempts[0]))
        raise HTTPException(429, f"Too many attempts. Try again in {remaining//60} min {remaining%60} sec.")

def _record_failure(email: str):
    _failed_attempts[email].append(time.time())

def _clear_failures(email: str):
    _failed_attempts.pop(email, None)

# ── JWT ────────────────────────────────────────────────────────────────────────
def _create_token(email: str, products: list) -> str:
    payload = {
        "sub":      email,
        "products": products,
        "iat":      datetime.utcnow(),
        "exp":      datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H),
        "jti":      secrets.token_hex(8),  # unique token id
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token.")

# ── Schemas ────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email:    str
    password: str

class RegisterRequest(BaseModel):
    email:    str
    password: str
    name:     str
    invite_code: str  # simple invite code gate before public launch

class ChangePasswordRequest(BaseModel):
    email:        str
    old_password: str
    new_password: str

# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/login")
async def login(req: LoginRequest, response: Response):
    email = req.email.strip().lower()

    # Rate limit
    _check_rate_limit(email)

    users = _load_users()
    user  = users.get(email)

    if not user or not user.get("active", True):
        _record_failure(email)
        raise HTTPException(401, "Invalid email or password.")

    # Verify password with bcrypt
    if not bcrypt.checkpw(req.password.encode(), user["password"].encode()):
        _record_failure(email)
        attempts_left = MAX_ATTEMPTS - len(_failed_attempts[email])
        raise HTTPException(401, f"Invalid email or password. {attempts_left} attempt(s) remaining.")

    _clear_failures(email)

    token = _create_token(email, user["products"])

    # Set httpOnly cookie
    response.set_cookie(
        key="mtu_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=JWT_EXPIRE_H * 3600,
        path="/",
    )

    # Update last login
    users[email]["last_login"] = datetime.now(IST).isoformat()
    _save_users(users)

    return {
        "status":   "ok",
        "token":    token,  # also return in body for JS localStorage fallback
        "name":     user["name"],
        "email":    email,
        "products": user["products"],
        "expires":  (datetime.now(IST) + timedelta(hours=JWT_EXPIRE_H)).isoformat(),
    }

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("mtu_token", path="/")
    return {"status": "ok"}

@router.get("/verify")
async def verify(mtu_token: str = Cookie(None), authorization: str = None):
    token = mtu_token
    # Fallback to Authorization header
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "Not authenticated.")
    payload = verify_token(token)
    return {
        "status":   "ok",
        "email":    payload["sub"],
        "products": payload["products"],
    }

@router.post("/change-password")
async def change_password(req: ChangePasswordRequest):
    email = req.email.strip().lower()
    users = _load_users()
    user  = users.get(email)
    if not user:
        raise HTTPException(404, "User not found.")
    if not bcrypt.checkpw(req.old_password.encode(), user["password"].encode()):
        raise HTTPException(401, "Current password is incorrect.")
    if len(req.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    users[email]["password"] = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    _save_users(users)
    return {"status": "ok", "message": "Password updated."}

# ── Admin routes (protected, only for mtu_admin) ───────────────────────────────
@router.post("/admin/create-user")
async def create_user(data: dict, authorization: str = None):
    # Verify caller is admin
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Admin token required.")
    payload = verify_token(authorization[7:])
    if "VAJRA" not in payload.get("products", []) or payload["sub"] != "balu@mtutrade.in":
        raise HTTPException(403, "Admin only.")

    email    = data.get("email","").strip().lower()
    password = data.get("password","")
    name     = data.get("name","")
    products = data.get("products", ["VAJRA"])

    if not email or not password or len(password) < 8:
        raise HTTPException(400, "Email and password (min 8 chars) required.")

    users = _load_users()
    if email in users:
        raise HTTPException(409, "User already exists.")

    users[email] = {
        "name":     name or email.split("@")[0],
        "password": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "products": products,
        "active":   True,
        "created":  datetime.now(IST).isoformat(),
    }
    _save_users(users)
    return {"status": "ok", "email": email, "products": products}

@router.post("/admin/deactivate-user")
async def deactivate_user(data: dict, authorization: str = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Admin token required.")
    payload = verify_token(authorization[7:])
    if payload["sub"] != "balu@mtutrade.in":
        raise HTTPException(403, "Admin only.")
    email = data.get("email","").strip().lower()
    users = _load_users()
    if email not in users:
        raise HTTPException(404, "User not found.")
    users[email]["active"] = False
    _save_users(users)
    return {"status": "ok", "message": f"{email} deactivated."}

@router.get("/admin/users")
async def list_users(authorization: str = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Admin token required.")
    payload = verify_token(authorization[7:])
    if payload["sub"] != "balu@mtutrade.in":
        raise HTTPException(403, "Admin only.")
    users = _load_users()
    return {
        "users": [
            {
                "email":      email,
                "name":       u["name"],
                "products":   u["products"],
                "active":     u.get("active", True),
                "created":    u.get("created",""),
                "last_login": u.get("last_login",""),
            }
            for email, u in users.items()
        ]
    }
