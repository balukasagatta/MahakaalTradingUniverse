"""
Mahakaal Options Sniper v4.1 — Kotak Neo Edition
==================================================
GCP VM | Zero Brokerage | Scalp-First

Auth flow (daily, automated at 8:30 AM):
  TOTP login → MPIN validate → session ready

Underlyings:
  Mon(0) → Sensex 3 DTE | Tue(1) → Sensex 2 DTE
  Wed(2) → Nifty  6 DTE | Thu(3) → Nifty  5 DTE SWEET SPOT
  Fri(4) → Nifty  4 DTE

Setup on GCP:
  pip install neo_api_client apscheduler pytz pyotp requests python-dotenv
  Set env.vars with credentials below
  python3 main.py
"""

import os
import re
import json
import math
import time
import threading
import requests
import pyotp
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from neo_api_client import NeoAPI

# ===== LOAD ENV =====
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.vars")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ===== CREDENTIALS =====
KOTAK_CONSUMER_KEY  = os.getenv("KOTAK_CONSUMER_KEY", "").strip()
KOTAK_MOBILE        = os.getenv("KOTAK_MOBILE", "").strip()
KOTAK_MPIN          = os.getenv("KOTAK_MPIN", "").strip()
KOTAK_UCC           = os.getenv("KOTAK_UCC", "").strip()
KOTAK_TOTP_SECRET   = os.getenv("KOTAK_TOTP_SECRET", "").strip()
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
PAPER_TRADE_MODE    = os.getenv("PAPER_TRADE_MODE", "true").lower() == "true"

IST           = pytz.timezone("Asia/Kolkata")
IV_STORE_FILE = "iv_history.json"

# ===== KOTAK NEO CLIENT =====
neo_client = None
neo_lock   = threading.Lock()

def init_neo_client():
    """Initialize Kotak Neo client with TOTP auto-login."""
    global neo_client
    try:
        client = NeoAPI(
            environment='prod',
            access_token=None,
            neo_fin_key=None,
            consumer_key=KOTAK_CONSUMER_KEY
        )
        # Generate TOTP
        totp = pyotp.TOTP(KOTAK_TOTP_SECRET).now()
        # Step 1: TOTP login
        resp1 = client.totp_login(
            mobile_number=KOTAK_MOBILE,
            ucc=KOTAK_UCC,
            totp=totp
        )
        print(f"[Neo] TOTP login: {resp1}")
        # Step 2: MPIN validate → generates trade token
        resp2 = client.totp_validate(mpin=KOTAK_MPIN)
        print(f"[Neo] MPIN validate: {resp2}")
        with neo_lock:
            neo_client = client
        print("[Neo] ✅ Client ready")
        return True
    except Exception as e:
        print(f"[Neo] Init failed: {e}")
        return False

def get_client():
    with neo_lock:
        return neo_client


print(f"[{datetime.now(IST)}] Mahakaal v4.1 Kotak Neo starting...")
print(f"[{datetime.now(IST)}] Paper={PAPER_TRADE_MODE}")


# ===== STATS =====
def percentile(data, p):
    if not data or len(data) < 2: return None
    s = sorted(data); k = (len(s)-1)*(p/100.0)
    f = math.floor(k); c = math.ceil(k)
    return s[int(k)] if f==c else s[f]*(c-k)+s[c]*(k-f)

def mean(data): return sum(data)/len(data) if data else 0


# ===== HOLIDAYS =====
NSE_HOLIDAYS = {"2026-05-01","2026-06-17","2026-08-27","2026-10-02",
                "2026-10-14","2026-11-05","2026-11-06","2026-12-25"}
def is_holiday(): return datetime.now(IST).strftime("%Y-%m-%d") in NSE_HOLIDAYS
def is_weekend(): return datetime.now(IST).weekday() > 4
def is_trading_day(): return not is_weekend() and not is_holiday()


# ===== UNDERLYINGS =====
# Kotak Neo exchange segments: nse_cm, nse_fo, bse_cm, bse_fo
UNDERLYINGS = {
    "nifty": {
        "name": "NIFTY",
        "index_token": "Nifty 50",      # for LTP quotes
        "index_segment": "nse_cm",
        "fo_segment": "nse_fo",
        "symbol_prefix": "NIFTY",       # for search_scrip
        "expiry_weekday": 1,
        "lot_size": 75,
        "strike_gap": 50,
    },
    "sensex": {
        "name": "SENSEX",
        "index_token": "Sensex",        # for LTP quotes
        "index_segment": "bse_cm",
        "fo_segment": "bse_fo",
        "symbol_prefix": "SENSEX",
        "expiry_weekday": 3,
        "lot_size": 20,
        "strike_gap": 100,
    },
}

DAY_MAP = {0:"sensex", 1:"sensex", 2:"nifty", 3:"nifty", 4:"nifty"}

def get_underlying():
    k = DAY_MAP.get(datetime.now(IST).weekday(), "nifty")
    return k, UNDERLYINGS[k]

def is_expiry(key=None):
    if key is None: key,_ = get_underlying()
    return datetime.now(IST).weekday() == UNDERLYINGS[key]["expiry_weekday"]

def oi_thresholds(key):
    return (50_000,200_000,500_000) if key=="sensex" else (500_000,2_000_000,5_000_000)


# ===== PARAMETERS =====
ER_CHOP, ER_TREND           = 0.25, 0.50
COMPRESSION, TREND_THRESH   = 0.60, 1.75
PCR_EXT_BEAR, PCR_EXT_BULL  = 0.68, 1.45
PCR_BEARISH, PCR_BULLISH    = 0.80, 1.35
IV_RANK_BUY_MAX             = 75
DTE_BUY_MIN                 = 2
DTE_SPREAD_MIN              = 2
DTE_IC_MIN                  = 3
SELL_LOTS_N, SELL_LOTS_S    = 6, 8
BUY_LOTS_N,  BUY_LOTS_S     = 2, 4
FLOW_THRESH                 = 45
BUY_WIN, BUY_SL, BUY_MINS  = 0.35, 0.50, 45
MAX_SELL, MAX_BUY           = 2, 5
DEDUP_SECS                  = 120
GAP_OVR_MINS                = 20
DAILY_TARGET                = 5_000
MAX_RISK                    = 3_500


def day_limits():
    return (1, 65) if datetime.now(IST).weekday() == 2 else (MAX_SELL, 50)

def lots_for_target(credit_per_lot, lot_size, capture=0.40):
    if credit_per_lot <= 0: return 1
    needed = math.ceil((DAILY_TARGET/capture)/(credit_per_lot*lot_size))
    max_by_risk = int(MAX_RISK/(credit_per_lot*1.5*lot_size))
    return max(1, min(needed, max_by_risk, 20))

def dte_target(net, dte, underlying_key):
    if dte>=6:   cap,note=0.20,"DTE 6 — need 200+ pt move."
    elif dte==5: cap,note=0.30,"DTE 5 — some move needed."
    elif dte==4: cap,note=0.40,"DTE 4 — 100pt move helps."
    elif dte==3: cap,note=0.50,"DTE 3 — sweet spot."
    elif dte==2: cap,note=0.45,f"Need ~{UNDERLYINGS[underlying_key]['strike_gap']}pt move."
    else:        cap,note=0.35,"1 DTE — directional bet."
    return {"capture_pct":int(cap*100),"target_per_lot":round(net*cap,2),"note":note}


# ===== STATE =====
OR   = {"date":None,"high":None,"low":None,"ticks":0,"locked":False,
         "announced":False,"gap_type":"UNKNOWN","gap_pct":0.0,
         "gap_fixed":False,"trend_day":False}
OR_L = threading.Lock()

REG  = {"dir":None,"score":None,"spot":None,"time":None,"pcr":None,
         "top_ce":None,"top_pe":None,"reversal":False,"ce_mult":0,"pe_mult":0}
REG_L = threading.Lock()

RISK = {"date":None,"sl":0,"fired":0,"halted":False,
         "sell":0,"buy":0,"pnl":0}
RISK_L = threading.Lock()

LAST = {"time":None,"mode":None}
LAST_L = threading.Lock()

TRADE = {
    "active":False,"is_buy":False,"strategy":None,
    "short_strike":None,"short_side":None,
    "entry_short":None,"net_credit":None,
    "tgt_pct":None,"sl_mult":None,
    "entry_time":None,"lots":None,"qty":None,
    "key":None,"expiry":None,
    "buy_strike":None,"buy_side":None,
    "buy_entry":None,"buy_tgt":None,"buy_sl":None,
    "l1_trig":None,"l1_sl":None,"l2_trig":None,"l2_sl":None,
    "l1_done":False,"l2_done":False
}
TRADE_L = threading.Lock()
API_L   = threading.Lock()

# OI history (Neo doesn't provide prev OI directly)
OI_HIST = {}
OI_L    = threading.Lock()

ADAPT = {}
def adapt(key):
    if key not in ADAPT:
        ADAPT[key] = {"er":[],"pcr":[],"flow":[],"scores":[]}
    return ADAPT[key]


# ===== TELEGRAM =====
def tg(msg, retries=3):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for i in range(retries):
        try:
            r = requests.post(url,
                json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},
                timeout=10)
            if r.status_code == 200: return True
        except Exception as e:
            print(f"[TG] Attempt {i+1}: {e}")
            if i < retries-1: time.sleep(5)
    return False


# ===== KOTAK NEO DATA LAYER =====
def neo_get_spot(key):
    """Get index LTP."""
    u = UNDERLYINGS[key]
    client = get_client()
    if not client: return {"ok":False,"err":"No client"}
    try:
        tokens = [{"instrument_token": u["index_token"],
                   "exchange_segment": u["index_segment"]}]
        resp = client.quotes(instrument_tokens=tokens, quote_type="ltp", isIndex=True)
        # Response: {'data': [{'ltp': '24350.50', ...}]}
        data = resp.get("data") or resp.get("stk") or []
        if data:
            ltp = float(data[0].get("ltp") or data[0].get("iv") or 0)
            if ltp > 0: return {"ok":True,"ltp":ltp}
        return {"ok":False,"err":str(resp)[:150]}
    except Exception as e:
        return {"ok":False,"err":str(e)}

def neo_get_expiries(key):
    """Get sorted upcoming expiry dates."""
    u = UNDERLYINGS[key]
    client = get_client()
    if not client: return {"ok":False,"err":"No client"}
    try:
        # Search for futures to get expiry list
        resp = client.search_scrip(
            exchange_segment=u["fo_segment"],
            symbol=u["symbol_prefix"],
            expiry="",
            option_type="",
            strike_price=""
        )
        data = resp if isinstance(resp, list) else (resp.get("data") or [])
        today = datetime.now(IST).date()
        expiries = set()
        for item in data:
            exp = item.get("exd") or item.get("expiry_date") or item.get("expiry") or ""
            if not exp: continue
            # Parse DD-Mon-YYYY or YYYY-MM-DD
            for fmt in ["%d-%b-%Y","%Y-%m-%d","%d/%m/%Y"]:
                try:
                    d = datetime.strptime(exp, fmt).date()
                    if d >= today: expiries.add(d.strftime("%Y-%m-%d")); break
                except: continue
        sorted_exp = sorted(expiries)
        return {"ok":True,"expiries":sorted_exp} if sorted_exp else {"ok":False,"err":"No expiries"}
    except Exception as e:
        return {"ok":False,"err":str(e)}

