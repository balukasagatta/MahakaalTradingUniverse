"""
Mahakaal T20 Scalp Bot v1.0 — CLEAN REWRITE
============================================
Data:      Upstox (REST + Websocket)
Execution: Kotak Neo (zero brokerage)
Strategy:  Institutional grade scalping

Bugs fixed in this version:
  1. atm_iv not passed to compute_score → added to signature
  2. pdh/pdl not defined in build_snapshot → fixed extraction
  3. snap.get("ema9") in compute_score → removed, uses candles directly
  4. Dead code after early return in check_signal → removed
  5. compute_ema had unreachable VWAP body → removed
  6. OR state lost on restart → persisted to JSON file
  7. /today command missing → added
  8. /setor missing from /help → added
  9. Duplicate scheduler jobs → fixed to single job
  10. alerts table schema → correct columns
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
IV_FILE            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iv_history.json")
OR_FILE            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "or_state.json")

# ===== CONSTANTS =====
UPSTOX_BASE        = "https://api.upstox.com/v2"
SENSEX_KEY         = "BSE_INDEX|SENSEX"
NIFTY_KEY          = "NSE_INDEX|Nifty 50"
SENSEX_FO_SEG      = "BSE_INDEX|SENSEX"

SCORE_NORMAL       = 7
SCORE_HIGH_IV      = 8
SCORE_POST_TARGET  = 10

LOTS_NORMAL        = 5
LOTS_HIGH_IV       = 3
LOT_SIZE           = 20

DAILY_TARGET       = 2500
DAILY_LOSS_LIMIT   = 4000
LOCK_PTS           = 20
SL_PTS             = 20

ATM_SPREAD_MAX     = 10
IV_HIGH_THRESHOLD  = 20.0
MAX_SCALPS         = 4
KILL_SL            = 2
DEDUP_SECS         = 120

EVENT_DAYS = {}

# ===== UTILS =====
def now_ist():    return datetime.now(IST)
def today_str():  return now_ist().strftime("%Y-%m-%d")
def now_mins():   n = now_ist(); return n.hour * 60 + n.minute
def ts_to_ist(ts): return datetime.fromisoformat(ts).astimezone(IST)

def compute_vwap(candles):
    """Compute VWAP from candles list [ts, o, h, l, c, v]."""
    total_pv = total_v = 0
    for c in candles:
        typical = (c[2] + c[3] + c[4]) / 3
        vol = c[5] if len(c) > 5 else 1
        total_pv += typical * vol
        total_v += vol
    return round(total_pv / total_v, 2) if total_v > 0 else 0

def compute_ema(closes, period):
    """Compute EMA for given period."""
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def compute_pivots(h, l, c):
    p = (h + l + c) / 3
    return {
        "pivot": round(p, 2),
        "r1": round(2 * p - l, 2),
        "r2": round(p + (h - l), 2),
        "s1": round(2 * p - h, 2),
        "s2": round(p - (h - l), 2),
        "pdh": round(h, 2),
        "pdl": round(l, 2),
    }

def compute_dte(expiry_str):
    try:
        return (datetime.strptime(expiry_str, "%Y-%m-%d").date()
                - now_ist().date()).days
    except:
        return 5

def detect_gap(prev_close, current):
    if not prev_close or not current:
        return "UNKNOWN", 0.0
    pct = (current - prev_close) / prev_close * 100
    if pct > 1.75:  return "EXTREME_GAP_UP", round(pct, 2)
    if pct > 1.00:  return "LARGE_GAP_UP", round(pct, 2)
    if pct > 0.55:  return "GAP_UP", round(pct, 2)
    if pct < -1.75: return "EXTREME_GAP_DOWN", round(pct, 2)
    if pct < -1.00: return "LARGE_GAP_DOWN", round(pct, 2)
    if pct < -0.55: return "GAP_DOWN", round(pct, 2)
    return "FLAT_OPEN", round(pct, 2)

# ===== TELEGRAM =====
def _db_alert(msg, category="general"):
    try:
        import sqlite3, datetime as dt
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mahakaal.db")
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, bot TEXT, category TEXT, message TEXT)""")
        conn.execute(
            "INSERT INTO alerts (timestamp, bot, category, message) VALUES (?,?,?,?)",
            (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "alakh", category, msg[:500]))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB_ALERT] {e}")

def tg(msg, retries=3, category="general"):
    _db_alert(msg, category)
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(retries):
        try:
            r = requests.post(url,
                json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
                timeout=10)
            if r.status_code == 200:
                return True
        except Exception as e:
            print(f"[TG] {e}")
            if i < retries - 1:
                time.sleep(3)
    return False

# ===== UPSTOX REST =====
def upstox_headers():
    return {"Authorization": f"Bearer {UPSTOX_TOKEN}", "Accept": "application/json"}

def upstox_ltp(instrument_key):
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

def upstox_candles_1min(instrument_key):
    try:
        r = requests.get(
            f"{UPSTOX_BASE}/historical-candle/intraday/{instrument_key}/1minute",
            headers=upstox_headers(), timeout=15)
        d = r.json()
        if d.get("status") == "success":
            candles = d["data"]["candles"]
            candles.sort(key=lambda x: x[0])
            return candles
    except Exception as e:
        print(f"[Upstox] Candles error: {e}")
    return []

def aggregate_to_3min(candles_1min):
    if not candles_1min:
        return []
    result = []
    group = []
    for candle in candles_1min:
        ts = ts_to_ist(candle[0])
        bucket = (ts.minute // 3) * 3
        bucket_ts = ts.replace(minute=bucket, second=0, microsecond=0)
        if group and group[0]["bucket"] != bucket_ts:
            c = group
            result.append([
                c[0]["bucket"].isoformat(),
                c[0]["o"],
                max(x["h"] for x in c),
                min(x["l"] for x in c),
                c[-1]["c"],
                sum(x["v"] for x in c),
            ])
            group = []
        group.append({
            "bucket": bucket_ts,
            "o": candle[1], "h": candle[2],
            "l": candle[3], "c": candle[4],
            "v": candle[5] if len(candle) > 5 else 0
        })
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
    try:
        to_date = today_str()
        from_date = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")
        r = requests.get(
            f"{UPSTOX_BASE}/historical-candle/{instrument_key}/day/{to_date}/{from_date}",
            headers=upstox_headers(), timeout=15)
        d = r.json()
        if d.get("status") == "success":
            candles = d["data"]["candles"]
            candles.sort(key=lambda x: x[0])
            return candles
    except Exception as e:
        print(f"[Upstox] Daily candles error: {e}")
    return []

def upstox_option_chain(expiry_date):
    try:
        r = requests.get(f"{UPSTOX_BASE}/option/chain",
            headers=upstox_headers(),
            params={"instrument_key": SENSEX_FO_SEG, "expiry_date": expiry_date},
            timeout=15)
        d = r.json()
        if d.get("status") == "success":
            return d["data"]
    except Exception as e:
        print(f"[Upstox] Chain error: {e}")
    return []

def upstox_expiries():
    try:
        r = requests.get(f"{UPSTOX_BASE}/option/contract",
            headers=upstox_headers(),
            params={"instrument_key": SENSEX_FO_SEG}, timeout=10)
        d = r.json()
        if d.get("status") == "success":
            today = now_ist().date()
            expiries = set()
            for item in d["data"]:
                exp = item.get("expiry", "")
                if exp:
                    try:
                        exp_date = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                        if exp_date >= today:
                            expiries.add(exp[:10])
                    except:
                        pass
            return sorted(list(expiries))
    except Exception as e:
        print(f"[Upstox] Expiries error: {e}")
    return []

def prev_ohlc():
    candles = upstox_daily_candles(SENSEX_KEY, 10)
    today = today_str()
    for c in reversed(candles):
        if c[0][:10] < today:
            return {"date": c[0][:10],
                    "open": c[1], "high": c[2],
                    "low": c[3], "close": c[4]}
    return None

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
            ucc=KOTAK_UCC, totp=totp)
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
WS_STATE = {
    "sensex_ltp": None, "nifty_ltp": None,
    "atm_ce_ltp": None, "atm_pe_ltp": None,
    "atm_tbq": 0, "atm_tsq": 0,
    "atm_key": None, "connected": False, "last_tick": None,
}
WS_LOCK = threading.Lock()

def on_ws_open(ws):
    with WS_LOCK: WS_STATE["connected"] = True
    print("[WS] Connected")
    sub_msg = json.dumps({
        "guid": "mahakaal-001", "method": "sub",
        "data": {"mode": "full", "instrumentKeys": [SENSEX_KEY, NIFTY_KEY]}
    })
    ws.send(sub_msg.encode())

