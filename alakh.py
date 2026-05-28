"""
Mahakaal T20 Scalp Bot v1.0
============================
Data:      Upstox (REST + Websocket)
Execution: Kotak Neo (zero brokerage)
Strategy:  Institutional grade scalping

Architecture:
  - 1-min candles from Upstox → aggregate to 3-min
  - Scoring engine (0-15 pts) → signal at ≥7
  - Pullback entry to key levels
  - Structure-based trailing exit (1-min candle close)
  - tbq/tsq sweep detection via Upstox websocket
  - Nifty/Sensex correlation filter

Capital: ₹2,00,000 | Kotak Neo
Daily target: ₹3,500 | Max loss: ₹4,000
"""

import os, json, math, time, threading, requests, pyotp
import websocket
from datetime import datetime, timedelta
from collections import deque
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from neo_api_client import NeoAPI
try:
    from db import (init_db, log_alakh_signal, update_alakh_signal,
                    upsert_alakh_daily, log_event)
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("[DB] db.py not found — logging disabled")

# ===== ENV LOADER =====
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.vars")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ===== CREDENTIALS =====
UPSTOX_TOKEN       = os.getenv("UPSTOX_ACCESS_TOKEN", "")
KOTAK_CONSUMER_KEY = os.getenv("KOTAK_CONSUMER_KEY", "")
KOTAK_MOBILE       = os.getenv("KOTAK_MOBILE", "")
KOTAK_MPIN         = os.getenv("KOTAK_MPIN", "")
KOTAK_UCC          = os.getenv("KOTAK_UCC", "")
KOTAK_TOTP_SECRET  = os.getenv("KOTAK_TOTP_SECRET", "")
TG_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT            = os.getenv("TELEGRAM_CHAT_ID", "")
PAPER              = os.getenv("PAPER_TRADE_MODE", "true").lower() == "true"
IST                = pytz.timezone("Asia/Kolkata")
IV_FILE            = "iv_history.json"

# ===== CONSTANTS =====
UPSTOX_BASE        = "https://api.upstox.com/v2"
SENSEX_KEY         = "BSE_INDEX|SENSEX"
NIFTY_KEY          = "NSE_INDEX|Nifty 50"
SENSEX_FO_SEG      = "BSE_INDEX|SENSEX"


def is_market_holiday():
    """Check if today is NSE market holiday by fetching from NSE."""
    try:
        today = now_ist().strftime("%Y-%m-%d")
        import requests
        r = requests.get(
            "https://www.nseindia.com/api/holiday-master?type=trading",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com"
            },
            timeout=10)
        if r.status_code == 200:
            data = r.json()
            holidays = data.get("CM", [])
            for h in holidays:
                if h.get("tradingDate", "").startswith(today):
                    return True
            return False
    except Exception as e:
        print(f"[Holiday] API error: {e} — assuming not holiday")
        return False

# ===== PARAMETERS =====
# Scoring thresholds
SCORE_NORMAL       = 7
SCORE_HIGH_IV      = 8
SCORE_POST_TARGET  = 10

# Position sizing
LOTS_NORMAL        = 5
LOTS_HIGH_IV       = 3
LOT_SIZE           = 20

# Targets
DAILY_TARGET       = 2500
DAILY_LOSS_LIMIT   = 4000
LOCK_PTS           = 30    # lock profit before trailing
SL_PTS             = 20    # initial SL on option premium

# Session windows
PRIME_START        = (9, 20)
PRIME_END          = (11, 30)

# Filters
ATM_SPREAD_MAX     = 10    # max bid-ask spread
IV_HIGH_THRESHOLD  = 20.0  # IV% above this = high IV day
MAX_SCALPS         = 4
KILL_SL            = 2
DEDUP_SECS         = 120

# ===== UTILS =====
def compute_vwap(candles):
    """Compute VWAP from candles list [ts, o, h, l, c, v]."""
    total_pv = 0
    total_v = 0
    for c in candles:
        typical = (c[2] + c[3] + c[4]) / 3
        vol = c[5] if len(c) > 5 else 1
        total_pv += typical * vol
        total_v += vol
    return total_pv / total_v if total_v > 0 else 0


def now_ist():    return datetime.now(IST)
def today_str():  return now_ist().strftime("%Y-%m-%d")
def now_mins():   n=now_ist(); return n.hour*60+n.minute
def ts_to_ist(ts): return datetime.fromisoformat(ts).astimezone(IST)