def neo_get_option_chain(key, expiry_str):
    """
    Build option chain by fetching all CE and PE strikes for given expiry.
    Returns dict matching standard analyze_chain input format.
    """
    u = UNDERLYINGS[key]
    client = get_client()
    if not client: return {"ok":False,"err":"No client"}
    try:
        # Get spot first
        spot_r = neo_get_spot(key)
        if not spot_r["ok"]: return {"ok":False,"err":"Spot failed"}
        spot = spot_r["ltp"]

        # Search all options for this expiry
        # Format expiry as DD-Mon-YYYY for Kotak search
        exp_date = datetime.strptime(expiry_str, "%Y-%m-%d")
        exp_fmt  = exp_date.strftime("%d-%b-%Y").upper()

        ce_resp = client.search_scrip(
            exchange_segment=u["fo_segment"],
            symbol=u["symbol_prefix"],
            expiry=exp_fmt,
            option_type="CE",
            strike_price=""
        )
        pe_resp = client.search_scrip(
            exchange_segment=u["fo_segment"],
            symbol=u["symbol_prefix"],
            expiry=exp_fmt,
            option_type="PE",
            strike_price=""
        )

        ce_list = ce_resp if isinstance(ce_resp, list) else (ce_resp.get("data") or [])
        pe_list = pe_resp if isinstance(pe_resp, list) else (pe_resp.get("data") or [])

        if not ce_list and not pe_list:
            return {"ok":False,"err":"No option data found"}

        # Build token → strike map
        ce_map = {}  # strike → scrip info
        pe_map = {}

        for item in ce_list:
            try:
                strike = float(item.get("strprc") or item.get("strike_price") or 0)
                token  = item.get("tok") or item.get("token") or ""
                tsym   = item.get("tsym") or item.get("trading_symbol") or ""
                if strike > 0 and token:
                    ce_map[strike] = {"token":token,"tsym":tsym}
            except: continue

        for item in pe_list:
            try:
                strike = float(item.get("strprc") or item.get("strike_price") or 0)
                token  = item.get("tok") or item.get("token") or ""
                tsym   = item.get("tsym") or item.get("trading_symbol") or ""
                if strike > 0 and token:
                    pe_map[strike] = {"token":token,"tsym":tsym}
            except: continue

        # Get quotes for ATM ± 20 strikes
        atr_est = spot * 0.02  # ~2% range
        all_strikes = sorted(set(list(ce_map.keys()) + list(pe_map.keys())))
        near_strikes = [s for s in all_strikes if abs(s-spot) <= atr_est*15]
        if not near_strikes: near_strikes = all_strikes

        # Fetch quotes in batches of 20
        def fetch_quotes(tokens_info):
            """tokens_info: list of {instrument_token, exchange_segment}"""
            if not tokens_info: return {}
            try:
                resp = client.quotes(instrument_tokens=tokens_info, quote_type="all", isIndex=False)
                data = resp.get("data") or resp.get("stk") or []
                result = {}
                for item in data:
                    tk = item.get("tk") or item.get("instrument_token") or ""
                    result[tk] = item
                return result
            except Exception as e:
                print(f"[Neo] Quotes error: {e}")
                return {}

        # Batch CE + PE tokens
        batch = []
        for s in near_strikes:
            if s in ce_map:
                batch.append({"instrument_token": ce_map[s]["token"],
                              "exchange_segment": u["fo_segment"]})
            if s in pe_map:
                batch.append({"instrument_token": pe_map[s]["token"],
                              "exchange_segment": u["fo_segment"]})

        # Fetch in chunks of 30
        quote_data = {}
        for i in range(0, len(batch), 30):
            chunk = batch[i:i+30]
            quote_data.update(fetch_quotes(chunk))
            if i + 30 < len(batch): time.sleep(0.5)

        # Build strikes list
        with OI_L: prev_oi = OI_HIST.get(key, {})
        strikes = []
        for s in near_strikes:
            ce_info = ce_map.get(s, {}); pe_info = pe_map.get(s, {})
            ce_q    = quote_data.get(ce_info.get("token",""), {})
            pe_q    = quote_data.get(pe_info.get("token",""), {})

            def safe_float(d, k, default=0):
                try: return float(d.get(k) or default)
                except: return float(default)

            ce_oi  = safe_float(ce_q,"oi")
            pe_oi  = safe_float(pe_q,"oi")
            ce_ltp = safe_float(ce_q,"lp") or safe_float(ce_q,"ltp")
            pe_ltp = safe_float(pe_q,"lp") or safe_float(pe_q,"ltp")

            if ce_ltp == 0 and pe_ltp == 0: continue

            strikes.append({
                "strike":s,
                "ce_ltp":ce_ltp,"ce_oi":ce_oi,
                "ce_oi_change":ce_oi - prev_oi.get(f"{s}_ce",ce_oi),
                "ce_volume":safe_float(ce_q,"v"),
                "ce_iv":safe_float(ce_q,"iv"),
                "ce_delta":0,"ce_theta":0,"ce_gamma":0,"ce_vega":0,
                "ce_top_bid":safe_float(ce_q,"bp1"),"ce_top_ask":safe_float(ce_q,"sp1"),
                "ce_bid_qty":safe_float(ce_q,"bq1"),"ce_ask_qty":safe_float(ce_q,"sq1"),
                "ce_tsym":ce_info.get("tsym",""),
                "pe_ltp":pe_ltp,"pe_oi":pe_oi,
                "pe_oi_change":pe_oi - prev_oi.get(f"{s}_pe",pe_oi),
                "pe_volume":safe_float(pe_q,"v"),
                "pe_iv":safe_float(pe_q,"iv"),
                "pe_delta":0,"pe_theta":0,"pe_gamma":0,"pe_vega":0,
                "pe_top_bid":safe_float(pe_q,"bp1"),"pe_top_ask":safe_float(pe_q,"sp1"),
                "pe_bid_qty":safe_float(pe_q,"bq1"),"pe_ask_qty":safe_float(pe_q,"sq1"),
                "pe_tsym":pe_info.get("tsym",""),
            })

        # Update OI history
        new_oi = {}
        for s in strikes:
            new_oi[f"{s['strike']}_ce"] = s["ce_oi"]
            new_oi[f"{s['strike']}_pe"] = s["pe_oi"]
        with OI_L: OI_HIST[key] = new_oi

        return {"ok":True,"spot":spot,"strikes":strikes,"expiry":expiry_str}
    except Exception as e:
        return {"ok":False,"err":str(e)}

def neo_get_candles(key, mins=5, days=5):
    """Get historical OHLCV candles for index."""
    u = UNDERLYINGS[key]
    client = get_client()
    if not client: return {"ok":False}
    try:
        # Get index token from scrip master
        now   = datetime.now(IST)
        start = now - timedelta(days=days)
        resp  = client.historical(
            instrument_token=u["index_token"],
            exchange_segment=u["index_segment"],
            to_date=now.strftime("%d-%m-%Y %H:%M:%S"),
            from_date=start.strftime("%d-%m-%Y %H:%M:%S"),
            interval=str(mins),
            isIndex=True,
            isDepth=False
        )
        data = resp.get("data") or []
        o,h,l,c,v,ts=[],[],[],[],[],[]
        for bar in data:
            try:
                o.append(float(bar.get("open") or bar.get("into") or 0))
                h.append(float(bar.get("high") or bar.get("inth") or 0))
                l.append(float(bar.get("low")  or bar.get("intl") or 0))
                c.append(float(bar.get("close") or bar.get("intc") or 0))
                v.append(int(float(bar.get("volume") or bar.get("intv") or 0)))
                t_str = bar.get("datetime") or bar.get("time") or ""
                for fmt in ["%Y-%m-%d %H:%M:%S","%d-%m-%Y %H:%M:%S"]:
                    try:
                        dt = datetime.strptime(t_str, fmt).replace(tzinfo=IST)
                        ts.append(int(dt.timestamp())); break
                    except: continue
                else: ts.append(0)
            except: continue
        return {"ok":True,"open":o,"high":h,"low":l,"close":c,"volume":v,"timestamp":ts}
    except Exception as e:
        print(f"[Neo] Candles error: {e}")
        return {"ok":False,"err":str(e)}


# ===== ANALYSIS HELPERS =====
def analyze_chain(chain_data):
    """Convert Neo chain data to standard analysis format."""
    spot     = chain_data.get("spot")
    strikes  = chain_data.get("strikes", [])
    if not spot or not strikes: return None

    atm = min(strikes, key=lambda x: abs(x["strike"]-spot))
    top_ce = sorted(strikes, key=lambda x: x["ce_oi"], reverse=True)[:5]
    top_pe = sorted(strikes, key=lambda x: x["pe_oi"], reverse=True)[:5]
    tce    = sum(s["ce_oi"] for s in strikes)
    tpe    = sum(s["pe_oi"] for s in strikes)
    pcr    = round(tpe/tce, 2) if tce > 0 else 0

    # Rename keys to standard format
    std_strikes = []
    for s in strikes:
        std_strikes.append({
            **s,
            "ce_top_bid": s.get("ce_top_bid",0),
            "ce_top_ask": s.get("ce_top_ask",0),
            "pe_top_bid": s.get("pe_top_bid",0),
            "pe_top_ask": s.get("pe_top_ask",0),
        })

    return {
        "spot":spot,"atm":atm,"top_ce_oi":top_ce,"top_pe_oi":top_pe,
        "pcr":pcr,"max_pain":max_pain(std_strikes),
        "total_ce_oi":tce,"total_pe_oi":tpe,"all_strikes":std_strikes,
    }

def max_pain(strikes):
    best=None; bp=float("inf")
    for s in strikes:
        t=s["strike"]
        pain=sum((t-k["strike"])*k["ce_oi"] if t>k["strike"] else
                 (k["strike"]-t)*k["pe_oi"] if t<k["strike"] else 0 for k in strikes)
        if pain<bp: bp=pain; best=t
    return best

def compute_atr(h,l,c,period=14):
    if len(h)<period+1: return None
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(h))]
    return round(sum(trs[-period:])/period,2) if len(trs)>=period else None

def compute_pivots(ph,pl,pc):
    p=(ph+pl+pc)/3
    return {"pivot":round(p,2),"r1":round(2*p-pl,2),"r2":round(p+(ph-pl),2),
            "s1":round(2*p-ph,2),"s2":round(p-(ph-pl),2)}

def ts_to_dt(ts):
    v=int(ts); return datetime.fromtimestamp(v/1000 if v>1e10 else v, IST)

def prev_ohlc_from_candles(candles):
    if not candles.get("ok"): return None
    today=datetime.now(IST).date(); by={}
    for i,ts in enumerate(candles.get("timestamp",[])):
        try: d=ts_to_dt(ts).date()
        except: continue
        if d>=today: continue
        if d not in by: by[d]={"h":[],"l":[],"c":[]}
        by[d]["h"].append(candles["high"][i])
        by[d]["l"].append(candles["low"][i])
        by[d]["c"].append(candles["close"][i])
    if not by: return None
    last=max(by.keys())
    return {"high":max(by[last]["h"]),"low":min(by[last]["l"]),"close":by[last]["c"][-1]}

def compute_dte(expiry_str):
    try: return (datetime.strptime(expiry_str,"%Y-%m-%d").date()-datetime.now(IST).date()).days
    except: return 5


# ===== IV RANK =====
def load_iv():
    try:
        if os.path.exists(IV_STORE_FILE):
            with open(IV_STORE_FILE) as f: return json.load(f)
    except: pass
    return {}

def save_iv(history):
    try:
        with open(IV_STORE_FILE,"w") as f: json.dump(history,f)
    except: pass

def store_eod_iv(key, atm_iv):
    history=load_iv(); today=datetime.now(IST).strftime("%Y-%m-%d")
    if key not in history: history[key]={}
    history[key][today]=round(atm_iv,2)
    sorted_dates=sorted(history[key].keys())
    if len(sorted_dates)>90:
        for old in sorted_dates[:-90]: del history[key][old]
    save_iv(history)

def compute_iv_rank(key, current_iv):
    iv_data=load_iv().get(key,{})
    if len(iv_data)<15: return None
    values=list(iv_data.values()); hi,lo=max(values),min(values)
    return 50 if hi==lo else round((current_iv-lo)/(hi-lo)*100,1)


# ===== PRICE STRUCTURE =====
def get_today_candles(candles, from_min=30):
    today=datetime.now(IST).date()
    cutoff=datetime.now(IST).replace(hour=9,minute=from_min,second=0,microsecond=0)
    o,h,l,c,v=[],[],[],[],[]
    for i,ts in enumerate(candles.get("timestamp",[])):
        try: ct=ts_to_dt(ts)
        except: continue
        if ct.date()!=today or ct<cutoff: continue
        if i<len(candles.get("close",[])):
            o.append(candles["open"][i]); h.append(candles["high"][i])
            l.append(candles["low"][i]);  c.append(candles["close"][i])
            v.append(candles["volume"][i])
    return o,h,l,c,v

def compute_vwap(candles):
    today=datetime.now(IST).date(); pv=vol=0
    for i,ts in enumerate(candles.get("timestamp",[])):
        try: ct=ts_to_dt(ts)
        except: continue
        if ct.date()!=today: continue
        if i>=len(candles.get("close",[])): continue
        hi=candles["high"][i]; lo=candles["low"][i]
        cl=candles["close"][i]; vi=candles["volume"][i]
        pv+=(hi+lo+cl)/3*vi; vol+=vi
    return round(pv/vol,2) if vol>0 else None