def on_ws_close(ws, code, msg):
    with WS_LOCK: WS_STATE["connected"] = False
    print(f"[WS] Disconnected: {code} {msg}")
    threading.Timer(5, start_websocket).start()

def on_ws_error(ws, error):
    print(f"[WS] Error: {error}")

def on_ws_message(ws, message):
    pass  # Protobuf parsing — uses REST fallback

def start_websocket():
    try:
        r = requests.get(
            "https://api.upstox.com/v3/feed/market-data-feed/authorize",
            headers=upstox_headers(), timeout=10)
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

# ===== OPENING RANGE STATE — persisted to file =====
OR_S = {
    "date": None, "high": None, "low": None,
    "ticks": 0, "locked": False, "announced": False,
    "gap_type": "UNKNOWN", "gap_pct": 0.0, "open_price": None,
}
OR_L = threading.Lock()

def or_save():
    """Persist OR state to file so it survives restarts."""
    try:
        with open(OR_FILE, "w") as f:
            json.dump(OR_S, f)
    except Exception as e:
        print(f"[OR] Save error: {e}")

def or_load():
    """Load OR state from file on startup."""
    global OR_S
    try:
        if os.path.exists(OR_FILE):
            with open(OR_FILE) as f:
                saved = json.load(f)
            if saved.get("date") == today_str():
                OR_S.update(saved)
                print(f"[OR] Restored: locked={OR_S['locked']} H={OR_S['high']} L={OR_S['low']}")
    except Exception as e:
        print(f"[OR] Load error: {e}")

# ===== RISK STATE =====
RISK = {
    "date": None, "sl_hits": 0, "halted": False,
    "alert_only": False, "scalps": 0, "pnl": 0, "daily_approved": True
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

LAST_SIGNAL = {"time": None, "pending_execute": None}
LAST_L = threading.Lock()

# ===== ALERT CANDLE STATE =====
ALERT_C = {
    "active": False, "direction": None,
    "high": None, "low": None,
    "st_val": None, "timestamp": None, "confirmed": False,
}
ALERT_L = threading.Lock()

# ===== DAILY RESET =====
def reset_daily():
    today = now_ist().date()
    with RISK_L:
        if RISK["date"] != today:
            is_event = today_str() in EVENT_DAYS
            RISK.update({
                "date": today, "sl_hits": 0,
                "halted": False, "alert_only": False, "scalps": 0,
                "pnl": 0, "daily_approved": not is_event
            })
            print(f"[Risk] Reset {today}")
            if is_event:
                event_name = EVENT_DAYS[today_str()]
                tg(f"⚠️ <b>HIGH IMPACT EVENT: {event_name}</b>\n"
                   f"Bot paused. Send /approve to enable trading.")

def is_allowed():
    reset_daily()
    n = now_ist()
    if n.weekday() > 4: return False, "Weekend"
    if n.hour >= 15: return False, "After 3PM"
    if n.hour < 9 or (n.hour == 9 and n.minute < 20):
        return False, "Pre-market"
    with RISK_L:
        if RISK["halted"]: return False, "Halted"
        if not RISK["daily_approved"]: return False, "Event day"
    return True, "OK"

def is_execution_allowed():
    with RISK_L:
        if RISK["alert_only"]: return False, "Alert only mode"
        if RISK["halted"]: return False, "Halted"
    return True, "OK"

def get_session():
    m = now_mins()
    if m < 9 * 60 + 20: return "PRE"
    elif m <= 11 * 60 + 30: return "PRIME"
    elif m <= 15 * 60: return "BONUS"
    else: return "CLOSED"

def register_sl(loss=0):
    with RISK_L:
        RISK["sl_hits"] += 1
        RISK["pnl"] -= abs(loss)
        hits = RISK["sl_hits"]
        if hits >= KILL_SL or abs(RISK["pnl"]) >= DAILY_LOSS_LIMIT:
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

# ===== IV HISTORY =====
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
    return 50 if hi == lo else round((current_iv - lo) / (hi - lo) * 100, 1)

def is_high_iv_day(atm_iv, iv_rank=None):
    if iv_rank is not None: return iv_rank > 70
    return atm_iv > IV_HIGH_THRESHOLD

# ===== INDICATORS =====
def compute_supertrend(candles_1min, period=10, mult=3.0):
    if len(candles_1min) < period + 5:
        return None, None, 0, None
    h = [c[2] for c in candles_1min]
    l = [c[3] for c in candles_1min]
    c = [c[4] for c in candles_1min]
    trs = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
           for i in range(1, len(h))]
    atr = [sum(trs[:period]) / period]
    for i in range(period, len(trs)):
        atr.append((atr[-1] * (period - 1) + trs[i]) / period)
    if not atr: return None, None, 0, None
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
    cur = direction[-1]
    stable = 0
    prev_direction = None
    for d in reversed(direction):
        if d == cur:
            stable += 1
        else:
            prev_direction = d
            break
    return cur, round(st[-1], 2), stable, prev_direction

