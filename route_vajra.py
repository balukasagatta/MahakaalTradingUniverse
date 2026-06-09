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
    "product_type": "I",
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
    ltp   = d.get("last_price") or d.get("ltp") or 0
    close = d.get("cp") or d.get("close") or 0
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
    # Broker status from user_tokens.json (first user for now — multi-user: pass email via JWT)
    import json as _json, os as _os
    _tokens_path = _os.path.expanduser("~/mahakaal/user_tokens.json")
    try:
        _all_tokens = _json.load(open(_tokens_path))
        _broker_status = "disconnected"
        for _email, _brokers in _all_tokens.items():
            for _broker, _data in _brokers.items():
                if _data.get("status") == "expired":
                    _broker_status = "expired"
                elif _data.get("access_token"):
                    _broker_status = "connected"
    except:
        _broker_status = "disconnected"

    return {
        "state":         state,
        "cfg":           cfg,
        "can_trade":     can_trade,
        "warnings":      warnings,
        "lock":          lock,
        "quote":         {"text": qt, "src": qs},
        "rewards_pts":   get_total_rewards(),
        "trades":        get_today_trades(PRODUCT),
        "broker_status": _broker_status,
    }

class TradeRequest(BaseModel):
    instrument:  str
    direction:   str
    entry:       float
    sl:          float
    target:      float
    lots:        int   = 1
    strategy:    str   = "MANUAL"
    upstox_key:  str   = ""   # BSE_FO|... instrument key for real order

class CloseRequest(BaseModel):
    trade_id:    int
    exit_price:  float
    exit_reason: str