def compute_ema(closes, period):
    if len(closes)<period: return None
    k=2/(period+1); ema=sum(closes[:period])/period
    for price in closes[period:]: ema=price*k+ema*(1-k)
    return round(ema,2)

def compute_swing(h,l):
    if len(h)<6: return "SIDEWAYS"
    fh,sh=max(h[:3]),max(h[3:]); fl,sl=min(l[:3]),min(l[3:])
    if sh>fh and sl>fl: return "UPTREND"
    if sh<fh and sl<fl: return "DOWNTREND"
    return "SIDEWAYS"

def compute_er(candles, period=10):
    _,_,_,c,_=get_today_candles(candles,30)
    if len(c)<6: return 0.3,f"Early ({len(c)} candles)"
    if len(c)<period+1: period=len(c)-1
    recent=c[-period:]
    net=abs(recent[-1]-recent[0])
    total=sum(abs(recent[i]-recent[i-1]) for i in range(1,len(recent)))
    if total==0: return 0.0,"No movement"
    er=round(net/total,3)
    return er,("CHOPPY" if er<ER_CHOP else "TRENDING" if er>ER_TREND else "NORMAL")

def compute_price_score(candles, spot, pivots, or_high, or_low, atr, is_trend=False):
    score=0; bias=0.0; reasons=[]
    atr_val=atr if atr else 25
    _,h,l,c,_=get_today_candles(candles,30)
    vwap=compute_vwap(candles)
    if vwap and spot:
        diff=spot-vwap; dist=abs(diff)/spot*100
        pts=6 if dist>0.3 else 3; bd=1.0 if dist>0.3 else 0.4
        if diff>0: score+=pts; bias+=bd; reasons.append(f"Above VWAP {vwap:,.0f} (+{diff:.0f})")
        else:      score+=pts; bias-=bd; reasons.append(f"Below VWAP {vwap:,.0f} ({diff:.0f})")
    else: reasons.append("VWAP building")
    ema9=compute_ema(c,9) if len(c)>=9 else None
    ema20=compute_ema(c,20) if len(c)>=20 else None
    if ema9 and ema20 and spot:
        if spot>ema9>ema20:   score+=10; bias+=1.5; reasons.append(f"Strong bullish: Spot>{ema9:.0f}>EMA20({ema20:.0f})")
        elif spot<ema9<ema20: score+=10; bias-=1.5; reasons.append(f"Strong bearish: Spot<{ema9:.0f}<EMA20({ema20:.0f})")
        elif spot>ema9:       score+=6;  bias+=0.8; reasons.append(f"Mild bullish: Spot>9EMA({ema9:.0f})")
        elif spot<ema9:       score+=6;  bias-=0.8; reasons.append(f"Mild bearish: Spot<9EMA({ema9:.0f})")
        else:                 score+=2;             reasons.append("Spot at 9EMA")
    elif ema9 and spot:
        if spot>ema9: score+=5; bias+=0.7; reasons.append(f"Above 9EMA({ema9:.0f})")
        else:         score+=5; bias-=0.7; reasons.append(f"Below 9EMA({ema9:.0f})")
    else: reasons.append("EMA insufficient")
    swing=compute_swing(h,l)
    if swing=="UPTREND":     score+=7; bias+=1.0; reasons.append("Swing: UPTREND")
    elif swing=="DOWNTREND": score+=7; bias-=1.0; reasons.append("Swing: DOWNTREND")
    else:                    score+=2;            reasons.append("Swing: SIDEWAYS")
    if or_high and or_low:
        if or_low<=spot<=or_high:
            if not is_trend: score+=4; reasons.append("Inside OR")
            else: reasons.append("Inside OR (trend day)")
        elif spot>or_high: score+=3; bias+=0.6; reasons.append(f"Above OR +{spot-or_high:.0f}")
        else:              score+=3; bias-=0.6; reasons.append(f"Below OR -{or_low-spot:.0f}")
    if pivots:
        diff=spot-pivots["pivot"]
        if abs(diff)<atr_val*0.3:
            if not is_trend: score+=3; reasons.append("Near pivot")
        elif spot>pivots["r1"]: bias+=0.5; reasons.append(f"Above R1 {pivots['r1']:,.0f}")
        elif spot<pivots["s1"]: bias-=0.5; reasons.append(f"Below S1 {pivots['s1']:,.0f}")
    if   bias>=2.0:  sdir="STRONG BULLISH"
    elif bias>=0.8:  sdir="MILD BULLISH"
    elif bias<=-2.0: sdir="STRONG BEARISH"
    elif bias<=-0.8: sdir="MILD BEARISH"
    else:            sdir="NEUTRAL"
    return min(score,35),bias,reasons,vwap,ema9,ema20,swing,sdir


# ===== GAP =====
def detect_gap(prev_close, spot):
    if not prev_close or not spot: return "UNKNOWN",0.0
    pct=(spot-prev_close)/prev_close*100
    if pct>1.75:  return "EXTREME_GAP_UP",  round(pct,2)
    if pct>1.00:  return "LARGE_GAP_UP",    round(pct,2)
    if pct>0.55:  return "GAP_UP",          round(pct,2)
    if pct<-1.75: return "EXTREME_GAP_DOWN",round(pct,2)
    if pct<-1.00: return "LARGE_GAP_DOWN",  round(pct,2)
    if pct<-0.55: return "GAP_DOWN",        round(pct,2)
    return "FLAT_OPEN",round(pct,2)

def gap_override_active(gap_type):
    if gap_type in ["FLAT_OPEN","UNKNOWN"]: return False
    now=datetime.now(IST)
    mo=now.replace(hour=9,minute=30,second=0,microsecond=0)
    return (now-mo).total_seconds()/60<=GAP_OVR_MINS

def gap_wait(gap_type):
    now=datetime.now(IST)
    mo=now.replace(hour=9,minute=30,second=0,microsecond=0)
    mins=max(0,(now-mo).total_seconds()/60)
    if "EXTREME" in gap_type: wait=30
    elif "LARGE" in gap_type: wait=15
    elif gap_type in ["GAP_UP","GAP_DOWN"]: wait=0
    else: return False,0
    return (True,int(wait-mins)) if mins<wait else (False,0)


# ===== VOL FILTER =====
def vol_filter(candles, atr):
    if not candles or not candles.get("ok") or not atr:
        return True,"No data",{},False
    _,th,tl,_,_=get_today_candles(candles,30)
    if len(th)<3: return True,"Pre-market",{},False
    rng=max(th)-min(tl); ratio=round(rng/atr,2)
    metrics={"today_range":round(rng,2),"atr":round(atr,2),"ratio":ratio}
    if ratio<COMPRESSION: return False,f"COMPRESSION R/ATR={ratio}",metrics,False
    if ratio>TREND_THRESH: return False,f"TREND R/ATR={ratio}",metrics,True
    return True,f"PASS R/ATR={ratio}",metrics,False


# ===== OI FLOW =====
def compute_oi_flow(analysis, atr, key="nifty"):
    if not analysis: return 0,[],False
    spot=analysis["spot"]; strikes=analysis["all_strikes"]
    atr_val=atr if atr else 25
    _,oi_sig,oi_strong=oi_thresholds(key)
    flow=0; signals=[]; reversal=False
    with REG_L:
        prev_pcr=REG.get("pcr"); prev_ce=REG.get("top_ce")
        prev_pe=REG.get("top_pe"); prev_ce_m=REG.get("ce_mult",0)
        prev_pe_m=REG.get("pe_mult",0)

    atm_s=[s for s in strikes if abs(s["strike"]-spot)<=atr_val*1.5]
    ce_b=ce_u=pe_b=pe_u=0
    for s in atm_s:
        cc=s["ce_oi_change"]; pc=s["pe_oi_change"]
        if cc>oi_sig:    ce_b+=cc
        elif cc<-oi_sig: ce_u+=abs(cc)
        if pc>oi_sig:    pe_b+=pc
        elif pc<-oi_sig: pe_u+=abs(pc)

    if ce_u>ce_b and ce_u>oi_sig:
        pts=min(35,int(ce_u/oi_sig)*8); flow+=pts
        signals.append(f"Call covering ({ce_u:,.0f}) +{pts}")
        if ce_u>oi_strong: reversal=True
    elif ce_b>ce_u and ce_b>oi_sig:
        pts=min(35,int(ce_b/oi_sig)*8); flow-=pts
        signals.append(f"Call build ({ce_b:,.0f}) -{pts}")
        if ce_b>oi_strong: reversal=True
    if pe_b>oi_sig:
        pts=min(20,int(pe_b/oi_sig)*5); flow-=pts
        signals.append(f"Put build ({pe_b:,.0f}) -{pts}")
        if pe_b>oi_strong: reversal=True
    elif pe_u>oi_sig:
        pts=min(20,int(pe_u/oi_sig)*5); flow+=pts
        signals.append(f"Put covering ({pe_u:,.0f}) +{pts}")
        if pe_u>oi_strong: reversal=True

    pcr=analysis["pcr"]
    if prev_pcr is not None:
        chg=pcr-prev_pcr
        if chg>0.15:
            pts=15 if chg>0.3 else 8; flow+=pts
            signals.append(f"PCR rising ({prev_pcr:.2f}→{pcr:.2f}) +{pts}")
            if chg>0.30: reversal=True
        elif chg<-0.15:
            pts=15 if chg<-0.3 else 8; flow-=pts
            signals.append(f"PCR falling ({prev_pcr:.2f}→{pcr:.2f}) -{pts}")
            if chg<-0.30: reversal=True
        else: signals.append(f"PCR stable ({prev_pcr:.2f}→{pcr:.2f})")
    else:
        if pcr>PCR_EXT_BULL: flow-=10; signals.append(f"PCR extreme high ({pcr})")
        elif pcr<PCR_EXT_BEAR: flow+=10; signals.append(f"PCR extreme low ({pcr})"); reversal=True
        else: signals.append(f"PCR: {pcr}")

    all_ce_v=[s["ce_volume"] for s in strikes if s["ce_volume"]>0]
    all_pe_v=[s["pe_volume"] for s in strikes if s["pe_volume"]>0]
    avg_ce=sum(all_ce_v)/len(all_ce_v) if all_ce_v else 1
    avg_pe=sum(all_pe_v)/len(all_pe_v) if all_pe_v else 1
    otm_ce=[s for s in strikes if spot+atr_val*0.5<s["strike"]<spot+atr_val*3]
    otm_pe=[s for s in strikes if spot-atr_val*3<s["strike"]<spot-atr_val*0.5]

    curr_ce_m=0
    surge_ce=[s for s in otm_ce if s["ce_volume"]>avg_ce*4]
    if surge_ce:
        top=max(surge_ce,key=lambda x:x["ce_volume"]); curr_ce_m=top["ce_volume"]/avg_ce
        pts=min(20,int(curr_ce_m/2)*5); flow+=pts
        signals.append(f"Call surge {top['strike']:,.0f} ({curr_ce_m:.1f}x) +{pts}")
        if curr_ce_m>5 and prev_ce_m<2: reversal=True

    curr_pe_m=0
    surge_pe=[s for s in otm_pe if s["pe_volume"]>avg_pe*4]
    if surge_pe:
        top=max(surge_pe,key=lambda x:x["pe_volume"]); curr_pe_m=top["pe_volume"]/avg_pe
        pts=min(20,int(curr_pe_m/2)*5); flow-=pts
        signals.append(f"Put surge {top['strike']:,.0f} ({curr_pe_m:.1f}x) -{pts}")
        if curr_pe_m>5 and prev_pe_m<2: reversal=True

    if not surge_ce and not surge_pe: signals.append("No unusual OTM volume")

    top_ce=analysis["top_ce_oi"][0]["strike"] if analysis["top_ce_oi"] else None
    top_pe=analysis["top_pe_oi"][0]["strike"] if analysis["top_pe_oi"] else None
    wall=False
    if top_ce and prev_ce and spot>=top_ce and prev_ce>spot-atr_val:
        flow+=30; reversal=True; wall=True; signals.append(f"🧱 CALL WALL BROKEN {top_ce:,.0f} +30")
    if top_pe and prev_pe and not wall and spot<=top_pe and prev_pe<spot+atr_val:
        flow-=30; reversal=True; signals.append(f"🧱 PUT WALL BROKEN {top_pe:,.0f} -30")
    if not wall and top_ce and top_pe:
        signals.append(f"Walls: Call {top_ce:,.0f}, Put {top_pe:,.0f}")

    flow=max(-100,min(100,flow))
    with REG_L: REG["ce_mult"]=curr_ce_m; REG["pe_mult"]=curr_pe_m
    return flow,signals,reversal