# ===== SCORING ENGINE =====
def compute_score(
    spot, candles_1min, candles_3min,
    or_high, or_low, or_open,
    prev_close, pivots,
    st_signal, st_val, st_stable,
    nifty_st, atm_ce, atm_pe,
    tbq, tsq, atm_iv=0
):
    """
    Compute signal score (0-18 pts with research paper additions).
    Returns (call_score, put_score, details)
    """
    call_pts = 0; put_pts = 0; details = {}

    # ===== PRICE ACTION (6 pts) =====

    # 1. Consecutive higher highs/lows (±2)
    if len(candles_3min) >= 4:
        last4 = candles_3min[-4:]
        highs = [c[2] for c in last4]
        lows  = [c[3] for c in last4]
        if all(highs[i] > highs[i-1] for i in range(1, 4)):
            call_pts += 2; details["consec"] = "3× HH → +2 CALL"
        elif all(highs[i] < highs[i-1] for i in range(1, 4)):
            put_pts += 2;  details["consec"] = "3× LL → +2 PUT"
        elif all(lows[i] > lows[i-1] for i in range(1, 4)):
            call_pts += 2; details["consec"] = "3× HL → +2 CALL"
        elif all(lows[i] < lows[i-1] for i in range(1, 4)):
            put_pts += 2;  details["consec"] = "3× LH → +2 PUT"

    # 2. Price at key level (±2)
    if pivots:
        prox = 50
        for level, pts, side in [
            ("s1", 2, "CALL"), ("s2", 2, "CALL"),
            ("r1", 2, "PUT"), ("r2", 2, "PUT")
        ]:
            if abs(spot - pivots[level]) < prox:
                if side == "CALL": call_pts += pts
                else: put_pts += pts
                details["level"] = f"At {level.upper()} {pivots[level]:,.0f} → +{pts} {side}"
                break

    # 3. Candle close strength (±1)
    if candles_3min:
        last = candles_3min[-1]
        rng = last[2] - last[3]
        if rng > 0:
            close_pct = (last[4] - last[3]) / rng
            if close_pct >= 0.7:
                call_pts += 1; details["close_str"] = f"Strong close {close_pct:.0%} → +1 CALL"
            elif close_pct <= 0.3:
                put_pts += 1;  details["close_str"] = f"Weak close {close_pct:.0%} → +1 PUT"

    # 4. Gap open position (±1)
    if or_high and or_low and or_open:
        or_range = or_high - or_low
        upper_z = or_high - or_range * 0.3
        lower_z = or_low + or_range * 0.3
        if or_open >= upper_z:
            call_pts += 1; details["gap_pos"] = f"Opened near high → +1 CALL"
        elif or_open <= lower_z:
            put_pts += 1;  details["gap_pos"] = f"Opened near low → +1 PUT"

    # ===== PRICE STRUCTURE (4 pts) =====

    # 5. VWAP (±1)
    vwap = compute_vwap(candles_1min)
    if vwap and spot:
        diff_pct = abs(spot - vwap) / spot * 100
        if spot > vwap and diff_pct > 0.15:
            call_pts += 1; details["vwap"] = f"Above VWAP {vwap:,.0f} → +1 CALL"
        elif spot < vwap and diff_pct > 0.15:
            put_pts += 1;  details["vwap"] = f"Below VWAP {vwap:,.0f} → +1 PUT"
        else:
            details["vwap"] = f"Near VWAP {vwap:,.0f}"

    # 6. Price vs prev close (±1)
    if prev_close and spot:
        if spot > prev_close:
            call_pts += 1; details["prev_close"] = f"Above prev close {prev_close:,.0f} → +1 CALL"
        else:
            put_pts += 1;  details["prev_close"] = f"Below prev close {prev_close:,.0f} → +1 PUT"

    # 7. ORB hugging (±1)
    if or_high and or_low and candles_3min:
        today = now_ist().date()
        or_mid = (or_high + or_low) / 2
        today_closes = [c[4] for c in candles_3min
                        if ts_to_ist(c[0]).date() == today]
        if today_closes:
            upper_count = sum(1 for c in today_closes if c > or_mid)
            lower_count = sum(1 for c in today_closes if c <= or_mid)
            if upper_count > lower_count * 1.5:
                call_pts += 1; put_pts -= 1
                details["orb_hug"] = "Hugging ORB top → +1 CALL / -1 PUT"
            elif lower_count > upper_count * 1.5:
                put_pts += 1; call_pts -= 1
                details["orb_hug"] = "Hugging ORB bottom → +1 PUT / -1 CALL"

    # 8. Volume direction (±1)
    if candles_3min:
        today = now_ist().date()
        up_vol = dn_vol = 0
        for c in candles_3min:
            try:
                if ts_to_ist(c[0]).date() == today:
                    if c[4] > c[1]: up_vol += c[5]
                    elif c[4] < c[1]: dn_vol += c[5]
            except: pass
        if up_vol > dn_vol * 1.3:
            call_pts += 1; details["vol_dir"] = f"Up vol dominant → +1 CALL"
        elif dn_vol > up_vol * 1.3:
            put_pts += 1;  details["vol_dir"] = f"Dn vol dominant → +1 PUT"

    # ===== INDICATORS (4 pts) =====

    # 9. Supertrend (±2)
    if st_signal:
        if st_signal == "BUY":
            call_pts += 2; details["st"] = f"ST BUY @ {st_val:,.0f} → +2 CALL"
        else:
            put_pts += 2;  details["st"] = f"ST SELL @ {st_val:,.0f} → +2 PUT"

    # 10. ST stable 2+ candles (+1)
    if st_stable >= 2:
        if st_signal == "BUY":
            call_pts += 1; details["st_stable"] = f"ST stable {st_stable}c → +1 CALL"
        elif st_signal == "SELL":
            put_pts += 1;  details["st_stable"] = f"ST stable {st_stable}c → +1 PUT"
    else:
        details["st_stable"] = f"ST only {st_stable}c — wait for 2"

    # 11. Nifty correlation (±1)
    if nifty_st:
        if nifty_st == st_signal:
            if st_signal == "BUY":
                call_pts += 1; details["nifty"] = "Nifty confirms BUY → +1"
            else:
                put_pts += 1;  details["nifty"] = "Nifty confirms SELL → +1"
        else:
            if st_signal == "BUY":
                call_pts -= 1; details["nifty"] = "Nifty diverges SELL → -1 CALL"
            else:
                put_pts -= 1;  details["nifty"] = "Nifty diverges BUY → -1 PUT"

    # T012: 3-EMA alignment (±1) — computed from candles directly
    if len(candles_1min) >= 50:
        closes = [c[4] for c in candles_1min]
        _ema9  = compute_ema(closes, 9)
        _ema21 = compute_ema(closes, 21)
        _ema50 = compute_ema(closes, 50)
        if _ema9 and _ema21 and _ema50:
            if _ema9 > _ema21 > _ema50:
                call_pts += 1; details["ema3"] = f"3-EMA aligned BUY → +1 CALL"
            elif _ema9 < _ema21 < _ema50:
                put_pts += 1;  details["ema3"] = f"3-EMA aligned SELL → +1 PUT"
            elif ((_ema9 > _ema21 and _ema21 < _ema50) or
                  (_ema9 < _ema21 and _ema21 > _ema50)):
                if st_signal == "BUY":
                    call_pts -= 1; details["ema3"] = "EMA50 opposes BUY → -1 CALL"
                elif st_signal == "SELL":
                    put_pts -= 1;  details["ema3"] = "EMA50 opposes SELL → -1 PUT"

    # T013: PDH/PDL S/R zone (±1)
    pdh = pivots.get("pdh", 0) if pivots else 0
    pdl = pivots.get("pdl", 0) if pivots else 0
    if pdh and pdl and spot:
        if spot > pdh and st_signal == "BUY":
            call_pts += 1; details["sr_zone"] = f"Breaking PDH {pdh:,.0f} → +1 CALL"
        elif spot < pdh * 0.998 and st_signal == "BUY":
            call_pts -= 1; details["sr_zone"] = f"Hitting PDH resistance {pdh:,.0f} → -1 CALL"
        elif spot < pdl and st_signal == "SELL":
            put_pts += 1;  details["sr_zone"] = f"Breaking PDL {pdl:,.0f} → +1 PUT"
        elif spot > pdl * 1.002 and st_signal == "SELL":
            put_pts -= 1;  details["sr_zone"] = f"Hitting PDL support {pdl:,.0f} → -1 PUT"

    # T020: 10-candle channel breakout (±1)
    if len(candles_1min) >= 10:
        last10 = candles_1min[-10:]
        ch_high = max(c[2] for c in last10)
        ch_low  = min(c[3] for c in last10)
        if spot > ch_high and st_signal == "BUY":
            call_pts += 1; details["channel"] = f"Breaking 10c high {ch_high:,.0f} → +1 CALL"
        elif spot < ch_high * 0.999 and spot > ch_high * 0.995 and st_signal == "BUY":
            call_pts -= 1; details["channel"] = f"At 10c resistance {ch_high:,.0f} → -1 CALL"
        elif spot < ch_low and st_signal == "SELL":
            put_pts += 1;  details["channel"] = f"Breaking 10c low {ch_low:,.0f} → +1 PUT"
        elif spot > ch_low * 1.001 and spot < ch_low * 1.005 and st_signal == "SELL":
            put_pts -= 1;  details["channel"] = f"At 10c support {ch_low:,.0f} → -1 PUT"
        else:
            details["channel"] = f"Inside channel {ch_low:,.0f}-{ch_high:,.0f}"

    # ===== OI/FLOW (2 pts) =====

    # T008: IV Momentum (±1)
    if atm_iv > 0:
        if atm_iv > 17 and st_signal:
            if st_signal == "BUY":
                call_pts += 1; details["iv_momentum"] = f"High IV {atm_iv:.1f}% → +1 CALL"
            else:
                put_pts += 1;  details["iv_momentum"] = f"High IV {atm_iv:.1f}% → +1 PUT"
        elif atm_iv < 11:
            call_pts -= 1; put_pts -= 1
            details["iv_momentum"] = f"Low IV {atm_iv:.1f}% — premium cheap → -1 both"
        else:
            details["iv_momentum"] = f"IV {atm_iv:.1f}% normal"

    # 12. tbq vs tsq (±1)
    if tbq and tsq and tbq + tsq > 0:
        ratio = tbq / (tbq + tsq)
        if ratio > 0.6:
            call_pts += 1; details["flow"] = f"Buyers {ratio:.0%} → +1 CALL"
        elif ratio < 0.4:
            put_pts += 1;  details["flow"] = f"Sellers {1-ratio:.0%} → +1 PUT"

    # 13. Spread quality (+1)
    if atm_ce:
        spread = atm_ce.get("ask_price", 0) - atm_ce.get("bid_price", 0)
        if 0 < spread < ATM_SPREAD_MAX:
            if call_pts > put_pts: call_pts += 1
            elif put_pts > call_pts: put_pts += 1
            details["spread"] = f"Spread ₹{spread:.1f} tight → +1"
        else:
            details["spread"] = f"Spread ₹{spread:.1f} wide"

    call_pts = max(0, call_pts)
    put_pts  = max(0, put_pts)
    details["vwap_val"]   = vwap
    details["call_score"] = call_pts
    details["put_score"]  = put_pts
    return call_pts, put_pts, details

