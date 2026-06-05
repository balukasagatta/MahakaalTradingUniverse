"""
VAJRA API Routes — Sensex scalping
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from token_manager import get_upstox_token
from pragnya_engine import (
    get_state, update_state, check_rules, trigger_kill,
    trigger_cooling, record_sl_hit, add_trade, close_trade,
    get_today_trades, get_daily_quote, get_total_rewards,
)
import pytz
from datetime import datetime

router = APIRouter()
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
        saved = json.load(open(CFG_PATH))
        merged = DEFAULT_CFG.copy()
        merged.update(saved)
        return merged
    return DEFAULT_CFG.copy()

# ── Market data ────────────────────────────────────────────────────────────────
SENSEX_KEY = "BSE_INDEX|SENSEX"

async def fetch_quote(instrument_key: str) -> dict:
    token = get_upstox_token()
    url   = f"https://api.upstox.com/v3/market-quote/quotes?instrument_key={instrument_key}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code == 200:
            data = r.json()
            d = data.get("data", {}).get(instrument_key, {})
            return {
                "ltp":    d.get("last_price", 0),
                "open":   d.get("ohlc", {}).get("open", 0),
                "high":   d.get("ohlc", {}).get("high", 0),
                "low":    d.get("ohlc", {}).get("low", 0),
                "close":  d.get("ohlc", {}).get("close", 0),
                "change": d.get("net_change", 0),
                "pct":    d.get("net_change_percentage", 0),
                "volume": d.get("volume", 0),
            }
    return {}

@router.get("/market")
async def get_market():
    """Live Sensex + VIX quote"""
    sensex = await fetch_quote(SENSEX_KEY)
    vix    = await fetch_quote("NSE_INDEX|India VIX")
    return {
        "sensex": sensex,
        "vix":    vix,
        "time":   datetime.now(IST).strftime("%H:%M:%S"),
    }

# ── PRAGNYA state ──────────────────────────────────────────────────────────────
@router.get("/state")
async def get_vajra_state():
    cfg   = load_cfg()
    state = get_state(PRODUCT)
    can_trade, warnings, lock = check_rules(PRODUCT, cfg)
    quote_text, quote_src = get_daily_quote()
    total_pts = get_total_rewards()
    return {
        "state":      state,
        "cfg":        cfg,
        "can_trade":  can_trade,
        "warnings":   warnings,
        "lock":       lock,
        "quote":      {"text": quote_text, "src": quote_src},
        "rewards_pts": total_pts,
        "trades":     get_today_trades(PRODUCT),
    }

# ── Trade actions ──────────────────────────────────────────────────────────────
class TradeRequest(BaseModel):
    instrument: str
    direction:  str   # LONG | SHORT
    entry:      float
    sl:         float
    target:     float
    lots:       int = 1
    strategy:   str = "MANUAL"

class CloseRequest(BaseModel):
    trade_id:    int
    exit_price:  float
    exit_reason: str   # TARGET | SL | MANUAL

@router.post("/trade/open")
async def open_trade(req: TradeRequest):
    cfg   = load_cfg()
    state = get_state(PRODUCT)
    can_trade, warnings, lock = check_rules(PRODUCT, cfg)
    if not can_trade:
        raise HTTPException(403, lock.get("reason", "Cannot trade"))
    tid = add_trade(
        PRODUCT, req.strategy, req.instrument, req.direction,
        req.entry, req.sl, req.target,
        extra={"lots": req.lots}
    )
    update_state(PRODUCT,
                 trades_taken=state["trades_taken"] + 1,
                 last_trade_time=datetime.now(IST).strftime("%H:%M:%S"))
    return {"status": "ok", "trade_id": tid}

@router.post("/trade/close")
async def close_trade_route(req: CloseRequest):
    cfg   = load_cfg()
    state = get_state(PRODUCT)
    trades = get_today_trades(PRODUCT)
    trade  = next((t for t in trades if t["id"] == req.trade_id), None)
    if not trade:
        raise HTTPException(404, "Trade not found")

    lot_size = 20  # Sensex lot size
    lots     = trade.get("extra_json") and json.loads(trade["extra_json"]).get("lots", cfg["position_size_lots"])
    lots     = lots or cfg["position_size_lots"]

    if trade["direction"] == "LONG":
        pnl = (req.exit_price - trade["entry"]) * lot_size * lots
    else:
        pnl = (trade["entry"] - req.exit_price) * lot_size * lots

    hold_mins = None
    try:
        entry_t = datetime.strptime(trade["time"], "%H:%M:%S")
        now_t   = datetime.now(IST).replace(tzinfo=None)
        hold_mins = int((now_t - entry_t.replace(year=now_t.year, month=now_t.month, day=now_t.day)).total_seconds() / 60)
    except Exception:
        pass

    close_trade(req.trade_id, req.exit_price, pnl, req.exit_reason, hold_mins)
    new_pnl = state["daily_pnl"] + pnl
    update_state(PRODUCT, daily_pnl=new_pnl)

    if req.exit_reason == "SL":
        record_sl_hit(PRODUCT, cfg)

    return {"status": "ok", "pnl": pnl, "daily_pnl": new_pnl}

# ── Kill switch ────────────────────────────────────────────────────────────────
@router.post("/kill")
async def kill_switch():
    trigger_kill(PRODUCT)
    return {"status": "ok", "message": "Kill switch activated"}

# ── Config ────────────────────────────────────────────────────────────────────
@router.get("/config")
async def get_config():
    return load_cfg()

@router.post("/config")
async def save_config(cfg: dict):
    json.dump(cfg, open(CFG_PATH, "w"), indent=2)
    return {"status": "ok"}