def update_regime(analysis, direction, score):
    with REG_L:
        REG["dir"]=direction; REG["score"]=score
        REG["spot"]=analysis["spot"] if analysis else None
        REG["time"]=datetime.now(IST)
        REG["pcr"]=analysis["pcr"] if analysis else None
        if analysis:
            REG["top_ce"]=analysis["top_ce_oi"][0]["strike"] if analysis["top_ce_oi"] else None
            REG["top_pe"]=analysis["top_pe_oi"][0]["strike"] if analysis["top_pe_oi"] else None


# ===== OPENING RANGE =====
def or_reset(key):
    today=datetime.now(IST).date()
    with OR_L:
        if OR["date"]!=today:
            OR.update({"date":today,"high":None,"low":None,"ticks":0,
                       "locked":False,"announced":False,
                       "gap_type":"UNKNOWN","gap_pct":0.0,
                       "gap_fixed":False,"trend_day":False})
            with REG_L: REG["reversal"]=False; REG["ce_mult"]=0; REG["pe_mult"]=0

def or_track_tick():
    if not is_trading_day(): return
    key,_=get_underlying(); or_reset(key)
    with OR_L:
        if OR["locked"]: return
    r=neo_get_spot(key)
    if not r["ok"]: return
    ltp=r["ltp"]
    with OR_L:
        OR["high"]=max(OR["high"] or ltp,ltp)
        OR["low"]=min(OR["low"] or ltp,ltp)
        OR["ticks"]=(OR["ticks"] or 0)+1

def or_lock_and_announce():
    if not is_trading_day(): return
    key,u=get_underlying(); or_reset(key)
    with OR_L:
        if OR["locked"] and OR["announced"]: return
        if OR["high"] is None:
            tg("⚠️ <b>OR Lock Delayed</b>\nRetrying in 15s")
            threading.Timer(15,or_lock_and_announce).start(); return
        OR["locked"]=True; OR["announced"]=True
        oh,ol=OR["high"],OR["low"]

    candles=neo_get_candles(key,5,5)
    atr_val=None; ratio=None
    if candles.get("ok"):
        atr_val=compute_atr(candles["high"],candles["low"],candles["close"])
        if atr_val: ratio=round((oh-ol)/atr_val,2)

    prev=prev_ohlc_from_candles(candles) if candles.get("ok") else None
    gap_type,gap_pct="UNKNOWN",0.0
    if prev:
        gap_type,gap_pct=detect_gap(prev["close"],(oh+ol)/2)
        with OR_L: OR["gap_type"]=gap_type; OR["gap_pct"]=gap_pct; OR["gap_fixed"]=True

    is_trend=False; hint=""
    if ratio:
        if ratio<COMPRESSION: hint="🔻 COMPRESSED"
        elif ratio>TREND_THRESH: hint="🔥 TREND DAY"; is_trend=True
        else: hint="✅ NORMAL"
    with OR_L: OR["trend_day"]=is_trend

    gap_str=f"\nGap: {gap_type.replace('_',' ')} ({gap_pct:+.2f}%)" if gap_type not in ["FLAT_OPEN","UNKNOWN"] else ""
    max_sell,thresh=day_limits()
    tg(
        f"📊 <b>OR LOCKED — {u['name']}</b>\n09:30 IST | {OR['date']}\n\n"
        f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
        f"Range: {oh-ol:.1f} pts | Ticks: {OR['ticks']}\n"
        f"{'ATR: '+str(atr_val)+' | R/ATR: '+str(ratio)+' → '+hint if atr_val else ''}"
        f"{gap_str}"
        f"{chr(10)+'⚡ EXPIRY DAY — exit 2:30 PM' if is_expiry(key) else ''}"
        f"{chr(10)+'⚠️ Wednesday — max 1 signal' if datetime.now(IST).weekday()==2 else ''}\n\n"
        f"<i>Bot silent until signal fires.</i>"
    )


# ===== SNAPSHOT =====
def build_snapshot(key=None):
    if not API_L.acquire(timeout=45):
        return {"error":"API busy"}
    try:
        now=datetime.now(IST)
        if now.hour==9 and now.minute<15: return {"error":"Pre-open"}
        if key is None: key,u=get_underlying()
        else: u=UNDERLYINGS[key]

        if not get_client(): return {"error":"Not logged in — send /login"}

        exp_r=neo_get_expiries(key)
        if not exp_r["ok"]: return {"error":f"Expiry: {exp_r.get('err')}"}
        nearest=exp_r["expiries"][0]; dte=compute_dte(nearest)

        time.sleep(2.0)
        chain_r=neo_get_option_chain(key,nearest)
        if not chain_r["ok"]: return {"error":f"Chain: {chain_r.get('err')}"}

        analysis=analyze_chain(chain_r)
        if not analysis: return {"error":"Chain parse failed"}

        candles=neo_get_candles(key,5,5)
        atr_val=None
        if candles.get("ok"):
            atr_val=compute_atr(candles["high"],candles["low"],candles["close"])

        prev=prev_ohlc_from_candles(candles) if candles.get("ok") else None
        pivots=compute_pivots(prev["high"],prev["low"],prev["close"]) if prev else None

        with OR_L:
            if OR["gap_fixed"]: gap_type,gap_pct=OR["gap_type"],OR["gap_pct"]
            else:
                gap_type,gap_pct="UNKNOWN",0.0
                if prev: gap_type,gap_pct=detect_gap(prev["close"],analysis["spot"])

        atm=analysis["atm"]
        atm_iv=(atm.get("ce_iv",0)+atm.get("pe_iv",0))/2
        iv_rank=compute_iv_rank(key,atm_iv)

        return {
            "analysis":analysis,"expiry":nearest,"dte":dte,"atr":atr_val,
            "pivots":pivots,"candles":candles,
            "underlying_key":key,"underlying_name":u["name"],
            "lot_size":u["lot_size"],"strike_gap":u["strike_gap"],
            "gap_type":gap_type,"gap_pct":gap_pct,
            "is_expiry_day":is_expiry(key),
            "atm_iv":round(atm_iv,2),"iv_rank":iv_rank,
        }
    finally:
        API_L.release()


# ===== DAILY RISK =====
def reset_daily():
    today=datetime.now(IST).date()
    with RISK_L:
        if RISK["date"]!=today:
            RISK.update({"date":today,"sl":0,"fired":0,"halted":False,
                         "sell":0,"buy":0,"pnl":0})
            print(f"[Risk] Reset {today}")
    with LAST_L:
        if LAST["time"] and LAST["time"].date()<today:
            LAST["time"]=None; LAST["mode"]=None
    with TRADE_L:
        if TRADE.get("entry_time") and TRADE["entry_time"].date()<today:
            TRADE["active"]=False

def register_sl(loss=0):
    reset_daily()
    with RISK_L:
        RISK["sl"]+=1; RISK["pnl"]-=abs(loss)
        hits=RISK["sl"]
        if hits>=2:
            RISK["halted"]=True
            tg("🛑 <b>KILL SWITCH — 2 SL Hits</b>\nNo more signals today."); return True
        tg(f"⚠️ <b>SL Hit #{hits}</b>")
        return False

def register_profit(amount):
    with RISK_L: RISK["pnl"]+=amount

def is_allowed():
    reset_daily(); now=datetime.now(IST)
    key,_=get_underlying()
    if is_weekend(): return False,"Weekend"
    if is_holiday(): return False,"Holiday"
    if now.hour>=15: return False,"After 3PM"
    if is_expiry(key) and now.hour>=14 and now.minute>=30: return False,"Expiry after 2:30"
    if now.hour<9 or (now.hour==9 and now.minute<30): return False,"Pre-market"
    with RISK_L:
        if RISK["halted"]: return False,"Halted"
    return True,"OK"

def get_time_quality(mode):
    now=datetime.now(IST); mins=now.hour*60+now.minute
    if mins<9*60+45:     return 0.75,"Opening noise"
    elif mins<=11*60+30: return 1.00,"Prime window"
    elif mins<=12*60+30: return 0.85,"Lunch lull"
    elif mins<=14*60+30: return 0.95,"Second window"
    elif mins<=14*60+45: return (0.85,"Late scalp") if mode=="BUY" else (0.80,"Late sell")
    else:                return (0.50,"Too late") if mode=="BUY" else (0.70,"Pre-close")


