"""
SUTRA API Routes — Nifty options chain + strategy
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List
import httpx, json, os
from datetime import datetime
import pytz

from token_manager import get_upstox_token
from pragnya_engine import (
    get_state, update_state, check_rules, trigger_kill,
    add_trade, get_today_trades, get_daily_quote,
)

router  = APIRouter()
import time as _time
_chain_cache = {}
_CACHE_TTL = 20
_CACHE_TTL = 20
IST     = pytz.timezone("Asia/Kolkata")
PRODUCT = "SUTRA"

INDICES = {
    "NIFTY":      {"key": "NSE_INDEX|Nifty 50",         "lot": 75,  "step": 50},
    "BANKNIFTY":  {"key": "NSE_INDEX|Nifty Bank",        "lot": 35,  "step": 100},
    "SENSEX":     {"key": "BSE_INDEX|SENSEX",            "lot": 20,  "step": 100},
    "MIDCPNIFTY": {"key": "NSE_INDEX|NIFTY MID SELECT",  "lot": 75,  "step": 25},
}

async def _get(url: str) -> dict:
    token = get_upstox_token()
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code == 200:
            return r.json()
        raise HTTPException(r.status_code, f"Upstox error: {r.text[:200]}")

@router.get("/indices")
async def get_indices():
    return list(INDICES.keys())

@router.get("/expiries")
async def get_expiries(index: str = "NIFTY"):
    if index not in INDICES:
        raise HTTPException(400, f"Unknown index: {index}")
    data = await _get(f"https://api.upstox.com/v2/option/contract?instrument_key={INDICES[index]['key']}")
    expiries = sorted(set(c["expiry"] for c in data.get("data", [])))
    return {"index": index, "expiries": expiries}

@router.get("/chain")
async def get_chain(index: str = "NIFTY", expiry: str = Query(...)):
    cache_key = f"{index}_{expiry}"
    now = _time.time()
    if cache_key in _chain_cache and now - _chain_cache[cache_key]["ts"] < _CACHE_TTL:
        return _chain_cache[cache_key]["data"]
    if index not in INDICES:
        raise HTTPException(400, f"Unknown index: {index}")
    info = INDICES[index]

    # Spot price
    ltp_data = await _get(f"https://api.upstox.com/v3/market-quote/ltp?instrument_key={info['key']}")
    spot = 0.0
    for v in ltp_data.get("data", {}).values():
        spot = float(v.get("last_price", 0))
        break

    # Option chain
    chain_data = await _get(f"https://api.upstox.com/v2/option/chain?instrument_key={info['key']}&expiry_date={expiry}")
    atm = round(spot / info["step"]) * info["step"]

    strikes = []
    for row in chain_data.get("data", []):
        call = row.get("call_options", {})
        put  = row.get("put_options",  {})
        cd   = call.get("market_data",   {})
        pd   = put.get("market_data",    {})
        cg   = call.get("option_greeks", {})
        pg   = put.get("option_greeks",  {})
        strike = row.get("strike_price", 0)
        strikes.append({
            "strike": strike,
            "is_atm": abs(strike - atm) <= info["step"] / 2,
            "ce": {
                "ltp":   cd.get("ltp", 0),   "oi":  cd.get("oi", 0),
                "vol":   cd.get("volume", 0), "iv":  cg.get("iv", 0),
                "delta": cg.get("delta", 0),  "theta": cg.get("theta", 0),
                "vega":  cg.get("vega", 0),   "key": call.get("instrument_key", ""),
            },
            "pe": {
                "ltp":   pd.get("ltp", 0),   "oi":  pd.get("oi", 0),
                "vol":   pd.get("volume", 0), "iv":  pg.get("iv", 0),
                "delta": pg.get("delta", 0),  "theta": pg.get("theta", 0),
                "vega":  pg.get("vega", 0),   "key": put.get("instrument_key", ""),
            },
        })

    result = {
        "index": index, "expiry": expiry,
        "spot": spot, "atm": atm,
        "lot": info["lot"], "step": info["step"],
        "strikes": strikes,
    }
    _chain_cache[cache_key] = {"data": result, "ts": _time.time()}
    return result

@router.get("/state")
async def get_sutra_state():
    cfg = {
        "max_trades_per_day": 3, "daily_loss_limit": -5000, "daily_target": 10000,
        "max_sl_hits": 2, "cooling_minutes_after_sl": 30,
        "time_restrictions": {"no_trade_before": "09:30", "no_trade_after": "15:00",
                              "lunch_break_start": "12:00", "lunch_break_end": "13:00"},
    }
    state = get_state(PRODUCT)
    can_trade, warnings, lock = check_rules(PRODUCT, cfg)
    qt, qs = get_daily_quote()
    return {
        "state": state, "can_trade": can_trade,
        "warnings": warnings, "lock": lock,
        "quote": {"text": qt, "src": qs},
        "trades": get_today_trades(PRODUCT),
    }

class StrategyRequest(BaseModel):
    name:   str
    index:  str
    expiry: str
    legs:   List[dict]
    credit: float
    lots:   int = 1

@router.post("/trade/paper")
async def paper_trade(req: StrategyRequest):
    if req.index not in INDICES:
        raise HTTPException(400, "Unknown index")
    state = get_state(PRODUCT)
    tid = add_trade(PRODUCT, req.name, f"{req.index} {req.expiry}",
                    "SELL" if req.credit > 0 else "BUY",
                    req.credit, req.credit * 0.5, req.credit * 2,
                    extra={"legs": req.legs, "index": req.index, "expiry": req.expiry, "lots": req.lots})
    update_state(PRODUCT, trades_taken=state["trades_taken"] + 1)
    return {"status": "ok", "trade_id": tid}

@router.post("/kill")
async def kill_switch():
    trigger_kill(PRODUCT)
    return {"status": "ok"}
