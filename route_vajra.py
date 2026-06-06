"""
VAJRA API Routes — Sensex scalping
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import httpx, json, os
from datetime import datetime
import pytz

from token_manager import get_upstox_token
from pragnya_engine import (
    get_state, update_state, check_rules, trigger_kill,
    record_sl_hit, add_trade, close_trade,
    get_today_trades, get_daily_quote, get_total_rewards,
)

router  = APIRouter()
IST     = pytz.timezone("Asia/Kolkata")
PRODUCT = "VAJRA"

CFG_PATH = os.path.expanduser("~/mahakaal/vajra_config.json")
DEFAULT_CFG = {
    "max_trades_per_day": 4,
    "daily_loss_limit": -2500,
    "daily_target": 5000,
    "max_sl_hits": 2,
    "cooling_minutes_after_sl": 15,
    "position_size_lots": 2,
    "sl_points": 20,
    "target_points": 40,
    "enable_pre_trade_breathe": True,
    "time_restrictions": {
        "no_trade_before": "09:15",
        "no_trade_after": "15:15",
        "lunch_break_start": "12:00",
        "lunch_break_end": "13:15",
    },
}

def load_cfg():
    if os.path.exists(CFG_PATH):
        merged = DEFAULT_CFG.copy()
        merged.update(json.load(open(CFG_PATH)))
        return merged
    return DEFAULT_CFG.copy()

async def fetch_ltp_multi(keys: list, email: str = None) -> dict:
    token = get_upstox_token(email)
    url   = "https://api.upstox.com/v3/market-quote/ltp?instrument_key=" + ",".join(keys)
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code == 200:
            return r.json().get("data", {})
    return {}

def parse_ltp(data: dict, key: str) -> dict:
    colon_key = key.replace("|", ":")
    d = data.get(colon_key) or data.get(key) or {}
    ltp   = d.get("last_price", 0)
    close = d.get("cp", 0)
    chg   = round(ltp - close, 2) if ltp and close else 0
    pct   = round((chg / close) * 100, 2) if close else 0
    return {"ltp": ltp, "close": close, "change": chg, "pct": pct}

@router.get("/market")
async def get_market(request: Request):
    from feed_manager import feed_manager
    feed = feed_manager.latest.get("data", {})
    def make(key):
        d = feed.get(key, {})
        ltp   = d.get("ltp", 0)
        close = d.get("close", 0)
        chg   = round(ltp - close, 2) if ltp and close else 0
        pct   = round((chg / close) * 100, 2) if close else 0
        return {"ltp": ltp, "close": close, "change": chg, "pct": pct}
    # Fallback to REST if feed is empty
    if not feed:
        email = None
        try:
            from route_auth import verify_token
            token = request.cookies.get("mtu_token")
            if not token:
                auth = request.headers.get("authorization","")
                if auth.startswith("Bearer "): token = auth[7:]
            if token: email = verify_token(token)["sub"]
        except: pass
        data   = await fetch_ltp_multi(["BSE_INDEX|SENSEX", "NSE_INDEX|Nifty 50", "NSE_INDEX|India VIX"], email)
        sensex = parse_ltp(data, "BSE_INDEX|SENSEX")
        nifty  = parse_ltp(data, "NSE_INDEX|Nifty 50")
        vix_d  = parse_ltp(data, "NSE_INDEX|India VIX")
        return {"sensex": sensex, "nifty": nifty, "vix": vix_d, "time": datetime.now(IST).strftime("%H:%M:%S")}
    return {"sensex": make("SENSEX"), "nifty": make("NIFTY"), "vix": make("VIX"), "time": datetime.now(IST).strftime("%H:%M:%S")}

@router.get("/state")
async def get_vajra_state():
    cfg   = load_cfg()
    state = get_state(PRODUCT)
    can_trade, warnings, lock = check_rules(PRODUCT, cfg)
    qt, qs = get_daily_quote()
    return {
        "state":      state,
        "cfg":        cfg,
        "can_trade":  can_trade,
        "warnings":   warnings,
        "lock":       lock,
        "quote":      {"text": qt, "src": qs},
        "rewards_pts": get_total_rewards(),
        "trades":     get_today_trades(PRODUCT),
    }

class TradeRequest(BaseModel):
    instrument: str
    direction:  str
    entry:      float
    sl:         float
    target:     float
    lots:       int   = 1
    strategy:   str   = "MANUAL"

class CloseRequest(BaseModel):
    trade_id:    int
    exit_price:  float
    exit_reason: str

@router.post("/trade/open")
async def open_trade(req: TradeRequest):
    cfg = load_cfg()
    can_trade, _, lock = check_rules(PRODUCT, cfg)
    if not can_trade:
        raise HTTPException(403, lock.get("reason", "Cannot trade"))
    state = get_state(PRODUCT)
    tid   = add_trade(PRODUCT, req.strategy, req.instrument, req.direction,
                      req.entry, req.sl, req.target, extra={"lots": req.lots})
    update_state(PRODUCT, trades_taken=state["trades_taken"]+1,
                 last_trade_time=datetime.now(IST).strftime("%H:%M:%S"))
    return {"status": "ok", "trade_id": tid}

@router.post("/trade/close")
async def close_trade_route(req: CloseRequest):
    cfg    = load_cfg()
    state  = get_state(PRODUCT)
    trades = get_today_trades(PRODUCT)
    trade  = next((t for t in trades if t["id"] == req.trade_id), None)
    if not trade:
        raise HTTPException(404, "Trade not found")
    lots     = json.loads(trade.get("extra_json") or "{}").get("lots", cfg["position_size_lots"])
    lot_size = 20  # Sensex
    pnl      = (req.exit_price - trade["entry"]) * lot_size * lots
    if trade["direction"] == "SHORT":
        pnl = -pnl
    close_trade(req.trade_id, req.exit_price, pnl, req.exit_reason)
    update_state(PRODUCT, daily_pnl=state["daily_pnl"] + pnl)
    if req.exit_reason == "SL":
        record_sl_hit(PRODUCT, cfg)
    return {"status": "ok", "pnl": round(pnl, 2), "daily_pnl": round(state["daily_pnl"] + pnl, 2)}

@router.post("/kill")
async def kill_switch():
    trigger_kill(PRODUCT)
    return {"status": "ok"}

@router.get("/config")
async def get_config():
    return load_cfg()

@router.post("/config")
async def save_config(cfg: dict):
    json.dump(cfg, open(CFG_PATH, "w"), indent=2)
    return {"status": "ok"}