@router.post("/trade/open")
async def open_trade(req: TradeRequest, request: Request):
    cfg = load_cfg()
    can_trade, _, lock = check_rules(PRODUCT, cfg)
    if not can_trade:
        raise HTTPException(403, lock.get("reason", "Cannot trade"))
    state = get_state(PRODUCT)

    # Place real Upstox order if instrument key provided
    upstox_order_id = None
    print(f'trade/open called: instrument={req.instrument} upstox_key={repr(req.upstox_key)}')
    if req.upstox_key:
        try:
            from jose import jwt as _jwt
            auth_header = request.headers.get("Authorization","")
            _payload = _jwt.get_unverified_claims(auth_header.replace("Bearer ",""))
            email = _payload.get("sub") or _payload.get("email")

            # Detect connected broker
            tokens = json.load(open(os.path.expanduser("~/mahakaal/user_tokens.json")))
            user_tokens = tokens.get(email, {})
            broker = None
            broker_token = None
            broker_info = {}
            for b in ["upstox", "dhan", "fyers", "zerodha"]:
                bt = user_tokens.get(b, {})
                if bt.get("access_token"):
                    broker = b
                    broker_token = bt["access_token"]
                    broker_info = bt
                    break

            if not broker or not broker_token:
                raise HTTPException(400, "No broker connected — connect from Settings")

            lot_size = 20
            qty = req.lots * lot_size
            transaction_type = req.direction  # BUY or SELL
            product_type = cfg.get("product_type", "I")

            print(f'Placing {broker} order for {email}: {transaction_type} {qty} {req.upstox_key}')

            async with httpx.AsyncClient(timeout=10) as client:
                if broker == "upstox":
                    order_payload = {
                        "quantity": qty, "product": product_type,
                        "validity": "DAY", "price": 0, "tag": "VAJRA",
                        "instrument_token": req.upstox_key,
                        "order_type": "MARKET", "transaction_type": transaction_type,
                        "disclosed_quantity": 0, "trigger_price": 0,
                        "is_amo": False, "variety": "NORMAL"
                    }
                    r = await client.post(
                        "https://api.upstox.com/v2/order/place",
                        json=order_payload,
                        headers={"Authorization": f"Bearer {broker_token}", "Content-Type": "application/json", "Accept": "application/json"}
                    )
                    print(f'Upstox response: {r.status_code} {r.text[:200]}')
                    if r.status_code == 200:
                        upstox_order_id = r.json().get("data", {}).get("order_id")
                    elif r.status_code == 401:
                        raise HTTPException(401, "Broker session expired — reconnect from Settings")
                    else:
                        err = r.json().get("errors", [{}])
                        msg = err[0].get("message", "Order rejected") if err else "Order rejected"
                        if "UDAPI1162" in r.text or "AMO" in msg:
                            msg = "After Market Orders not supported via API. Place during market hours (9:15 AM - 3:30 PM)."
                        elif "Upstox" in msg or "upstox" in msg:
                            msg = msg.replace("Upstox: ", "").replace("Upstox", "").strip()
                        raise HTTPException(400, msg)

                elif broker == "dhan":
                    client_id = broker_info.get("client_id", "")
                    # BSE_FO|1132638 → security_id = 1132638
                    security_id = req.upstox_key.split("|")[-1] if "|" in req.upstox_key else req.upstox_key
                    dhan_product = "INTRADAY" if product_type == "I" else "CNC"
                    # Determine option type from instrument key
                    opt_type = "CALL" if req.instrument.endswith("CE") else "PUT"
                    # Extract strike from instrument e.g. SENSEX73500CE → 73500
                    import re as _re
                    strike_match = _re.search(r'(\d+)(CE|PE)$', req.instrument)
                    strike_price = float(strike_match.group(1)) if strike_match else 0.0
                    order_payload = {
                        "dhanClientId": client_id,
                        "transactionType": transaction_type,
                        "exchangeSegment": "BSE_FNO",
                        "productType": dhan_product,
                        "orderType": "MARKET",
                        "validity": "DAY",
                        "tradingSymbol": "",
                        "securityId": security_id,
                        "quantity": qty,
                        "disclosedQuantity": 0,
                        "price": 0,
                        "triggerPrice": 0,
                        "afterMarketOrder": False,
                        "amoTime": "",
                        "boProfitValue": 0,
                        "boStopLossValue": 0,
                        "drvExpiryDate": "",
                        "drvOptionType": opt_type,
                        "drvStrikePrice": strike_price
                    }
                    r = await client.post(
                        "https://api.dhan.co/v2/orders",
                        json=order_payload,
                        headers={"access-token": broker_token, "client-id": client_id, "Content-Type": "application/json"}
                    )
                    print(f'Dhan response: {r.status_code} {r.text[:300]}')
                    if r.status_code == 200:
                        upstox_order_id = r.json().get("orderId") or r.json().get("data", {}).get("orderId")
                    elif r.status_code == 401:
                        raise HTTPException(401, "Dhan session expired — reconnect from Settings")
                    else:
                        try:
                            err_data = r.json()
                            msg = err_data.get("message") or err_data.get("errorMessage") or r.text[:200]
                        except Exception:
                            msg = r.text[:200]
                        raise HTTPException(400, msg)

        except HTTPException:
            raise
        except Exception as e:
            print(f'Order placement error: {e}')
            raise HTTPException(500, f'Order failed: {str(e)}')

    # If real order placed, mark as PENDING until exchange confirms
    initial_status = "PENDING" if upstox_order_id else "OPEN"
    tid = add_trade(PRODUCT, req.strategy, req.instrument, req.direction,
                    req.entry, req.sl, req.target,
                    extra={"lots": req.lots, "upstox_order_id": upstox_order_id},
                    status=initial_status)
    update_state(PRODUCT, trades_taken=state["trades_taken"]+1,
                 last_trade_time=datetime.now(IST).strftime("%H:%M:%S"))
    return {"status": "ok", "trade_id": tid, "upstox_order_id": upstox_order_id}

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

# Per-user order cache — prevents hammering Upstox API
_orders_cache = {}  # {email: {"data": [...], "ts": timestamp}}
_ORDERS_CACHE_TTL = 2  # seconds

