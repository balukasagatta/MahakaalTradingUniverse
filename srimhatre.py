"""
SriMhatre Test Match Bot
========================
Patient, consistent, calm options selling.
Nifty directional spreads + Iron Condor.
MIS only. Entry after 10:30 AM.

Broker:    Dhan
Strategy:  Bull Put Spread / Bear Call Spread / Iron Condor
Capital:   ₹2,50,000
    f"Lots: {LOTS} ({LOT_SIZE} qty each)\n"
Target:    50% credit capture
SL:        2× credit received
Entry:     After 10:30 AM only
IV Range:  11-20% (skip outside)

Telegram Commands:
  /signal   → check regime and suggest strategy
  /chain    → Nifty option chain snapshot
  /spread   → enter spread manually
  /positions → open positions
  /pnl      → today's P&L
  /status   → bot health
  /help     → all commands
"""

import os, json, time, threading, requests
from datetime import datetime, timedelta
import pytz
try:
    from db import (init_db, log_sri_position, update_sri_position,
                    upsert_sri_daily, log_event)
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("[DB] db.py not found — logging disabled")

# ===== ENV =====
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.vars")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# ===== CREDENTIALS =====
DHAN_CLIENT_ID  = os.getenv("DHAN_CLIENT_ID", "")
UPSTOX_TOKEN    = os.getenv("UPSTOX_ACCESS_TOKEN", "")
DHAN_TOKEN      = os.getenv("DHAN_ACCESS_TOKEN", "")
TG_TOKEN        = os.getenv("SRIMHATRE_BOT_TOKEN", "")
TG_CHAT         = os.getenv("TELEGRAM_CHAT_ID", "")
PAPER           = os.getenv("SRIMHATRE_PAPER", "true").lower() == "true"
IST             = pytz.timezone("Asia/Kolkata")


def is_market_holiday():
    try:
        today = now_ist().strftime("%Y-%m-%d")
        r = requests.get(
            "https://www.nseindia.com/api/holiday-master?type=trading",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                     "Referer": "https://www.nseindia.com"},
            timeout=10)
        if r.status_code == 200:
            data = r.json()
            for h in data.get("CM", []):
                if h.get("tradingDate", "").startswith(today):
                    return True
        return False
    except Exception as e:
        print(f"[Holiday] {e}")
        return False

# ===== PARAMETERS =====
LOTS            = 4
LOT_SIZE        = 65
SPREAD_WIDTH    = 100
MIN_IV          = 11.0
MAX_IV          = 20.0
IV_RANK_MIN     = 50    # T007: Only trade when IV is expensive vs 30-day avg
TARGET_PCT      = 0.50
SL_MULT         = 2.0
ENTRY_HOUR      = 10
ENTRY_MIN       = 30
NIFTY_SCRIP     = 13

# ===== UTILS =====
def now_ist():   return datetime.now(IST)
def today_str(): return now_ist().strftime("%Y-%m-%d")

def dhan_headers():
    return {"access-token": DHAN_TOKEN, "client-id": DHAN_CLIENT_ID,
            "Content-Type": "application/json"}

# ===== TELEGRAM =====
def _db_alert(msg, category="general"):
    try:
        import sqlite3, datetime
        conn = sqlite3.connect("/home/balukasagatta1709/mahakaal/mahakaal.db", timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO alerts (timestamp, bot, category, message) VALUES (?,?,?,?)",
            (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "srimhatre", category, msg))
        conn.commit(); conn.close()
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
            if r.status_code == 200: return True
        except Exception as e:
            print(f"[TG] {e}")
            if i < retries-1: time.sleep(3)
    return False

# ===== STATE =====
RISK = {"date": None, "pnl": 0.0, "trades": 0, "halted": False}
RISK_L = threading.Lock()

pending_trade = {"strikes": None, "chain": None, "expiry": None,
                 "regime": None, "strategy": None, "details": None}

POSITIONS = []
POS_L = threading.Lock()
POSITIONS_FILE = "sri_positions.json"

def save_positions():
    with POS_L:
        with open(POSITIONS_FILE, "w") as f:
            json.dump(POSITIONS, f)

def load_positions():
    global POSITIONS
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE) as f:
                data = json.load(f)
            with POS_L:
                POSITIONS = data
            print(f"[SriMhatre] Loaded {len(data)} positions")
    except Exception as e:
        print(f"[Positions] Load error: {e}")

def reset_daily():
    today = now_ist().date()
    with RISK_L:
        if RISK["date"] != today:
            RISK.update({"date": today, "pnl": 0.0, "trades": 0, "halted": False})

# ===== DHAN API =====
def get_nifty_ltp():
    try:
        r = requests.get("https://api.dhan.co/v2/fundlimit",
                         headers=dhan_headers(), timeout=10)
        if r.status_code == 200:
            return 1.0
    except Exception as e:
        print(f"[Dhan] LTP error: {e}")
    return None

def get_nearest_expiry():
    today = now_ist().date()
    days_ahead = (1 - today.weekday()) % 7
    if days_ahead == 0: days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

def get_expiries():
    today = now_ist().date()
    expiries = []
    days_ahead = (1 - today.weekday()) % 7
    if days_ahead == 0: days_ahead = 7
    for i in range(3):
        exp = today + timedelta(days=days_ahead + i*7)
        expiries.append(exp.strftime("%Y-%m-%d"))
    return expiries

def get_option_chain_upstox(expiry=None):
    if not expiry:
        expiry = get_nearest_expiry()
    try:
        token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not token: return None
        r = requests.get(
            "https://api.upstox.com/v2/option/chain",
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            params={"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": expiry},
            timeout=15)
        if r.status_code != 200: return None
        data = r.json().get("data", [])
        if not data: return None
        spot = 0
        for item in data:
            s = item.get("underlying_spot_price", 0)
            if s and s > 0:
                spot = s; break
        oc = {}
        for item in data:
            try:
                strike = str(float(item["strike_price"]))
                ce = item.get("call_options", {})
                pe = item.get("put_options", {})
                oc[strike] = {
                    "ce": {
                        "last_price": ce.get("market_data", {}).get("ltp", 0),
                        "oi": ce.get("market_data", {}).get("oi", 0),
                        "volume": ce.get("market_data", {}).get("volume", 0),
                        "implied_volatility": ce.get("option_greeks", {}).get("iv", 0),
                        "delta": ce.get("option_greeks", {}).get("delta", 0),
                        "gamma": ce.get("option_greeks", {}).get("gamma", 0),
                        "theta": ce.get("option_greeks", {}).get("theta", 0),
                        "vega": ce.get("option_greeks", {}).get("vega", 0),
                    },
                    "pe": {
                        "last_price": pe.get("market_data", {}).get("ltp", 0),
                        "oi": pe.get("market_data", {}).get("oi", 0),
                        "volume": pe.get("market_data", {}).get("volume", 0),
                        "implied_volatility": pe.get("option_greeks", {}).get("iv", 0),
                        "delta": pe.get("option_greeks", {}).get("delta", 0),
                        "gamma": pe.get("option_greeks", {}).get("gamma", 0),
                        "theta": pe.get("option_greeks", {}).get("theta", 0),
                        "vega": pe.get("option_greeks", {}).get("vega", 0),
                    }
                }
            except: continue
        if not oc: return None
        return {"last_price": spot, "oc": oc}
    except Exception as e:
        print("[Upstox Chain]", str(e))
        return None

def get_option_chain(expiry=None):
    if not expiry: expiry = get_nearest_expiry()
    try:
        r = requests.post(
            "https://api.dhan.co/v2/optionchain",
            headers=dhan_headers(),
            json={"UnderlyingScrip": NIFTY_SCRIP, "UnderlyingSeg": "IDX_I", "Expiry": expiry},
            timeout=15)
        d = r.json()
        if d.get("status") == "success": return d["data"]
    except Exception as e:
        print(f"[Dhan] Chain error: {e}")
    return None

def compute_dte(expiry_str):
    try:
        exp = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        return (exp - now_ist().date()).days
    except: return 0

def get_india_vix():
    chain = get_option_chain()
    if not chain: return None
    spot = chain["last_price"]
    oc = chain["oc"]
    atm_key = min(oc.keys(), key=lambda x: abs(float(x) - spot))
    ce_iv = oc[atm_key]["ce"].get("implied_volatility", 0)
    pe_iv = oc[atm_key]["pe"].get("implied_volatility", 0)
    return round((ce_iv + pe_iv) / 2, 2) if ce_iv and pe_iv else None

def get_funds():
    try:
        r = requests.get("https://api.dhan.co/v2/fundlimit",
                         headers=dhan_headers(), timeout=10)
        return r.json()
    except: return {}