# ===== CLASSIFIER =====
def classify_regime(snap):
    if "error" in snap: return "SKIP",{"error":snap["error"]}
    a=snap["analysis"]; spot=a["spot"]; atm=a["atm"]
    p=snap.get("pivots"); atr=snap.get("atr"); candles=snap.get("candles",{})
    u_name=snap.get("underlying_name","NIFTY"); u_key=snap.get("underlying_key","nifty")
    dte=snap.get("dte",5); gap_type=snap.get("gap_type","FLAT_OPEN")
    gap_pct=snap.get("gap_pct",0.0); expiry_day=snap.get("is_expiry_day",False)
    iv_rank=snap.get("iv_rank"); atr_val=atr if atr else 25; skip_reasons=[]

    with OR_L:
        or_high=OR["high"] if OR["locked"] else None
        or_low=OR["low"]  if OR["locked"] else None
        or_trend=OR["trend_day"]

    hist=adapt(u_key)
    er_chop_t=ER_CHOP; er_trend_t=ER_TREND
    if len(hist["er"])>=20:
        er_chop_t=percentile(hist["er"],20) or ER_CHOP
        er_trend_t=percentile(hist["er"],80) or ER_TREND

    er,er_label=compute_er(candles)
    is_chop=er<er_chop_t; is_trend=er>er_trend_t or or_trend

    gw,wm=gap_wait(gap_type)
    if gw: skip_reasons.append(f"GAP WAIT: {wm}m")

    vol_pass,vol_reason,vol_metrics,_=vol_filter(candles,atr)
    if not vol_pass and "COMPRESSION" in vol_reason: skip_reasons.append("COMPRESSION")

    flow_score,flow_sigs,reversal=compute_oi_flow(a,atr,u_key)
    oi_pts=min(abs(flow_score)//3,35)

    price_score,price_bias,price_reasons,vwap,ema9,ema20,swing,sdir=\
        compute_price_score(candles,spot,p,or_high,or_low,atr_val,is_trend)

    # Greeks score — simplified since Neo doesn't provide greeks
    greeks_score=5 if dte>=5 else 4 if dte==4 else 2 if dte==3 else 0
    greeks_quality="GOOD" if dte>=4 else "MARGINAL" if dte==3 else "POOR"

    iv_rank_note="IV Rank building"
    if iv_rank is not None:
        if iv_rank>=75: iv_rank_note=f"⭐ IV Rank {iv_rank}"
        elif iv_rank>=60: iv_rank_note=f"✅ IV Rank {iv_rank}"
        else: iv_rank_note=f"⚠️ IV Rank {iv_rank}"

    pos_pts=0; pos_bias=0.0; pcr=a["pcr"]
    if 1.20>=pcr>=0.80: pos_pts+=5
    elif pcr>PCR_BULLISH: pos_bias+=0.4; pos_pts+=2
    elif pcr<PCR_BEARISH: pos_bias-=0.4; pos_pts+=2

    mp=a.get("max_pain")
    if mp:
        mp_diff=mp-spot
        if abs(mp_diff)/atr_val<0.5: pos_pts+=5
        elif abs(mp_diff)/atr_val<1.5: pos_pts+=2; pos_bias+=0.2 if mp_diff>0 else -0.2
    pos_pts=min(pos_pts,10)

    oi_bias=flow_score/50
    bias_score=round(oi_bias+price_bias+pos_bias,2)
    score=min(100,int(oi_pts+price_score+greeks_score+pos_pts))

    oi_dir="BULLISH" if flow_score>20 else "BEARISH" if flow_score<-20 else "NEUTRAL"
    confluence="AGREE"
    if oi_dir!="NEUTRAL" and "NEUTRAL" not in sdir:
        if ("BULLISH" in oi_dir)!=("BULLISH" in sdir):
            confluence="CONFLICT"; score=int(score*0.65)
            skip_reasons.append(f"OI/Price CONFLICT: OI={oi_dir}, Price={sdir}")

    if is_trend:
        if flow_score>=10 and bias_score>=0:    direction="STRONG BULLISH"
        elif flow_score<=-10 and bias_score<=0: direction="STRONG BEARISH"
        elif bias_score>=1.0:                   direction="STRONG BULLISH"
        elif bias_score<=-1.0:                  direction="STRONG BEARISH"
        else:                                   direction="NEUTRAL"
    elif bias_score>=2.0:   direction="STRONG BULLISH"
    elif bias_score>=0.8:   direction="MILD BULLISH"
    elif bias_score<=-2.0:  direction="STRONG BEARISH"
    elif bias_score<=-0.8:  direction="MILD BEARISH"
    else:                   direction="NEUTRAL"

    if "STRONG BULLISH" in direction:   suggested="SELL PUT SPREAD"
    elif "MILD BULLISH" in direction:   suggested="IRON CONDOR (lean put)"
    elif "STRONG BEARISH" in direction: suggested="SELL CALL SPREAD"
    elif "MILD BEARISH" in direction:   suggested="IRON CONDOR (lean call)"
    else:                               suggested="IRON CONDOR"

    goa=gap_override_active(gap_type)
    if goa and direction=="NEUTRAL":
        if "UP" in gap_type: suggested="SELL PUT SPREAD"
        elif "DOWN" in gap_type: suggested="SELL CALL SPREAD"

    rev_new=reversal and not REG.get("reversal",False)
    if is_chop and rev_new and (pcr<=PCR_EXT_BEAR or pcr>=PCR_EXT_BULL): is_chop=False
    elif is_chop: skip_reasons.append(f"CHOP: ER={er}")

    max_sell,day_thresh=day_limits()
    if dte>=6: spread_thresh=max(day_thresh,55)
    elif dte==5: spread_thresh=max(day_thresh,52)
    elif reversal and confluence=="AGREE": spread_thresh=max(day_thresh-5,45)
    else: spread_thresh=day_thresh

    # Probabilistic — scalp first
    if is_trend and abs(bias_score)>=1.0:
        probs={"sell_spread":0.10,"ic":0.05,"buy":0.65,"cash":0.20}
    elif is_chop:
        probs={"sell_spread":0.15,"ic":0.40,"buy":0.10,"cash":0.35}
    elif abs(bias_score)<1.5:
        probs={"sell_spread":0.15,"ic":0.25,"buy":0.35,"cash":0.25}
    else:
        probs={"sell_spread":0.15,"ic":0.10,"buy":0.55,"cash":0.20}

    mode="SKIP"
    if skip_reasons: mode="SKIP"
    elif greeks_quality=="POOR" and not is_trend:
        skip_reasons.append("Greeks POOR"); mode="SKIP"
    elif dte<DTE_SPREAD_MIN:
        skip_reasons.append(f"DTE {dte} — too close"); mode="SKIP"
    elif not is_trend and score>=60 and dte>=DTE_IC_MIN and vol_pass: mode="IC"
    elif not is_trend and score>=spread_thresh and dte>=DTE_SPREAD_MIN: mode="SPREAD"

    # Scalp detection — REVERSAL and MOMENTUM paths
    buy_signal=None; buy_direction=None; scalp_type=None
    can_buy=(dte>=DTE_BUY_MIN and not expiry_day and not is_chop and
             (iv_rank is None or iv_rank<=IV_RANK_BUY_MAX) and confluence=="AGREE")

    if can_buy and abs(flow_score)>=FLOW_THRESH:
        if reversal:
            or_break=True
            if or_high and or_low:
                or_break=spot>(or_high+atr_val*0.3) if flow_score>0 else spot<(or_low-atr_val*0.3)
            if or_break:
                scalp_type="REVERSAL"
                if flow_score>0 and bias_score>0:
                    buy_direction="CALL"; buy_signal=f"⚡ BUY CALL — REVERSAL | flow {flow_score:+d}, bias {bias_score:+.1f}"
                elif flow_score<0 and bias_score<0:
                    buy_direction="PUT";  buy_signal=f"⚡ BUY PUT  — REVERSAL | flow {flow_score:+d}, bias {bias_score:+.1f}"
        elif is_trend and abs(bias_score)>=0.8:
            or_ok=True
            if or_high and or_low:
                or_ok=spot>or_low if flow_score>0 else spot<or_high
            if or_ok:
                scalp_type="MOMENTUM"
                if flow_score>0 and bias_score>0:
                    buy_direction="CALL"; buy_signal=f"⚡ BUY CALL — MOMENTUM | flow {flow_score:+d}, bias {bias_score:+.1f}"
                elif flow_score<0 and bias_score<0:
                    buy_direction="PUT";  buy_signal=f"⚡ BUY PUT  — MOMENTUM | flow {flow_score:+d}, bias {bias_score:+.1f}"

        if buy_signal: mode="BUY"

    if skip_reasons:
        critical=["CHOP","CONFLICT","DTE","Greeks","COMPRESSION"]
        has_critical=any(kw in " ".join(skip_reasons) for kw in critical)
        if mode=="BUY" and has_critical: mode="SKIP"; buy_signal=None
        elif mode!="BUY": mode="SKIP"

    if mode=="BUY":      verdict="⚡ SCALP"
    elif mode=="IC":     verdict="🟢 IRON CONDOR"
    elif mode=="SPREAD": verdict="🟢 DIRECTIONAL SPREAD"
    elif skip_reasons:   verdict="🔴 SKIP"
    else:                verdict="🟠 WEAK"

    result={
        "mode":mode,"verdict":verdict,"score":score,"direction":direction,
        "bias_score":bias_score,"suggested":suggested,
        "flow_score":flow_score,"flow_signals":flow_sigs,"reversal":reversal,
        "skip_reasons":skip_reasons,"spot":spot,"atm_strike":atm["strike"],
        "price_score":price_score,"price_reasons":price_reasons,
        "vwap":vwap,"ema9":ema9,"ema20":ema20,"swing":swing,"structure_dir":sdir,
        "confluence":confluence,"oi_direction":oi_dir,
        "vol_pass":vol_pass,"vol_reason":vol_reason,
        "underlying_name":u_name,"dte":dte,"is_trend_day":is_trend,
        "is_expiry_day":expiry_day,"gap_type":gap_type,"gap_pct":gap_pct,
        "gap_override_active":goa,"er":er,"er_label":er_label,"is_chop":is_chop,
        "iv_rank":iv_rank,"iv_rank_note":iv_rank_note,
        "buy_signal":buy_signal,"buy_direction":buy_direction,"scalp_type":scalp_type,
        "pcr":pcr,"spread_threshold":spread_thresh,"regime_probs":probs,
    }

    hist["er"].append(abs(er)); hist["pcr"].append(pcr)
    hist["flow"].append(flow_score); hist["scores"].append(score)
    for k in hist:
        if len(hist[k])>50: hist[k]=hist[k][-50:]
    update_regime(a,direction,score)
    with REG_L: REG["reversal"]=reversal
    return mode,result


# ===== SIGNAL FIRE =====
def can_fire(mode):
    reset_daily(); max_sell,_=day_limits()
    with RISK_L:
        if mode=="BUY" and RISK["buy"]>=MAX_BUY: return False
        elif mode!="BUY" and RISK["sell"]>=max_sell: return False
    if mode=="BUY": return True
    now=datetime.now(IST)
    with LAST_L:
        lt=LAST["time"]; lm=LAST["mode"]
    if lt is None: return True
    if lm!=mode: return True
    return (now-lt).total_seconds()>=DEDUP_SECS

def record_signal(mode):
    with LAST_L: LAST["time"]=datetime.now(IST); LAST["mode"]=mode
    with RISK_L:
        RISK["fired"]+=1
        if mode=="BUY": RISK["buy"]+=1
        else: RISK["sell"]+=1

def try_fire(snap, mode, classification, source=""):
    if mode=="SKIP": return False
    allowed,_=is_allowed()
    if not allowed and not PAPER_TRADE_MODE: return False
    score=classification.get("score",0)
    spread_thresh=classification.get("spread_threshold",50)
    if mode in ["SPREAD","IC"] and score<spread_thresh:
        print(f"[Signal] Score {score}<{spread_thresh}"); return False
    if not can_fire(mode): return False
    quality,_=get_time_quality(mode)
    if quality<0.70: return False
    msg=format_signal(snap,mode,classification)
    if not msg: return False
    print(f"[Signal] Firing {mode} from {source} — score={score}")
    if tg(msg): record_signal(mode)
    return True


# ===== SIGNAL FORMATTER =====
def format_signal(snap, mode, classification):
    if not classification or "error" in classification: return None
    allowed,_=is_allowed()
    if not allowed and not PAPER_TRADE_MODE: return None
    if mode=="SKIP": return None

    # Strike selection
    a=snap["analysis"]; spot=a["spot"]; strikes=a["all_strikes"]
    sg=snap.get("strike_gap",50); ls=snap.get("lot_size",75)
    dte=snap.get("dte",5); u_key=snap.get("underlying_key","nifty")
    expiry=snap.get("expiry","N/A"); u_name=snap.get("underlying_name","NIFTY")
    expiry_day=snap.get("is_expiry_day",False)
    sorted_strikes=sorted(strikes,key=lambda x:x["strike"])

    if expiry_day:   delta_spread=0.18
    elif dte<=3:     delta_spread=0.22
    elif dte<=5:     delta_spread=0.26
    else:            delta_spread=0.28
    width=2

    def find_delta(target,side="ce"):
        ltp_k=f"{side}_ltp"; del_k=f"{side}_delta"
        cands=[s for s in sorted_strikes if 25<s[ltp_k]<700]
        if not cands: cands=[s for s in sorted_strikes if s[ltp_k]>10]
        if not cands: return None
        return min(cands,key=lambda x:abs(abs(x.get(del_k,0))-abs(target)))

    def find_offset(base,offset,side="ce"):
        ts=base+offset*sg
        cands=[s for s in sorted_strikes if s[f"{side}_ltp"]>0]
        if not cands: return None
        return min(cands,key=lambda x:abs(x["strike"]-ts))

    is_paper=PAPER_TRADE_MODE or not allowed
    paper_prefix="📝 <b>PAPER</b> — " if is_paper else "🔴 <b>LIVE</b> — "
    sl_mult=1.2 if expiry_day else 1.5
    _,quality_note=get_time_quality(mode)
    vwap=classification.get("vwap"); ema9=classification.get("ema9")
    structure=classification.get("structure_dir","")
    confluence=classification.get("confluence","AGREE")

    with RISK_L: realized=RISK["pnl"]
    remaining=DAILY_TARGET-realized

    if mode=="BUY":
        buy_dir=classification.get("buy_direction")
        if buy_dir=="CALL" or (buy_dir is None and "BULLISH" in classification.get("direction","")):
            atm_c=min([s for s in sorted_strikes if s["ce_ltp"]>10],
                      key=lambda x:abs(x.get("ce_delta",0.5)-0.50),default=None)
            if not atm_c: return None
            prem=atm_c["ce_ltp"]; side="ce"
            strategy="BUY CALL"; tsym=atm_c.get("ce_tsym","")
            strike=atm_c["strike"]
        else:
            atm_p=min([s for s in sorted_strikes if s["pe_ltp"]>10],
                      key=lambda x:abs(abs(x.get("pe_delta",0.5))-0.50),default=None)
            if not atm_p: return None
            prem=atm_p["pe_ltp"]; side="pe"
            strategy="BUY PUT"; tsym=atm_p.get("pe_tsym","")
            strike=atm_p["strike"]

        lots=BUY_LOTS_N if u_key=="nifty" else BUY_LOTS_S
        qty=lots*ls
        target=round(prem*(1+BUY_WIN),2); sl_price=round(prem*(1-BUY_SL),2)
        t1=round(prem*1.20,2); t2=round(prem*1.30,2); t2_sl=round(prem*1.15,2)
        win=round((target-prem)*qty,0); loss=round((prem-sl_price)*qty,0)
        scalp_type=classification.get("scalp_type","SCALP")

        msg=f"🎯 {paper_prefix}<b>{u_name} {strategy}</b>\n"
        if classification.get("is_trend_day"): msg+="🔥 Trend day\n"
        if expiry_day: msg+=f"⚡ Expiry — exit 2:30 PM\n"
        msg+=f"DTE: {dte} | Spot: {spot:,.2f}\n"
        ctx=[]
        if vwap: ctx.append(f"VWAP {'✅' if spot>vwap else '❌'}{vwap:,.0f}")
        if ema9: ctx.append(f"9EMA {'✅' if spot>ema9 else '❌'}{ema9:,.0f}")
        if structure: ctx.append(structure)
        if ctx: msg+=" | ".join(ctx)+"\n"
        msg+=f"Confluence: <b>{confluence}</b> | {quality_note}\n"
        msg+=f"Lots: {lots} | Qty: {qty:,}\n\n"
        msg+=f"<b>═══ {scalp_type} SCALP ═══</b>\n"
        msg+=f"BUY {strike:,.0f} {'Call' if 'CALL' in strategy else 'Put'}\n"
        msg+=f"Entry: ₹{prem:.2f} | Qty: {qty:,}\n"
        if is_paper and tsym: msg+=f"<i>Symbol: {tsym}</i>\n"
        msg+=f"\n<b>Scalp Math (35% target):</b>\n"
        msg+=f"Entry ₹{prem:.2f} | Target ₹{target:.2f} | SL ₹{sl_price:.2f}\n"
        msg+=f"Win: +₹{win:,.0f} | Loss: -₹{loss:,.0f}\n\n"
        msg+=f"<b>Tight Trails — Book Fast:</b>\n"
        msg+=f"L1 @ ₹{t1:.2f} (+20%) → SL to breakeven\n"
        msg+=f"L2 @ ₹{t2:.2f} (+30%) → SL to ₹{t2_sl:.2f}\n"
        msg+=f"⏰ Hard exit: {BUY_MINS} min\n"
        msg+=f"\n<b>Daily: {'+'if realized>=0 else ''}₹{realized:,.0f} | Remaining ₹{remaining:,.0f}</b>\n"
        msg+=f"\n<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v4.1 Kotak Neo</i>"

        with TRADE_L:
            TRADE.update({"active":True,"is_buy":True,"strategy":strategy,
                "buy_strike":strike,"buy_side":side,
                "buy_entry":prem,"buy_tgt":target,"buy_sl":sl_price,
                "l1_trig":t1,"l1_sl":prem,"l2_trig":t2,"l2_sl":t2_sl,
                "entry_time":datetime.now(IST),"qty":qty,"lots":lots,
                "key":u_key,"expiry":expiry,"l1_done":False,"l2_done":False})
        return msg

    # Selling
    suggested=classification.get("suggested","")
    is_ic=("IRON CONDOR" in suggested or mode=="IC")
    is_put=("PUT SPREAD" in suggested or "BULLISH" in suggested) and not is_ic
    is_call=("CALL SPREAD" in suggested or "BEARISH" in suggested) and not is_ic

    if is_ic:
        cs=find_delta(delta_spread,"ce"); ps=find_delta(delta_spread,"pe")
        if not cs or not ps: return None
        ch=find_offset(cs["strike"],width,"ce"); ph=find_offset(ps["strike"],-width,"pe")
        if not ch or not ph: return None
        net=cs["ce_ltp"]+ps["pe_ltp"]-ch["ce_ltp"]-ph["pe_ltp"]
        max_loss=abs(ch["strike"]-cs["strike"])-net
        width_pts=abs(ch["strike"]-cs["strike"])
        strategy="IRON CONDOR"
        short_strike=cs["strike"]; short_side="ce"
        legs_msg=(f"BUY  {ch['strike']:,.0f} Call @ ₹{ch['ce_ltp']:.2f} × ?\n"
                  f"BUY  {ph['strike']:,.0f} Put  @ ₹{ph['pe_ltp']:.2f} × ?\n"
                  f"SELL {cs['strike']:,.0f} Call @ ₹{cs['ce_ltp']:.2f} × ?\n"
                  f"SELL {ps['strike']:,.0f} Put  @ ₹{ps['pe_ltp']:.2f} × ?\n"
                  f"Call Δ≈0.22 | Put Δ≈0.22\n")
        if is_paper:
            legs_msg+=(f"<i>CE sell: {cs.get('ce_tsym','')} | PE sell: {ps.get('pe_tsym','')}</i>\n")
    elif is_put:
        ps=find_delta(delta_spread,"pe")
        if not ps: return None
        ph=find_offset(ps["strike"],-width,"pe")
        if not ph: return None
        net=ps["pe_ltp"]-ph["pe_ltp"]
        max_loss=abs(ps["strike"]-ph["strike"])-net
        width_pts=abs(ps["strike"]-ph["strike"])
        strategy="BULL PUT SPREAD"; short_strike=ps["strike"]; short_side="pe"
        legs_msg=(f"BUY  {ph['strike']:,.0f} Put @ ₹{ph['pe_ltp']:.2f} × ?\n"
                  f"SELL {ps['strike']:,.0f} Put @ ₹{ps['pe_ltp']:.2f} × ?\n")
        if is_paper: legs_msg+=f"<i>Sell: {ps.get('pe_tsym','')} | Buy: {ph.get('pe_tsym','')}</i>\n"
    elif is_call:
        cs=find_delta(delta_spread,"ce")
        if not cs: return None
        ch=find_offset(cs["strike"],width,"ce")
        if not ch: return None
        net=cs["ce_ltp"]-ch["ce_ltp"]
        max_loss=abs(ch["strike"]-cs["strike"])-net
        width_pts=abs(ch["strike"]-cs["strike"])
        strategy="BEAR CALL SPREAD"; short_strike=cs["strike"]; short_side="ce"
        legs_msg=(f"BUY  {ch['strike']:,.0f} Call @ ₹{ch['ce_ltp']:.2f} × ?\n"
                  f"SELL {cs['strike']:,.0f} Call @ ₹{cs['ce_ltp']:.2f} × ?\n")
        if is_paper: legs_msg+=f"<i>Sell: {cs.get('ce_tsym','')} | Buy: {ch.get('ce_tsym','')}</i>\n"
    else:
        return None

    if net<=0: return None
    ti=dte_target(net,dte,u_key)
    lots=lots_for_target(net,ls,ti["capture_pct"]/100)
    qty=lots*ls; total_credit=round(net*qty,0)
    sl_amount=round(net*sl_mult*qty,0); target_total=round(ti["target_per_lot"]*qty,0)
    eff=round(net/(net+max_loss)*100,1)

    msg=f"🎯 {paper_prefix}<b>{u_name} {strategy}</b>\n"
    if expiry_day: msg+=f"⚡ Expiry — SL {sl_mult}×, exit 2:30 PM\n"
    msg+=f"DTE: {dte} | Spot: {spot:,.2f}\n"
    ctx=[]
    if vwap: ctx.append(f"VWAP {'✅' if spot>vwap else '❌'}{vwap:,.0f}")
    if ema9: ctx.append(f"9EMA {'✅' if spot>ema9 else '❌'}{ema9:,.0f}")
    if ctx: msg+=" | ".join(ctx)+"\n"
    msg+=f"Confluence: <b>{confluence}</b> | {quality_note}\n"
    msg+=f"Lots: {lots} | Qty: {qty:,}\n\n"
    msg+=f"<b>{eff}% credit | {100-eff:.0f}% risk | {width_pts:.0f}pts wide</b>\n\n"
    msg+=f"<b>═══ ORDER SEQUENCE ═══</b>\n<i>⚠️ Hedges FIRST always</i>\n\n"
    msg+=legs_msg
    msg+=f"\n<b>═══ TRADE MATH ═══</b>\n"
    msg+=f"Credit: ₹{net:.2f}/lot | Total: ₹{total_credit:,.0f}\n"
    msg+=f"Max loss: ₹{max_loss:.2f}/lot\n"
    msg+=f"<b>Target ({ti['capture_pct']}%): ₹{target_total:,.0f}</b>\n"
    msg+=f"Why: {ti['note']}\n"
    msg+=f"SL: ₹{round(net*sl_mult,2):.2f}/lot = ₹{sl_amount:,.0f}\n"
    msg+=f"\n<b>Daily: {'+'if realized>=0 else ''}₹{realized:,.0f} | Remaining ₹{remaining:,.0f}</b>\n"
    msg+=f"\n🎯 Target hit → exit | 🛑 SL hit → /sl | ⏰ {'2:30 PM' if expiry_day else '3:00 PM'}\n"
    msg+=f"\n<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v4.1 Kotak Neo</i>"

    with TRADE_L:
        entry_leg_ltp = cs["ce_ltp"] if short_side=="ce" else ps["pe_ltp"] if is_put else ps["pe_ltp"]
        TRADE.update({"active":True,"is_buy":False,"strategy":strategy,
            "short_strike":short_strike,"short_side":short_side,
            "entry_short":entry_leg_ltp,"net_credit":net,
            "tgt_pct":ti["capture_pct"]/100,"sl_mult":sl_mult,
            "entry_time":datetime.now(IST),"lots":lots,"qty":qty,
            "key":u_key,"expiry":expiry})
    return msg


# ===== TRADE MONITOR =====
def monitor_trade():
    with TRADE_L:
        if not TRADE["active"]: return
        is_buy=TRADE["is_buy"]; key=TRADE["key"]
        entry_time=TRADE["entry_time"]
    if not is_trading_day(): return
    now=datetime.now(IST)
    if now<now.replace(hour=9,minute=30) or now>=now.replace(hour=15,minute=0): return
    snap=build_snapshot(key)
    if "error" in snap: return
    strikes=snap["analysis"]["all_strikes"]; spot=snap["analysis"]["spot"]
    elapsed=int((now-entry_time).total_seconds()/60)
    if is_buy: monitor_buy(strikes,elapsed)
    else: monitor_sell(strikes,spot,elapsed)

def monitor_sell(strikes,spot,elapsed):
    with TRADE_L:
        ss=TRADE["short_strike"]; sd=TRADE["short_side"]
        ep=TRADE["entry_short"]; nc=TRADE["net_credit"]
        tp=TRADE["tgt_pct"]; sm=TRADE["sl_mult"]
        qty=TRADE["qty"]; strategy=TRADE["strategy"]
    match=next((s for s in strikes if s["strike"]==ss),None)
    if not match: return
    current=match.get(f"{sd}_ltp",0)
    if not current or current<=0: return
    decay=ep-current; captured=decay/nc if nc>0 else 0
    pnl=round(decay*qty,0)
    if captured>=tp:
        tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n{strategy} | Short {sd.upper()} {ss:,.0f}\n₹{ep:.2f}→₹{current:.2f} | {captured:.0%}\n<b>+₹{pnl:,.0f}</b>\n→ /tradesquared")
        register_profit(pnl)
        with TRADE_L: TRADE["active"]=False; return
    if current>=ep*sm:
        loss=round((current-ep)*qty,0)
        tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n{strategy} | {sd.upper()} {ss:,.0f}\n₹{ep:.2f}→₹{current:.2f}\n<b>-₹{loss:,.0f}</b>\n→ /sl")
        with TRADE_L: TRADE["active"]=False
        register_sl(loss); return
    if elapsed>0 and elapsed%30==0:
        tg(f"📊 <b>Trade | {elapsed} min</b>\n{sd.upper()} {ss:,.0f}: ₹{ep:.2f}→₹{current:.2f}\nCaptured: {captured:.0%}/{tp:.0%} | {'+'if pnl>=0 else ''}₹{pnl:,.0f}")

def monitor_buy(strikes,elapsed):
    with TRADE_L:
        bs=TRADE["buy_strike"]; bd=TRADE["buy_side"]
        entry=TRADE["buy_entry"]; tgt=TRADE["buy_tgt"]
        csl=TRADE["buy_sl"]
        l1t=TRADE["l1_trig"]; l1s=TRADE["l1_sl"]
        l2t=TRADE["l2_trig"]; l2s=TRADE["l2_sl"]
        l1d=TRADE["l1_done"]; l2d=TRADE["l2_done"]
        qty=TRADE["qty"]
    match=next((s for s in strikes if s["strike"]==bs),None)
    if not match: return
    current=match.get(f"{bd}_ltp",0)
    if not current or current<=0: return
    pnl=round((current-entry)*qty,0)
    if elapsed>=BUY_MINS:
        tg(f"⏰ <b>TIME STOP — EXIT NOW</b>\nBUY {bd.upper()} {bs:,.0f}\n₹{entry:.2f}→₹{current:.2f} | {'+'if pnl>=0 else ''}₹{pnl:,.0f}\n→ /tradesquared")
        if pnl>0: register_profit(pnl)
        with TRADE_L: TRADE["active"]=False; return
    if current>=tgt:
        tg(f"🎯 <b>SCALP TARGET — BOOK IT</b>\nBUY {bd.upper()} {bs:,.0f}\n₹{entry:.2f}→₹{current:.2f} | <b>+₹{pnl:,.0f} (+{int(BUY_WIN*100)}%)</b>\n→ /tradesquared")
        register_profit(pnl)
        with TRADE_L: TRADE["active"]=False; return
    if current<=csl:
        tg(f"🛑 <b>SL HIT — EXIT NOW</b>\nBUY {bd.upper()} {bs:,.0f}\n₹{entry:.2f}→₹{current:.2f} | -₹{abs(pnl):,.0f}\n→ /sl")
        with TRADE_L: TRADE["active"]=False
        register_sl(abs(pnl)); return
    if not l2d and current>=l2t:
        tg(f"⭐ <b>TRAIL L2 — Lock profit</b>\nMove SL to ₹{l2s:.2f}\nPremium +30% @ ₹{current:.2f}")
        with TRADE_L: TRADE["buy_sl"]=l2s; TRADE["l2_done"]=True; return
    if not l1d and current>=l1t:
        tg(f"✅ <b>TRAIL L1 — Breakeven</b>\nMove SL to ₹{l1s:.2f}\nPremium +20% @ ₹{current:.2f}")
        with TRADE_L: TRADE["buy_sl"]=l1s; TRADE["l1_done"]=True


# ===== JOBS =====
def job_login():
    """8:30 AM auto-login via TOTP."""
    if not is_trading_day(): return
    print("[Login] Auto-login starting...")
    if init_neo_client():
        tg(f"🔑 <b>Kotak Neo Connected</b>\n{datetime.now(IST).strftime('%H:%M:%S')} IST\nReady for trading.")
    else:
        tg("🚨 <b>Kotak Neo Login Failed</b>\nCheck TOTP secret and MPIN in env.vars.\nSend /login to retry.")

def job_premarket():
    if not is_trading_day(): return
    key,u=get_underlying(); reset_daily(); or_reset(key)
    exp_r=neo_get_expiries(key)
    dte_str=""
    if exp_r["ok"]:
        dte=compute_dte(exp_r["expiries"][0])
        sweet="⭐ SWEET SPOT" if 3<=dte<=5 else "⚡ GAMMA RISK" if dte<=2 else "📅 Early week"
        dte_str=f"DTE: {dte} — {sweet}\n"
    candles=neo_get_candles(key,5,5); pivot_str=""; gap_str=""
    if candles.get("ok"):
        prev=prev_ohlc_from_candles(candles)
        if prev:
            piv=compute_pivots(prev["high"],prev["low"],prev["close"])
            pivot_str=f"Prev Close: {prev['close']:,.2f}\nPivot: {piv['pivot']:,.2f} | R1: {piv['r1']:,.2f} | S1: {piv['s1']:,.2f}\n"
            spot_r=neo_get_spot(key)
            if spot_r["ok"]:
                spot=spot_r["ltp"]; gp=(spot-prev["close"])/prev["close"]*100
                gi="⬆️" if gp>0 else "⬇️"
                gn="🚀 EXTREME GAP" if abs(gp)>1.75 else "🔥 LARGE GAP" if abs(gp)>1.00 else "⚠️ GAP DAY" if abs(gp)>0.55 else ""
                gap_str=f"Pre-open: {spot:,.2f} {gi} ({gp:+.2f}%) {gn}\n"
    max_sell,thresh=day_limits(); dow=datetime.now(IST).weekday()
    day_note=f"⚠️ Wednesday — max {max_sell} signal, threshold {thresh}\n" if dow==2 else ""
    tg(
        f"☀️ <b>PRE-MARKET — {u['name']}</b>{' ⚡ EXPIRY' if is_expiry(key) else ''}\n"
        f"{'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'} | Kotak Neo\n\n"
        f"{dte_str}{gap_str}{pivot_str}{day_note}\n"
        f"Target: ₹{DAILY_TARGET:,.0f} | Risk: ₹{MAX_RISK:,.0f}/scalp\n"
        f"9:15 → OR tracking | 9:30 → OR lock + first signal\n"
        f"<i>Bot silent until signal fires.</i>"
    )

def job_or_track():
    if not is_trading_day(): return
    or_track_tick()

def job_or_lock():
    if not is_trading_day(): return
    or_lock_and_announce()
    key,_=get_underlying()
    snap=build_snapshot(key)
    if "error" not in snap:
        mode,c=classify_regime(snap)
        try_fire(snap,mode,c,source="or_lock")

def job_regime():
    if not is_trading_day(): return
    now=datetime.now(IST)
    if now<now.replace(hour=9,minute=30) or now>now.replace(hour=14,minute=45): return
    def _run():
        try:
            key,_=get_underlying()
            snap=build_snapshot(key)
            if "error" in snap: print(f"[Regime] {snap['error']}"); return
            mode,c=classify_regime(snap)
            if "error" in c: return
            with REG_L:
                ld=REG.get("dir"); ls=REG.get("score"); lr=REG.get("reversal",False)
            nd=c["direction"]; ns=c["score"]; nr=c.get("reversal",False)
            flip=ld and nd and ld!=nd
            swung=ls is not None and abs(ns-ls)>=20
            rev_new=nr and not lr
            if flip or swung or rev_new:
                parts=[]
                if rev_new: parts.append("NEW reversal")
                if flip:    parts.append(f"{ld}→{nd}")
                if swung:   parts.append(f"Score {ls}→{ns}")
                tg(format_classifier_msg(snap,True," | ".join(parts)))
                print(f"[Regime] Alert: {' | '.join(parts)}")
            else:
                print(f"[Regime] Silent — dir={nd}, score={ns}")
            try_fire(snap,mode,c,source="regime")
        except Exception as e:
            print(f"[Regime] Error: {e}")
    t=threading.Thread(target=_run,daemon=True)
    t.start(); t.join(timeout=50)
    if t.is_alive(): print("[Regime] Timeout — releasing scheduler")

def format_classifier_msg(snap,is_update=False,trigger=None):
    mode,c=classify_regime(snap)
    if "error" in c: return f"❌ {c['error']}"
    u=c.get("underlying_name","NIFTY")
    hdr=f"🚨 <b>REGIME CHANGE — {u}</b>" if is_update else f"🧠 <b>REGIME — {u}</b>"
    msg=f"{hdr}\n"
    if trigger: msg+=f"<i>{trigger}</i>\n"
    msg+=f"{datetime.now(IST).strftime('%H:%M:%S')} IST\n"
    msg+=f"Spot: <b>{c['spot']:,.2f}</b> | DTE: {c['dte']}\n"
    if c["is_expiry_day"]: msg+="⚡ EXPIRY DAY\n"
    if c.get("is_trend_day"): msg+="🔥 TREND DAY\n"
    msg+=f"\n<b>━━ {c['verdict']} ━━</b>\n"
    msg+=f"Score: {c['score']}/100 | Threshold: {c['spread_threshold']}\n"
    msg+=f"Direction: <b>{c['direction']}</b> | {c['confluence']}\n"
    msg+=f"OI: {c['flow_score']:+d} | Bias: {c['bias_score']:+.2f}\n"
    if c.get("buy_signal"): msg+=f"{c['buy_signal']}\n"
    if c.get("skip_reasons"): msg+="🚫 "+" | ".join(c["skip_reasons"])+"\n"
    with RISK_L:
        sell=RISK["sell"]; buy=RISK["buy"]; realized=RISK["pnl"]
    max_sell,_=day_limits()
    msg+=f"\nSignals: {sell}/{max_sell} sell | {buy}/{MAX_BUY} buy"
    msg+=f"\nP&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}"
    msg+=f"\n<i>v4.1 Kotak Neo | {'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'}</i>"
    return msg

def job_pre_close():
    if not is_trading_day(): return
    key,_=get_underlying(); expiry_day=is_expiry(key)
    with RISK_L: sell=RISK["sell"]; buy=RISK["buy"]; realized=RISK["pnl"]
    with TRADE_L: trade_active=TRADE["active"]; TRADE["active"]=False
    msg=(f"⏰ <b>PRE-CLOSE</b>\nClose ALL positions NOW.\n"
         f"{'Exit by 2:30 PM (expiry)' if expiry_day else 'Hard exit: 3:00 PM'}\n"
         f"Today: {buy} scalps | {sell} sells\n"
         f"P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n")
    if trade_active: msg+="⚠️ <b>Active trade — close NOW</b>\n"
    tg(msg)

def job_eod():
    if not is_trading_day(): return
    key,u=get_underlying()
    with TRADE_L: TRADE["active"]=False
    snap=build_snapshot(key)
    if "error" not in snap:
        atm_iv=snap.get("atm_iv",0)
        if atm_iv>0: store_eod_iv(key,atm_iv)
    with RISK_L:
        sl_hits=RISK["sl"]; sell=RISK["sell"]; buy=RISK["buy"]; realized=RISK["pnl"]
    iv_days=len(load_iv().get(key,{}))
    icon="✅" if realized>=DAILY_TARGET else "⚠️" if realized>0 else "❌"
    tg(
        f"🌙 <b>EOD — {u['name']} | v4.1 Kotak Neo</b>\n\n"
        f"{icon} P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
        f"⚡ Scalps: {buy} | 📉 Sells: {sell} | 🛑 SL: {sl_hits}/2\n"
        f"IV history: {iv_days}/15 days\n"
        f"{'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'}"
    )

def job_health():
    _,u=get_underlying()
    print(f"[Health] {u['name']} {datetime.now(IST).strftime('%H:%M')}")


# ===== TELEGRAM LISTENER =====
def tg_updates(offset=None, timeout=30):
    params={"timeout":timeout}
    if offset: params["offset"]=offset
    try:
        r=requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
                       params=params,timeout=timeout+5)
        if r.status_code==200: return r.json().get("result",[])
    except Exception as e: print(f"[TG] {e}")
    return []

