"""
Token Manager — reads tokens from user_tokens.json (per user) or env.vars (fallback)
"""
import os, json

ENV_PATH    = os.path.expanduser("~/mahakaal/env.vars")
TOKENS_PATH = os.path.expanduser("~/mahakaal/user_tokens.json")

def _read_env():
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "): line = line[7:]
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def _get_user_token(email: str, broker: str) -> str:
    if not email or not os.path.exists(TOKENS_PATH):
        return ""
    try:
        tokens = json.load(open(TOKENS_PATH))
        return tokens.get(email, {}).get(broker, {}).get("access_token", "")
    except:
        return ""

def get_upstox_token(email: str = None) -> str:
    # Try user token first
    if email:
        token = _get_user_token(email, "upstox")
        if token: return token
    # Fallback to env.vars
    token = _read_env().get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not found")
    return token

def get_dhan_token(email: str = None) -> str:
    if email:
        token = _get_user_token(email, "dhan")
        if token: return token
    token = _read_env().get("DHAN_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN not found")
    return token

def get_upstox_api_key() -> str:
    return _read_env().get("UPSTOX_API_KEY", "92c6ea83-b7dc-44f3-b286-f89b1d9f5f6e")