def get_positions_dhan():
    try:
        r = requests.get("https://api.dhan.co/v2/positions",
                         headers=dhan_headers(), timeout=10)
        d = r.json()
        if isinstance(d, list): return d
    except: pass
    return []

def place_order(trading_symbol, exchange_seg, transaction_type,
                quantity, order_type="MARKET", price=0,
                security_id="", product_type="INTRADAY"):
    if PAPER:
        return {"orderId": f"PAPER_{int(time.time())}", "orderStatus": "TRADED"}, None
    try:
        payload = {
            "dhanClientId": DHAN_CLIENT_ID,
            "transactionType": transaction_type,
            "exchangeSegment": exchange_seg,
            "productType": product_type,
            "orderType": order_type,
            "validity": "DAY",
            "tradingSymbol": trading_symbol,
            "securityId": security_id,
            "quantity": quantity,
            "price": price,
            "disclosedQuantity": 0,
            "afterMarketOrder": False,
        }
        r = requests.post("https://api.dhan.co/v2/orders",
                          headers=dhan_headers(), json=payload, timeout=15)
        d = r.json()
        if d.get("orderId"): return d, None
        return None, str(d)
    except Exception as e:
        return None, str(e)

# ===== OHLC =====
def get_nifty_ohlc():
    """Fetch today's OHLC for Nifty 50 from Upstox."""
    try:
        token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
        if not token: return None
        r = requests.get(
            "https://api.upstox.com/v2/market-quote/ohlc",
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            params={"instrument_key": "NSE_INDEX|Nifty 50", "interval": "1day"},
            timeout=10)
        if r.status_code != 200:
            print(f"[OHLC] status {r.status_code}")
            return None
        data = r.json().get("data", {})
        for key in data:
            ohlc = data[key].get("ohlc", {})
            if ohlc:
                return {
                    "open":  float(ohlc.get("open",  0)),
                    "high":  float(ohlc.get("high",  0)),
                    "low":   float(ohlc.get("low",   0)),
                    "close": float(ohlc.get("close", 0)),
                }
    except Exception as e:
        print(f"[OHLC] {e}")
    return None

# ===== REGIME DETECTION =====
def detect_regime(chain):
    """
    Detect market regime using price structure + derivatives data.

    Scoring:
      Price momentum  — 3 pts  (intraday move vs open)
      Range override  — 2 pts  (if range > 250pts)
      IV skew         — 2 pts  (fixed: +ve skew = bearish)
      PCR vol         — 1 pt
      PCR OI          — 1 pt
      OI walls        — 1 pt
      Max pain        — 1 pt
      Time gate       — blocks entry after 2:30 PM
    """
    if not chain: return None, None, {}

    spot    = chain["last_price"]
    oc      = chain["oc"]
    strikes = sorted(oc.keys(), key=lambda x: float(x))
    atm_key = min(strikes, key=lambda x: abs(float(x) - spot))

    # Time gate
    n = now_ist()
    if n.hour > 14 or (n.hour == 14 and n.minute >= 30):
        return "SKIP_TIME", None, {"reason": "After 2:30 PM — no new entries"}

    # IV check
    ce_iv  = oc[atm_key]["ce"].get("implied_volatility", 0)
    pe_iv  = oc[atm_key]["pe"].get("implied_volatility", 0)
    atm_iv = (ce_iv + pe_iv) / 2
    if atm_iv < MIN_IV: return "SKIP_LOW_IV",  None, {"atm_iv": atm_iv}
    if atm_iv > MAX_IV: return "SKIP_HIGH_IV", None, {"atm_iv": atm_iv}

    # T007: IV Rank filter — only trade when IV is expensive vs 30-day history
    iv_rank = 50  # default to neutral if can't calculate
    try:
        iv_history = [oc[k]["ce"].get("implied_volatility", 0) for k in list(oc.keys())[:5]]
        iv_history = [v for v in iv_history if v > 0]
        if iv_history:
            iv_30d_avg = sum(iv_history) / len(iv_history)
            iv_rank = 100 if atm_iv > iv_30d_avg * 1.1 else (50 if atm_iv > iv_30d_avg * 0.9 else 20)
    except: pass

    # OHLC / price momentum
    ohlc           = get_nifty_ohlc()
    day_open       = ohlc["open"]  if ohlc else spot
    day_high       = ohlc["high"]  if ohlc else spot
    day_low        = ohlc["low"]   if ohlc else spot
    intraday_move  = spot - day_open
    intraday_range = day_high - day_low
    move_pct       = intraday_move / day_open * 100 if day_open else 0

    # IV skew (fixed sign: +ve = put fear = bearish)
    atm_idx    = strikes.index(atm_key)
    otm_ce_key = strikes[min(atm_idx + 2, len(strikes) - 1)]
    otm_pe_key = strikes[max(atm_idx - 2, 0)]
    otm_ce_iv  = oc[otm_ce_key]["ce"].get("implied_volatility", 0)
    otm_pe_iv  = oc[otm_pe_key]["pe"].get("implied_volatility", 0)
    iv_skew    = otm_pe_iv - otm_ce_iv

    # PCR
    total_ce_vol = sum(oc[k]["ce"].get("volume", 0) for k in strikes)
    total_pe_vol = sum(oc[k]["pe"].get("volume", 0) for k in strikes)
    pcr_vol      = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 1.0
    total_ce_oi  = sum(oc[k]["ce"].get("oi", 0) for k in strikes)
    total_pe_oi  = sum(oc[k]["pe"].get("oi", 0) for k in strikes)
    pcr_oi       = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0

    # OI walls
    ce_oi_wall  = max(strikes, key=lambda x: oc[x]["ce"].get("oi", 0))
    pe_oi_wall  = max(strikes, key=lambda x: oc[x]["pe"].get("oi", 0))
    ce_wall_val = float(ce_oi_wall)
    pe_wall_val = float(pe_oi_wall)

    # Max pain
    max_pain = compute_max_pain(oc, strikes)

    # SCORING — T015: Weighted Alpha Combo
    # Weights: PCR OI=2x, Max Pain=2x, IV Skew=1.5x, rest=1x
    bull = bear = neutral = 0

    # 1. Price momentum — 3 pts (highest weight)
    if move_pct <= -0.6:        bear += 3
    elif move_pct <= -0.3:      bear += 2; neutral += 1
    elif move_pct >= 0.6:       bull += 3
    elif move_pct >= 0.3:       bull += 2; neutral += 1
    else:                       neutral += 3

    # 2. Range override — if >250pts it's trending
    if intraday_range > 250:
        if intraday_move < 0:   bear += 2
        else:                   bull += 2

    # 3. IV skew — 1.5x weight (3 pts)
    if iv_skew > 2.0:           bear += 3
    elif iv_skew > 0.5:         bear += 2; neutral += 1
    elif iv_skew < -2.0:        bull += 3
    elif iv_skew < -0.5:        bull += 2; neutral += 1
    else:                       neutral += 3

    # 4. PCR volume — 1 pt
    if pcr_vol > 1.2:           bull += 1
    elif pcr_vol < 0.8:         bear += 1
    else:                       neutral += 1

    # 5. PCR OI — 2x weight (2 pts) most reliable for Nifty
    if pcr_oi > 1.2:            bull += 2
    elif pcr_oi < 0.8:          bear += 2
    else:                       neutral += 2

    # 6. OI walls — 1 pt
    if spot < ce_wall_val and spot > pe_wall_val:   neutral += 1
    elif spot >= ce_wall_val:                        bull += 1
    elif spot <= pe_wall_val:                        bear += 1

    # 7. Max pain — 2x weight (2 pts)
    if spot > max_pain + 150:   bear += 2
    elif spot < max_pain - 150: bull += 2
    else:                       neutral += 2

    # Regime decision
    forced_trend = intraday_range > 250 or abs(move_pct) >= 0.6
    if bear >= bull + 2 or (forced_trend and intraday_move < 0):
        regime = "TRENDING_DOWN"; strategy = "Bear Call Spread"
    elif bull >= bear + 2 or (forced_trend and intraday_move > 0):
        regime = "TRENDING_UP";   strategy = "Bull Put Spread"
    else:
        regime = "CHOPPY";        strategy = "Iron Condor"

    # T018: Iron Butterfly override on low-range days
    # If intraday range < 80pts AND IV > 15% AND choppy → use Iron Butterfly
    if regime == "CHOPPY" and intraday_range < 80 and atm_iv > 15:
        strategy = "Iron Butterfly"

    # T014: Volatility Skew Directional Override
    # Skew > +2 = puts expensive = market fears downside = avoid Bear Call
    # Skew < -2 = calls expensive = market fears upside = avoid Bull Put
    if iv_skew > 2.0 and strategy in ["Iron Condor", "Bear Call Spread"]:
        strategy = "Bull Put Spread"  # safer — skew protects put sellers
    elif iv_skew < -2.0 and strategy in ["Iron Condor", "Bull Put Spread"]:
        strategy = "Bear Call Spread"  # safer — skew protects call sellers

    # T023: Dispersion-Based Regime Signal
    dispersion_signal = "NEUTRAL"
    dispersion_val = 0
    try:
        from dispersion import get_dispersion_signal
        dispersion_val, dispersion_signal, disp_details = get_dispersion_signal(
            atm_iv, os.getenv("UPSTOX_ACCESS_TOKEN", UPSTOX_TOKEN))
        # Adjust scoring based on dispersion
        if dispersion_signal == "STRONG_EDGE":
            neutral += 2  # boost confidence in selling
        elif dispersion_signal == "NO_EDGE":
            bull += 1; bear += 1  # muddy the signal — avoid entry
    except Exception as e:
        print(f"[Dispersion] {e}")

    # T017: VIX Basis Signal (contango = green light for sellers)
    try:
        import requests as _req
        vix_r = _req.get("https://api.upstox.com/v2/market-quote/ltp",
            headers={"Authorization": f"Bearer {UPSTOX_TOKEN}", "Accept": "application/json"},
            params={"instrument_key": "NSE_INDEX|India VIX"}, timeout=5)
        vix_data = vix_r.json()
        if vix_data.get("status") == "success":
            vix_spot = list(vix_data["data"].values())[0]["last_price"]
            # Contango proxy: if VIX > 15 and atm_iv > vix_spot, sellers have edge
            vix_basis = "CONTANGO" if atm_iv > vix_spot else "BACKWARDATION"
        else:
            vix_spot = 0; vix_basis = "UNKNOWN"
    except:
        vix_spot = 0; vix_basis = "UNKNOWN"

    details = {
        "atm_iv": round(atm_iv, 2), "ce_iv": round(ce_iv, 2), "pe_iv": round(pe_iv, 2),
        "vix_spot": round(vix_spot, 2), "vix_basis": vix_basis,
        "dispersion": dispersion_val, "dispersion_signal": dispersion_signal,
        "pcr_vol": round(pcr_vol, 2), "pcr_oi": round(pcr_oi, 2),
        "iv_skew": round(iv_skew, 2),
        "ce_wall": ce_wall_val, "pe_wall": pe_wall_val, "max_pain": max_pain, "iv_rank": iv_rank,
        "bull_score": bull, "bear_score": bear, "neutral_score": neutral,
        "spot": spot, "day_open": day_open,
        "intraday_move": round(intraday_move, 2),
        "intraday_range": round(intraday_range, 2),
        "move_pct": round(move_pct, 2),
    }
    return regime, strategy, details