# ===== OPENING RANGE =====
def or_reset():
    today = now_ist().date()
    with OR_L:
        if OR_S["date"] != today:
            OR_S.update({
                "date": today, "high": None, "low": None,
                "ticks": 0, "locked": False, "announced": False,
                "gap_type": "UNKNOWN", "gap_pct": 0.0, "open_price": None,
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
            OR_S["open_price"] = ltp
        else:
            OR_S["high"] = max(OR_S["high"], ltp)
            OR_S["low"]  = min(OR_S["low"], ltp)
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

    prev = prev_ohlc()
    pivots_str = gap_str = dte_str = ""
    if prev:
        gap_type, gap_pct = detect_gap(prev["close"], (oh + ol) / 2)
        with OR_L:
            OR_S["gap_type"] = gap_type
            OR_S["gap_pct"]  = gap_pct
        pivots = compute_pivots(prev["high"], prev["low"], prev["close"])
        gap_str = f"\nGap: {gap_type.replace('_', ' ')} ({gap_pct:+.2f}%)" \
            if gap_type not in ["FLAT_OPEN", "UNKNOWN"] else ""
        pivots_str = (f"\nR1: {pivots['r1']:,.0f} | "
                      f"Pivot: {pivots['pivot']:,.0f} | "
                      f"S1: {pivots['s1']:,.0f}")

    expiries = upstox_expiries()
    if expiries:
        dte = compute_dte(expiries[0])
        sweet = "⭐ SWEET" if 3 <= dte <= 5 else "⚡ GAMMA" if dte <= 2 else "📅"
        dte_str = f"\nDTE: {dte} {sweet}"

    or_save()  # persist to file

    tg(f"📊 <b>OR LOCKED — SENSEX</b>\n"
       f"09:20 IST | {today_str()}\n\n"
       f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
       f"Range: {oh - ol:.1f} pts | Ticks: {OR_S['ticks']}"
       f"{gap_str}{pivots_str}{dte_str}\n\n"
       f"<i>Scoring engine active from 9:20 AM</i>")

# ===== SNAPSHOT =====
def build_snapshot():
    try:
        expiries = upstox_expiries()
        if not expiries: return {"error": "No expiries"}
        nearest = expiries[0]; dte = compute_dte(nearest)

        chain = upstox_option_chain(nearest)
        if not chain: return {"error": "No chain data"}

        spot = upstox_ltp(SENSEX_KEY)
        if not spot: return {"error": "No spot"}

        nifty_spot = upstox_ltp(NIFTY_KEY)

        c1 = upstox_candles_1min(SENSEX_KEY)
        c1_nifty = upstox_candles_1min(NIFTY_KEY)
        c3 = aggregate_to_3min(c1)
        c3_nifty = aggregate_to_3min(c1_nifty)

        st_sig, st_val, st_stable, prev_st_dir = compute_supertrend(c1)
        nifty_st, _, _, _ = compute_supertrend(c1_nifty)

        closes_1min = [c[4] for c in c1]
        ema9  = compute_ema(closes_1min, 9)
        ema21 = compute_ema(closes_1min, 21)
        ema50 = compute_ema(closes_1min, 50)
        ema_trend = ("BUY" if ema9 > ema21 else "SELL") if ema9 and ema21 else None
        ema_aligned = bool(ema9 and ema21 and ema50 and
            ((ema9 > ema21 > ema50) or (ema9 < ema21 < ema50)))

        prev = prev_ohlc()
        pivots = prev_close = None
        pdh = pdl = 0
        if prev:
            pivots = compute_pivots(prev["high"], prev["low"], prev["close"])
            prev_close = prev["close"]
            pdh = pivots.get("pdh", 0)
            pdl = pivots.get("pdl", 0)

        atm_data = min(chain, key=lambda x: abs(x["strike_price"] - spot), default=None)
        atm_ce = atm_pe = None
        atm_iv = 0
        if atm_data:
            atm_ce    = atm_data.get("call_options", {}).get("market_data", {})
            atm_pe    = atm_data.get("put_options", {}).get("market_data", {})
            ce_greeks = atm_data.get("call_options", {}).get("option_greeks", {})
            pe_greeks = atm_data.get("put_options", {}).get("option_greeks", {})
            atm_iv    = (ce_greeks.get("iv", 0) + pe_greeks.get("iv", 0)) / 2

        iv_rank = get_iv_rank(atm_iv)

        with OR_L:
            or_locked  = OR_S["locked"]
            or_high    = OR_S["high"]
            or_low     = OR_S["low"]
            or_open    = OR_S["open_price"]
            gap_type   = OR_S["gap_type"]
            gap_pct    = OR_S["gap_pct"]

        with WS_LOCK:
            tbq = WS_STATE.get("atm_tbq", 0)
            tsq = WS_STATE.get("atm_tsq", 0)

        return {
            "spot": spot, "nifty_spot": nifty_spot,
            "expiry": nearest, "dte": dte,
            "chain": chain, "atm_data": atm_data,
            "atm_ce": atm_ce, "atm_pe": atm_pe,
            "atm_iv": round(atm_iv, 2), "iv_rank": iv_rank,
            "c1": c1, "c3": c3, "c3_nifty": c3_nifty,
            "st_sig": st_sig, "st_val": st_val,
            "st_stable": st_stable, "prev_st_dir": prev_st_dir,
            "ema9": ema9, "ema21": ema21, "ema50": ema50,
            "ema_trend": ema_trend, "ema_aligned": ema_aligned,
            "nifty_st": nifty_st,
            "pivots": pivots, "prev_close": prev_close,
            "pdh": pdh, "pdl": pdl,
            "or_locked": or_locked,
            "or_high": or_high, "or_low": or_low, "or_open": or_open,
            "gap_type": gap_type, "gap_pct": gap_pct,
            "tbq": tbq, "tsq": tsq,
            "vwap": compute_vwap(c1),
        }
    except Exception as e:
        print(f"[Snapshot] Error: {e}")
        import traceback; traceback.print_exc()
        return {"error": str(e)}

# ===== ENTRY GATE =====
def check_entry_gate(snap):
    global ALERT_C
    spot      = snap["spot"]
    st_sig    = snap["st_sig"]
    st_val    = snap["st_val"]
    st_stable = snap["st_stable"]
    prev_st   = snap.get("prev_st_dir")
    ema9      = snap.get("ema9")
    c1        = snap.get("c1", [])

    if not st_sig or not c1:
        return None, None, None

    last = c1[-1]
    is_fresh_flip = (prev_st is not None and st_sig != prev_st and st_stable == 1)

    with ALERT_L:
        if is_fresh_flip:
            alert_candle = c1[-2] if len(c1) >= 2 else c1[-1]
            ALERT_C.update({
                "active": True, "direction": st_sig,
                "high": alert_candle[2], "low": alert_candle[3],
                "st_val": st_val, "timestamp": alert_candle[0], "confirmed": False,
            })
            print(f"[Gate] Alert candle: {st_sig} H={alert_candle[2]} L={alert_candle[3]}")
            return None, None, None

        if ALERT_C["active"] and ALERT_C["direction"] != st_sig:
            ALERT_C["active"] = False; ALERT_C["confirmed"] = False
            print("[Gate] Alert candle invalidated")
            return None, None, None

        if not ALERT_C["active"]:
            return None, None, None

        alert_high = ALERT_C["high"]
        alert_low  = ALERT_C["low"]
        direction  = ALERT_C["direction"]

        PROXIMITY = 80
        near_st  = st_val and abs(spot - st_val) <= PROXIMITY
        near_ema = ema9 and abs(spot - ema9) <= PROXIMITY
        if not (near_st or near_ema):
            print(f"[Gate] Pullback failed — spot {spot} ST {st_val} EMA9 {ema9}")
            return None, None, None

        if not ALERT_C["confirmed"]:
            if direction == "SELL":
                if last[4] < alert_low:
                    ALERT_C["confirmed"] = True
                    print(f"[Gate] PUT confirmed below {alert_low}")
                else:
                    return None, None, None
            else:
                if last[4] > alert_high:
                    ALERT_C["confirmed"] = True
                    print(f"[Gate] CALL confirmed above {alert_high}")
                else:
                    return None, None, None

        if not ALERT_C["confirmed"]:
            return None, None, None

        sl_level = alert_high if direction == "SELL" else alert_low
        entry_direction = "PUT" if direction == "SELL" else "CALL"
        ALERT_C["active"] = False; ALERT_C["confirmed"] = False
        return entry_direction, sl_level, "PULLBACK"

# ===== SIGNAL ENGINE =====
def check_signal(snap):
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

    with LAST_L:
        lt = LAST_SIGNAL["time"]
        if lt and (now_ist() - lt).total_seconds() < DEDUP_SECS:
            return None, 0, 0, {"skip": "Dedup"}, None

    with TRADE_L:
        if TRADE["active"]: return None, 0, 0, {"skip": "Trade active"}, None

    if not snap.get("or_locked"):
        return None, 0, 0, {"skip": "OR not locked"}, None

    direction, sl_index, entry_type = check_entry_gate(snap)
    if not direction:
        st_stable = snap.get("st_stable", 0)
        st_sig    = snap.get("st_sig", "?")
        ema9      = snap.get("ema9")
        spot      = snap.get("spot", 0)
        st_val    = snap.get("st_val", 0)
        skip_reason = f"Gate: ST={st_sig}({st_stable}c) spot={spot} ST={st_val} EMA9={ema9}"
        return None, 0, 0, {"skip": skip_reason}, None

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
        atm_iv=snap["atm_iv"],
    )

    score    = put_pts if direction == "PUT" else call_pts
    opposite = call_pts if direction == "PUT" else put_pts
    if opposite >= score - 1:
        return None, 0, 0, {
            "skip": f"Score conflict: {direction}={score} vs opposite={opposite}"
        }, None

    # T024: Economic announcement filter
    try:
        from event_calendar import is_high_impact_window
        event_hit, event_name = is_high_impact_window(30)
        if event_hit:
            tg(f"⚠️ <b>SIGNAL HELD — Economic Event</b>\n"
               f"{event_name} within 30 mins\n"
               f"Score: {score}/15 | Direction: {direction}")
            return None, 0, 0, {"skip": f"Event: {event_name}"}, None
    except Exception as e:
        print(f"[Event] {e}")

    high_iv   = is_high_iv_day(snap["atm_iv"], snap["iv_rank"])
    captured  = pnl / DAILY_TARGET if DAILY_TARGET > 0 else 0

    if captured >= 1.0:       threshold = SCORE_POST_TARGET
    elif high_iv:             threshold = SCORE_HIGH_IV
    else:                     threshold = SCORE_NORMAL

    if score < threshold:
        return None, 0, 0, {
            "skip": f"Score {score} < threshold {threshold}",
            "call_score": call_pts, "put_score": put_pts,
            "threshold": threshold,
        }, None

    if captured >= 1.0:   base_lots = 1
    elif captured >= 0.7: base_lots = 1
    elif captured >= 0.5: base_lots = 2
    else:                 base_lots = LOTS_HIGH_IV if high_iv else LOTS_NORMAL

    details["threshold"]   = threshold
    details["high_iv"]     = high_iv
    details["session"]     = session
    details["captured_pct"] = f"{captured:.0%}"
    details["entry_type"]  = entry_type
    details["sl_index"]    = sl_index
    details["call_score"]  = call_pts
    details["put_score"]   = put_pts
    return direction, score, base_lots, details, sl_index

# ===== STRIKE SELECTION =====
def select_strike(chain, spot, direction, atm_iv):
    try:
        sorted_chain = sorted(chain, key=lambda x: abs(x["strike_price"] - spot))
        for strike_data in sorted_chain[:5]:
            key = "call_options" if direction == "CALL" else "put_options"
            md     = strike_data.get(key, {}).get("market_data", {})
            greeks = strike_data.get(key, {}).get("option_greeks", {})
            ik     = strike_data.get(key, {}).get("instrument_key", "")
            ltp    = md.get("ltp", 0)
            if 200 <= ltp <= 500:
                return {
                    "strike": strike_data["strike_price"],
                    "instrument_key": ik, "ltp": ltp,
                    "bid": md.get("bid_price", ltp), "ask": md.get("ask_price", ltp),
                    "delta": greeks.get("delta", 0), "iv": greeks.get("iv", atm_iv),
                    "theta": greeks.get("theta", 0),
                    "spread": md.get("ask_price", 0) - md.get("bid_price", 0),
                }
        atm = sorted_chain[0]
        key    = "call_options" if direction == "CALL" else "put_options"
        md     = atm.get(key, {}).get("market_data", {})
        greeks = atm.get(key, {}).get("option_greeks", {})
        ik     = atm.get(key, {}).get("instrument_key", "")
        ltp    = md.get("ltp", 0)
        return {
            "strike": atm["strike_price"], "instrument_key": ik, "ltp": ltp,
            "bid": md.get("bid_price", ltp), "ask": md.get("ask_price", ltp),
            "delta": greeks.get("delta", 0), "iv": greeks.get("iv", atm_iv),
            "theta": greeks.get("theta", 0),
            "spread": md.get("ask_price", 0) - md.get("bid_price", 0),
        }
    except Exception as e:
        print(f"[Strike] Error: {e}")
        return None

# ===== FIRE SIGNAL =====
def fire_signal(snap, direction, score, lots, details, sl_index=None):
    allowed, _  = is_allowed()
    exec_ok, _  = is_execution_allowed()
    is_paper    = PAPER or not allowed
    alert_only  = not exec_ok
    spot        = snap["spot"]
    atm_iv      = snap["atm_iv"]
    expiry      = snap["expiry"]
    dte         = snap["dte"]
    high_iv     = details.get("high_iv", False)
    session     = details.get("session", "")
    captured    = details.get("captured_pct", "0%")
    entry_type  = details.get("entry_type", "PULLBACK")

    strike_data = select_strike(snap["chain"], spot, direction, atm_iv)
    if not strike_data:
        print("[Signal] No valid strike"); return False

    prem  = strike_data["ltp"]
    qty   = lots * LOT_SIZE
    delta = abs(strike_data.get("delta", 0.5)) or 0.5

    if sl_index:
        idx_sl_dist    = abs(spot - sl_index)
        sl_pts_dynamic = max(15, min(60, round(idx_sl_dist * delta, 1)))
    else:
        sl_pts_dynamic = SL_PTS

    sl_price   = round(prem - sl_pts_dynamic, 2)
    lock_price = round(prem + LOCK_PTS, 2)
    win        = round(LOCK_PTS * qty, 0)
    loss       = round(sl_pts_dynamic * qty, 0)

    # R:R check — skip if SL > lock
    if sl_pts_dynamic > LOCK_PTS:
        tg(f"⛔ <b>SIGNAL SKIPPED — Bad R:R</b>\n"
           f"{direction} {strike_data['strike']:,.0f} | Score {score}/15\n"
           f"SL: ₹{sl_pts_dynamic:.1f} > Lock: ₹{LOCK_PTS:.1f}\n"
           f"R:R unfavorable")
        return False

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
           f"{'Index SL: ' + str(sl_index) + ' (alert candle)' if sl_index else ''}\n"
           f"<b>Lock: ₹{lock_price:.2f} (+₹{LOCK_PTS} pts)</b>\n"
           f"After lock → structure trail on 1-min\n\n"
           f"Win (lock): +₹{win:,.0f} | Max loss: -₹{loss:,.0f}\n"
           f"{'⚠️ NOT EXECUTED — Send /execute to trade manually' if alert_only else ''}\n\n"
           f"<b>Score breakdown:</b>\n")

    for k, v in details.items():
        if isinstance(v, str) and ("→" in v or "CALL" in v or "PUT" in v):
            msg += f"  {v}\n"

    with RISK_L: pnl = RISK["pnl"]
    remaining = DAILY_TARGET - pnl
    msg += (f"\n<b>Daily:</b> {'+'if pnl>=0 else ''}₹{pnl:,.0f} / "
            f"₹{DAILY_TARGET:,.0f} | Remaining: ₹{remaining:,.0f}\n"
            f"Target captured: {captured}\n"
            f"<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v1.0</i>")

    if not tg(msg):
        return False

    with LAST_L: LAST_SIGNAL["time"] = now_ist()
    with RISK_L: RISK["scalps"] += 1

    signal_id = None
    if DB_AVAILABLE:
        try:
            signal_id = log_alakh_signal(
                direction=direction, score=score,
                threshold=details.get("threshold", 7),
                strike=strike_data["strike"], entry_price=prem,
                sl_price=sl_price, lock_price=lock_price,
                qty=qty, lots=lots, expiry=expiry, dte=dte,
                atm_iv=atm_iv, session=details.get("session", ""),
                entry_type=entry_type, sl_index=sl_index or 0, spot=spot)
        except Exception as e:
            print(f"[DB] Log error: {e}")

    if alert_only:
        with LAST_L:
            LAST_SIGNAL["pending_execute"] = {
                "direction": direction, "strike": strike_data,
                "lots": lots, "qty": qty, "expiry": expiry,
                "spot": spot, "prem": prem, "sl_price": sl_price,
            }
        return True

    with TRADE_L:
        TRADE.update({
            "active": True, "side": direction,
            "strike": strike_data["strike"],
            "instrument_key": strike_data["instrument_key"],
            "entry_premium": prem, "sl_price": sl_price,
            "trail_sl": sl_price, "lock_achieved": False,
            "entry_time": now_ist(), "lots": lots, "qty": qty,
            "expiry": expiry, "entry_idx": spot,
            "candles_since_entry": 0,
            "prev_1min_lows": deque(maxlen=5),
            "prev_1min_highs": deque(maxlen=5),
            "signal_id": signal_id,
        })
    print(f"[Signal] Fired {direction} {strike_data['strike']} @ ₹{prem} | Score {score}/15")
    return True