# ===== TELEGRAM =====
def tg(msg, retries=3):
    url=f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(retries):
        try:
            r=requests.post(url,
                json={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"},
                timeout=10)
            if r.status_code==200: return True
        except Exception as e:
            print(f"[TG] {e}")
            if i<retries-1: time.sleep(3)
    return False

# ===== UPSTOX REST =====
def upstox_headers():
    return {"Authorization": f"Bearer {UPSTOX_TOKEN}",
            "Accept": "application/json"}

def upstox_ltp(instrument_key):
    """Get last traded price for an instrument."""
    try:
        r = requests.get(f"{UPSTOX_BASE}/market-quote/ltp",
            headers=upstox_headers(),
            params={"instrument_key": instrument_key},
            timeout=10)
        d = r.json()
        if d.get("status") == "success":
            key = instrument_key.replace("|", ":")
            return d["data"][key]["last_price"]
    except Exception as e:
        print(f"[Upstox] LTP error: {e}")
    return None

def upstox_candles_1min(instrument_key, days=1):
    """
    Fetch 1-min intraday candles.
    Format: [timestamp, open, high, low, close, volume, oi]
    Returns newest first.
    """
    try:
        r = requests.get(
            f"{UPSTOX_BASE}/historical-candle/intraday/{instrument_key}/1minute",
            headers=upstox_headers(),
            timeout=15)
        d = r.json()
        if d.get("status") == "success":
            candles = d["data"]["candles"]
            # Sort oldest first
            candles.sort(key=lambda x: x[0])
            return candles
    except Exception as e:
        print(f"[Upstox] Candles error: {e}")
    return []

def aggregate_to_3min(candles_1min):
    """
    Aggregate 1-min candles to 3-min candles.
    Input: [[ts, o, h, l, c, v, oi], ...]  oldest first
    Output: [[ts, o, h, l, c, v], ...]  oldest first
    """
    if not candles_1min:
        return []
    result = []
    group = []
    for candle in candles_1min:
        ts = ts_to_ist(candle[0])
        # Group by 3-min buckets: 0,3,6,9...
        bucket = (ts.minute // 3) * 3
        bucket_ts = ts.replace(minute=bucket, second=0, microsecond=0)
        if group and group[0]["bucket"] != bucket_ts:
            # Finalize previous group
            c = group
            result.append([
                c[0]["bucket"].isoformat(),
                c[0]["o"],           # open of first candle
                max(x["h"] for x in c),  # highest high
                min(x["l"] for x in c),  # lowest low
                c[-1]["c"],          # close of last candle
                sum(x["v"] for x in c),  # total volume
            ])
            group = []
        group.append({
            "bucket": bucket_ts,
            "o": candle[1], "h": candle[2],
            "l": candle[3], "c": candle[4],
            "v": candle[5]
        })
    # Add last group if has enough candles
    if len(group) >= 2:
        c = group
        result.append([
            c[0]["bucket"].isoformat(),
            c[0]["o"], max(x["h"] for x in c),
            min(x["l"] for x in c), c[-1]["c"],
            sum(x["v"] for x in c)
        ])
    return result

def upstox_daily_candles(instrument_key, days=10):
    """Fetch daily candles for pivot calculation."""
    try:
        to_date = today_str()
        from_date = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = requests.get(
            f"{UPSTOX_BASE}/historical-candle/{instrument_key}/day/{to_date}/{from_date}",
            headers=upstox_headers(),
            timeout=15)
        d = r.json()
        if d.get("status") == "success":
            candles = d["data"]["candles"]
            candles.sort(key=lambda x: x[0])
            return candles
    except Exception as e:
        print(f"[Upstox] Daily candles error: {e}")
    return []

def upstox_option_chain(expiry_date):
    """
    Fetch full option chain with greeks.
    Returns list of strike dicts.
    """
    try:
        r = requests.get(f"{UPSTOX_BASE}/option/chain",
            headers=upstox_headers(),
            params={"instrument_key": SENSEX_FO_SEG,
                    "expiry_date": expiry_date},
            timeout=15)
        d = r.json()
        if d.get("status") == "success":
            return d["data"]
    except Exception as e:
        print(f"[Upstox] Chain error: {e}")
    return []

def upstox_expiries():
    """Get upcoming Sensex expiry dates."""
    try:
        r = requests.get(f"{UPSTOX_BASE}/option/contract",
            headers=upstox_headers(),
            params={"instrument_key": SENSEX_FO_SEG},
            timeout=10)
        d = r.json()
        if d.get("status") == "success":
            today = now_ist().date()
            expiries = set()
            for item in d["data"]:
                exp = item.get("expiry", "")
                if exp:
                    try:
                        exp_date = datetime.strptime(
                            exp[:10], "%Y-%m-%d").date()
                        if exp_date >= today:
                            expiries.add(exp[:10])
                    except: pass
            return sorted(list(expiries))
    except Exception as e:
        print(f"[Upstox] Expiries error: {e}")
    return []

# ===== KOTAK NEO =====
_neo = None
_neo_lock = threading.Lock()

def neo_login():
    global _neo
    try:
        client = NeoAPI(
            environment='prod',
            access_token=None,
            neo_fin_key=None,
            consumer_key=KOTAK_CONSUMER_KEY)
        totp = pyotp.TOTP(KOTAK_TOTP_SECRET).now()
        r1 = client.totp_login(
            mobile_number=KOTAK_MOBILE,
            ucc=KOTAK_UCC,
            totp=totp)
        if r1.get('data', {}).get('status') != 'success':
            print(f"[Neo] Login failed: {r1}"); return False
        r2 = client.totp_validate(mpin=KOTAK_MPIN)
        if r2.get('data', {}).get('status') != 'success':
            print(f"[Neo] Validate failed: {r2}"); return False
        with _neo_lock: _neo = client
        print("[Neo] ✅ Connected"); return True
    except Exception as e:
        print(f"[Neo] Login error: {e}"); return False

def neo(): 
    with _neo_lock: return _neo

# ===== WEBSOCKET STATE =====
# Real-time tick data from Upstox websocket
WS_STATE = {
    "sensex_ltp": None,
    "nifty_ltp": None,
    "atm_ce_ltp": None,
    "atm_pe_ltp": None,
    "atm_tbq": 0,   # total buy qty
    "atm_tsq": 0,   # total sell qty
    "atm_key": None,
    "connected": False,
    "last_tick": None,
}
WS_LOCK = threading.Lock()

# 1-min candle builder from ticks
TICK_BUFFER = {
    "sensex": deque(maxlen=500),
    "nifty": deque(maxlen=500),
}
TICK_LOCK = threading.Lock()

def on_ws_message(ws, message):
    """Process websocket tick data."""
    try:
        import struct, json
        # Upstox V3 uses protobuf — parse binary
        # For now using REST polling as fallback
        # Full protobuf implementation below
        pass
    except Exception as e:
        print(f"[WS] Message error: {e}")

def on_ws_open(ws):
    with WS_LOCK: WS_STATE["connected"] = True
    print("[WS] Connected")
    # Subscribe to Sensex + Nifty in full mode
    sub_msg = json.dumps({
        "guid": "mahakaal-001",
        "method": "sub",
        "data": {
            "mode": "full",
            "instrumentKeys": [SENSEX_KEY, NIFTY_KEY]
        }
    })
    ws.send(sub_msg.encode())

def on_ws_close(ws, code, msg):
    with WS_LOCK: WS_STATE["connected"] = False
    print(f"[WS] Disconnected: {code} {msg}")
    # Reconnect after 5s
    threading.Timer(5, start_websocket).start()

def on_ws_error(ws, error):
    print(f"[WS] Error: {error}")

def start_websocket():
    """Start Upstox websocket connection."""
    try:
        r = requests.get(
            "https://api.upstox.com/v3/feed/market-data-feed/authorize",
            headers=upstox_headers(),
            timeout=10)
        d = r.json()
        if d.get("status") != "success":
            print(f"[WS] Auth failed: {d}"); return
        ws_url = d["data"]["authorizedRedirectUri"]
        ws_app = websocket.WebSocketApp(
            ws_url,
            on_open=on_ws_open,
            on_message=on_ws_message,
            on_close=on_ws_close,
            on_error=on_ws_error)
        t = threading.Thread(
            target=ws_app.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True)
        t.start()
        print("[WS] Starting...")
    except Exception as e:
        print(f"[WS] Start error: {e}")

# ===== STATE =====
OR_S = {
    "date": None, "high": None, "low": None,
    "ticks": 0, "locked": False, "announced": False,
    "gap_type": "UNKNOWN", "gap_pct": 0.0,
    "open_price": None,   # first candle open (gap signal)
}
OR_L = threading.Lock()

RISK = {
    "date": None, "sl_hits": 0, "halted": False,
    "alert_only": False,
    "scalps": 0, "pnl": 0, "daily_approved": True
}
RISK_L = threading.Lock()

TRADE = {
    "active": False, "side": None,
    "strike": None, "instrument_key": None,
    "entry_premium": None, "sl_price": None,
    "trail_sl": None, "lock_achieved": False,
    "entry_time": None, "lots": None, "qty": None,
    "expiry": None, "entry_idx": None,
    "candles_since_entry": 0,
    "prev_1min_lows": deque(maxlen=5),
    "prev_1min_highs": deque(maxlen=5),
    "signal_id": None,
}
TRADE_L = threading.Lock()

LAST_SIGNAL = {"time": None}
LAST_L = threading.Lock()

EVENT_DAYS = {
    # Add known high impact event dates here
    # "2026-06-05": "RBI Policy",
}

# ===== DAILY RESET =====
def reset_daily():
    today = now_ist().date()
    with RISK_L:
        if RISK["date"] != today:
            is_event = today_str() in EVENT_DAYS
            RISK.update({
                "date": today, "sl_hits": 0,
                "halted": False, "alert_only": False, "scalps": 0,
                "pnl": 0,
                "daily_approved": not is_event
            })
            print(f"[Risk] Reset {today}")
            if is_event:
                event_name = EVENT_DAYS[today_str()]
                tg(f"⚠️ <b>HIGH IMPACT EVENT: {event_name}</b>\n"
                   f"Bot paused. Send /approve to enable trading.")

def is_allowed():
    reset_daily(); n = now_ist()
    if n.weekday() > 4: return False, "Weekend"
    if n.hour >= 15: return False, "After 3PM"
    if n.hour < 9 or (n.hour == 9 and n.minute < 20):
        return False, "Pre-market"
    with RISK_L:
        if RISK["halted"]: return False, "Halted"
        if not RISK["daily_approved"]: return False, "Event day"
    return True, "OK"

def is_execution_allowed():
    """Separate check for execution (stricter than alerts)."""
    with RISK_L:
        if RISK["alert_only"]: return False, "Alert only mode"
        if RISK["halted"]: return False, "Halted"
    return True, "OK"

def get_session():
    m = now_mins()
    if m < PRIME_START[0]*60+PRIME_START[1]: return "PRE"
    elif m <= PRIME_END[0]*60+PRIME_END[1]: return "PRIME"
    elif m <= 15*60: return "BONUS"
    else: return "CLOSED"

def register_sl(loss=0):
    with RISK_L:
        RISK["sl_hits"] += 1
        RISK["pnl"] -= abs(loss)
        hits = RISK["sl_hits"]
        if hits >= KILL_SL or abs(RISK["pnl"]) >= DAILY_LOSS_LIMIT:
            # ALERT ONLY mode — don't halt completely
            # Bot continues sending signals but won't auto-execute
            RISK["alert_only"] = True
            reason = '2 SL hits' if hits >= KILL_SL else 'Loss limit'
            tg(f"🛑 <b>KILL SWITCH — ALERT ONLY MODE</b>\n"
               f"Reason: {reason}\n"
               f"P&L: -₹{abs(RISK['pnl']):,.0f}\n\n"
               f"✅ Bot continues sending signals\n"
               f"❌ Auto-execution stopped\n"
               f"Send /execute after next signal to trade manually")
            return True
        tg(f"⚠️ <b>SL #{hits}</b> | -₹{abs(loss):,.0f} | "
           f"{'1 more → Alert Only mode' if hits == 1 else ''}")
        return False

def register_profit(amount):
    with RISK_L:
        RISK["pnl"] += amount

# ===== INDICATORS =====
def compute_supertrend(candles_1min, period=10, mult=3.0):
    """
    Compute Supertrend(10,3) on 1-min candles.
    Returns (direction, st_value, stable_candles, prev_direction)
    stable_candles = consecutive candles in CURRENT direction only
    prev_direction = direction before current (to detect fresh flip)
    """
    if len(candles_1min) < period + 5:
        return None, None, 0, None
    h = [c[2] for c in candles_1min]
    l = [c[3] for c in candles_1min]
    c = [c[4] for c in candles_1min]
    # True Range
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]),
                abs(l[i]-c[i-1])) for i in range(1, len(h))]
    # Wilder ATR
    atr = [sum(trs[:period]) / period]
    for i in range(period, len(trs)):
        atr.append((atr[-1] * (period-1) + trs[i]) / period)
    if not atr: return None, None, 0, None
    # Supertrend
    st = []; direction = []
    offset = len(h) - len(atr) - 1
    for i in range(len(atr)):
        idx = i + offset + 1
        if idx >= len(h): break
        hl2 = (h[idx] + l[idx]) / 2
        upper = hl2 + mult * atr[i]
        lower = hl2 - mult * atr[i]
        if i == 0:
            val = lower if c[idx] > upper else upper
            st.append(val)
            direction.append("BUY" if c[idx] > val else "SELL")
        else:
            pst = st[-1]; pdir = direction[-1]
            if pdir == "BUY":
                val = max(lower, pst) if c[idx] > lower else upper
            else:
                val = min(upper, pst) if c[idx] < upper else lower
            st.append(val)
            direction.append("BUY" if c[idx] > val else "SELL")
    if not direction: return None, None, 0, None

    # FIX 1: Count ONLY consecutive candles in CURRENT direction
    # Stop counting at the first candle that was different direction
    cur = direction[-1]
    stable = 0
    prev_direction = None
    for i, d in enumerate(reversed(direction)):
        if d == cur:
            stable += 1
        else:
            prev_direction = d  # direction before the flip
            break

    return cur, round(st[-1], 2), stable, prev_direction

# ===== ALERT CANDLE STATE =====
# Stores the ST flip candle for entry confirmation
ALERT_C = {
    "active": False,
    "direction": None,  # BUY or SELL
    "high": None,       # alert candle high (index)
    "low": None,        # alert candle low (index)
    "st_val": None,     # ST value at flip
    "timestamp": None,
    "confirmed": False, # True when candle 2 broke H/L
}
ALERT_L = threading.Lock()

def compute_ema(closes, period):
    """Compute EMA for given period."""
    if len(closes) < period: return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)
    """VWAP from today's 1-min candles."""
    today = now_ist().date()
    pv = vol = 0
    for c in candles_1min:
        ts = ts_to_ist(c[0])
        if ts.date() != today: continue
        h, lo, cl, v = c[2], c[3], c[4], c[5]
        pv += (h + lo + cl) / 3 * v
        vol += v
    return round(pv / vol, 2) if vol > 0 else None

def compute_pivots(h, l, c):
    p = (h + l + c) / 3
    return {
        "pivot": round(p, 2),
        "r1": round(2*p - l, 2),
        "r2": round(p + (h-l), 2),
        "s1": round(2*p - h, 2),
        "s2": round(p - (h-l), 2),
    }

def prev_ohlc():
    """Get previous day OHLC from daily candles."""
    candles = upstox_daily_candles(SENSEX_KEY, 10)
    today = today_str()
    for c in reversed(candles):
        if c[0][:10] < today:
            return {"date": c[0][:10],
                    "open": c[1], "high": c[2],
                    "low": c[3], "close": c[4]}
    return None

def detect_gap(prev_close, current):
    if not prev_close or not current: return "UNKNOWN", 0.0
    pct = (current - prev_close) / prev_close * 100
    if pct > 1.75:  return "EXTREME_GAP_UP", round(pct, 2)
    if pct > 1.00:  return "LARGE_GAP_UP", round(pct, 2)
    if pct > 0.55:  return "GAP_UP", round(pct, 2)
    if pct < -1.75: return "EXTREME_GAP_DOWN", round(pct, 2)
    if pct < -1.00: return "LARGE_GAP_DOWN", round(pct, 2)
    if pct < -0.55: return "GAP_DOWN", round(pct, 2)
    return "FLAT_OPEN", round(pct, 2)

def compute_dte(expiry_str):
    try:
        return (datetime.strptime(expiry_str, "%Y-%m-%d").date()
                - now_ist().date()).days
    except: return 5

# ===== IV RANK =====
def load_iv():
    try:
        if os.path.exists(IV_FILE):
            with open(IV_FILE) as f: return json.load(f)
    except: pass
    return {}

def save_iv(h):
    try:
        with open(IV_FILE, "w") as f: json.dump(h, f)
    except: pass

def store_eod_iv(atm_iv):
    h = load_iv()
    if "sensex" not in h: h["sensex"] = {}
    h["sensex"][today_str()] = round(atm_iv, 2)
    sd = sorted(h["sensex"].keys())
    for old in sd[:-90]: del h["sensex"][old]
    save_iv(h)

def get_iv_rank(current_iv):
    d = load_iv().get("sensex", {})
    if len(d) < 15: return None
    vals = list(d.values())
    hi, lo = max(vals), min(vals)
    return 50 if hi == lo else round(
        (current_iv - lo) / (hi - lo) * 100, 1)

def is_high_iv_day(atm_iv, iv_rank=None):
    if iv_rank is not None: return iv_rank > 70
    return atm_iv > IV_HIGH_THRESHOLD