@router.get("/orders")
async def get_orders(request: Request):
    try:
        from jose import jwt as _jwt
        auth_header = request.headers.get("Authorization","")
        _token_str = auth_header.replace("Bearer ","")
        _payload = _jwt.get_unverified_claims(_token_str)
        email = _payload.get("sub") or _payload.get("email")
        token = get_upstox_token(email)
        if not token:
            return {"orders": []}
        # Serve from cache if fresh
        import time as _time
        cached = _orders_cache.get(email)
        if cached and (_time.time() - cached["ts"]) < _ORDERS_CACHE_TTL:
            return {"orders": cached["data"]}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.upstox.com/v2/order/retrieve-all",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
            )
            if r.status_code == 200:
                orders = r.json().get("data", [])
                vajra_orders = sorted([o for o in orders if o.get("tag") == "VAJRA"], key=lambda x: x.get("order_id",""), reverse=True)
                _orders_cache[email] = {"data": vajra_orders, "ts": _time.time()}
                return {"orders": vajra_orders}
    except Exception as e:
        print(f"Orders fetch error: {e}")
    return {"orders": []}

@router.post("/trade/close-all")
async def close_all_trades(request: Request):
    import sqlite3
    from datetime import datetime
    conn = sqlite3.connect(os.path.expanduser("~/mahakaal/pragnya.db"))
    now = datetime.now(IST).strftime("%H:%M:%S")
    n = conn.execute(
        "UPDATE trades SET status='CLOSED',exit_price=0,exit_reason='MARKET_EXIT' WHERE status='OPEN' AND product=?",
        (PRODUCT,)
    ).rowcount
    conn.commit()
    conn.close()
    return {"status": "ok", "closed": n}

@router.post("/trade/close-instrument")
async def close_instrument_trades(request: Request):
    import sqlite3
    data = await request.json()
    instrument = data.get("instrument")
    direction  = data.get("direction")
    exit_price = data.get("exit_price", 0)
    close_all  = data.get("close_all", False)
    if not instrument or not direction:
        return {"status":"error","msg":"instrument and direction required"}
    conn = sqlite3.connect(os.path.expanduser("~/mahakaal/pragnya.db"))
    if close_all:
        n = conn.execute(
            "UPDATE trades SET status='CLOSED',exit_price=?,exit_reason='SQUARE_OFF' WHERE status='OPEN' AND product=? AND instrument=? AND direction=?",
            (exit_price, PRODUCT, instrument, direction)
        ).rowcount
    else:
        # Close only ONE trade (oldest first)
        row = conn.execute(
            "SELECT id FROM trades WHERE status='OPEN' AND product=? AND instrument=? AND direction=? ORDER BY id ASC LIMIT 1",
            (PRODUCT, instrument, direction)
        ).fetchone()
        if row:
            conn.execute("UPDATE trades SET status='CLOSED',exit_price=?,exit_reason='SQUARE_OFF' WHERE id=?", (exit_price, row[0]))
            n = 1
        else:
            n = 0
    conn.commit()
    conn.close()
    return {"status":"ok","closed":n}

@router.post("/orders/sync")
async def sync_orders(request: Request):
    """Sync PENDING orders from Upstox — call this on page load"""
    try:
        from jose import jwt as _jwt
        auth_header = request.headers.get("Authorization","")
        _payload = _jwt.get_unverified_claims(auth_header.replace("Bearer ",""))
        email = _payload.get("sub") or _payload.get("email")
        token = get_upstox_token(email)
        if not token: return {"synced": 0}
        # Get pending trades from DB
        conn = sqlite3.connect(os.path.expanduser("~/mahakaal/pragnya.db"))
        pending = conn.execute(
            "SELECT id, extra_json FROM trades WHERE status='PENDING' AND product=?", (PRODUCT,)
        ).fetchall()
        if not pending: conn.close(); return {"synced": 0}
        # Check each order status from Upstox
        synced = 0
        async with httpx.AsyncClient(timeout=10) as client:
            for trade_id, extra_json in pending:
                extra = json.loads(extra_json or "{}")
                order_id = extra.get("upstox_order_id")
                if not order_id: continue
                r = await client.get(
                    f"https://api.upstox.com/v2/order/details?order_id={order_id}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
                )
                if r.status_code == 200:
                    od = r.json().get("data", {})
                    status = od.get("status", "").lower()
                    if "complete" in status or "traded" in status:
                        avg_price = od.get("average_price", 0)
                        conn.execute(
                            "UPDATE trades SET status='OPEN', entry=? WHERE id=?",
                            (avg_price or extra.get("entry", 0), trade_id)
                        )
                        synced += 1
                    elif "reject" in status or "cancel" in status:
                        conn.execute("UPDATE trades SET status='CLOSED', exit_reason='REJECTED' WHERE id=?", (trade_id,))
                        synced += 1
        conn.commit()
        conn.close()
        return {"synced": synced}
    except Exception as e:
        return {"error": str(e)}

