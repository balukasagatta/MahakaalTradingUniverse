"""
Token Manager — reads Upstox + Dhan tokens from ~/mahakaal/env.vars
"""
import os, re

ENV_PATH = os.path.expanduser("~/mahakaal/env.vars")

def _read_env():
    env = {}
    if not os.path.exists(ENV_PATH):
        return env
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def get_upstox_token() -> str:
    env = _read_env()
    token = env.get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not found in env.vars")
    return token

def get_dhan_token() -> str:
    env = _read_env()
    token = env.get("DHAN_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN not found in env.vars")
    return token

def get_upstox_api_key() -> str:
    env = _read_env()
    return env.get("UPSTOX_API_KEY", "92c6ea83-b7dc-44f3-b286-f89b1d9f5f6e")