# ===== SCORING ENGINE =====
def compute_score(
    spot, candles_1min, candles_3min,
    or_high, or_low, or_open,
    prev_close, pivots,
    st_signal, st_val, st_stable,
    nifty_st,
    atm_ce, atm_pe,
    tbq, tsq
):
    """
    Compute signal score (0-15).
    Positive = CALL bias, Negative = PUT bias
    Returns (call_score, put_score, details)
    """
    call_pts = 0; put_pts = 0; details = {}

    # ===== PRICE ACTION (6 pts) =====

    # 1. Consecutive higher highs/lows (±2)
    if len(candles_3min) >= 4:
        last4 = candles_3min[-4:]
        highs = [c[2] for c in last4]
        lows  = [c[3] for c in last4]
        if all(highs[i] > highs[i-1] for i in range(1,4)):
            call_pts += 2
            details["consec_hh"] = "3 consecutive HH → +2 CALL"
        elif all(highs[i] < highs[i-1] for i in range(1,4)):
            put_pts += 2
            details["consec_ll"] = "3 consecutive LL → +2 PUT"
        elif all(lows[i] > lows[i-1] for i in range(1,4)):
            call_pts += 2
            details["consec_hl"] = "3 consecutive HL → +2 CALL"
        elif all(lows[i] < lows[i-1] for i in range(1,4)):
            put_pts += 2
            details["consec_lh"] = "3 consecutive LH → +2 PUT"

    # 2. Price at key level (±2)
    atr = 50  # default
    if pivots:
        prox = atr * 0.5
        near_s1 = abs(spot - pivots["s1"]) < prox
        near_s2 = abs(spot - pivots["s2"]) < prox
        near_r1 = abs(spot - pivots["r1"]) < prox
        near_r2 = abs(spot - pivots["r2"]) < prox
        near_piv = abs(spot - pivots["pivot"]) < prox
        if near_s1 or near_s2:
            call_pts += 2
            level = "S1" if near_s1 else "S2"
            details["level"] = f"Price at {level} {pivots[level.lower()]:,.0f} → +2 CALL"
        elif near_r1 or near_r2:
            put_pts += 2
            level = "R1" if near_r1 else "R2"
            details["level"] = f"Price at {level} {pivots[level.lower()]:,.0f} → +2 PUT"
        elif near_piv:
            # Neutral at pivot — add based on direction
            details["level"] = f"Price at Pivot {pivots['pivot']:,.0f}"

    # 3. Candle close strength (±1)
    if candles_3min:
        last = candles_3min[-1]
        o, h, l, c = last[1], last[2], last[3], last[4]
        rng = h - l
        if rng > 0:
            close_pct = (c - l) / rng
            if close_pct >= 0.7:
                call_pts += 1
                details["close_str"] = f"Strong close {close_pct:.0%} → +1 CALL"
            elif close_pct <= 0.3:
                put_pts += 1
                details["close_str"] = f"Weak close {close_pct:.0%} → +1 PUT"

    # 4. Gap open position (±1)
    if or_high and or_low and or_open:
        or_range = or_high - or_low
        upper_z = or_high - or_range * 0.3
        lower_z = or_low + or_range * 0.3
        if or_open >= upper_z:
            call_pts += 1
            details["gap_pos"] = f"Opened near high {or_open:,.0f} → +1 CALL"
        elif or_open <= lower_z:
            put_pts += 1
            details["gap_pos"] = f"Opened near low {or_open:,.0f} → +1 PUT"
        else:
            details["gap_pos"] = "Opened in middle"

    # ===== PRICE STRUCTURE (4 pts) =====

    # 5. Price vs VWAP (±1)
    vwap = compute_vwap(candles_1min)
    if vwap and spot:
        diff_pct = abs(spot - vwap) / spot * 100
        if spot > vwap and diff_pct > 0.15:
            call_pts += 1
            details["vwap"] = f"Above VWAP {vwap:,.0f} (+{diff_pct:.2f}%) → +1 CALL"
        elif spot < vwap and diff_pct > 0.15:
            put_pts += 1
            details["vwap"] = f"Below VWAP {vwap:,.0f} (-{diff_pct:.2f}%) → +1 PUT"
        else:
            details["vwap"] = f"Near VWAP {vwap:,.0f}"

    # 6. Price vs prev day close (±1)
    if prev_close and spot:
        if spot > prev_close:
            call_pts += 1
            details["prev_close"] = f"Above prev close {prev_close:,.0f} → +1 CALL"
        else:
            put_pts += 1
            details["prev_close"] = f"Below prev close {prev_close:,.0f} → +1 PUT"

    # 7. ORB side hugging (±1)
    if or_high and or_low and candles_3min:
        today = now_ist().date()
        or_mid = (or_high + or_low) / 2
        today_closes = []
        for c in candles_3min:
            try:
                if ts_to_ist(c[0]).date() == today:
                    today_closes.append(c[4])
            except: pass
        if today_closes:
            upper_count = sum(1 for c in today_closes if c > or_mid)
            lower_count = sum(1 for c in today_closes if c <= or_mid)
            if upper_count > lower_count * 1.5:
                call_pts += 1
                put_pts -= 1
                details["orb_hug"] = "Hugging ORB top → +1 CALL / -1 PUT"
            elif lower_count > upper_count * 1.5:
                put_pts += 1
                call_pts -= 1
                details["orb_hug"] = "Hugging ORB bottom → +1 PUT / -1 CALL"

    # 8. Volume up vs down (±1)
    if candles_3min:
        today = now_ist().date()
        up_vol = dn_vol = 0
        for c in candles_3min:
            try:
                if ts_to_ist(c[0]).date() == today:
                    if c[4] > c[1]: up_vol += c[5]  # green
                    elif c[4] < c[1]: dn_vol += c[5]  # red
            except: pass
        if up_vol > dn_vol * 1.3:
            call_pts += 1
            details["vol_dir"] = f"Up vol {up_vol:,.0f} > Dn vol {dn_vol:,.0f} → +1 CALL"
        elif dn_vol > up_vol * 1.3:
            put_pts += 1
            details["vol_dir"] = f"Dn vol {dn_vol:,.0f} > Up vol {up_vol:,.0f} → +1 PUT"

    # ===== INDICATORS (4 pts) =====

    # 9. Supertrend direction (±2)
    if st_signal:
        if st_signal == "BUY":
            call_pts += 2
            details["st"] = f"ST BUY @ {st_val:,.0f} → +2 CALL"
        else:
            put_pts += 2
            details["st"] = f"ST SELL @ {st_val:,.0f} → +2 PUT"

    # 10. ST trap rule (2-candle confirm) (+1)
    if st_stable >= 2:
        if st_signal == "BUY":
            call_pts += 1
            details["st_stable"] = f"ST stable {st_stable} candles → +1 CALL"
        elif st_signal == "SELL":
            put_pts += 1
            details["st_stable"] = f"ST stable {st_stable} candles → +1 PUT"
    else:
        details["st_stable"] = f"ST only {st_stable} candle(s) — wait for 2"

    # 11. Nifty correlation (±1)
    if nifty_st:
        if nifty_st == st_signal:
            if st_signal == "BUY":
                call_pts += 1
                details["nifty"] = "Nifty confirms BUY → +1"
            else:
                put_pts += 1
                details["nifty"] = "Nifty confirms SELL → +1"
        else:
            if st_signal == "BUY":
                call_pts -= 1
                details["nifty"] = "Nifty diverges (SELL) → -1 CALL"
            else:
                put_pts -= 1
                details["nifty"] = "Nifty diverges (BUY) → -1 PUT"

    # ===== OI/FLOW (2 pts) =====

    # 12. tbq vs tsq (±1)
    if tbq and tsq and tbq + tsq > 0:
        ratio = tbq / (tbq + tsq)
        if ratio > 0.6:
            call_pts += 1
            details["flow"] = f"Buyers dominant {ratio:.0%} → +1 CALL"
        elif ratio < 0.4:
            put_pts += 1
            details["flow"] = f"Sellers dominant {1-ratio:.0%} → +1 PUT"

    # 13. Spread quality (+1 if tight)
    if atm_ce:
        spread = atm_ce.get("ask_price", 0) - atm_ce.get("bid_price", 0)
        if 0 < spread < ATM_SPREAD_MAX:
            # Neutral quality bonus — applies to whichever side leads
            if call_pts > put_pts: call_pts += 1
            elif put_pts > call_pts: put_pts += 1
            details["spread"] = f"Spread ₹{spread:.1f} tight → +1"
        else:
            details["spread"] = f"Spread ₹{spread:.1f} wide → skip"

    # Ensure non-negative
    call_pts = max(0, call_pts)
    put_pts = max(0, put_pts)

    details["vwap_val"] = vwap
    details["call_score"] = call_pts
    details["put_score"] = put_pts

    return call_pts, put_pts, details

# ===== OPENING RANGE =====
def or_reset():
    today = now_ist().date()
    with OR_L:
        if OR_S["date"] != today:
            OR_S.update({
                "date": today, "high": None, "low": None,
                "ticks": 0, "locked": False, "announced": False,
                "gap_type": "UNKNOWN", "gap_pct": 0.0,
                "open_price": None,
            })

def or_track():
    if now_ist().weekday() > 4: return
    or_reset()
    with OR_L:
        if OR_S["locked"]: return
    ltp = upstox_ltp(SENSEX_KEY)
    if ltp is None: return
    with OR_L:
        if OR_S["high"] is None:
            OR_S["high"] = OR_S["low"] = ltp
            OR_S["open_price"] = ltp  # first tick = open
        else:
            OR_S["high"] = max(OR_S["high"], ltp)
            OR_S["low"] = min(OR_S["low"], ltp)
        OR_S["ticks"] += 1

def or_lock():
    if now_ist().weekday() > 4: return
    or_reset()
    with OR_L:
        if OR_S["locked"] and OR_S["announced"]: return
        if OR_S["high"] is None:
            tg("⚠️ OR Lock delayed — retrying in 15s")
            threading.Timer(15, or_lock).start(); return
        OR_S["locked"] = True; OR_S["announced"] = True
        oh, ol = OR_S["high"], OR_S["low"]
        op = OR_S["open_price"]

    # Get prev OHLC for gap and pivots
    prev = prev_ohlc()
    pivots_str = ""
    gap_str = ""
    if prev:
        gap_type, gap_pct = detect_gap(prev["close"], (oh+ol)/2)
        with OR_L:
            OR_S["gap_type"] = gap_type
            OR_S["gap_pct"] = gap_pct
        pivots = compute_pivots(prev["high"], prev["low"], prev["close"])
        gap_str = f"\nGap: {gap_type.replace('_',' ')} ({gap_pct:+.2f}%)" \
            if gap_type not in ["FLAT_OPEN","UNKNOWN"] else ""
        pivots_str = (f"\nR1: {pivots['r1']:,.0f} | "
                      f"Pivot: {pivots['pivot']:,.0f} | "
                      f"S1: {pivots['s1']:,.0f}")

    # Get expiry info
    expiries = upstox_expiries()
    dte_str = ""
    if expiries:
        dte = compute_dte(expiries[0])
        sweet = "⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
        dte_str = f"\nDTE: {dte} {sweet}"

    tg(f"📊 <b>OR LOCKED — SENSEX</b>\n"
       f"09:20 IST | {today_str()}\n\n"
       f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
       f"Range: {oh-ol:.1f} pts | Ticks: {OR_S['ticks']}"
       f"{gap_str}{pivots_str}{dte_str}\n\n"
       f"<i>Scoring engine active from 9:20 AM</i>")