@router.post("/orders/cancel-all")
async def cancel_all_orders(request: Request):
    """Cancel all open/pending orders tagged VAJRA"""
    import sqlite3 as _sqlite3
    try:
        from jose import jwt as _jwt
        auth_header = request.headers.get("Authorization","")
        _payload = _jwt.get_unverified_claims(auth_header.replace("Bearer ",""))
        email = _payload.get("sub") or _payload.get("email")

        # Detect active broker
        tokens = json.load(open(os.path.expanduser("~/mahakaal/user_tokens.json")))
        user_tokens = tokens.get(email, {})
        broker = None
        broker_token = None
        broker_info = {}
        for b in ["upstox", "dhan"]:
            bt = user_tokens.get(b, {})
            if bt.get("access_token"):
                broker = b
                broker_token = bt["access_token"]
                broker_info = bt
                break

        if not broker or not broker_token:
            raise HTTPException(400, "No broker connected")

        cancelled = 0
        async with httpx.AsyncClient(timeout=10) as client:
            if broker == "upstox":
                r = await client.get(
                    "https://api.upstox.com/v2/order/retrieve-all",
                    headers={"Authorization": f"Bearer {broker_token}", "Accept": "application/json"}
                )
                if r.status_code == 200:
                    orders = r.json().get("data", [])
                    to_cancel = [o for o in orders if o.get("tag") == "VAJRA"
                                and o.get("status","").lower() not in ("complete","cancelled","rejected","cancelled after market order")]
                    for o in to_cancel:
                        cr = await client.delete(
                            f"https://api.upstox.com/v2/order/{o['order_id']}",
                            headers={"Authorization": f"Bearer {broker_token}", "Accept": "application/json"}
                        )
                        if cr.status_code == 200:
                            cancelled += 1

            elif broker == "dhan":
                client_id = broker_info.get("client_id", "")
                r = await client.get(
                    "https://api.dhan.co/v2/orders",
                    headers={"access-token": broker_token, "client-id": client_id, "Content-Type": "application/json"}
                )
                if r.status_code == 200:
                    orders = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
                    to_cancel = [o for o in orders if o.get("orderStatus","").upper() in ("PENDING","TRANSIT","PARTIALLY_TRADED")]
                    for o in to_cancel:
                        cr = await client.delete(
                            f"https://api.dhan.co/v2/orders/{o['orderId']}",
                            headers={"access-token": broker_token, "client-id": client_id, "Content-Type": "application/json"}
                        )
                        if cr.status_code in (200, 202):
                            cancelled += 1

        # Mark pending trades as closed in DB
        conn = _sqlite3.connect(os.path.expanduser("~/mahakaal/pragnya.db"))
        conn.execute("UPDATE trades SET status='CLOSED',exit_reason='CANCELLED' WHERE status='PENDING' AND product=?", (PRODUCT,))
        conn.commit()
        conn.close()
        return {"status": "ok", "cancelled": cancelled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/pragnya/emotion")
async def save_emotion(request: Request):
    try:
        body = await request.json()
        email = None
        try:
            from route_auth import verify_token
            token = request.cookies.get("mtu_token")
            if not token:
                auth = request.headers.get("authorization","")
                if auth.startswith("Bearer "): token = auth[7:]
            if token: email = verify_token(token)["sub"]
        except: pass
        save_eod_emotion(PRODUCT, body.get("emotion",""), body.get("note",""))
        add_reward(PRODUCT, "EMOTION_LOGGED")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/pragnya/rewards")
async def get_rewards(request: Request):
    try:
        total = get_total_rewards()
        history = get_rewards_history(20)
        eod = get_eod_emotion(PRODUCT)
        violations = get_today_violations(PRODUCT)
        return {"total_points": total, "history": history, "eod": eod, "violations": violations}
    except Exception as e:
        raise HTTPException(500, str(e))