def handle_cmd(text, chat_id):
    text=text.strip().lower()
    if str(chat_id)!=str(TELEGRAM_CHAT_ID): return
    print(f"[TG] {text}")

    if text in ["/login"]:
        tg("⏳ Logging in to Kotak Neo...")
        if init_neo_client(): tg("✅ <b>Kotak Neo Connected</b>")
        else: tg("❌ Login failed. Check TOTP secret and MPIN in env.vars.")

    elif text in ["/snapshot","/snap"]:
        tg("⏳ Fetching...")
        snap=build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        a=snap["analysis"]; spot=a["spot"]; atm=a["atm"]
        msg=f"📸 {snap.get('underlying_name','NIFTY')} | {datetime.now(IST).strftime('%H:%M:%S')}\n"
        msg+=f"Spot: <b>{spot:,.2f}</b> | DTE: {snap.get('dte',5)}\n"
        msg+=f"ATM: {atm['strike']:,.0f} | PCR: {a['pcr']} | Max Pain: {a.get('max_pain',0):,.0f}\n"
        msg+=f"CE: ₹{atm['ce_ltp']:.2f} | IV: {atm['ce_iv']:.1f}%\n"
        msg+=f"PE: ₹{atm['pe_ltp']:.2f} | IV: {atm['pe_iv']:.1f}%\n"
        p=snap.get("pivots")
        if p: msg+=f"Pivot: {p['pivot']:,.2f} | R1: {p['r1']:,.2f} | S1: {p['s1']:,.2f}\n"
        msg+="🔴 Call OI\n"
        for s in a["top_ce_oi"][:3]:
            msg+=f"  {s['strike']:,.0f}: {s['ce_oi']:,} ({s['ce_oi_change']:+,})\n"
        msg+="🟢 Put OI\n"
        for s in a["top_pe_oi"][:3]:
            msg+=f"  {s['strike']:,.0f}: {s['pe_oi']:,} ({s['pe_oi_change']:+,})\n"
        tg(msg)

    elif text in ["/classify","/regime","/edge"]:
        tg("⏳ Classifying...")
        snap=build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        mode,c=classify_regime(snap)
        tg(format_classifier_msg(snap))
        try_fire(snap,mode,c,source="manual")

    elif text in ["/signal","/trade"]:
        tg("⏳ Computing...")
        snap=build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        mode,c=classify_regime(snap)
        if not try_fire(snap,mode,c,source="manual"):
            if mode=="SKIP":
                tg("🚫 <b>No Signal</b>\n"+"\n".join(f"• {r}" for r in c.get("skip_reasons",[])))
            else:
                tg(f"ℹ️ Mode: {mode} | Score: {c.get('score',0)}/{c.get('spread_threshold',50)}")

    elif text in ["/sl","/slhit"]: register_sl()

    elif text in ["/tradesquared","/closed"]:
        with TRADE_L: was=TRADE["active"]; TRADE["active"]=False
        tg("✅ Trade cleared." if was else "ℹ️ No active trade.")

    elif text in ["/monitor","/trade_status"]:
        with TRADE_L:
            if not TRADE["active"]: tg("ℹ️ No active trade."); return
            elapsed=int((datetime.now(IST)-TRADE["entry_time"]).total_seconds()/60)
            if TRADE["is_buy"]:
                tg(f"📊 <b>BUY Trade</b>\n{TRADE['buy_side'].upper()} {TRADE['buy_strike']:,.0f}\n"
                   f"Entry: ₹{TRADE['buy_entry']:.2f} | SL: ₹{TRADE['buy_sl']:.2f}\n"
                   f"L1: {'✅' if TRADE['l1_done'] else '⏳'} L2: {'✅' if TRADE['l2_done'] else '⏳'}\n"
                   f"Target: ₹{TRADE['buy_tgt']:.2f} | {elapsed} min")
            else:
                tg(f"📊 <b>SELL Trade</b>\nShort {TRADE['short_side'].upper()} {TRADE['short_strike']:,.0f}\n"
                   f"Entry: ₹{TRADE['entry_short']:.2f} | Credit: ₹{TRADE['net_credit']:.2f}/lot\n"
                   f"Target: {TRADE['tgt_pct']:.0%} | {elapsed} min")

    elif text in ["/nifty"]:
        snap=build_snapshot("nifty")
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        tg(format_classifier_msg(snap))

    elif text in ["/sensex"]:
        snap=build_snapshot("sensex")
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        tg(format_classifier_msg(snap))

    elif text in ["/spot","/ltp"]:
        key,u=get_underlying()
        r=neo_get_spot(key)
        if r["ok"]: tg(f"💰 <b>{u['name']}:</b> {r['ltp']:,.2f} | {datetime.now(IST).strftime('%H:%M:%S')}")
        else: tg(f"❌ {r.get('err')}")

    elif text in ["/or"]:
        with OR_L:
            if not OR["locked"]: tg("⏳ OR not locked yet."); return
            msg=(f"📊 <b>OR</b>\nHigh: {OR['high']:,.2f} | Low: {OR['low']:,.2f}\n"
                 f"Range: {OR['high']-OR['low']:.1f} pts\n"
                 f"Gap: {OR['gap_type']} ({OR['gap_pct']:+.2f}%)\n"
                 f"Trend day: {'✅' if OR['trend_day'] else '❌'}")
        tg(msg)

    elif text in ["/levels"]:
        snap=build_snapshot()
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        p=snap.get("pivots")
        if not p: tg("ℹ️ No pivot data"); return
        tg(f"📐 <b>Levels — {snap.get('underlying_name')}</b>\n"
           f"Spot: {snap['analysis']['spot']:,.2f}\n\n"
           f"R2: {p['r2']:,.2f} | R1: {p['r1']:,.2f}\n"
           f"<b>Pivot: {p['pivot']:,.2f}</b>\n"
           f"S1: {p['s1']:,.2f} | S2: {p['s2']:,.2f}")

    elif text in ["/expiries"]:
        key,u=get_underlying()
        r=neo_get_expiries(key)
        if not r["ok"]: tg(f"❌ {r.get('err')}"); return
        msg=f"📅 <b>Expiries — {u['name']}</b>\n"
        for i,exp in enumerate(r["expiries"][:5]):
            dte=compute_dte(exp); sweet="⭐" if 3<=dte<=5 else "⚡" if dte<=2 else ""
            msg+=f"  {i+1}. {exp} (DTE {dte}) {sweet}\n"
        tg(msg)

    elif text in ["/ivrank"]:
        key,u=get_underlying(); iv_data=load_iv().get(key,{}); days=len(iv_data)
        if days<15: tg(f"📊 IV Rank — {u['name']}\n{days}/15 days")
        else:
            values=list(iv_data.values())
            tg(f"📊 IV Rank — {u['name']}\nDays: {days} | High: {max(values):.1f}% | Low: {min(values):.1f}%")

    elif text in ["/today"]:
        key,u=get_underlying()
        dow_n={0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}
        dow=datetime.now(IST).weekday()
        with RISK_L:
            sl_hits=RISK["sl"]; halted=RISK["halted"]
            sell=RISK["sell"]; buy=RISK["buy"]; realized=RISK["pnl"]
        with TRADE_L: ts="✅ ACTIVE" if TRADE["active"] else "None"
        market="🏖️" if is_holiday() else "🔴" if is_weekend() else "✅ Trading"
        max_sell,thresh=day_limits()
        tg(f"📅 <b>{dow_n.get(dow,'?')} — {datetime.now(IST).strftime('%Y-%m-%d')}</b>\n"
           f"Market: {market} | <b>{u['name']}</b>\n\n"
           f"⚡ Scalps: {buy}/{MAX_BUY} | 📉 Sells: {sell}/{max_sell}\n"
           f"Threshold: {thresh}\n"
           f"P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
           f"Monitor: {ts}\n"
           f"SL: {sl_hits}/2 | {'🛑 HALTED' if halted else '✅ Active'}\n"
           f"{'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'}")

    elif text in ["/status","/ping"]:
        _,u=get_underlying()
        with REG_L: ld=REG.get("dir","N/A"); ls=REG.get("score","N/A"); lt=REG.get("time")
        with RISK_L:
            sl_hits=RISK["sl"]; halted=RISK["halted"]
            sell=RISK["sell"]; buy=RISK["buy"]; realized=RISK["pnl"]
        with TRADE_L: ta=TRADE["active"]
        max_sell,_=day_limits()
        market="🏖️" if is_holiday() else "🔴" if is_weekend() else "✅"
        client_ok=get_client() is not None
        tg(f"✅ <b>Mahakaal v4.1 — Kotak Neo</b>\n"
           f"{datetime.now(IST).strftime('%H:%M:%S')} IST | {market} {u['name']}\n"
           f"{'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'}\n"
           f"API: {'✅ Connected' if client_ok else '❌ Not logged in — send /login'}\n"
           f"Regime: {ld} ({ls}) @ {lt.strftime('%H:%M') if lt else 'N/A'}\n"
           f"⚡ Scalps: {buy}/{MAX_BUY} | 📉 Sells: {sell}/{max_sell}\n"
           f"P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
           f"Monitor: {'✅ ACTIVE' if ta else 'None'}\n"
           f"SL: {sl_hits}/2 | {'🛑 HALTED' if halted else '✅ Active'}")

    elif text in ["/help","/start"]:
        _,u=get_underlying(); max_sell,thresh=day_limits()
        tg(f"🤖 <b>Mahakaal v4.1 — Kotak Neo</b>\n"
           f"{'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'} | {u['name']}\n\n"
           f"<b>v4.1 Scalp-First:</b>\n"
           f"⚡ REVERSAL + MOMENTUM scalps\n"
           f"⚡ 35% target | 45min hold | 5/day\n"
           f"✅ Kotak Neo — ₹0 brokerage\n"
           f"✅ Auto TOTP login 8:30 AM\n"
           f"✅ GCP — stable, no phone\n\n"
           f"<b>Commands:</b>\n"
           f"/signal /classify /snapshot\n"
           f"/spot /or /levels /expiries /ivrank\n"
           f"/monitor /tradesquared /sl\n"
           f"/nifty /sensex /today /status /login\n\n"
           f"Today: {MAX_BUY} scalps | {max_sell} sells | risk ₹{MAX_RISK:,.0f}")
    else:
        tg(f"❓ Unknown: <code>{text}</code>\n/help")