# ===== SNAPSHOT =====
def build_snapshot():
    """Build complete market snapshot for scoring."""
    try:
        # Expiries
        expiries = upstox_expiries()
        if not expiries: return {"error": "No expiries"}
        nearest = expiries[0]; dte = compute_dte(nearest)

        # Option chain
        chain = upstox_option_chain(nearest)
        if not chain: return {"error": "No chain data"}

        # Spot
        spot = upstox_ltp(SENSEX_KEY)
        if not spot: return {"error": "No spot"}

        # Nifty LTP
        nifty_spot = upstox_ltp(NIFTY_KEY)

        # 1-min candles
        c1 = upstox_candles_1min(SENSEX_KEY)
        c1_nifty = upstox_candles_1min(NIFTY_KEY)

        # 3-min candles (aggregated) — kept for scoring context
        c3 = aggregate_to_3min(c1)
        c3_nifty = aggregate_to_3min(c1_nifty)

        # FIX: Supertrend on 1-MIN candles (not 3-min)
        st_sig, st_val, st_stable, prev_st_dir = compute_supertrend(c1)
        nifty_st, _, _, _ = compute_supertrend(c1_nifty)

        # EMA 9 and 21 on 1-min
        closes_1min = [c[4] for c in c1]
        ema9  = compute_ema(closes_1min, 9)
        ema21 = compute_ema(closes_1min, 21)

        # EMA trend direction
        if ema9 and ema21:
            ema_trend = "BUY" if ema9 > ema21 else "SELL"
        else:
            ema_trend = None

        # Prev OHLC + pivots
        prev = prev_ohlc()
        pivots = None; prev_close = None
        if prev:
            pivots = compute_pivots(
                prev["high"], prev["low"], prev["close"])
            prev_close = prev["close"]

        # Find ATM strike
        atm_data = min(chain,
            key=lambda x: abs(x["strike_price"] - spot),
            default=None)

        atm_ce = atm_pe = None
        atm_iv = 0
        if atm_data:
            atm_ce = atm_data.get("call_options", {}).get("market_data", {})
            atm_pe = atm_data.get("put_options", {}).get("market_data", {})
            ce_greeks = atm_data.get("call_options", {}).get("option_greeks", {})
            pe_greeks = atm_data.get("put_options", {}).get("option_greeks", {})
            atm_iv = (ce_greeks.get("iv", 0) + pe_greeks.get("iv", 0)) / 2

        iv_rank = get_iv_rank(atm_iv)

        # OR state
        with OR_L:
            or_locked = OR_S["locked"]
            or_high = OR_S["high"]
            or_low = OR_S["low"]
            or_open = OR_S["open_price"]
            gap_type = OR_S["gap_type"]
            gap_pct = OR_S["gap_pct"]

        # tbq/tsq from websocket (or fallback to 0)
        with WS_LOCK:
            tbq = WS_STATE.get("atm_tbq", 0)
            tsq = WS_STATE.get("atm_tsq", 0)

        return {
            "spot": spot, "nifty_spot": nifty_spot,
            "expiry": nearest, "dte": dte,
            "chain": chain, "atm_data": atm_data,
            "atm_ce": atm_ce, "atm_pe": atm_pe,
            "atm_iv": round(atm_iv, 2),
            "iv_rank": iv_rank,
            "c1": c1, "c3": c3,
            "c3_nifty": c3_nifty,
            "st_sig": st_sig, "st_val": st_val,
            "st_stable": st_stable,
            "prev_st_dir": prev_st_dir,
            "ema9": ema9, "ema21": ema21,
            "ema_trend": ema_trend,
            "nifty_st": nifty_st,
            "pivots": pivots, "prev_close": prev_close,
            "or_locked": or_locked,
            "or_high": or_high, "or_low": or_low,
            "or_open": or_open,
            "gap_type": gap_type, "gap_pct": gap_pct,
            "tbq": tbq, "tsq": tsq,
            "vwap": compute_vwap(c1),
        }
    except Exception as e:
        print(f"[Snapshot] Error: {e}")
        return {"error": str(e)}

# ===== ENTRY GATE — 4 FIXES =====
def check_entry_gate(snap):
    """
    Implements all 4 fixes:
    Fix 1: ST stable count correct (already fixed in compute_supertrend)
    Fix 2: Alert candle rule
    Fix 3: Pullback check (price near ST/EMA)
    Fix 4: Structure SL (alert candle based)

    Returns (direction, sl_level, entry_type) or (None, None, None)
    """
    global ALERT_C

    spot       = snap["spot"]
    st_sig     = snap["st_sig"]
    st_val     = snap["st_val"]
    st_stable  = snap["st_stable"]
    prev_st    = snap.get("prev_st_dir")
    ema9       = snap.get("ema9")
    ema21      = snap.get("ema21")
    ema_trend  = snap.get("ema_trend")
    c1         = snap.get("c1", [])

    if not st_sig or not c1:
        return None, None, None

    last   = c1[-1]   # current candle
    prev   = c1[-2] if len(c1) >= 2 else None

    # ===== FIX 2: ALERT CANDLE RULE =====
    # Detect fresh ST flip → store alert candle
    is_fresh_flip = (prev_st is not None and st_sig != prev_st and st_stable == 1)

    with ALERT_L:
        if is_fresh_flip:
            # New flip detected — store alert candle
            # Alert candle = the candle that caused the flip
            alert_candle = c1[-2] if len(c1) >= 2 else c1[-1]
            ALERT_C.update({
                "active": True,
                "direction": st_sig,
                "high": alert_candle[2],   # alert candle high
                "low": alert_candle[3],    # alert candle low
                "st_val": st_val,
                "timestamp": alert_candle[0],
                "confirmed": False,
            })
            print(f"[Gate] Alert candle set: {st_sig} H={alert_candle[2]} L={alert_candle[3]}")
            return None, None, None  # wait for candle 2

        # If ST flipped back → invalidate alert candle
        if ALERT_C["active"] and ALERT_C["direction"] != st_sig:
            ALERT_C["active"] = False
            ALERT_C["confirmed"] = False
            print("[Gate] Alert candle invalidated — ST flipped back")
            return None, None, None

        if not ALERT_C["active"]:
            return None, None, None

        alert_high = ALERT_C["high"]
        alert_low  = ALERT_C["low"]
        direction  = ALERT_C["direction"]

        # ===== FIX 3: PULLBACK CHECK =====
        # Price must be near ST line or EMA (not chasing)
        # Within 80pts on Sensex
        PROXIMITY = 80

        near_st = st_val and abs(spot - st_val) <= PROXIMITY
        near_ema = ema9 and abs(spot - ema9) <= PROXIMITY
        near_level = near_st or near_ema

        if not near_level:
            print(f"[Gate] Pullback check failed — spot {spot} too far from ST {st_val} EMA9 {ema9}")
            return None, None, None

        # ===== FIX 2 (continued): CANDLE 2 BREAK =====
        # For PUT: current candle must close BELOW alert candle LOW
        # For CALL: current candle must close ABOVE alert candle HIGH
        if not ALERT_C["confirmed"]:
            if direction == "SELL":
                if last[4] < alert_low:  # close below alert low
                    ALERT_C["confirmed"] = True
                    print(f"[Gate] PUT confirmed — candle closed below alert low {alert_low}")
                else:
                    return None, None, None  # wait
            else:  # BUY
                if last[4] > alert_high:  # close above alert high
                    ALERT_C["confirmed"] = True
                    print(f"[Gate] CALL confirmed — candle closed above alert high {alert_high}")
                else:
                    return None, None, None  # wait

        # Alert candle confirmed — check if still valid
        if not ALERT_C["confirmed"]:
            return None, None, None

        # ===== FIX 4: STRUCTURE SL =====
        # SL = alert candle HIGH (for PUT)
        #      alert candle LOW (for CALL)
        if direction == "SELL":
            sl_level = alert_high   # index level SL for PUT
            entry_direction = "PUT"
        else:
            sl_level = alert_low    # index level SL for CALL
            entry_direction = "CALL"

        # Reset alert candle after confirmed entry
        ALERT_C["active"] = False
        ALERT_C["confirmed"] = False

        return entry_direction, sl_level, "PULLBACK"

# ===== SIGNAL ENGINE =====
def check_signal(snap):
    """
    Run entry gate first, then scoring.
    Returns (direction, score, lots, details, sl_index) or None
    """
    allowed, reason = is_allowed()
    if not allowed and not PAPER:
        return None, 0, 0, {"skip": reason}, None

    with RISK_L:
        if RISK["scalps"] >= MAX_SCALPS and not RISK.get("alert_only"):
            return None, 0, 0, {"skip": "Max scalps"}, None
        pnl = RISK["pnl"]

    session = get_session()
    if session in ["PRE", "CLOSED"]:
        return None, 0, 0, {"skip": f"Session {session}"}, None

    # Dedup check
    with LAST_L:
        lt = LAST_SIGNAL["time"]
        if lt and (now_ist()-lt).total_seconds() < DEDUP_SECS:
            return None, 0, 0, {"skip": "Dedup"}, None

    with TRADE_L:
        if TRADE["active"]: return None, 0, 0, {"skip": "Trade active"}, None

    # Must have OR locked
    if not snap.get("or_locked"):
        return None, 0, 0, {"skip": "OR not locked"}, None

    # ===== RUN ENTRY GATE (4 fixes) =====
    direction, sl_index, entry_type = check_entry_gate(snap)
    if not direction:
        # Check what blocked it for reporting
        st_stable = snap.get("st_stable", 0)
        st_sig = snap.get("st_sig", "?")
        ema9 = snap.get("ema9")
        spot = snap.get("spot", 0)
        st_val = snap.get("st_val", 0)
        skip_reason = f"Gate: ST={st_sig}({st_stable}c) spot={spot} ST={st_val} EMA9={ema9}"
        return None, 0, 0, {"skip": skip_reason}, None

    # ===== SCORING (now only runs on valid setups) =====
    call_pts, put_pts, details = compute_score(
        spot=snap["spot"],
        candles_1min=snap["c1"],
        candles_3min=snap["c3"],
        or_high=snap["or_high"],
        or_low=snap["or_low"],
        or_open=snap["or_open"],
        prev_close=snap["prev_close"],
        pivots=snap["pivots"],
        st_signal=snap["st_sig"],
        st_val=snap["st_val"],
        st_stable=snap["st_stable"],
        nifty_st=snap["nifty_st"],
        atm_ce=snap["atm_ce"],
        atm_pe=snap["atm_pe"],
        tbq=snap["tbq"],
        tsq=snap["tsq"],
    )

    # Score for the confirmed direction only
    score = put_pts if direction == "PUT" else call_pts

    # FIX 7: Conflict filter — if opposite side scores too high, skip
    opposite = call_pts if direction == "PUT" else put_pts
    if opposite >= score - 1:
        return None, 0, 0, {
            "skip": f"Score conflict: {direction}={score} vs opposite={opposite}"
        }, None

    # Determine threshold
    high_iv = is_high_iv_day(snap["atm_iv"], snap["iv_rank"])
    captured = pnl / DAILY_TARGET if DAILY_TARGET > 0 else 0

    if captured >= 1.0:
        threshold = SCORE_POST_TARGET
    elif high_iv:
        threshold = SCORE_HIGH_IV
    else:
        threshold = SCORE_NORMAL

    if score < threshold:
        return None, 0, 0, {
            "skip": f"Score {score} < threshold {threshold}",
            "call_score": call_pts,
            "put_score": put_pts,
            "threshold": threshold,
        }, None

    # Determine lots
    if captured >= 1.0:
        base_lots = 1
    elif captured >= 0.70:
        base_lots = 1
    elif captured >= 0.50:
        base_lots = 2
    else:
        base_lots = LOTS_HIGH_IV if high_iv else LOTS_NORMAL

    details["threshold"] = threshold
    details["high_iv"] = high_iv
    details["session"] = session
    details["captured_pct"] = f"{captured:.0%}"
    details["entry_type"] = entry_type
    details["sl_index"] = sl_index
    details["call_score"] = call_pts
    details["put_score"] = put_pts

    return direction, score, base_lots, details, sl_index

    # Direction
    direction = None
    score = 0
    if call_pts >= threshold and call_pts > put_pts:
        direction = "CALL"
        score = call_pts
    elif put_pts >= threshold and put_pts > call_pts:
        direction = "PUT"
        score = put_pts

    details["threshold"] = threshold
    details["high_iv"] = high_iv
    details["session"] = session
    details["captured_pct"] = f"{captured:.0%}"

    return direction, score, base_lots, details