# ===== TRADE MONITOR =====
def monitor_trade():
    with TRADE_L:
        if not TRADE["active"]: return
        side       = TRADE["side"]
        ik         = TRADE["instrument_key"]
        entry      = TRADE["entry_premium"]
        sl         = TRADE["trail_sl"]
        lock       = TRADE["lock_achieved"]
        qty        = TRADE["qty"]
        entry_time = TRADE["entry_time"]

    if now_ist().weekday() > 4: return
    n = now_ist()
    if n.hour >= 15: return
    if n.hour >= 14 and n.minute >= 55:
        _force_exit("Pre-close 2:55 PM"); return

    expiries = upstox_expiries()
    if not expiries: return
    chain = upstox_option_chain(expiries[0])
    if not chain: return

    spot = upstox_ltp(SENSEX_KEY)
    if not spot: return

    current_prem = None
    for s in chain:
        key = "call_options" if side == "CALL" else "put_options"
        if s.get(key, {}).get("instrument_key") == ik:
            current_prem = s[key]["market_data"].get("ltp")
            break

    if not current_prem: return

    pnl     = round((current_prem - entry) * qty, 0)
    elapsed = int((n - entry_time).total_seconds() / 60)

    if not lock:
        if current_prem <= sl:
            _stop_loss(entry, current_prem, qty, pnl, elapsed); return
        if current_prem >= entry + LOCK_PTS:
            with TRADE_L:
                TRADE["lock_achieved"] = True
                TRADE["trail_sl"]      = entry
            tg(f"🔒 <b>PROFIT LOCKED +₹{LOCK_PTS}/unit</b>\n"
               f"SL → breakeven ₹{entry:.2f}\n"
               f"Premium ₹{current_prem:.2f} | +₹{pnl:,.0f}\n"
               f"Riding with structure trail...")
    else:
        if current_prem < sl:
            with WS_LOCK:
                tbq = WS_STATE.get("atm_tbq", 0)
                tsq = WS_STATE.get("atm_tsq", 0)
            if tbq > tsq * 1.2:
                tg(f"💧 <b>SWEEP DETECTED — HOLDING</b>\n"
                   f"Premium ₹{current_prem:.2f} < trail ₹{sl:.2f}\n"
                   f"Buyers absorbing...")
                return
            _stop_loss(entry, current_prem, qty, pnl, elapsed); return

        if current_prem >= entry + 80:
            _take_profit(entry, current_prem, qty, pnl, elapsed); return

    if elapsed > 0 and elapsed % 15 == 0:
        tg(f"📊 <b>Trade Update | {elapsed}min</b>\n"
           f"{side} {TRADE['strike']:,.0f}\n"
           f"Entry ₹{entry:.2f} → ₹{current_prem:.2f}\n"
           f"Trail SL: ₹{sl:.2f}\n"
           f"P&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f} | Lock: {'✅' if lock else '⏳'}")