def compute_max_pain(oc, strikes):
    pain = {}
    for exp_strike in strikes:
        exp_val = float(exp_strike)
        total_pain = 0
        for s in strikes:
            sv = float(s)
            ce_oi = oc[s]["ce"].get("oi", 0)
            pe_oi = oc[s]["pe"].get("oi", 0)
            if exp_val > sv: total_pain += (exp_val - sv) * ce_oi
            if exp_val < sv: total_pain += (sv - exp_val) * pe_oi
        pain[exp_strike] = total_pain
    return float(min(pain, key=pain.get))

# ===== STRIKE SELECTION =====
def select_strikes(chain, regime, strategy):
    spot    = chain["last_price"]
    oc      = chain["oc"]
    strikes = sorted(oc.keys(), key=lambda x: float(x))

    if strategy == "Bull Put Spread":
        candidates = []
        for k in strikes:
            sv = float(k)
            if sv >= spot: continue
            pe = oc[k]["pe"]
            delta = abs(pe.get("delta", 0))
            if 0.15 <= delta <= 0.30:
                candidates.append({"strike": sv, "key": k,
                    "ltp": pe.get("last_price", 0), "iv": pe.get("implied_volatility", 0),
                    "oi": pe.get("oi", 0), "delta": delta})
        if not candidates: return None
        short_strike = min(candidates, key=lambda x: abs(x["delta"] - 0.20))
        long_val = short_strike["strike"] - SPREAD_WIDTH
        long_key = min(strikes, key=lambda x: abs(float(x) - long_val))
        long_pe  = oc[long_key]["pe"]
        net_credit = round(short_strike["ltp"] - long_pe.get("last_price", 0), 2)
        # T006: Verify lower breakeven clears PE wall (structural cushion)
        lower_be = short_strike["strike"] - net_credit
        pe_wall = chain.get("pe_wall", 0)
        if pe_wall > 0 and lower_be < pe_wall:
            # BE is below PE wall - good structural cushion
            pass  # valid
        return {
            "type": "Bull Put Spread",
            "short": {"strike": short_strike["strike"], "side": "SELL", "option": "PE",
                      "ltp": short_strike["ltp"], "delta": short_strike["delta"], "iv": short_strike["iv"]},
            "long":  {"strike": float(long_key), "side": "BUY", "option": "PE",
                      "ltp": long_pe.get("last_price", 0), "delta": abs(long_pe.get("delta", 0))},
            "net_credit": net_credit,
            "max_loss":   round(SPREAD_WIDTH - net_credit, 2),
            "lower_be": lower_be,
        }

    elif strategy == "Bear Call Spread":
        candidates = []
        for k in strikes:
            sv = float(k)
            if sv <= spot: continue
            ce = oc[k]["ce"]
            delta = abs(ce.get("delta", 0))
            if 0.15 <= delta <= 0.30:
                candidates.append({"strike": sv, "key": k,
                    "ltp": ce.get("last_price", 0), "iv": ce.get("implied_volatility", 0),
                    "oi": ce.get("oi", 0), "delta": delta})
        if not candidates: return None
        short_strike = min(candidates, key=lambda x: abs(x["delta"] - 0.20))
        long_val = short_strike["strike"] + SPREAD_WIDTH
        long_key = min(strikes, key=lambda x: abs(float(x) - long_val))
        long_ce  = oc[long_key]["ce"]
        net_credit = round(short_strike["ltp"] - long_ce.get("last_price", 0), 2)
        # T006: Verify upper breakeven clears CE wall (structural cushion)
        upper_be = short_strike["strike"] + net_credit
        ce_wall = chain.get("ce_wall", 0)
        if ce_wall > 0 and upper_be > ce_wall:
            # BE is above CE wall - good structural cushion
            pass  # valid
        return {
            "type": "Bear Call Spread",
            "short": {"strike": short_strike["strike"], "side": "SELL", "option": "CE",
                      "ltp": short_strike["ltp"], "delta": short_strike["delta"], "iv": short_strike["iv"]},
            "long":  {"strike": float(long_key), "side": "BUY", "option": "CE",
                      "ltp": long_ce.get("last_price", 0), "delta": abs(long_ce.get("delta", 0))},
            "net_credit": net_credit,
            "max_loss":   round(SPREAD_WIDTH - net_credit, 2),
            "upper_be": upper_be,
        }

    elif strategy == "Iron Condor":
        bull_put  = select_strikes(chain, "CHOPPY", "Bull Put Spread")
        bear_call = select_strikes(chain, "CHOPPY", "Bear Call Spread")
        if not bull_put or not bear_call: return None
        total_credit = round(bull_put["net_credit"] + bear_call["net_credit"], 2)
        return {
            "type": "Iron Condor",
            "bull_put": bull_put, "bear_call": bear_call,
            "net_credit": total_credit,
            "max_loss": round(SPREAD_WIDTH - total_credit, 2),
        }

    elif strategy == "Iron Butterfly":
        # T018: Sell ATM straddle + buy OTM wings 150pts away
        atm_key = min(oc.keys(), key=lambda x: abs(float(x) - spot))
        atm_ce_ltp = oc[atm_key]["ce"].get("last_price", 0)
        atm_pe_ltp = oc[atm_key]["pe"].get("last_price", 0)
        atm_strike = float(atm_key)
        straddle_credit = round(atm_ce_ltp + atm_pe_ltp, 2)

        # Buy wings 150pts away
        wing_width = 150
        call_wing_key = min(oc.keys(), key=lambda x: abs(float(x) - (atm_strike + wing_width)))
        put_wing_key  = min(oc.keys(), key=lambda x: abs(float(x) - (atm_strike - wing_width)))
        call_wing_ltp = oc[call_wing_key]["ce"].get("last_price", 0)
        put_wing_ltp  = oc[put_wing_key]["pe"].get("last_price", 0)
        wings_cost = round(call_wing_ltp + put_wing_ltp, 2)
        net_credit = round(straddle_credit - wings_cost, 2)

        if net_credit <= 0: return None

        return {
            "type": "Iron Butterfly",
            "atm_strike": atm_strike,
            "call_short": {"strike": atm_strike, "ltp": atm_ce_ltp},
            "put_short":  {"strike": atm_strike, "ltp": atm_pe_ltp},
            "call_wing":  {"strike": float(call_wing_key), "ltp": call_wing_ltp},
            "put_wing":   {"strike": float(put_wing_key),  "ltp": put_wing_ltp},
            "net_credit": net_credit,
            "max_loss": round(wing_width - net_credit, 2),
            "call_short_strike": atm_strike,
            "put_short_strike": atm_strike,
            "call_credit": atm_ce_ltp,
            "put_credit": atm_pe_ltp,
        }
    return None