# ===== STRIKE SELECTION =====
def select_strike(chain, spot, direction, atm_iv):
    """
    Select best strike for entry.
    ATM default, 1 strike ITM if premium out of range.
    Premium range: ₹200-500
    """
    try:
        sorted_chain = sorted(chain,
            key=lambda x: abs(x["strike_price"] - spot))

        for strike_data in sorted_chain[:5]:
            if direction == "CALL":
                md = strike_data.get("call_options", {}).get("market_data", {})
                greeks = strike_data.get("call_options", {}).get("option_greeks", {})
                ik = strike_data.get("call_options", {}).get("instrument_key", "")
            else:
                md = strike_data.get("put_options", {}).get("market_data", {})
                greeks = strike_data.get("put_options", {}).get("option_greeks", {})
                ik = strike_data.get("put_options", {}).get("instrument_key", "")

            ltp = md.get("ltp", 0)
            if 200 <= ltp <= 500:
                return {
                    "strike": strike_data["strike_price"],
                    "instrument_key": ik,
                    "ltp": ltp,
                    "bid": md.get("bid_price", ltp),
                    "ask": md.get("ask_price", ltp),
                    "delta": greeks.get("delta", 0),
                    "iv": greeks.get("iv", atm_iv),
                    "theta": greeks.get("theta", 0),
                    "spread": md.get("ask_price",0) - md.get("bid_price",0),
                }

        # Fallback: closest to ATM regardless of premium
        atm = sorted_chain[0]
        if direction == "CALL":
            md = atm.get("call_options", {}).get("market_data", {})
            greeks = atm.get("call_options", {}).get("option_greeks", {})
            ik = atm.get("call_options", {}).get("instrument_key", "")
        else:
            md = atm.get("put_options", {}).get("market_data", {})
            greeks = atm.get("put_options", {}).get("option_greeks", {})
            ik = atm.get("put_options", {}).get("instrument_key", "")

        ltp = md.get("ltp", 0)
        return {
            "strike": atm["strike_price"],
            "instrument_key": ik,
            "ltp": ltp,
            "bid": md.get("bid_price", ltp),
            "ask": md.get("ask_price", ltp),
            "delta": greeks.get("delta", 0),
            "iv": greeks.get("iv", atm_iv),
            "theta": greeks.get("theta", 0),
            "spread": md.get("ask_price",0) - md.get("bid_price",0),
        }
    except Exception as e:
        print(f"[Strike] Error: {e}")
        return None

# ===== FIRE SIGNAL =====
def fire_signal(snap, direction, score, lots, details, sl_index=None):
    """Format and send signal. Execute if live and execution allowed."""
    allowed, _ = is_allowed()
    exec_ok, exec_reason = is_execution_allowed()
    is_paper = PAPER or not allowed
    alert_only = not exec_ok
    spot = snap["spot"]
    atm_iv = snap["atm_iv"]
    expiry = snap["expiry"]
    dte = snap["dte"]
    high_iv = details.get("high_iv", False)
    session = details.get("session", "")
    captured = details.get("captured_pct", "0%")
    entry_type = details.get("entry_type", "PULLBACK")

    # Select strike
    strike_data = select_strike(
        snap["chain"], spot, direction, atm_iv)
    if not strike_data:
        print("[Signal] No valid strike found"); return False

    prem = strike_data["ltp"]
    qty = lots * LOT_SIZE

    # FIX 4: Structure SL based on alert candle
    # Convert index SL to option premium SL using delta
    delta = abs(strike_data.get("delta", 0.5)) or 0.5
    if sl_index:
        idx_sl_distance = abs(spot - sl_index)
        sl_pts_dynamic = round(idx_sl_distance * delta, 1)
        # Cap between 15 and 60 pts
        sl_pts_dynamic = max(15, min(60, sl_pts_dynamic))
    else:
        sl_pts_dynamic = SL_PTS  # fallback to fixed

    sl_price = round(prem - sl_pts_dynamic, 2)
    lock_price = round(prem + LOCK_PTS, 2)

    win = round(LOCK_PTS * qty, 0)
    loss = round(sl_pts_dynamic * qty, 0)

    # Build message
    pfx = "🔔 ALERT ONLY — " if alert_only else "📝 PAPER — " if is_paper else "🔴 LIVE — "
    iv_note = "⚡ HIGH IV" if high_iv else ""

    msg = (f"⚡ {pfx}<b>SENSEX {direction} SCALP</b> {iv_note}\n"
           f"{now_ist().strftime('%H:%M:%S')} | DTE {dte} | {session}\n"
           f"Type: <b>{entry_type}</b> | Score: <b>{score}/15</b>\n\n"
           f"<b>Strike: {strike_data['strike']:,.0f} {direction}</b>\n"
           f"Entry: ₹{prem:.2f} | Qty: {qty}\n"
           f"Δ={strike_data['delta']:.3f} | "
           f"IV={strike_data['iv']:.1f}% | "
           f"Spread=₹{strike_data['spread']:.1f}\n\n"
           f"<b>SL: ₹{sl_price:.2f} (-₹{sl_pts_dynamic}/unit)</b>\n"
           f"{'Index SL: '+str(sl_index)+' (alert candle structure)' if sl_index else ''}\n"
           f"<b>Lock: ₹{lock_price:.2f} (+₹{LOCK_PTS} pts)</b>\n"
           f"After lock → structure trail on 1-min\n\n"
           f"Win (lock): +₹{win:,.0f} | Max loss: -₹{loss:,.0f}\n"
           f"{chr(10)+'⚠️ NOT EXECUTED — Send /execute to trade manually' if alert_only else ''}\n")

    # Score breakdown
    msg += "<b>Score breakdown:</b>\n"
    for k, v in details.items():
        if isinstance(v, str) and ("→" in v or "CALL" in v or "PUT" in v):
            msg += f"  {v}\n"

    with RISK_L:
        pnl = RISK["pnl"]
    remaining = DAILY_TARGET - pnl
    msg += (f"\n<b>Daily:</b> {'+'if pnl>=0 else ''}₹{pnl:,.0f} / "
            f"₹{DAILY_TARGET:,.0f} | Remaining: ₹{remaining:,.0f}\n"
            f"Target captured: {captured}\n"
            f"<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v1.0</i>")

    if tg(msg):
        # R:R Check — skip if SL > target (lock)
        sl_pts = abs(prem - sl_price)
        lock_pts = 20  # fixed lock distance
        if sl_pts > lock_pts:
            tg(f"⛔ <b>SIGNAL SKIPPED — Bad R:R</b>\n"
               f"{direction} {strike_data['strike']} | Score {score}/15\n"
               f"SL: ₹{sl_pts:.1f} > Lock: ₹{lock_pts:.1f}\n"
               f"R:R unfavorable — not eligible")
            return

        # Record signal
        with LAST_L: LAST_SIGNAL["time"] = now_ist()
        with RISK_L: RISK["scalps"] += 1

        # Log to DB
        signal_id = None
        if DB_AVAILABLE:
            try:
                signal_id = log_alakh_signal(
                    direction=direction,
                    score=score,
                    threshold=details.get("threshold", 7),
                    strike=strike_data["strike"],
                    entry_price=prem,
                    sl_price=sl_price,
                    lock_price=lock_price,
                    qty=qty, lots=lots,
                    expiry=expiry, dte=dte,
                    atm_iv=atm_iv,
                    session=details.get("session", ""),
                    entry_type=details.get("entry_type", "PULLBACK"),
                    sl_index=sl_index or 0,
                    spot=spot)
                log_event("ALAKH", "SIGNAL",
                         f"{direction} {strike_data['strike']} score={score}")
            except Exception as e:
                print(f"[DB] Log error: {e}")

        # Skip execution in alert-only mode
        if alert_only:
            # Store last signal for /execute command
            with LAST_L:
                LAST_SIGNAL["pending_execute"] = {
                    "direction": direction,
                    "strike": strike_data,
                    "lots": lots,
                    "qty": qty,
                    "expiry": expiry,
                    "spot": spot,
                    "prem": prem,
                    "sl_price": sl_price,
                }
            print(f"[Signal] Alert only — {direction} {strike_data['strike']}")
            return True

        # Update trade state
        with TRADE_L:
            TRADE.update({
                "active": True, "side": direction,
                "strike": strike_data["strike"],
                "instrument_key": strike_data["instrument_key"],
                "entry_premium": prem,
                "sl_price": sl_price,
                "trail_sl": sl_price,
                "lock_achieved": False,
                "entry_time": now_ist(),
                "lots": lots, "qty": qty,
                "expiry": expiry,
                "entry_idx": spot,
                "candles_since_entry": 0,
                "prev_1min_lows": deque(maxlen=5),
                "prev_1min_highs": deque(maxlen=5),
                "signal_id": signal_id,
            })

        print(f"[Signal] Fired {direction} {strike_data['strike']} "
              f"@ ₹{prem} | Score {score}/15")
        return True
    return False