def _stop_loss(entry, current, qty, pnl, elapsed):
    loss = abs(pnl)
    tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n"
       f"Entry ₹{entry:.2f} → ₹{current:.2f}\n"
       f"<b>-₹{loss:,.0f}</b> in {elapsed} min\n→ Send /sl to confirm")
    with TRADE_L:
        signal_id = TRADE.get("signal_id")
        TRADE["active"] = False
    if DB_AVAILABLE and signal_id:
        try: update_alakh_signal(signal_id, "LOSS", current, -loss)
        except: pass
    register_sl(loss)

def _take_profit(entry, current, qty, pnl, elapsed):
    tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n"
       f"Entry ₹{entry:.2f} → ₹{current:.2f}\n"
       f"<b>+₹{pnl:,.0f}</b> in {elapsed} min\n→ Send /tradesquared to confirm")
    with TRADE_L:
        signal_id = TRADE.get("signal_id")
        TRADE["active"] = False
    if DB_AVAILABLE and signal_id:
        try: update_alakh_signal(signal_id, "WIN", current, pnl)
        except: pass
    register_profit(pnl)

def _force_exit(reason):
    with TRADE_L:
        if not TRADE["active"]: return
        TRADE["active"] = False
    tg(f"⏰ <b>FORCED EXIT: {reason}</b>\nClose position manually now.")

# ===== SCHEDULED JOBS =====
def job_login():
    if now_ist().weekday() > 4: return
    print("[Login] Auto-login 8:30 AM...")
    if neo_login():
        tg(f"🔑 <b>Kotak Neo Connected</b>\n{now_ist().strftime('%H:%M:%S')} IST")
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
        pivots = compute_pivots(prev["high"], prev["low"], prev["close"])
        spot   = upstox_ltp(SENSEX_KEY)
        if spot:
            gtype, gpct = detect_gap(prev["close"], spot)
            if gtype not in ["FLAT_OPEN", "UNKNOWN"]:
                gap_str = f"Pre-open: {spot:,.2f} ({'⬆️' if gpct>0 else '⬇️'}) ({gpct:+.2f}%)\n"
        pivot_str = (f"Prev: H={prev['high']:,.0f} L={prev['low']:,.0f} C={prev['close']:,.0f}\n"
                     f"R1: {pivots['r1']:,.0f} | Pivot: {pivots['pivot']:,.0f} | S1: {pivots['s1']:,.0f}\n")

    iv_days  = len(load_iv().get("sensex", {}))
    expiries = upstox_expiries()
    dte_str  = ""
    if expiries:
        dte    = compute_dte(expiries[0])
        sweet  = "⭐ SWEET" if 3 <= dte <= 5 else "⚡ GAMMA" if dte <= 2 else "📅"
        dte_str = f"DTE: {dte} {sweet}\n"

    tg(f"☀️ <b>PRE-MARKET — SENSEX</b>\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | v1.0\n\n"
       f"{dte_str}{gap_str}{pivot_str}\n"
       f"Target: ₹{DAILY_TARGET:,.0f} | Lots: {LOTS_NORMAL} (or {LOTS_HIGH_IV} if high IV)\n"
       f"IV history: {iv_days}/15 days\n"
       f"Score engine: ≥{SCORE_NORMAL} normal | ≥{SCORE_HIGH_IV} high IV | ≥{SCORE_POST_TARGET} post-target\n"
       f"9:15→OR | 9:20→Lock | 9:20+→Signals")

def job_or_track():
    if now_ist().weekday() > 4: return
    or_track()

def job_or_lock():
    if now_ist().weekday() > 4: return
    or_lock()

def job_signal_check():
    if now_ist().weekday() > 4: return
    n = now_ist()
    if n < n.replace(hour=9, minute=20): return
    if n > n.replace(hour=15, minute=30): return
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
        cs   = details.get("call_score", 0)
        ps   = details.get("put_score", 0)
        print(f"[Signal] Skip: {skip} | Call:{cs} Put:{ps}")

def job_monitor():
    if now_ist().weekday() > 4: return
    monitor_trade()

def job_pre_close():
    if now_ist().weekday() > 4: return
    with RISK_L: s = RISK["scalps"]; p = RISK["pnl"]
    with TRADE_L: ta = TRADE["active"]; TRADE["active"] = False
    tg(f"⏰ <b>PRE-CLOSE 2:55 PM</b>\n"
       f"Close ALL positions NOW.\n"
       f"Scalps: {s} | P&L: {'+'if p>=0 else ''}₹{p:,.0f}\n"
       f"{'⚠️ ACTIVE TRADE — CLOSE NOW' if ta else ''}")