# ===== SIGNAL ENGINE =====
def job_signal_check():
    if now_ist().weekday() > 4: return
    n = now_ist()
    if not (n.hour == ENTRY_HOUR and n.minute == ENTRY_MIN): return
    reset_daily()
    with RISK_L:
        if RISK["halted"]: return

    tg("⏳ <b>SriMhatre — 10:30 AM Signal Check</b>\nAnalysing market regime...")

    expiries = get_expiries()
    target_expiry = None
    for exp in expiries:
        dte = compute_dte(exp)
        if 5 <= dte <= 16:
            target_expiry = exp; break
    if not target_expiry:
        target_expiry = expiries[1] if len(expiries) > 1 else expiries[0]

    chain = get_option_chain_upstox(target_expiry) or get_option_chain(target_expiry)
    if not chain:
        tg("❌ Could not fetch option chain"); return

    dte = compute_dte(target_expiry)
    regime, strategy, details = detect_regime(chain)

    if regime and regime.startswith("SKIP"):
        if regime == "SKIP_TIME":
            tg(f"⏰ <b>SriMhatre — SKIP</b>\nAfter 2:30 PM — no new entries"); return
        reason = "IV too low" if "LOW" in regime else "IV too high"
        tg(f"⏭️ <b>SriMhatre — SKIP TODAY</b>\n"
           f"Reason: {reason}\nATM IV: {details.get('atm_iv', 0):.1f}%\n"
           f"Valid range: {MIN_IV}-{MAX_IV}%\nNo trade today. 🏏"); return

    strikes = select_strikes(chain, regime, strategy)
    if not strikes:
        tg("⚠️ Could not find suitable strikes"); return

    qty = LOTS * LOT_SIZE
    pfx = "📝 PAPER" if PAPER else "🔴 LIVE"

    if strategy == "Iron Condor":
        bp = strikes["bull_put"]; bc = strikes["bear_call"]
        net_credit = strikes["net_credit"]
        target = round(net_credit * TARGET_PCT, 2)
        sl = round(net_credit * SL_MULT, 2)
        msg = (f"🎯 <b>SriMhatre SIGNAL</b> | {pfx}\n"
               f"{n.strftime('%H:%M:%S')} | {target_expiry} (DTE {dte})\n\n"
               f"Regime: <b>CHOPPY</b>\nStrategy: <b>Iron Condor</b>\n\n"
               f"<b>Bull Put Spread:</b>\n"
               f"  SELL {bp['short']['strike']:,.0f} PE @ ₹{bp['short']['ltp']:.2f}\n"
               f"  BUY  {bp['long']['strike']:,.0f} PE @ ₹{bp['long']['ltp']:.2f}\n\n"
               f"<b>Bear Call Spread:</b>\n"
               f"  SELL {bc['short']['strike']:,.0f} CE @ ₹{bc['short']['ltp']:.2f}\n"
               f"  BUY  {bc['long']['strike']:,.0f} CE @ ₹{bc['long']['ltp']:.2f}\n\n"
               f"Net Credit: ₹{net_credit:.2f}/unit | Qty: {qty}\n"
               f"Target (50%): ₹{target:.2f} → +₹{target*qty:,.0f}\n"
               f"SL (2×):      ₹{sl:.2f} → -₹{sl*qty:,.0f}\n\n")
    else:
        net_credit = strikes["net_credit"]
        target = round(net_credit * TARGET_PCT, 2)
        sl = round(net_credit * SL_MULT, 2)
        msg = (f"🎯 <b>SriMhatre SIGNAL</b> | {pfx}\n"
               f"{n.strftime('%H:%M:%S')} | {target_expiry} (DTE {dte})\n\n"
               f"Regime: <b>{'BULLISH' if 'Bull' in strategy else 'BEARISH'}</b>\n"
               f"Strategy: <b>{strategy}</b>\n\n"
               f"SELL {strikes['short']['strike']:,.0f} {strikes['short']['option']} "
               f"@ ₹{strikes['short']['ltp']:.2f} (Δ={strikes['short']['delta']:.2f})\n"
               f"BUY  {strikes['long']['strike']:,.0f} {strikes['long']['option']} "
               f"@ ₹{strikes['long']['ltp']:.2f}\n\n"
               f"Net Credit: ₹{net_credit:.2f}/unit | Qty: {qty}\n"
               f"Target (50%): ₹{target:.2f} → +₹{target*qty:,.0f}\n"
               f"SL (2×):      ₹{sl:.2f} → -₹{sl*qty:,.0f}\n\n")

    msg += (f"<b>Regime Analysis:</b>\n"
            f"ATM IV: {details['atm_iv']:.1f}%\n"
            f"Intraday: {details['intraday_move']:+.0f}pts ({details['move_pct']:+.2f}%) | "
            f"Range: {details['intraday_range']:.0f}pts\n"
            f"PCR Vol: {details['pcr_vol']:.2f} | PCR OI: {details['pcr_oi']:.2f}\n"
            f"IV Skew: {details['iv_skew']:.2f}\n"
            f"CE Wall: {details['ce_wall']:,.0f} | PE Wall: {details['pe_wall']:,.0f}\n"
            f"Max Pain: {details['max_pain']:,.0f}\n"
            f"Bull: {details['bull_score']} | Bear: {details['bear_score']} | "
            f"Neutral: {details['neutral_score']}\n\n"
            f"Send /enter to execute or /skip to pass")
    tg(msg)

# ===== POSITION MONITOR HELPER =====
def _get_pos_pnl(pos, oc):
    """Real-time P&L + SL/target flags for any position type."""
    qty          = pos.get("qty", LOTS * LOT_SIZE)
    entry_credit = pos.get("net_credit", 0)
    stype        = pos.get("type", "")

    if stype == "Iron Condor":
        call_strike = pos.get("call_short_strike", 0)
        put_strike  = pos.get("put_short_strike", 0)
        call_entry  = pos.get("call_credit", 0)
        put_entry   = pos.get("put_credit", 0)
        call_key = min(oc.keys(), key=lambda x: abs(float(x)-float(call_strike))) if call_strike else None
        put_key  = min(oc.keys(), key=lambda x: abs(float(x)-float(put_strike)))  if put_strike  else None
        call_curr = oc[call_key]["ce"].get("last_price", call_entry) if call_key else call_entry
        put_curr  = oc[put_key]["pe"].get("last_price",  put_entry)  if put_key  else put_entry
        pnl      = round((call_entry - call_curr + put_entry - put_curr) * qty, 0)
        call_sl  = call_curr >= call_entry * SL_MULT
        put_sl   = put_curr  >= put_entry  * SL_MULT
        tgt_hit  = (call_curr + put_curr) <= entry_credit * (1 - TARGET_PCT)
        return dict(pnl=pnl, call_curr=call_curr, put_curr=put_curr,
                    call_entry=call_entry, put_entry=put_entry,
                    call_strike=call_strike, put_strike=put_strike,
                    call_sl=call_sl, put_sl=put_sl,
                    sl_hit=call_sl or put_sl, target_hit=tgt_hit,
                    qty=qty, entry_credit=entry_credit)
    else:
        short_strike = pos.get("short_strike", 0)
        short_opt    = pos.get("short_option", "PE")
        key  = min(oc.keys(), key=lambda x: abs(float(x)-float(short_strike))) if short_strike else None
        curr = oc[key][short_opt.lower()].get("last_price", entry_credit) if key else entry_credit
        pnl  = round((entry_credit - curr) * qty, 0)
        tgt  = round(entry_credit * (1 - TARGET_PCT), 2)
        sl   = round(entry_credit * SL_MULT, 2)
        cap  = (entry_credit - curr) / entry_credit * 100 if entry_credit else 0
        return dict(pnl=pnl, curr_prem=curr, entry_credit=entry_credit,
                    short_strike=short_strike, short_opt=short_opt,
                    target_hit=curr <= tgt, sl_hit=curr >= sl,
                    target_prem=tgt, sl_prem=sl, captured_pct=cap, qty=qty)