# ===== TRADE MONITOR =====
def monitor_trade():
    """Monitor active trade with structure-based trailing."""
    with TRADE_L:
        if not TRADE["active"]: return
        side = TRADE["side"]
        ik = TRADE["instrument_key"]
        entry = TRADE["entry_premium"]
        sl = TRADE["trail_sl"]
        lock = TRADE["lock_achieved"]
        qty = TRADE["qty"]
        entry_time = TRADE["entry_time"]
        lows = TRADE["prev_1min_lows"]
        highs = TRADE["prev_1min_highs"]

    if now_ist().weekday() > 4: return
    n = now_ist()
    if n >= n.replace(hour=15, minute=0): return

    # Hard exit at 2:55 PM
    if n.hour >= 14 and n.minute >= 55:
        _force_exit("Pre-close 2:55 PM")
        return

    # Get current premium from chain
    expiries = upstox_expiries()
    if not expiries: return
    chain = upstox_option_chain(expiries[0])
    if not chain: return

    spot = upstox_ltp(SENSEX_KEY)
    if not spot: return

    # Find current premium for our strike
    current_prem = None
    for s in chain:
        if side == "CALL":
            if s.get("call_options", {}).get("instrument_key") == ik:
                current_prem = s["call_options"]["market_data"].get("ltp")
                break
        else:
            if s.get("put_options", {}).get("instrument_key") == ik:
                current_prem = s["put_options"]["market_data"].get("ltp")
                break

    if not current_prem: return

    pnl = round((current_prem - entry) * qty, 0)
    elapsed = int((n - entry_time).total_seconds() / 60)

    # Get 1-min candles for trail
    c1 = upstox_candles_1min(SENSEX_KEY)
    today = now_ist().date()
    today_c1 = [c for c in c1
                if ts_to_ist(c[0]).date() == today]

    # Update 1-min low/high history for trailing
    if today_c1:
        last_1min = today_c1[-1]
        if side == "CALL":
            with TRADE_L:
                TRADE["prev_1min_lows"].append(last_1min[3])
        else:
            with TRADE_L:
                TRADE["prev_1min_highs"].append(last_1min[2])

    # ===== PHASE 1: Hard SL (before lock) =====
    if not lock:
        if current_prem <= sl:
            _stop_loss(entry, current_prem, qty, pnl, elapsed)
            return

        # Check if lock achieved
        if current_prem >= entry + LOCK_PTS:
            with TRADE_L:
                TRADE["lock_achieved"] = True
                TRADE["trail_sl"] = entry  # SL to breakeven
            tg(f"🔒 <b>PROFIT LOCKED +₹{LOCK_PTS}/unit</b>\n"
               f"SL moved to breakeven ₹{entry:.2f}\n"
               f"Premium ₹{current_prem:.2f} | +₹{pnl:,.0f}\n"
               f"Now riding with structure trail on 1-min...")
            return

    # ===== PHASE 2: Structure trail (after lock) =====
    else:
        # Update trail SL based on previous 1-min candle
        if today_c1 and len(today_c1) >= 2:
            prev_candle = today_c1[-2]  # previous completed candle
            if side == "CALL":
                # Trail SL = prev 1-min candle LOW (converted to premium)
                # We trail in premium space, not index space
                new_trail = max(entry, sl)  # never below breakeven
                # Premium trail: give 5pt buffer below prev candle low
                # Use index movement × delta as premium proxy
                if len(today_c1) >= 2:
                    prev_low = prev_candle[3]  # index low
                    curr_low = today_c1[-1][3]  # current candle low
                    if curr_low > prev_low:  # making higher lows
                        # Trail up: move SL up
                        delta = 0.5  # approximate
                        premium_move = (curr_low - prev_low) * delta * 0.8
                        candidate = round(sl + premium_move, 2)
                        if candidate > sl:
                            with TRADE_L:
                                TRADE["trail_sl"] = candidate
                            sl = candidate

            else:  # PUT
                if len(today_c1) >= 2:
                    prev_high = prev_candle[2]
                    curr_high = today_c1[-1][2]
                    if curr_high < prev_high:  # making lower highs
                        delta = 0.5
                        premium_move = (prev_high - curr_high) * delta * 0.8
                        candidate = round(sl + premium_move, 2)
                        if candidate > sl:
                            with TRADE_L:
                                TRADE["trail_sl"] = candidate
                            sl = candidate

        # ===== SWEEP DETECTION =====
        # Check if current candle CLOSES below trail SL
        if today_c1:
            last_close = today_c1[-1][4]  # close of last 1-min candle

            if current_prem < sl:
                # Check volume for sweep detection
                # Get tbq/tsq from websocket
                with WS_LOCK:
                    tbq = WS_STATE.get("atm_tbq", 0)
                    tsq = WS_STATE.get("atm_tsq", 0)

                # Sweep = buyers still absorbing (tbq > tsq)
                if tbq > tsq * 1.2:
                    tg(f"💧 <b>SWEEP DETECTED — HOLDING</b>\n"
                       f"Premium ₹{current_prem:.2f} below trail ₹{sl:.2f}\n"
                       f"But buyers absorbing: tbq={tbq:,} > tsq={tsq:,}\n"
                       f"Wait for 2nd candle confirmation...")
                    return

                # Check if candle closed below trail SL
                if last_close < sl:
                    # Real breakdown — but wait for next candle open
                    tg(f"⚠️ <b>TRAIL SL WARNING</b>\n"
                       f"Candle closed ₹{last_close:.2f} below trail ₹{sl:.2f}\n"
                       f"Waiting for next candle confirmation...")
                    # Set flag to exit on next candle if it opens below
                    with TRADE_L:
                        TRADE["candles_since_entry"] += 1
                    return

        # Progress check: if no new high (call) or low (put) in 3 candles
        # Exit the trade
        with TRADE_L:
            cse = TRADE["candles_since_entry"]

        # Target hit
        tgt = entry + 80  # trail catches big moves
        if current_prem >= tgt:
            _take_profit(entry, current_prem, qty, pnl, elapsed)
            return

    # Periodic update every 15 min
    if elapsed > 0 and elapsed % 15 == 0:
        tg(f"📊 <b>Trade Update | {elapsed}min</b>\n"
           f"{side} {TRADE['strike']:,.0f}\n"
           f"Entry ₹{entry:.2f} → Current ₹{current_prem:.2f}\n"
           f"Trail SL: ₹{sl:.2f}\n"
           f"P&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f} | "
           f"Lock: {'✅' if lock else '⏳'}")

def _stop_loss(entry, current, qty, pnl, elapsed):
    loss = abs(pnl)
    tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n"
       f"Entry ₹{entry:.2f} → ₹{current:.2f}\n"
       f"<b>-₹{loss:,.0f}</b> in {elapsed} min\n"
       f"→ Send /sl to confirm")
    with TRADE_L:
        signal_id = TRADE.get("signal_id")
        TRADE["active"] = False
    if DB_AVAILABLE and signal_id:
        try:
            update_alakh_signal(signal_id, "LOSS", current, -loss)
            log_event("ALAKH", "SL_HIT", f"-₹{loss:,.0f} in {elapsed}min")
        except: pass
    register_sl(loss)

def _take_profit(entry, current, qty, pnl, elapsed):
    tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n"
       f"Entry ₹{entry:.2f} → ₹{current:.2f}\n"
       f"<b>+₹{pnl:,.0f}</b> in {elapsed} min\n"
       f"→ Send /tradesquared to confirm")
    with TRADE_L:
        signal_id = TRADE.get("signal_id")
        TRADE["active"] = False
    if DB_AVAILABLE and signal_id:
        try:
            update_alakh_signal(signal_id, "WIN", current, pnl)
            log_event("ALAKH", "TARGET_HIT", f"+₹{pnl:,.0f} in {elapsed}min")
        except: pass
    register_profit(pnl)

def _force_exit(reason):
    with TRADE_L:
        if not TRADE["active"]: return
        entry = TRADE["entry_premium"]
        qty = TRADE["qty"]
        TRADE["active"] = False
    tg(f"⏰ <b>FORCED EXIT: {reason}</b>\n"
       f"Close position manually now.")

# ===== JOBS =====
def job_login():
    if now_ist().weekday() > 4: return
    print("[Login] Auto-login 8:30 AM...")
    if neo_login():
        tg(f"🔑 <b>Kotak Neo Connected</b>\n"
           f"{now_ist().strftime('%H:%M:%S')} IST")
    else:
        tg("🚨 <b>Kotak Neo Login Failed</b>\nSend /login")

def job_premarket():
    if now_ist().weekday() > 4: return
    reset_daily()
    with OR_L:
        OR_S.update({"date": None})
    or_reset()

    prev = prev_ohlc()
    pivot_str = gap_str = iv_str = ""

    if prev:
        pivots = compute_pivots(
            prev["high"], prev["low"], prev["close"])
        spot = upstox_ltp(SENSEX_KEY)
        if spot:
            gtype, gpct = detect_gap(prev["close"], spot)
            gap_str = (f"Pre-open: {spot:,.2f} "
                      f"({'⬆️' if gpct>0 else '⬇️'}) ({gpct:+.2f}%)\n"
                      if gtype not in ["FLAT_OPEN","UNKNOWN"] else "")
        pivot_str = (f"Prev: H={prev['high']:,.0f} "
                    f"L={prev['low']:,.0f} C={prev['close']:,.0f}\n"
                    f"R1: {pivots['r1']:,.0f} | "
                    f"Pivot: {pivots['pivot']:,.0f} | "
                    f"S1: {pivots['s1']:,.0f}\n")

    iv_days = len(load_iv().get("sensex", {}))
    expiries = upstox_expiries()
    dte_str = ""
    if expiries:
        dte = compute_dte(expiries[0])
        sweet = "⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
        dte_str = f"DTE: {dte} {sweet}\n"

    tg(f"☀️ <b>PRE-MARKET — SENSEX</b>\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | v1.0\n\n"
       f"{dte_str}{gap_str}{pivot_str}\n"
       f"Target: ₹{DAILY_TARGET:,.0f} | "
       f"Lots: {LOTS_NORMAL} (or {LOTS_HIGH_IV} if high IV)\n"
       f"IV history: {iv_days}/15 days\n"
       f"Score engine: ≥{SCORE_NORMAL} normal | "
       f"≥{SCORE_HIGH_IV} high IV | "
       f"≥{SCORE_POST_TARGET} post-target\n"
       f"9:15→OR | 9:20→Lock | 9:20+→Signals")

def job_or_track():
    if now_ist().weekday() > 4: return
    or_track()

def job_or_lock():
    if now_ist().weekday() > 4: return
    or_lock()

def job_signal_check():
    """Main signal check — runs every 1 min (1-min candles)."""
    if now_ist().weekday() > 4: return
    n = now_ist()
    if n < n.replace(hour=9, minute=20): return
    if n > n.replace(hour=15, minute=30): return  # run till EOD

    # Don't stop for halted — alerts continue in alert-only mode
    with TRADE_L:
        if TRADE["active"]: return

    snap = build_snapshot()
    if "error" in snap:
        print(f"[Signal] Snap error: {snap['error']}"); return

    direction, score, lots, details, sl_index = check_signal(snap)

    if direction:
        print(f"[Signal] {direction} score={score} lots={lots}")
        fire_signal(snap, direction, score, lots, details, sl_index)
    else:
        skip = details.get("skip", "Low score")
        cs = details.get("call_score", 0)
        ps = details.get("put_score", 0)
        print(f"[Signal] Skip: {skip} | Call:{cs} Put:{ps}")

def job_monitor():
    """Trade monitoring — runs every minute."""
    if now_ist().weekday() > 4: return
    monitor_trade()

def job_pre_close():
    if now_ist().weekday() > 4: return
    with RISK_L:
        s = RISK["scalps"]; p = RISK["pnl"]
    with TRADE_L:
        ta = TRADE["active"]
        TRADE["active"] = False
    tg(f"⏰ <b>PRE-CLOSE 2:55 PM</b>\n"
       f"Close ALL positions NOW.\n"
       f"Scalps: {s} | P&L: {'+'if p>=0 else ''}₹{p:,.0f}\n"
       f"{'⚠️ ACTIVE TRADE — CLOSE NOW' if ta else ''}")