def job_eod():
    if now_ist().weekday() > 4: return
    with TRADE_L: TRADE["active"] = False
    snap = build_snapshot()
    if "error" not in snap and snap.get("atm_iv", 0) > 0:
        store_eod_iv(snap["atm_iv"])
    with RISK_L: sl = RISK["sl_hits"]; s = RISK["scalps"]; p = RISK["pnl"]
    icon = "✅" if p >= DAILY_TARGET else "⚠️" if p > 0 else "❌"
    tg(f"🌙 <b>EOD — SENSEX T20 | v1.0</b>\n\n"
       f"{icon} <b>P&L: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}</b>\n\n"
       f"Scalps: {s} | SL hits: {sl}/2\n"
       f"IV days: {len(load_iv().get('sensex',{}))}/15\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

def job_health():
    n = now_ist()
    with WS_LOCK: ws_ok = WS_STATE["connected"]
    neo_ok = neo() is not None
    print(f"[Health] {n.strftime('%H:%M')} | WS:{ws_ok} Neo:{neo_ok}")

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
        with RISK_L: RISK["daily_approved"] = True; RISK["alert_only"] = False
        tg("✅ <b>Trading approved for today</b>\nSignal engine active.")

    elif text == "/skip":
        with RISK_L: RISK["daily_approved"] = False; RISK["halted"] = True
        tg("⛔ <b>Trading skipped for today</b>")

    elif text.startswith("/setor"):
        try:
            parts = text.split()
            oh = float(parts[1]); ol = float(parts[2])
            with OR_L:
                OR_S.update({
                    "date": today_str(), "locked": True, "announced": True,
                    "high": oh, "low": ol, "open_price": (oh + ol) / 2,
                    "gap_type": "FLAT", "gap_pct": 0.0
                })
            or_save()
            tg(f"✅ OR manually set\nHigh: {oh:,.2f} | Low: {ol:,.2f}\nRange: {oh-ol:.1f} pts")
        except Exception as e:
            tg(f"❌ Usage: /setor <high> <low>\nError: {e}")

    elif text in ["/signal", "/trade"]:
        tg("⏳ Computing signal...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        direction, score, lots, details, sl_index = check_signal(snap)
        if direction:
            fire_signal(snap, direction, score, lots, details, sl_index)
        else:
            skip  = details.get("skip", "")
            cs    = details.get("call_score", 0)
            ps    = details.get("put_score", 0)
            thresh = details.get("threshold", SCORE_NORMAL)
            tg(f"ℹ️ <b>No Signal</b>\nReason: {skip}\n"
               f"Call: {cs}/15 | Put: {ps}/15\nThreshold: {thresh}/15")

    elif text in ["/snapshot", "/snap"]:
        tg("⏳ Fetching...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        spot = snap["spot"]; atm_data = snap["atm_data"]
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
               f"ST(10,3): {'🟢 BUY' if st=='BUY' else '🔴 SELL' if st else '❓'}"
               f" @ {stv:,.0f} ({snap['st_stable']} candles)\n"
               f"EMA9: {snap.get('ema9','N/A')} | EMA21: {snap.get('ema21','N/A')} | EMA50: {snap.get('ema50','N/A')}\n"
               f"EMA Trend: {'🟢 BULL' if snap.get('ema_trend')=='BUY' else '🔴 BEAR' if snap.get('ema_trend')=='SELL' else '❓'}\n"
               f"3-EMA Aligned: {'✅' if snap.get('ema_aligned') else '❌'}\n"
               f"Nifty ST: {'🟢 BUY' if snap['nifty_st']=='BUY' else '🔴 SELL' if snap['nifty_st'] else '❓'}\n")
        if vwap:
            msg += f"VWAP: {vwap:,.2f} ({'✅ Above' if spot>vwap else '❌ Below'})\n"
        msg += (f"ATM IV: {iv:.1f}% {'⚡ HIGH IV → 3 lots' if high_iv else '✅ Normal → 5 lots'}\n")
        if iv_rank: msg += f"IV Rank: {iv_rank:.0f}/100\n"
        with OR_L:
            if OR_S["locked"]:
                oh, ol = OR_S["high"], OR_S["low"]
                pos = "⬆️ ABOVE" if spot>oh else "⬇️ BELOW" if spot<ol else "🎯 INSIDE"
                msg += f"\nOR: {ol:,.0f}–{oh:,.0f} | {pos}\n"
        if snap["pivots"]:
            p = snap["pivots"]
            msg += f"\nR1: {p['r1']:,.0f} | Pivot: {p['pivot']:,.0f} | S1: {p['s1']:,.0f}\n"
        if atm_data:
            strike = atm_data.get("strike_price", 0)
            msg += f"\nATM {strike:,.0f}:\nCE: ₹{atm_ce.get('ltp',0):.2f} | PE: ₹{atm_pe.get('ltp',0):.2f}\n"
        tg(msg)

    elif text in ["/classify", "/score"]:
        tg("⏳ Computing score...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        direction, score, lots, details, sl_index = check_signal(snap)
        high_iv = is_high_iv_day(snap["atm_iv"], snap["iv_rank"])
        msg = (f"🧠 <b>Score Engine</b>\n{now_ist().strftime('%H:%M:%S')}\n\n"
               f"Call: <b>{details.get('call_score',0)}/15</b> | "
               f"Put: <b>{details.get('put_score',0)}/15</b>\n"
               f"Threshold: {details.get('threshold', SCORE_NORMAL)}/15\n"
               f"Session: {details.get('session','?')}\n"
               f"IV: {snap['atm_iv']:.1f}% {'⚡ HIGH' if high_iv else '✅ Normal'}\n\n"
               f"<b>Signals:</b>\n")
        for k, v in details.items():
            if isinstance(v, str) and "→" in v: msg += f"  {v}\n"
        if direction: msg += f"\n<b>→ {direction} SIGNAL ({score}/15)</b>"
        else: msg += f"\nSkip: {details.get('skip','')}"
        tg(msg)

    elif text in ["/oi", "/chain"]:
        tg("⏳ Fetching chain...")
        snap = build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        spot = snap["spot"]; chain = snap["chain"]
        ce_oi = sorted(chain, key=lambda x: x.get("call_options",{}).get("market_data",{}).get("oi",0), reverse=True)[:5]
        pe_oi = sorted(chain, key=lambda x: x.get("put_options",{}).get("market_data",{}).get("oi",0), reverse=True)[:5]
        total_ce = sum(s.get("call_options",{}).get("market_data",{}).get("oi",0) for s in chain)
        total_pe = sum(s.get("put_options",{}).get("market_data",{}).get("oi",0) for s in chain)
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        msg = f"📊 <b>OI — SENSEX</b>\nSpot: {spot:,.2f} | PCR: {pcr}\n\n<b>🔴 Call OI (resistance):</b>\n"
        for s in ce_oi:
            oi = s.get("call_options",{}).get("market_data",{}).get("oi",0)
            msg += f"  {s['strike_price']:,.0f}: {oi:,.0f}\n"
        msg += "<b>🟢 Put OI (support):</b>\n"
        for s in pe_oi:
            oi = s.get("put_options",{}).get("market_data",{}).get("oi",0)
            msg += f"  {s['strike_price']:,.0f}: {oi:,.0f}\n"
        tg(msg)

    elif text in ["/levels", "/pivots"]:
        tg("⏳ Fetching levels...")
        prev = prev_ohlc()
        if not prev: tg("❌ No prev OHLC"); return
        p = compute_pivots(prev["high"], prev["low"], prev["close"])
        spot = upstox_ltp(SENSEX_KEY)
        def here(v): return " ← HERE" if spot and abs(spot - v) < 30 else ""
        tg(f"📐 <b>Levels — SENSEX</b>\n"
           f"Prev: H={prev['high']:,.0f} L={prev['low']:,.0f} C={prev['close']:,.0f}\n\n"
           f"R2: <b>{p['r2']:,.0f}</b>{here(p['r2'])}\n"
           f"R1: <b>{p['r1']:,.0f}</b>{here(p['r1'])}\n"
           f"<b>Pivot: {p['pivot']:,.0f}</b>{here(p['pivot'])}\n"
           f"S1: <b>{p['s1']:,.0f}</b>{here(p['s1'])}\n"
           f"S2: <b>{p['s2']:,.0f}</b>{here(p['s2'])}\n"
           f"PDH: {p['pdh']:,.0f} | PDL: {p['pdl']:,.0f}\n"
           f"{'Spot: ' + str(round(spot,2)) if spot else ''}")

    elif text in ["/spot", "/ltp"]:
        spot  = upstox_ltp(SENSEX_KEY)
        nifty = upstox_ltp(NIFTY_KEY)
        if spot:
            tg(f"💰 <b>SENSEX:</b> {spot:,.2f}\n💰 <b>NIFTY:</b> {nifty:,.2f}\n{now_ist().strftime('%H:%M:%S')}")
        else:
            tg("❌ LTP fetch failed")

    elif text in ["/or"]:
        with OR_L:
            if not OR_S["locked"]: tg("⏳ OR not locked yet"); return
            oh, ol = OR_S["high"], OR_S["low"]
            gt, gp = OR_S["gap_type"], OR_S["gap_pct"]
        spot = upstox_ltp(SENSEX_KEY)
        pos  = ""
        if spot: pos = "⬆️ ABOVE" if spot>oh else "⬇️ BELOW" if spot<ol else "🎯 INSIDE"
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
            dte   = compute_dte(e)
            sweet = "⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
            msg  += f"  {i+1}. {e} (DTE {dte}) {sweet}\n"
        tg(msg)

    elif text in ["/ivrank", "/iv"]:
        snap = build_snapshot()
        iv   = snap.get("atm_iv", 0)
        ir   = snap.get("iv_rank")
        days = len(load_iv().get("sensex", {}))
        high = is_high_iv_day(iv, ir)
        if ir:
            tg(f"📊 <b>IV Status</b>\nATM IV: {iv:.1f}%\nIV Rank: {ir:.0f}/100\n"
               f"Mode: {'⚡ HIGH IV → 3 lots' if high else '✅ Normal → 5 lots'}")
        else:
            tg(f"📊 <b>IV Status</b>\nATM IV: {iv:.1f}%\n"
               f"IV Rank: Building ({days}/15 days)\n"
               f"Mode: {'⚡ HIGH IV → 3 lots' if high else '✅ Normal → 5 lots'}")

    elif text in ["/sl", "/slhit"]:
        with TRADE_L: TRADE["active"] = False
        register_sl()
        tg("🛑 SL registered.")

    elif text in ["/tradesquared", "/closed"]:
        with TRADE_L: was = TRADE["active"]; TRADE["active"] = False
        tg("✅ Trade cleared." if was else "ℹ️ No active trade.")

    elif text in ["/monitor", "/trade_status"]:
        with TRADE_L:
            if not TRADE["active"]: tg("ℹ️ No active trade."); return
            elapsed = int((now_ist() - TRADE["entry_time"]).total_seconds() / 60)
            tg(f"📊 <b>{TRADE['side']} Trade | {elapsed}min</b>\n"
               f"Strike: {TRADE['strike']:,.0f}\n"
               f"Entry: ₹{TRADE['entry_premium']:.2f}\n"
               f"Trail SL: ₹{TRADE['trail_sl']:.2f}\n"
               f"Lock: {'✅' if TRADE['lock_achieved'] else '⏳ Not yet'}")

    elif text == "/execute":
        with LAST_L: pending = LAST_SIGNAL.get("pending_execute")
        if not pending: tg("ℹ️ No pending signal to execute."); return
        strike_data = pending["strike"]
        with TRADE_L:
            TRADE.update({
                "active": True, "side": pending["direction"],
                "strike": strike_data["strike"],
                "instrument_key": strike_data["instrument_key"],
                "entry_premium": pending["prem"], "sl_price": pending["sl_price"],
                "trail_sl": pending["sl_price"], "lock_achieved": False,
                "entry_time": now_ist(), "lots": pending["lots"], "qty": pending["qty"],
                "expiry": pending["expiry"], "entry_idx": pending["spot"],
                "candles_since_entry": 0,
                "prev_1min_lows": deque(maxlen=5), "prev_1min_highs": deque(maxlen=5),
            })
        with LAST_L: LAST_SIGNAL["pending_execute"] = None
        tg(f"✅ <b>MANUALLY EXECUTED</b>\n"
           f"{pending['direction']} {strike_data['strike']:,.0f}\n"
           f"Entry: ₹{pending['prem']:.2f} | Qty: {pending['qty']}\n"
           f"SL: ₹{pending['sl_price']:.2f}\n"
           f"<i>Trade active — bot monitoring</i>")

    elif text in ["/today", "/status"]:
        with WS_LOCK: ws_ok = WS_STATE["connected"]
        neo_ok = neo() is not None
        spot   = upstox_ltp(SENSEX_KEY)
        with RISK_L:
            sl = RISK["sl_hits"]; h = RISK["halted"]
            ao = RISK.get("alert_only", False)
            s  = RISK["scalps"]; p = RISK["pnl"]
            approved = RISK["daily_approved"]
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
           f"P&L: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
           f"SL: {sl}/2 | {mode_str}\n"
           f"Monitor: {'✅ ACTIVE' if ta else 'None'}\n"
           f"{'🔔 Send /execute after next signal' if ao else ''}")

    elif text in ["/help", "/start"]:
        tg(f"🤖 <b>Mahakaal T20 v1.0</b>\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
           f"Data: Upstox | Exec: Kotak Neo\n\n"
           f"<b>Strategy:</b>\n"
           f"Score ≥{SCORE_NORMAL} → CALL/PUT scalp\n"
           f"{LOTS_NORMAL} lots normal | {LOTS_HIGH_IV} lots high IV\n"
           f"Lock +{LOCK_PTS}pts → structure trail exit\n"
           f"Prime: 9:20-11:30 | Bonus: 11:30-3PM\n\n"
           f"<b>Commands:</b>\n"
           f"/signal — force signal check\n"
           f"/score — full score breakdown\n"
           f"/snapshot — market data\n"
           f"/oi — option chain OI\n"
           f"/spot — live LTP\n"
           f"/or — opening range status\n"
           f"/setor &lt;high&gt; &lt;low&gt; — manually set OR\n"
           f"/levels — pivot levels\n"
           f"/expiries — upcoming expiries\n"
           f"/ivrank — IV status\n"
           f"/monitor — active trade status\n"
           f"/tradesquared — clear active trade\n"
           f"/sl — register SL hit\n"
           f"/execute — manually execute last alert signal\n"
           f"/today — day summary & bot health\n"
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
                    uid    = upd["update_id"]; last_id = uid + 1
                    if uid in processed: continue
                    processed.add(uid)
                    if len(processed) > 100: processed = set(list(processed)[-50:])
                    msg  = upd.get("message", {})
                    text = msg.get("text", "")
                    cid  = msg.get("chat", {}).get("id")
                    if text and cid: handle_cmd(text, cid)
        except Exception as e:
            print(f"[TG] Error: {e}"); time.sleep(5)

# ===== MAIN =====
def main():
    print("=" * 60)
    print(f"MAHAKAAL T20 SCALP BOT v1.0 | Paper={PAPER}")
    print(f"Data: Upstox | Execution: Kotak Neo")
    print(f"Target: ₹{DAILY_TARGET:,.0f} | Lots: {LOTS_NORMAL}/{LOTS_HIGH_IV}")
    print(f"Score: ≥{SCORE_NORMAL} | ≥{SCORE_HIGH_IV} high IV | ≥{SCORE_POST_TARGET} post-target")
    print(f"Started: {now_ist()}")
    print("=" * 60)

    reset_daily()
    or_load()  # Restore OR state from file

    # Ensure alerts table exists
    try:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mahakaal.db")
        conn = sqlite3.connect(db_path, timeout=5)
        conn.execute("""CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, bot TEXT, category TEXT, message TEXT)""")
        conn.commit(); conn.close()
        print("[DB] Initialized: mahakaal.db")
    except Exception as e:
        print(f"[DB] Init error: {e}")

    if DB_AVAILABLE:
        try: init_db()
        except Exception as e: print(f"[DB] init_db error: {e}")

    neo_ok = neo_login()
    start_websocket()

    spot   = upstox_ltp(SENSEX_KEY)
    nifty  = upstox_ltp(NIFTY_KEY)
    iv_days = len(load_iv().get("sensex", {}))
    expiries = upstox_expiries()
    dte_str = ""
    if expiries:
        dte   = compute_dte(expiries[0])
        sweet = "⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
        dte_str = f"DTE: {dte} {sweet}\n"

    dow    = {0:"Monday",1:"Tuesday",2:"Wednesday",3:"Thursday",4:"Friday",5:"Saturday",6:"Sunday"}
    market = "✅ Trading" if now_ist().weekday() < 5 else "🔴 Weekend"

    # Show if OR was restored from file
    with OR_L: or_restored = OR_S["locked"]
    or_note = "\n⚠️ OR state restored from file ✅" if or_restored else ""

    tg(f"🚀 <b>Mahakaal T20 v1.0</b>\n"
       f"{now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | {dow[now_ist().weekday()]} | {market}\n"
       f"Upstox: {'✅' if spot else '❌'} | Neo: {'✅' if neo_ok else '⚠️ /login'}\n\n"
       f"<b>Data:</b> Upstox websocket + REST\n"
       f"<b>Exec:</b> Kotak Neo (zero brokerage)\n\n"
       f"{dte_str}"
       f"Sensex: {spot or 0:,.2f} | Nifty: {nifty or 0:,.2f}\n\n"
       f"<b>Scoring Engine (0-15):</b>\n"
       f"Price action: 6pts | Structure: 4pts\n"
       f"Indicators: 4pts | OI/Flow: 2pts\n\n"
       f"Threshold: ≥{SCORE_NORMAL} | High IV: ≥{SCORE_HIGH_IV} | Post-target: ≥{SCORE_POST_TARGET}\n"
       f"IV history: {iv_days}/15 days\n"
       f"/help for commands{or_note}")

    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(job_login,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=IST), id="login")

    scheduler.add_job(job_premarket,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=IST), id="premarket")

    scheduler.add_job(job_or_track,
        CronTrigger(day_of_week="mon-fri", hour=9, minute="15-19", second="*/30", timezone=IST),
        id="or_track", max_instances=1, coalesce=True)

    scheduler.add_job(job_or_lock,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=20, timezone=IST), id="or_lock")

    # Single signal job (fixed duplicate issue)
    scheduler.add_job(job_signal_check,
        CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*", timezone=IST),
        id="signals", max_instances=1, coalesce=True)

    scheduler.add_job(job_monitor,
        CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*", timezone=IST),
        id="monitor", max_instances=1, coalesce=True)

    scheduler.add_job(job_pre_close,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=55, timezone=IST), id="preclose")

    scheduler.add_job(job_eod,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone=IST), id="eod")

    scheduler.add_job(job_health,
        CronTrigger(minute=0, timezone=IST), id="health")

    print(f"[Scheduler] {len(scheduler.get_jobs())} jobs")
    threading.Thread(target=tg_listener, daemon=True).start()
    print("[Main] Running — bot silent until signals...")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[Main] Stopped")

if __name__ == "__main__":
    main()