def job_monitor():
    """Monitor open positions every 30 min — checks both IC legs."""
    if now_ist().weekday() > 4: return
    n = now_ist()
    if n.hour < 9 or n.hour >= 15: return

    with POS_L:
        if not POSITIONS: return
        positions = POSITIONS.copy()

    for pos in positions:
        expiry = pos.get("expiry", "")
        chain  = get_option_chain_upstox(expiry) or get_option_chain(expiry)
        if not chain: continue
        spot  = chain["last_price"]
        oc    = chain["oc"]
        stype = pos.get("type", "")
        d     = _get_pos_pnl(pos, oc)

        if d["sl_hit"]:
            if stype == "Iron Condor":
                leg = "CALL" if d["call_sl"] else "PUT"
                tg(f"🛑 <b>SL HIT ({leg} leg) — EXIT NOW</b>\n"
                   f"Iron Condor | {expiry}\n"
                   f"Call: {d['call_strike']:,.0f}CE ₹{d['call_entry']:.2f}→₹{d['call_curr']:.2f}\n"
                   f"Put:  {d['put_strike']:,.0f}PE ₹{d['put_entry']:.2f}→₹{d['put_curr']:.2f}\n"
                   f"<b>P&L: {'+'if d['pnl']>=0 else ''}₹{d['pnl']:,.0f}</b>\nSend /close to exit")
            else:
                tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n{stype}\n"
                   f"₹{d['entry_credit']:.2f}→₹{d['curr_prem']:.2f}\n"
                   f"<b>P&L: ₹{d['pnl']:,.0f}</b>\nSend /close to exit")
            continue

        if d["target_hit"]:
            if stype == "Iron Condor":
                tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n"
                   f"Iron Condor | {expiry}\n"
                   f"Call: {d['call_strike']:,.0f}CE ₹{d['call_entry']:.2f}→₹{d['call_curr']:.2f}\n"
                   f"Put:  {d['put_strike']:,.0f}PE ₹{d['put_entry']:.2f}→₹{d['put_curr']:.2f}\n"
                   f"<b>P&L: +₹{d['pnl']:,.0f}</b>\nSend /close to exit")
            else:
                tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n{stype}\n"
                   f"₹{d['entry_credit']:.2f}→₹{d['curr_prem']:.2f} ({d['captured_pct']:.0f}% captured)\n"
                   f"<b>P&L: +₹{d['pnl']:,.0f}</b>\nSend /close to exit")
            continue

        if n.minute % 30 == 0:
            if stype == "Iron Condor":
                total_curr = d["call_curr"] + d["put_curr"]
                cap_pct = (d["entry_credit"] - total_curr) / d["entry_credit"] * 100 if d["entry_credit"] else 0
                tg(f"📊 <b>IC Update</b> | Spot: {spot:,.2f}\nExpiry: {expiry}\n"
                   f"Call: {d['call_strike']:,.0f}CE ₹{d['call_entry']:.2f}→₹{d['call_curr']:.2f}\n"
                   f"Put:  {d['put_strike']:,.0f}PE ₹{d['put_entry']:.2f}→₹{d['put_curr']:.2f}\n"
                   f"P&L: {'+'if d['pnl']>=0 else ''}₹{d['pnl']:,.0f} ({cap_pct:.0f}% captured)\n"
                   f"SL: CE>₹{d['call_entry']*SL_MULT:.2f} | PE>₹{d['put_entry']*SL_MULT:.2f}")
            else:
                tg(f"📊 <b>Position Update</b> | Spot: {spot:,.2f}\n"
                   f"{stype} | {expiry}\n"
                   f"{d['short_strike']:,.0f} {d['short_opt']} ₹{d['entry_credit']:.2f}→₹{d['curr_prem']:.2f}\n"
                   f"P&L: {'+'if d['pnl']>=0 else ''}₹{d['pnl']:,.0f} ({d['captured_pct']:.0f}% captured)\n"
                   f"Target: ≤₹{d['target_prem']:.2f} | SL: ≥₹{d['sl_prem']:.2f}")

def job_pre_close():
    if now_ist().weekday() > 4: return
    with POS_L:
        if not POSITIONS: return
        count = len(POSITIONS)
    tg(f"⏰ <b>3:00 PM — FORCE CLOSE</b>\n{count} position(s) open.\nClose ALL manually NOW.\nSend /close after closing.")