def job_eod():
    if now_ist().weekday() > 4: return
    with TRADE_L: TRADE["active"] = False

    # Store IV
    snap = build_snapshot()
    if "error" not in snap and snap.get("atm_iv", 0) > 0:
        store_eod_iv(snap["atm_iv"])

    with RISK_L:
        sl = RISK["sl_hits"]; s = RISK["scalps"]; p = RISK["pnl"]

    icon = "✅" if p >= DAILY_TARGET else "⚠️" if p > 0 else "❌"
    tg(f"🌙 <b>EOD — SENSEX T20 | v1.0</b>\n\n"
       f"{icon} <b>P&L: {'+'if p>=0 else ''}₹{p:,.0f} / "
       f"₹{DAILY_TARGET:,.0f}</b>\n\n"
       f"Scalps: {s} | SL hits: {sl}/2\n"
       f"IV days: {len(load_iv().get('sensex',{}))}/15\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

def job_health():
    n = now_ist()
    with WS_LOCK: ws_ok = WS_STATE["connected"]
    neo_ok = neo() is not None
    print(f"[Health] {n.strftime('%H:%M')} | "
          f"WS:{ws_ok} Neo:{neo_ok}")

# ===== TELEGRAM COMMANDS =====
def handle_cmd(text, chat_id):
    text = text.strip().lower().split("@")[0]
    if str(chat_id) != str(TG_CHAT): return
    print(f"[TG] {text}")

    if text == "/login":
        tg("⏳ Logging in...")
        if neo_login(): tg("✅ <b>Kotak Neo Connected</b>")
        else: tg("❌ Login failed")

    elif text == "/approve":
        with RISK_L: RISK["daily_approved"] = True
        tg("✅ <b>Trading approved for today</b>\n"
           "Signal engine active.")

    elif text == "/skip":
        with RISK_L:
            RISK["daily_approved"] = False
            RISK["halted"] = True
        tg("⛔ <b>Trading skipped for today</b>")

    elif text in ["/signal", "/trade"]:
        tg("⏳ Computing signal...")
        snap = build_snapshot()
        if "error" in snap:
            tg(f"❌ {snap['error']}"); return
        direction, score, lots, details, sl_index = check_signal(snap)
        if direction:
            fire_signal(snap, direction, score, lots, details, sl_index)
        else:
            skip = details.get("skip", "")
            cs = details.get("call_score", 0)
            ps = details.get("put_score", 0)
            thresh = details.get("threshold", SCORE_NORMAL)
            tg(f"ℹ️ <b>No Signal</b>\n"
               f"Reason: {skip}\n"
               f"Call: {cs}/15 | Put: {ps}/15\n"
               f"Threshold: {thresh}/15")

    elif text in ["/snapshot", "/snap"]:
        tg("⏳ Fetching...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        spot = snap["spot"]
        atm_data = snap["atm_data"]
        st = snap["st_sig"]; stv = snap["st_val"]
        vwap = snap["vwap"]; iv = snap["atm_iv"]
        iv_rank = snap["iv_rank"]
        high_iv = is_high_iv_day(iv, iv_rank)

        atm_ce = snap.get("atm_ce") or {}
        atm_pe = snap.get("atm_pe") or {}

        msg = (f"📸 <b>SENSEX</b> | {now_ist().strftime('%H:%M:%S')}\n"
               f"Spot: <b>{spot:,.2f}</b> | DTE: {snap['dte']}\n"
               f"Expiry: {snap['expiry']}\n\n"
               f"<b>Indicators:</b>\n"
               f"ST(10,3): {'🟢 BUY' if st=='BUY' else '🔴 SELL' if st=='SELL' else '❓'}"
               f" @ {stv:,.0f} ({snap['st_stable']} candles)\n"
               f"EMA9: {snap.get('ema9','N/A')} | EMA21: {snap.get('ema21','N/A')}\n"
               f"EMA Trend: {'🟢 BULL' if snap.get('ema_trend')=='BUY' else '🔴 BEAR' if snap.get('ema_trend')=='SELL' else '❓'}\n"
               f"Nifty ST: {'🟢' if snap['nifty_st']=='BUY' else '🔴' if snap['nifty_st']=='SELL' else '❓'} "
               f"{snap['nifty_st'] or 'N/A'}\n")
        if vwap:
            msg += (f"VWAP: {vwap:,.2f} "
                   f"({'✅ Above' if spot>vwap else '❌ Below'})\n")
        msg += (f"ATM IV: {iv:.1f}% "
                f"{'⚡ HIGH IV → 3 lots' if high_iv else '✅ Normal → 5 lots'}\n")
        if iv_rank:
            msg += f"IV Rank: {iv_rank:.0f}/100\n"

        with OR_L:
            if OR_S["locked"]:
                oh, ol = OR_S["high"], OR_S["low"]
                pos = ("⬆️ ABOVE" if spot>oh else
                       "⬇️ BELOW" if spot<ol else "🎯 INSIDE")
                msg += f"\nOR: {ol:,.0f}–{oh:,.0f} | {pos}\n"

        if snap["pivots"]:
            p = snap["pivots"]
            msg += (f"\nR1: {p['r1']:,.0f} | "
                   f"Pivot: {p['pivot']:,.0f} | "
                   f"S1: {p['s1']:,.0f}\n")

        if atm_data:
            strike = atm_data.get("strike_price", 0)
            ce_ltp = atm_ce.get("ltp", 0)
            pe_ltp = atm_pe.get("ltp", 0)
            msg += (f"\nATM {strike:,.0f}:\n"
                   f"CE: ₹{ce_ltp:.2f} | "
                   f"PE: ₹{pe_ltp:.2f}\n")

        tg(msg)

    elif text in ["/classify", "/score"]:
        tg("⏳ Computing score...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        direction, score, lots, details, sl_index = check_signal(snap)
        high_iv = is_high_iv_day(snap["atm_iv"], snap["iv_rank"])

        msg = (f"🧠 <b>Score Engine</b>\n"
               f"{now_ist().strftime('%H:%M:%S')}\n\n"
               f"Call: <b>{details.get('call_score',0)}/15</b> | "
               f"Put: <b>{details.get('put_score',0)}/15</b>\n"
               f"Threshold: {details.get('threshold', SCORE_NORMAL)}/15\n"
               f"Session: {details.get('session','?')}\n"
               f"IV: {snap['atm_iv']:.1f}% "
               f"{'⚡ HIGH' if high_iv else '✅ Normal'}\n\n"
               f"<b>Signals:</b>\n")
        for k, v in details.items():
            if isinstance(v, str) and "→" in v:
                msg += f"  {v}\n"

        if direction:
            msg += f"\n<b>→ {direction} SIGNAL ({score}/15)</b>"
        else:
            msg += f"\nSkip: {details.get('skip','')}"
        tg(msg)

    elif text in ["/oi", "/chain"]:
        tg("⏳ Fetching chain...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        spot = snap["spot"]
        chain = snap["chain"]

        # Find top OI strikes
        ce_oi = sorted(chain,
            key=lambda x: x.get("call_options",{}).get(
                "market_data",{}).get("oi",0), reverse=True)[:5]
        pe_oi = sorted(chain,
            key=lambda x: x.get("put_options",{}).get(
                "market_data",{}).get("oi",0), reverse=True)[:5]

        total_ce = sum(s.get("call_options",{}).get(
            "market_data",{}).get("oi",0) for s in chain)
        total_pe = sum(s.get("put_options",{}).get(
            "market_data",{}).get("oi",0) for s in chain)
        pcr = round(total_pe/total_ce, 2) if total_ce > 0 else 0

        msg = (f"📊 <b>OI — SENSEX</b>\n"
               f"Spot: {spot:,.2f} | PCR: {pcr}\n\n"
               f"<b>🔴 Call OI (resistance):</b>\n")
        for s in ce_oi:
            strike = s["strike_price"]
            oi = s.get("call_options",{}).get(
                "market_data",{}).get("oi",0)
            prev_oi = s.get("call_options",{}).get(
                "market_data",{}).get("prev_oi",0)
            chg = oi - prev_oi
            msg += f"  {strike:,.0f}: {oi:,.0f} ({chg:+,.0f})\n"

        msg += "<b>🟢 Put OI (support):</b>\n"
        for s in pe_oi:
            strike = s["strike_price"]
            oi = s.get("put_options",{}).get(
                "market_data",{}).get("oi",0)
            prev_oi = s.get("put_options",{}).get(
                "market_data",{}).get("prev_oi",0)
            chg = oi - prev_oi
            msg += f"  {strike:,.0f}: {oi:,.0f} ({chg:+,.0f})\n"

        top_ce = ce_oi[0]["strike_price"] if ce_oi else 0
        top_pe = pe_oi[0]["strike_price"] if pe_oi else 0
        if top_ce and top_pe:
            msg += (f"\nCall wall: {top_ce:,.0f} | "
                   f"Put wall: {top_pe:,.0f}\n"
                   f"Range: {top_pe:,.0f}–{top_ce:,.0f} "
                   f"({top_ce-top_pe:.0f} pts)")
        tg(msg)

    elif text in ["/levels", "/pivots"]:
        tg("⏳ Fetching levels...")
        prev = prev_ohlc()
        if not prev: tg("❌ No prev OHLC"); return
        p = compute_pivots(prev["high"], prev["low"], prev["close"])
        spot = upstox_ltp(SENSEX_KEY)
        def here(v):
            return " ← HERE" if spot and abs(spot-v) < 30 else ""
        tg(f"📐 <b>Levels — SENSEX</b>\n"
           f"Prev: H={prev['high']:,.0f} "
           f"L={prev['low']:,.0f} C={prev['close']:,.0f}\n\n"
           f"R2: <b>{p['r2']:,.0f}</b>{here(p['r2'])}\n"
           f"R1: <b>{p['r1']:,.0f}</b>{here(p['r1'])}\n"
           f"<b>Pivot: {p['pivot']:,.0f}</b>{here(p['pivot'])}\n"
           f"S1: <b>{p['s1']:,.0f}</b>{here(p['s1'])}\n"
           f"S2: <b>{p['s2']:,.0f}</b>{here(p['s2'])}\n"
           f"{'Spot: '+str(round(spot,2)) if spot else ''}")

    elif text in ["/spot", "/ltp"]:
        spot = upstox_ltp(SENSEX_KEY)
        nifty = upstox_ltp(NIFTY_KEY)
        if spot:
            tg(f"💰 <b>SENSEX:</b> {spot:,.2f}\n"
               f"💰 <b>NIFTY:</b> {nifty:,.2f}\n"
               f"{now_ist().strftime('%H:%M:%S')}")
        else: tg("❌ LTP fetch failed")

    elif text in ["/or"]:
        with OR_L:
            if not OR_S["locked"]:
                tg("⏳ OR not locked yet"); return
            oh, ol = OR_S["high"], OR_S["low"]
            gt, gp = OR_S["gap_type"], OR_S["gap_pct"]
        spot = upstox_ltp(SENSEX_KEY)
        pos = ""
        if spot:
            pos = ("⬆️ ABOVE" if spot>oh else
                  "⬇️ BELOW" if spot<ol else "🎯 INSIDE")
        tg(f"📊 <b>Opening Range</b>\n"
           f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
           f"Range: {oh-ol:.1f} pts\n"
           f"Gap: {gt.replace('_',' ')} ({gp:+.2f}%)\n"
           f"{f'Spot {spot:,.2f} → {pos}' if spot else ''}")

    elif text in ["/expiries", "/expiry"]:
        exps = upstox_expiries()
        if not exps: tg("❌ No expiry data"); return
        msg = "📅 <b>Expiries — SENSEX</b>\n"
        for i, e in enumerate(exps[:6]):
            dte = compute_dte(e)
            sweet = ("⭐ SWEET" if 3<=dte<=5 else
                    "⚡ GAMMA" if dte<=2 else "📅")
            msg += f"  {i+1}. {e} (DTE {dte}) {sweet}\n"
        tg(msg)

    elif text in ["/ivrank", "/iv"]:
        snap = build_snapshot()
        iv = snap.get("atm_iv", 0)
        ir = snap.get("iv_rank")
        days = len(load_iv().get("sensex", {}))
        high = is_high_iv_day(iv, ir)
        tg(f"📊 <b>IV Status</b>\n"
           f"ATM IV: {iv:.1f}%\n"
           f"IV Rank: {ir:.0f}/100\n" if ir else
           f"ATM IV: {iv:.1f}%\nIV Rank: {days}/15 days (building)\n"
           f"Mode: {'⚡ HIGH IV → 3 lots' if high else '✅ Normal → 5 lots'}")

    elif text in ["/sl", "/slhit"]:
        with TRADE_L:
            TRADE["active"] = False
        register_sl()
        tg("🛑 SL registered.")

    elif text in ["/tradesquared", "/closed"]:
        with TRADE_L:
            was = TRADE["active"]
            TRADE["active"] = False
        tg("✅ Trade cleared." if was else "ℹ️ No active trade.")

    elif text in ["/monitor", "/trade_status"]:
        with TRADE_L:
            if not TRADE["active"]:
                tg("ℹ️ No active trade."); return
            elapsed = int((now_ist()-TRADE["entry_time"]).total_seconds()/60)
            tg(f"📊 <b>{TRADE['side']} Trade | {elapsed}min</b>\n"
               f"Strike: {TRADE['strike']:,.0f}\n"
               f"Entry: ₹{TRADE['entry_premium']:.2f}\n"
               f"Trail SL: ₹{TRADE['trail_sl']:.2f}\n"
               f"Lock: {'✅' if TRADE['lock_achieved'] else '⏳ Not yet'}")

    elif text == "/execute":
        with LAST_L:
            pending = LAST_SIGNAL.get("pending_execute")
        if not pending:
            tg("ℹ️ No pending signal to execute."); return
        # Execute the pending signal manually
        strike_data = pending["strike"]
        direction = pending["direction"]
        qty = pending["qty"]
        prem = pending["prem"]
        sl_price = pending["sl_price"]
        expiry = pending["expiry"]
        spot = pending["spot"]
        with TRADE_L:
            TRADE.update({
                "active": True, "side": direction,
                "strike": strike_data["strike"],
                "instrument_key": strike_data["instrument_key"],
                "entry_premium": prem,
                "sl_price": sl_price,
                "trail_sl": sl_price,
                "lock_achieved": False,
                "entry_time": now_ist(),
                "lots": pending["lots"], "qty": qty,
                "expiry": expiry,
                "entry_idx": spot,
                "candles_since_entry": 0,
                "prev_1min_lows": deque(maxlen=5),
                "prev_1min_highs": deque(maxlen=5),
            })
        with LAST_L: LAST_SIGNAL["pending_execute"] = None
        tg(f"✅ <b>MANUALLY EXECUTED</b>\n"
           f"{direction} {strike_data['strike']:,.0f}\n"
           f"Entry: ₹{prem:.2f} | Qty: {qty}\n"
           f"SL: ₹{sl_price:.2f}\n"
           f"<i>Trade active — bot monitoring</i>")
        with RISK_L:
            sl = RISK["sl_hits"]; h = RISK["halted"]
            s = RISK["scalps"]; p = RISK["pnl"]
            approved = RISK["daily_approved"]
        with TRADE_L: ta = TRADE["active"]
        session = get_session()
        tg(f"📅 <b>{now_ist().strftime('%A %d %b')}</b>\n"
           f"Session: {session}\n"
           f"Trading: {'✅' if approved else '⛔ Event day'}\n\n"
           f"Scalps: {s}/{MAX_SCALPS}\n"
           f"P&L: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
           f"SL: {sl}/2 | {'🛑 HALTED' if h else '✅ Active'}\n"
           f"Monitor: {'✅ ACTIVE' if ta else 'None'}\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

    elif text in ["/status", "/ping"]:
        with WS_LOCK: ws_ok = WS_STATE["connected"]
        neo_ok = neo() is not None
        spot = upstox_ltp(SENSEX_KEY)
        with RISK_L:
            sl = RISK["sl_hits"]; h = RISK["halted"]
            ao = RISK.get("alert_only", False)
            s = RISK["scalps"]; p = RISK["pnl"]
        with TRADE_L: ta = TRADE["active"]
        mode_str = "🛑 HALTED" if h else "🔔 ALERT ONLY" if ao else "✅ Active"
        tg(f"✅ <b>Mahakaal T20 v1.0</b>\n"
           f"{now_ist().strftime('%H:%M:%S')} IST\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
           f"Upstox: {'✅' if spot else '❌'} | "
           f"WS: {'✅' if ws_ok else '⚠️'} | "
           f"Neo: {'✅' if neo_ok else '❌ /login'}\n"
           f"Spot: {spot:,.2f}\n\n"
           f"Scalps: {s}/{MAX_SCALPS} | "
           f"P&L: {'+'if p>=0 else ''}₹{p:,.0f}\n"
           f"SL: {sl}/2 | {mode_str}\n"
           f"Monitor: {'✅' if ta else 'None'}\n"
           f"{'🔔 Send /execute after next signal' if ao else ''}")

    elif text in ["/help", "/start"]:
        tg(f"🤖 <b>Mahakaal T20 v1.0</b>\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
           f"Data: Upstox | Exec: Kotak Neo\n\n"
           f"<b>Strategy:</b>\n"
           f"Score ≥{SCORE_NORMAL} → CALL/PUT scalp\n"
           f"5 lots normal | 3 lots high IV\n"
           f"Lock +30pts → structure trail exit\n"
           f"Prime: 9:20-11:30 | Bonus: 11:30-3PM\n\n"
           f"<b>Commands:</b>\n"
           f"/signal — force signal check\n"
           f"/score — full score breakdown\n"
           f"/snapshot — market data\n"
           f"/oi — option chain OI\n"
           f"/spot — live LTP\n"
           f"/or — opening range\n"
           f"/levels — pivot levels\n"
           f"/expiries — upcoming expiries\n"
           f"/ivrank — IV status\n"
           f"/monitor — active trade\n"
           f"/tradesquared — clear trade\n"
           f"/sl — register SL hit\n"
           f"/execute — manually execute last alert signal\n"
           f"/today — day summary\n"
           f"/status — bot health\n"
           f"/login — Kotak Neo login\n"
           f"/approve — enable on event days\n"
           f"/skip — disable today")
    else:
        tg(f"❓ Unknown: <code>{text}</code>\n/help")

def tg_listener():
    print("[TG] Listener starting...")
    last_id = None; processed = set()
    while True:
        try:
            params = {"timeout": 30}
            if last_id: params["offset"] = last_id
            r = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params=params, timeout=35)
            if r.status_code == 200:
                for upd in r.json().get("result", []):
                    uid = upd["update_id"]; last_id = uid + 1
                    if uid in processed: continue
                    processed.add(uid)
                    if len(processed) > 100:
                        processed = set(list(processed)[-50:])
                    msg = upd.get("message", {})
                    text = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")
                    if text and chat_id:
                        handle_cmd(text, chat_id)
        except Exception as e:
            print(f"[TG] Error: {e}"); time.sleep(5)

# ===== MAIN =====
def main():
    print("=" * 60)
    print(f"MAHAKAAL T20 SCALP BOT v1.0 | Paper={PAPER}")
    print(f"Data: Upstox | Execution: Kotak Neo")
    print(f"Target: ₹{DAILY_TARGET:,.0f} | "
          f"Lots: {LOTS_NORMAL} normal / {LOTS_HIGH_IV} high IV")
    print(f"Score: ≥{SCORE_NORMAL} normal | "
          f"≥{SCORE_HIGH_IV} high IV | "
          f"≥{SCORE_POST_TARGET} post-target")
    print(f"Started: {now_ist()}")
    print("=" * 60)

    reset_daily()
    if DB_AVAILABLE:
        try:
            init_db()
        except Exception as e:
            print(f"[DB] Init error: {e}")
    neo_ok = neo_login()

    # Start websocket
    start_websocket()

    # Startup message
    spot = upstox_ltp(SENSEX_KEY)
    nifty = upstox_ltp(NIFTY_KEY)
    prev = prev_ohlc()
    iv_days = len(load_iv().get("sensex", {}))
    expiries = upstox_expiries()
    dte_str = ""
    if expiries:
        dte = compute_dte(expiries[0])
        sweet = "⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
        dte_str = f"DTE: {dte} {sweet}\n"

    dow = {0:"Monday",1:"Tuesday",2:"Wednesday",
           3:"Thursday",4:"Friday",5:"Saturday",6:"Sunday"}
    market = "✅ Trading" if now_ist().weekday() < 5 else "🔴 Weekend"

    tg(f"🚀 <b>Mahakaal T20 v1.0</b>\n"
       f"{now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | "
       f"{dow[now_ist().weekday()]} | {market}\n"
       f"Upstox: {'✅' if spot else '❌'} | "
       f"Neo: {'✅' if neo_ok else '⚠️ /login'}\n\n"
       f"<b>Data:</b> Upstox websocket + REST\n"
       f"<b>Exec:</b> Kotak Neo (zero brokerage)\n\n"
       f"{dte_str}"
       f"Sensex: {spot:,.2f} | Nifty: {nifty:,.2f}\n\n"
       f"<b>Scoring Engine (0-15):</b>\n"
       f"Price action: 6pts | Structure: 4pts\n"
       f"Indicators: 4pts | OI/Flow: 2pts\n\n"
       f"Threshold: ≥{SCORE_NORMAL} | "
       f"High IV: ≥{SCORE_HIGH_IV} | "
       f"Post-target: ≥{SCORE_POST_TARGET}\n"
       f"IV history: {iv_days}/15 days\n"
       f"/help for commands")

    # Scheduler
    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(job_login,
        CronTrigger(day_of_week="mon-fri",
                    hour=8, minute=30, timezone=IST),
        id="login")

    scheduler.add_job(job_premarket,
        CronTrigger(day_of_week="mon-fri",
                    hour=9, minute=0, timezone=IST),
        id="premarket")

    scheduler.add_job(job_or_track,
        CronTrigger(day_of_week="mon-fri",
                    hour=9, minute="15-19",
                    second="*/30", timezone=IST),
        id="or_track", max_instances=1, coalesce=True)

    scheduler.add_job(job_or_lock,
        CronTrigger(day_of_week="mon-fri",
                    hour=9, minute=20, timezone=IST),
        id="or_lock")

    # Signal check every 1 minute from 9:20 (1-min candles)
    scheduler.add_job(job_signal_check,
        CronTrigger(day_of_week="mon-fri",
                    hour="9", minute="20-59",
                    timezone=IST),
        id="signals_9",
        max_instances=1, coalesce=True)

    scheduler.add_job(job_signal_check,
        CronTrigger(day_of_week="mon-fri",
                    hour="10-14", minute="*",
                    timezone=IST),
        id="signals_10",
        max_instances=1, coalesce=True)

    # Trade monitor every minute
    scheduler.add_job(job_monitor,
        CronTrigger(day_of_week="mon-fri",
                    hour="9-14", minute="*",
                    timezone=IST),
        id="monitor",
        max_instances=1, coalesce=True)

    scheduler.add_job(job_pre_close,
        CronTrigger(day_of_week="mon-fri",
                    hour=14, minute=55, timezone=IST),
        id="preclose")

    scheduler.add_job(job_eod,
        CronTrigger(day_of_week="mon-fri",
                    hour=15, minute=30, timezone=IST),
        id="eod")

    scheduler.add_job(job_health,
        CronTrigger(minute=0, timezone=IST),
        id="health")

    print(f"[Scheduler] {len(scheduler.get_jobs())} jobs")
    threading.Thread(target=tg_listener, daemon=True).start()
    print("[Main] Running — bot silent until signals...")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[Main] Stopped")

if __name__ == "__main__":
    main()