def tg_listener():
    print("[TG] Listener starting...")
    last_id=None; processed=set()
    while True:
        try:
            updates=tg_updates(offset=last_id)
            for upd in updates:
                uid=upd["update_id"]; last_id=uid+1
                if uid in processed: continue
                processed.add(uid)
                if len(processed)>100: processed=set(list(processed)[-50:])
                msg=upd.get("message",{}); text=msg.get("text","")
                chat_id=msg.get("chat",{}).get("id")
                if text and chat_id: handle_cmd(text,chat_id)
        except Exception as e:
            print(f"[TG] {e}"); time.sleep(5)


# ===== MAIN =====
def main():
    print("="*60)
    print(f"MAHAKAAL v4.1 — KOTAK NEO | Paper={PAPER_TRADE_MODE}")
    print(f"Target: ₹{DAILY_TARGET:,.0f} | Risk: ₹{MAX_RISK:,.0f}/scalp")
    print(f"Started: {datetime.now(IST)}")
    print("="*60)

    reset_daily()
    if not init_neo_client():
        print("[Startup] Login failed — will retry at 8:30 AM or send /login")

    key,u=get_underlying()
    dow_n={0:"Monday",1:"Tuesday",2:"Wednesday",3:"Thursday",4:"Friday",5:"Saturday",6:"Sunday"}
    dow=datetime.now(IST).weekday()
    market=("🏖️ HOLIDAY" if is_holiday() else "🔴 WEEKEND" if is_weekend() else "✅ Trading")
    iv_days=len(load_iv().get(key,{}))
    client_ok=get_client() is not None

    tg(
        f"🚀 <b>Mahakaal v4.1 — Kotak Neo</b>\n"
        f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST\n"
        f"Mode: {'📝 PAPER' if PAPER_TRADE_MODE else '🔴 LIVE'}\n\n"
        f"<b>{dow_n.get(dow,'?')} → {u['name']}</b>\n"
        f"Market: {market}\n"
        f"API: {'✅ Connected' if client_ok else '⚠️ Send /login if needed'}\n\n"
        f"<b>v4.1 Scalp-First:</b>\n"
        f"⚡ REVERSAL + MOMENTUM entry paths\n"
        f"⚡ 35% quick target | 45min hold\n"
        f"⚡ 5 scalps/day | selling = backup only\n"
        f"✅ Kotak Neo — ₹0 brokerage F&O\n"
        f"✅ Auto TOTP login 8:30 AM\n"
        f"✅ GCP VM — stable 24/7\n"
        f"✅ Telegram retry — no missed alerts\n\n"
        f"IV history: {iv_days}/15 days\n"
        f"Send /help for commands."
    )

    scheduler=BlockingScheduler(timezone=IST)

    # Auto-login at 8:30 AM
    scheduler.add_job(job_login,
        CronTrigger(day_of_week="mon-fri",hour=8,minute=30,timezone=IST),id="login")

    # Pre-market
    scheduler.add_job(job_premarket,
        CronTrigger(day_of_week="mon-fri",hour=9,minute=0,timezone=IST),id="premarket")

    # OR tracking 9:15-9:29
    scheduler.add_job(job_or_track,
        CronTrigger(day_of_week="mon-fri",hour=9,minute="15-29",second="*/30",timezone=IST),
        id="or_track",max_instances=1,coalesce=True)

    # OR lock + first signal
    scheduler.add_job(job_or_lock,
        CronTrigger(day_of_week="mon-fri",hour=9,minute=30,timezone=IST),id="or_lock")

    # Regime checks every 5 min for scalping
    scheduler.add_job(job_regime,
        CronTrigger(day_of_week="mon-fri",hour="9",minute="35-59/5",timezone=IST),id="regime_9")
    scheduler.add_job(job_regime,
        CronTrigger(day_of_week="mon-fri",hour="10-14",minute="*/5",timezone=IST),id="regime_10")

    # Trade monitor every 5 min
    scheduler.add_job(monitor_trade,
        CronTrigger(day_of_week="mon-fri",hour="9-14",minute="*/5",timezone=IST),
        id="monitor",max_instances=1,coalesce=True)

    # Pre-close + EOD
    scheduler.add_job(job_pre_close,
        CronTrigger(day_of_week="mon-fri",hour=14,minute=55,timezone=IST),id="preclose")
    scheduler.add_job(job_eod,
        CronTrigger(day_of_week="mon-fri",hour=15,minute=30,timezone=IST),id="eod")
    scheduler.add_job(job_health,
        CronTrigger(minute=0,timezone=IST),id="health")

    print(f"[Scheduler] {len(scheduler.get_jobs())} jobs")
    threading.Thread(target=tg_listener,daemon=True).start()
    print("[Main] Running on GCP — bot silent until signals...")

    try:
        scheduler.start()
    except (KeyboardInterrupt,SystemExit):
        print("[Main] Stopped")

if __name__=="__main__":
    main()