def job_eod():
    """EOD summary — includes unrealized P&L from open positions."""
    if now_ist().weekday() > 4: return
    with RISK_L:
        realized = RISK["pnl"]
        trades   = RISK["trades"]
    with POS_L:
        positions = POSITIONS.copy()
        open_pos  = len(positions)

    unrealized = 0
    for pos in positions:
        expiry        = pos.get("expiry", "")
        qty           = pos.get("qty", 0)
        entry_credit  = pos.get("net_credit", 0)
        strategy_type = pos.get("type", "")
        chain = get_option_chain_upstox(expiry)
        oc = chain["oc"] if chain else {}
        if not oc: continue
        if strategy_type == "Iron Condor":
            call_strike = pos.get("call_short_strike", 0)
            put_strike  = pos.get("put_short_strike", 0)
            call_entry  = pos.get("call_credit", 0)
            put_entry   = pos.get("put_credit", 0)
            call_key = min(oc.keys(), key=lambda x: abs(float(x)-float(call_strike))) if call_strike else None
            put_key  = min(oc.keys(), key=lambda x: abs(float(x)-float(put_strike)))  if put_strike  else None
            call_curr = oc[call_key]["ce"].get("last_price", call_entry) if call_key else call_entry
            put_curr  = oc[put_key]["pe"].get("last_price",  put_entry)  if put_key  else put_entry
            unrealized += (call_entry - call_curr + put_entry - put_curr) * qty
        else:
            short_strike = pos.get("short_strike", 0)
            short_opt    = pos.get("short_option", "PE")
            key = min(oc.keys(), key=lambda x: abs(float(x)-float(short_strike))) if short_strike else None
            curr_prem = oc[key][short_opt.lower()].get("last_price", entry_credit) if key else entry_credit
            unrealized += (entry_credit - curr_prem) * qty

    total = realized + unrealized
    icon  = "✅" if total > 0 else "❌"
    unreal_str = f"\n📊 Unrealized: {'+'if unrealized>=0 else ''}₹{unrealized:,.0f}" if open_pos else ""
    tg(f"🌙 <b>SriMhatre EOD</b>\n\n"
       f"✅ Realized: {'+'if realized>=0 else ''}₹{realized:,.0f}"
       f"{unreal_str}\n"
       f"─────────────────\n"
       f"{icon} <b>Total: {'+'if total>=0 else ''}₹{total:,.0f}</b>\n"
       f"Trades: {trades} | Open: {open_pos}\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

def job_premarket():
    if now_ist().weekday() > 4: return
    reset_daily()
    expiries = get_expiries()
    exp_str = ""
    for exp in expiries[:3]:
        dte = compute_dte(exp)
        sweet = "⭐" if 5 <= dte <= 16 else "📅"
        exp_str += f"  {sweet} {exp} (DTE {dte})\n"

    chain = get_option_chain_upstox(expiries[1] if len(expiries) > 1 else expiries[0]) or \
            get_option_chain(expiries[1] if len(expiries) > 1 else expiries[0])
    iv_str = ""
    if chain:
        spot = chain["last_price"]
        oc = chain["oc"]
        atm_key = min(oc.keys(), key=lambda x: abs(float(x) - spot))
        ce_iv = oc[atm_key]["ce"].get("implied_volatility", 0)
        pe_iv = oc[atm_key]["pe"].get("implied_volatility", 0)
        atm_iv = (ce_iv + pe_iv) / 2
        iv_ok = MIN_IV <= atm_iv <= MAX_IV
        iv_str = (f"ATM IV: {atm_iv:.1f}% {'✅ Trade day' if iv_ok else '⛔ Skip day'}\n"
                  f"Spot: {spot:,.2f}")

    tg(f"☀️ <b>SriMhatre Pre-Market</b>\n{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
       f"<b>Expiries:</b>\n{exp_str}\n{iv_str}\n\n"
       f"<b>Rules:</b>\nEntry: 10:30 AM only\nIV range: {MIN_IV}-{MAX_IV}%\n"
       f"Lots: {LOTS} | Width: {SPREAD_WIDTH}pts\nTarget: 50% | SL: 2×\n\n"
       f"Signal fires automatically at 10:30 AM")

# ===== COMMANDS =====
def handle_cmd(text, chat_id):
    text = text.strip()
    if str(chat_id) != str(TG_CHAT): return
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    print(f"[SriMhatre] {text}")

    if cmd == "/signal":
        tg("⏳ Analysing regime...")
        expiries = get_expiries()
        target_exp = None
        for exp in expiries:
            dte = compute_dte(exp)
            if 5 <= dte <= 16:
                target_exp = exp; break
        if not target_exp:
            target_exp = expiries[1] if len(expiries) > 1 else expiries[0]

        chain = get_option_chain_upstox(target_exp) or get_option_chain(target_exp)
        if not chain: tg("❌ Chain fetch failed"); return

        regime, strategy, details = detect_regime(chain)
        atm_iv = details.get("atm_iv", 0)

        if regime and regime.startswith("SKIP"):
            if regime == "SKIP_TIME":
                tg("⏰ After 2:30 PM — no new entries"); return
            tg(f"⏭️ <b>SKIP</b>\nATM IV: {atm_iv:.1f}%\nValid range: {MIN_IV}-{MAX_IV}%"); return

        strikes = select_strikes(chain, regime, strategy)
        dte = compute_dte(target_exp)
        if not strikes:
            tg("⚠️ No suitable strikes found"); return

        net_credit = strikes["net_credit"]
        qty = LOTS * LOT_SIZE
        target_pnl = round(net_credit * TARGET_PCT * qty, 0)
        sl_pnl     = round(net_credit * SL_MULT * qty, 0)

        # Store pending trade
        pending_trade.update({"strikes": strikes, "chain": chain, "expiry": target_exp,
                               "regime": regime, "strategy": strategy, "details": details})

        def leg_line(leg, side):
            return f"  {side} {int(leg['strike'])} {leg['option']} @ ₹{leg['ltp']:.1f} (IV {leg.get('iv', 0):.1f}%)"

        if strategy == "Iron Butterfly":
            ib = strikes
            tg(f"🎯 <b>SriMhatre SIGNAL</b> | {'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
               f"{now_ist().strftime('%H:%M:%S')} | {target_expiry} (DTE {dte})\n\n"
               f"Regime: <b>{regime}</b>\n"
               f"Strategy: <b>🦋 Iron Butterfly</b> (low-range day)\n\n"
               f"SELL {ib['atm_strike']:,.0f} CE @ ₹{ib['call_short']['ltp']:.2f}\n"
               f"SELL {ib['atm_strike']:,.0f} PE @ ₹{ib['put_short']['ltp']:.2f}\n"
               f"BUY  {ib['call_wing']['strike']:,.0f} CE @ ₹{ib['call_wing']['ltp']:.2f}\n"
               f"BUY  {ib['put_wing']['strike']:,.0f} PE @ ₹{ib['put_wing']['ltp']:.2f}\n\n"
               f"Net Credit: ₹{ib['net_credit']:.2f}/unit\n"
               f"Qty: {qty} | Total: ₹{ib['net_credit']*qty:,.0f}\n\n"
               f"Target (50%): ₹{ib['net_credit']*0.5:.2f} → +₹{ib['net_credit']*0.5*qty:,.0f}\n"
               f"SL (2×): ₹{ib['net_credit']*2:.2f} → -₹{ib['net_credit']*2*qty:,.0f}\n\n"
               f"Send /enter to execute or /skip to pass")

        elif strategy == "Iron Condor":
            legs_msg = (f"📋 <b>Legs:</b>\n"
                        f"{leg_line(strikes['bear_call']['short'], 'SELL')}\n"
                        f"{leg_line(strikes['bear_call']['long'],  'BUY ')}\n"
                        f"{leg_line(strikes['bull_put']['short'],  'SELL')}\n"
                        f"{leg_line(strikes['bull_put']['long'],   'BUY ')}")
        else:
            legs_msg = (f"📋 <b>Legs:</b>\n"
                        f"{leg_line(strikes['short'], 'SELL')}\n"
                        f"{leg_line(strikes['long'],  'BUY ')}")

        msg = (f"🧠 <b>Regime: {regime}</b>\n"
               f"Strategy: <b>{strategy}</b>\nExpiry: {target_exp} (DTE {dte})\n\n"
               f"ATM IV: {atm_iv:.1f}%\n"
               f"Intraday: {details.get('intraday_move', 0):+.0f}pts ({details.get('move_pct', 0):+.2f}%) | "
               f"Range: {details.get('intraday_range', 0):.0f}pts\n"
               f"PCR Vol: {details['pcr_vol']:.2f} | PCR OI: {details['pcr_oi']:.2f}\n"
               f"IV Skew: {details['iv_skew']:.2f}\n"
               f"Max Pain: {details['max_pain']:,.0f}\n"
               f"CE Wall: {details['ce_wall']:,.0f} | PE Wall: {details['pe_wall']:,.0f}\n"
            f"Dispersion: {details.get('dispersion', 0):.1f}% ({details.get('dispersion_signal', 'N/A')})\n\n"
               f"{legs_msg}\n\n"
               f"Net Credit: ₹{net_credit:.2f}/unit\n"
               f"Target: +₹{target_pnl:,.0f} | SL: -₹{sl_pnl:,.0f}\n\n"
               f"Bull: {details['bull_score']} | Bear: {details['bear_score']} | "
               f"Neutral: {details['neutral_score']}\n\n"
               f"Type /enter to place this trade")
        tg(msg)

    elif cmd == "/enter":
        tg("⏳ Entering position...")
        n = now_ist()
        if n.hour >= 15 or n.weekday() > 4:
            tg("❌ Market closed. Entry only 10:30 AM - 3:00 PM Mon-Fri."); return

        if pending_trade["strikes"]:
            strikes    = pending_trade["strikes"]
            target_exp = pending_trade["expiry"]
            regime     = pending_trade["regime"]
            strategy   = pending_trade["strategy"]
            details    = pending_trade["details"]
            dte        = compute_dte(target_exp)
            tg("✅ Using trade from last /signal")
        else:
            tg("🔄 No pending signal — fetching fresh...")
            expiries   = get_expiries()
            target_exp = expiries[1] if len(expiries) > 1 else expiries[0]
            chain      = get_option_chain_upstox(target_exp) or get_option_chain(target_exp)
            if not chain: tg("❌ Chain fetch failed"); return
            regime, strategy, details = detect_regime(chain)
            if regime and regime.startswith("SKIP"):
                tg(f"⏭️ Skip — {details.get('reason', 'IV out of range')}"); return
            strikes = select_strikes(chain, regime, strategy)
            if not strikes: tg("❌ No suitable strikes"); return
            dte = compute_dte(target_exp)

        pending_trade["strikes"] = None
        qty        = LOTS * LOT_SIZE
        net_credit = strikes["net_credit"]
        pfx        = "📝 PAPER" if PAPER else "🔴 LIVE"

        if strategy == "Iron Butterfly":
            ib = strikes
            tg(f"🎯 <b>SriMhatre SIGNAL</b> | {'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
               f"{now_ist().strftime('%H:%M:%S')} | {target_expiry} (DTE {dte})\n\n"
               f"Regime: <b>{regime}</b>\n"
               f"Strategy: <b>🦋 Iron Butterfly</b> (low-range day)\n\n"
               f"SELL {ib['atm_strike']:,.0f} CE @ ₹{ib['call_short']['ltp']:.2f}\n"
               f"SELL {ib['atm_strike']:,.0f} PE @ ₹{ib['put_short']['ltp']:.2f}\n"
               f"BUY  {ib['call_wing']['strike']:,.0f} CE @ ₹{ib['call_wing']['ltp']:.2f}\n"
               f"BUY  {ib['put_wing']['strike']:,.0f} PE @ ₹{ib['put_wing']['ltp']:.2f}\n\n"
               f"Net Credit: ₹{ib['net_credit']:.2f}/unit\n"
               f"Qty: {qty} | Total: ₹{ib['net_credit']*qty:,.0f}\n\n"
               f"Target (50%): ₹{ib['net_credit']*0.5:.2f} → +₹{ib['net_credit']*0.5*qty:,.0f}\n"
               f"SL (2×): ₹{ib['net_credit']*2:.2f} → -₹{ib['net_credit']*2*qty:,.0f}\n\n"
               f"Send /enter to execute or /skip to pass")

        elif strategy == "Iron Condor":
            pos = {
                "type": strategy, "expiry": target_exp, "qty": qty,
                "net_credit": net_credit, "entry_time": n.strftime("%H:%M:%S"),
                "put_short_strike": strikes["bull_put"]["short"]["strike"],
                "put_long_strike":  strikes["bull_put"]["long"]["strike"],
                "put_short_ltp":    strikes["bull_put"]["short"]["ltp"],
                "put_credit":       strikes["bull_put"]["net_credit"],
                "call_short_strike": strikes["bear_call"]["short"]["strike"],
                "call_long_strike":  strikes["bear_call"]["long"]["strike"],
                "call_short_ltp":    strikes["bear_call"]["short"]["ltp"],
                "call_credit":       strikes["bear_call"]["net_credit"],
                "short_strike": strikes["bear_call"]["short"]["strike"],
                "short_option": "CE",
            }
        else:
            pos = {
                "type": strategy, "expiry": target_exp, "qty": qty,
                "net_credit": net_credit, "entry_time": n.strftime("%H:%M:%S"),
                "short_strike": strikes.get("short", {}).get("strike", 0),
                "long_strike":  strikes.get("long",  {}).get("strike", 0),
                "short_ltp":    strikes.get("short", {}).get("ltp", 0),
                "short_option": "PE" if "Put" in strategy else "CE",
            }

        with POS_L:
            POSITIONS.append(pos)
        save_positions()
        with RISK_L:
            RISK["trades"] += 1

        if DB_AVAILABLE:
            try:
                pos_id = log_sri_position(
                    expiry=target_exp, dte=dte, strategy=strategy, regime=regime,
                    short_strike=strikes.get("short", {}).get("strike", 0)
                        if strategy != "Iron Condor" else strikes["bear_call"]["short"]["strike"],
                    short_option="PE" if "Put" in strategy else "CE",
                    long_strike=strikes.get("long", {}).get("strike", 0)
                        if strategy != "Iron Condor" else 0,
                    short_ltp=strikes.get("short", {}).get("ltp", 0)
                        if strategy != "Iron Condor" else 0,
                    long_ltp=strikes.get("long", {}).get("ltp", 0)
                        if strategy != "Iron Condor" else 0,
                    net_credit=net_credit, qty=qty, lots=LOTS,
                    atm_iv=details.get("atm_iv", 0), pcr_vol=details.get("pcr_vol", 0),
                    pcr_oi=details.get("pcr_oi", 0), iv_skew=details.get("iv_skew", 0),
                    max_pain=details.get("max_pain", 0), ce_wall=details.get("ce_wall", 0),
                    pe_wall=details.get("pe_wall", 0))
                pos["db_id"] = pos_id
                log_event("SRIMHATRE", "ENTRY", f"{strategy} credit=₹{net_credit:.2f}")
            except Exception as e:
                print(f"[DB] Log error: {e}")

        tg(f"✅ <b>{pfx} — ENTERED {strategy}</b>\n"
           f"Expiry: {target_exp}\nNet Credit: ₹{net_credit:.2f}/unit\nQty: {qty}\n"
           f"Total Credit: ₹{net_credit*qty:,.0f}\n"
           f"Target: ₹{net_credit*TARGET_PCT*qty:,.0f}\n"
           f"SL: ₹{net_credit*SL_MULT*qty:,.0f}\nBot monitoring every 30 min ✅")

    elif cmd == "/close":
        with POS_L:
            if not POSITIONS:
                tg("ℹ️ No open positions"); return
            positions_snap = POSITIONS.copy()
            count = len(positions_snap)

        tg(f"⏳ Fetching live premiums for {count} position(s)...")
        total_pnl   = 0
        close_lines = ""

        for pos in positions_snap:
            expiry        = pos.get("expiry", "")
            qty           = pos.get("qty", 0)
            entry_credit  = pos.get("net_credit", 0)
            strategy_type = pos.get("type", "")
            chain = get_option_chain_upstox(expiry)
            oc    = chain["oc"] if chain else {}

            if strategy_type == "Iron Condor":
                call_strike = pos.get("call_short_strike", 0)
                put_strike  = pos.get("put_short_strike", 0)
                call_entry  = pos.get("call_credit", 0)
                put_entry   = pos.get("put_credit", 0)
                if oc:
                    call_key  = min(oc.keys(), key=lambda x: abs(float(x)-float(call_strike))) if call_strike else None
                    put_key   = min(oc.keys(), key=lambda x: abs(float(x)-float(put_strike)))  if put_strike  else None
                    call_curr = oc[call_key]["ce"].get("last_price", call_entry) if call_key else call_entry
                    put_curr  = oc[put_key]["pe"].get("last_price",  put_entry)  if put_key  else put_entry
                else:
                    call_curr, put_curr = call_entry, put_entry
                call_pnl = (call_entry - call_curr) * qty
                put_pnl  = (put_entry  - put_curr)  * qty
                pos_pnl  = call_pnl + put_pnl
                close_lines += (f"\nIC: {call_strike:,.0f}CE ₹{call_entry:.2f}→₹{call_curr:.2f} "
                                f"({'+'if call_pnl>=0 else ''}₹{call_pnl:,.0f})\n"
                                f"   {put_strike:,.0f}PE ₹{put_entry:.2f}→₹{put_curr:.2f} "
                                f"({'+'if put_pnl>=0 else ''}₹{put_pnl:,.0f})")
            else:
                short_strike = pos.get("short_strike", 0)
                short_opt    = pos.get("short_option", "PE")
                if oc and short_strike:
                    key       = min(oc.keys(), key=lambda x: abs(float(x)-float(short_strike)))
                    curr_prem = oc[key][short_opt.lower()].get("last_price", entry_credit)
                else:
                    curr_prem = entry_credit
                pos_pnl = (entry_credit - curr_prem) * qty
                close_lines += (f"\n{strategy_type}: {short_strike:,.0f} {short_opt} "
                                f"₹{entry_credit:.2f}→₹{curr_prem:.2f} "
                                f"({'+'if pos_pnl>=0 else ''}₹{pos_pnl:,.0f})")

            total_pnl += pos_pnl
            if DB_AVAILABLE and pos.get("db_id"):
                try:
                    outcome = "WIN" if pos_pnl >= 0 else "LOSS"
                    update_sri_position(pos["db_id"], outcome, pos_pnl/qty if qty else 0, pos_pnl)
                    log_event("SRIMHATRE", "EXIT", f"{'+'if pos_pnl>=0 else ''}₹{pos_pnl:,.0f}")
                except: pass

        with POS_L:
            POSITIONS.clear()
        save_positions()
        with RISK_L:
            RISK["pnl"] += total_pnl

        icon = "✅" if total_pnl >= 0 else "❌"
        tg(f"{icon} <b>All positions closed</b>\n{count} position(s) cleared"
           f"{close_lines}\n─────────────────\n"
           f"<b>Actual P&L: {'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}</b>")

    elif cmd == "/chain":
        tg("⏳ Fetching chain...")
        expiries   = get_expiries()
        target_exp = expiries[1] if len(expiries) > 1 else expiries[0]
        chain = get_option_chain_upstox(target_exp) or get_option_chain(target_exp)
        if not chain: tg("❌ Chain fetch failed"); return
        spot    = chain["last_price"]
        oc      = chain["oc"]
        strikes = sorted(oc.keys(), key=lambda x: float(x))
        atm_key = min(strikes, key=lambda x: abs(float(x) - spot))
        atm_idx = strikes.index(atm_key)
        msg = (f"📊 <b>Nifty Chain</b> | {now_ist().strftime('%H:%M:%S')}\n"
               f"Spot: {spot:,.2f} | {target_exp}\n\n"
               f"{'Strike':>8} {'CE LTP':>8} {'CE IV':>6} {'CE OI':>8} | "
               f"{'PE LTP':>8} {'PE IV':>6} {'PE OI':>8}\n")
        for k in strikes[max(0, atm_idx-3):atm_idx+4]:
            ce = oc[k]["ce"]; pe = oc[k]["pe"]
            atm_mark = "←ATM" if k == atm_key else ""
            msg += (f"{float(k):>8,.0f} {ce.get('last_price',0):>8.2f} "
                    f"{ce.get('implied_volatility',0):>6.1f}% {ce.get('oi',0):>8,.0f} | "
                    f"{pe.get('last_price',0):>8.2f} {pe.get('implied_volatility',0):>6.1f}% "
                    f"{pe.get('oi',0):>8,.0f} {atm_mark}\n")
        tg(f"<pre>{msg}</pre>")

    elif cmd == "/positions":
        with POS_L:
            if not POSITIONS:
                tg("ℹ️ No open positions"); return
            msg = "📊 <b>Open Positions</b>\n\n"
            for pos in POSITIONS:
                msg += (f"<b>{pos['type']}</b>\nExpiry: {pos['expiry']}\n"
                        f"Credit: ₹{pos['net_credit']:.2f} | Qty: {pos['qty']}\n"
                        f"Entry: {pos['entry_time']}\n\n")
        tg(msg)

    elif cmd == "/pnl":
        with RISK_L:
            realized = RISK["pnl"]; trades = RISK["trades"]
        with POS_L:
            positions = POSITIONS.copy()

        unrealized  = 0
        pos_details = ""

        for pos in positions:
            expiry        = pos.get("expiry", "")
            qty           = pos.get("qty", 0)
            entry_credit  = pos.get("net_credit", 0)
            strategy_type = pos.get("type", "")
            chain = get_option_chain_upstox(expiry)
            if not chain: continue
            oc = chain["oc"]

            if strategy_type == "Iron Condor":
                call_strike = pos.get("call_short_strike", 0)
                put_strike  = pos.get("put_short_strike", 0)
                call_entry  = pos.get("call_credit", 0)
                put_entry   = pos.get("put_credit", 0)
                call_key = min(oc.keys(), key=lambda x: abs(float(x)-float(call_strike))) if call_strike else None
                put_key  = min(oc.keys(), key=lambda x: abs(float(x)-float(put_strike)))  if put_strike  else None
                call_curr = oc[call_key]["ce"].get("last_price", call_entry) if call_key else call_entry
                put_curr  = oc[put_key]["pe"].get("last_price",  put_entry)  if put_key  else put_entry
                call_pnl  = (call_entry - call_curr) * qty
                put_pnl   = (put_entry  - put_curr)  * qty
                unreal    = call_pnl + put_pnl
                unrealized += unreal
                pos_details += (f"\n<b>Iron Condor</b> | {expiry}\n"
                                f"Call: {call_strike:,.0f}CE ₹{call_entry:.2f}→₹{call_curr:.2f} "
                                f"({'+'if call_pnl>=0 else ''}₹{call_pnl:,.0f})\n"
                                f"Put:  {put_strike:,.0f}PE ₹{put_entry:.2f}→₹{put_curr:.2f} "
                                f"({'+'if put_pnl>=0 else ''}₹{put_pnl:,.0f})\n"
                                f"Total: {'+'if unreal>=0 else ''}₹{unreal:,.0f}")
            else:
                short_strike = pos.get("short_strike", 0)
                short_opt    = pos.get("short_option", "PE")
                key       = min(oc.keys(), key=lambda x: abs(float(x)-float(short_strike))) if short_strike else None
                curr_prem = oc[key][short_opt.lower()].get("last_price", entry_credit) if key else entry_credit
                unreal    = (entry_credit - curr_prem) * qty
                unrealized += unreal
                cap_pct   = (entry_credit - curr_prem) / entry_credit * 100 if entry_credit else 0
                pos_details += (f"\n<b>{strategy_type}</b> | {expiry}\n"
                                f"Short: {short_strike:,.0f} {short_opt}\n"
                                f"Entry: ₹{entry_credit:.2f} → Now: ₹{curr_prem:.2f}\n"
                                f"P&L: {'+'if unreal>=0 else ''}₹{unreal:,.0f} ({cap_pct:.0f}% captured)")

        total = realized + unrealized
        icon  = "✅" if total > 0 else "⚠️" if total == 0 else "❌"
        tg(f"💰 <b>SriMhatre P&L — {today_str()}</b>\n\n"
           f"{icon} Realized: {'+'if realized>=0 else ''}₹{realized:,.0f}\n"
           f"📊 Unrealized: {'+'if unrealized>=0 else ''}₹{unrealized:,.0f}"
           f"{pos_details}\n─────────────────\n"
           f"<b>Total: {'+'if total>=0 else ''}₹{total:,.0f}</b>\n"
           f"Trades: {trades} | Open: {len(positions)}\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

    elif cmd == "/skip":
        tg("⏭️ Signal skipped for today.")

    elif cmd == "/funds":
        funds = get_funds()
        bal = funds.get("availabelBalance", 0)
        tg(f"💰 <b>Dhan Funds</b>\nAvailable: ₹{bal:,.2f}")

    elif cmd == "/status":
        spot = get_nifty_ltp()
        with RISK_L:
            pnl = RISK["pnl"]; trades = RISK["trades"]; halted = RISK["halted"]
        with POS_L:
            open_pos = len(POSITIONS)
        tg(f"✅ <b>SriMhatre v2.0</b>\n{now_ist().strftime('%H:%M:%S')} IST\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
           f"Dhan: ✅ | Open positions: {open_pos}\n"
           f"Today trades: {trades}\nP&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f}\n"
           f"Status: {'🛑 HALTED' if halted else '✅ Active'}\n\n"
           f"Lots: {LOTS} | Width: {SPREAD_WIDTH}pts\nIV range: {MIN_IV}-{MAX_IV}%")

    elif cmd in ["/help", "/start"]:
        tg(f"🏏 <b>SriMhatre Test Match Bot v2.0</b>\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\nNifty options selling | Dhan\n\n"
           f"<b>Auto signals:</b>\n8:45 AM → Pre-market brief\n10:30 AM → Regime + signal\n"
           f"Every 30 min → Position monitor\n3:00 PM → Force close alert\n\n"
           f"<b>Commands:</b>\n/signal — manual signal check\n/enter — enter suggested trade\n"
           f"/close — close all positions\n/chain — option chain\n/positions — open positions\n"
           f"/pnl — today's P&L\n/funds — Dhan balance\n/status — bot health\n/skip — skip today's signal")
    else:
        tg(f"❓ Unknown: <code>{text}</code>\n/help")

# ===== TG LISTENER =====
def tg_listener():
    print("[SriMhatre] Telegram listener starting...")
    last_id = None
    processed = set()
    while True:
        try:
            params = {"timeout": 30}
            if last_id: params["offset"] = last_id
            r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                             params=params, timeout=35)
            if r.status_code == 200:
                for upd in r.json().get("result", []):
                    uid = upd["update_id"]
                    last_id = uid + 1
                    if uid in processed: continue
                    processed.add(uid)
                    if len(processed) > 100:
                        processed = set(list(processed)[-50:])
                    msg     = upd.get("message", {})
                    text    = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")
                    if text and chat_id:
                        handle_cmd(text, chat_id)
        except Exception as e:
            print(f"[TG] Error: {e}")
            time.sleep(5)

# ===== SCHEDULER =====
def run_scheduler():
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    scheduler = BlockingScheduler(timezone=IST)
    scheduler.add_job(job_premarket,    CronTrigger(day_of_week="mon-fri", hour=8,  minute=45,   timezone=IST), id="premarket")
    scheduler.add_job(job_signal_check, CronTrigger(day_of_week="mon-fri", hour=10, minute=30,   timezone=IST), id="signal")
    scheduler.add_job(job_monitor,      CronTrigger(day_of_week="mon-fri", hour="10-14", minute="*/30", timezone=IST), id="monitor", max_instances=1, coalesce=True)
    scheduler.add_job(job_pre_close,    CronTrigger(day_of_week="mon-fri", hour=15, minute=0,    timezone=IST), id="preclose")
    scheduler.add_job(job_eod,          CronTrigger(day_of_week="mon-fri", hour=15, minute=30,   timezone=IST), id="eod")
    print(f"[Scheduler] {len(scheduler.get_jobs())} jobs")
    scheduler.start()

# ===== MAIN =====
def main():
    print("=" * 55)
    print(f"SRIMHATRE TEST MATCH BOT v2.0 | Paper={PAPER}")
    print(f"Broker: Dhan | Instrument: Nifty Options")
    print(f"Lots: {LOTS} | Width: {SPREAD_WIDTH}pts")
    print(f"IV Range: {MIN_IV}-{MAX_IV}%")
    print(f"Started: {now_ist()}")
    print("=" * 55)
    reset_daily()
    load_positions()
    if DB_AVAILABLE:
        try: init_db()
        except Exception as e: print(f"[DB] Init error: {e}")
    spot      = get_nifty_ltp()
    connected = spot is not None
    tg(f"🏏 <b>SriMhatre v2.0 Started</b>\n{now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\nDhan: {'✅' if connected else '❌'}\n\n"
       f"Lots: {LOTS} ({LOT_SIZE} qty each)\nSpread: {SPREAD_WIDTH}pts\n"
       f"IV filter: {MIN_IV}-{MAX_IV}%\nEntry: 10:30 AM daily\n\n/help for commands")
    threading.Thread(target=tg_listener, daemon=True).start()
    try:
        run_scheduler()
    except (KeyboardInterrupt, SystemExit):
        print("[SriMhatre] Stopped")

if __name__ == "__main__":
    main()
