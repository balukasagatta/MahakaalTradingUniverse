"""
Mahakaal Options Sniper v5.0
=============================
Data:      Dhan API (candles, option chain, greeks, OI, L2)
Execution: Kotak Neo (zero brokerage) — paper mode now
Server:    GCP VM | Systemd | Telegram alerts

Strategy:
  SCALP MODE → Trend days (ADX>25, ER>0.5, OR wide)
    5 lots | SL ₹20 | Target ₹30 | 10min stop
    Supertrend(10,3) + Pivot + OR break + VWAP + L2 gate

  SELL MODE → Chop days (ADX<20, ER<0.25, OR narrow)
    2 lots | Spreads only | After 10:30 AM | DTE 3-5
    50% credit target | Hard exit 2:30 PM

  NO TRADE → Mixed signals → full silence

Day Classification (locked 10:30 AM):
  5 signals: ER, ADX(15m), OR width, Gap, VWAP direction
  4/5 TREND → SCALP | 4/5 CHOP → SELL | Mixed → NO TRADE

Schedule:
  8:30 → Kotak Neo auto-login (TOTP)
  9:00 → Pre-market brief
  9:15 → OR tracking
  9:30 → OR lock + asset premium check
  9:45 → Tentative classification (fire if 5/5)
  10:30 → Mode LOCKED
  Every 5m → Signal check + trade monitor
  2:30 → Hard exit sells
  2:55 → Pre-close alert
  3:30 → EOD summary
"""

import os, json, math, time, threading, requests, pyotp
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from neo_api_client import NeoAPI
from dhanhq import dhanhq, DhanContext

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
KOTAK_CONSUMER_KEY = os.getenv("KOTAK_CONSUMER_KEY", "")
KOTAK_MOBILE       = os.getenv("KOTAK_MOBILE", "")
KOTAK_MPIN         = os.getenv("KOTAK_MPIN", "")
KOTAK_UCC          = os.getenv("KOTAK_UCC", "")
KOTAK_TOTP_SECRET  = os.getenv("KOTAK_TOTP_SECRET", "")
DHAN_CLIENT_ID     = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN  = os.getenv("DHAN_ACCESS_TOKEN", "")
TG_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT            = os.getenv("TELEGRAM_CHAT_ID", "")
PAPER              = os.getenv("PAPER_TRADE_MODE", "true").lower() == "true"
IST                = pytz.timezone("Asia/Kolkata")
IV_FILE            = "iv_history.json"

# ===== DHAN CLIENT =====
_dhan = None
_dhan_lock = threading.Lock()

def init_dhan():
    global _dhan
    try:
        ctx = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        with _dhan_lock: _dhan = dhanhq(ctx)
        print("[Dhan] ✅ Client ready")
        return True
    except Exception as e:
        print(f"[Dhan] Init failed: {e}"); return False

def dhan():
    with _dhan_lock: return _dhan

# ===== KOTAK NEO CLIENT =====
_neo = None
_neo_lock = threading.Lock()

def neo_login():
    global _neo
    try:
        client = NeoAPI(environment='prod', access_token=None,
                        neo_fin_key=None, consumer_key=KOTAK_CONSUMER_KEY)
        totp = pyotp.TOTP(KOTAK_TOTP_SECRET).now()
        r1 = client.totp_login(mobile_number=KOTAK_MOBILE,
                               ucc=KOTAK_UCC, totp=totp)
        if r1.get('data', {}).get('status') != 'success':
            print(f"[Neo] Login failed: {r1}"); return False
        r2 = client.totp_validate(mpin=KOTAK_MPIN)
        if r2.get('data', {}).get('status') != 'success':
            print(f"[Neo] Validate failed: {r2}"); return False
        with _neo_lock: _neo = client
        print("[Neo] ✅ Connected")
        return True
    except Exception as e:
        print(f"[Neo] Login failed: {e}"); return False

def neo():
    with _neo_lock: return _neo

# ===== INIT =====
init_dhan()
print(f"[{datetime.now(IST)}] Mahakaal v5.0 starting | Paper={PAPER}")

# ===== UTILS =====
def now_ist(): return datetime.now(IST)
def today_str(): return now_ist().strftime("%Y-%m-%d")
def now_mins(): n=now_ist(); return n.hour*60+n.minute

def percentile(data, p):
    if not data or len(data)<2: return None
    s=sorted(data); k=(len(s)-1)*(p/100)
    f=math.floor(k); c=math.ceil(k)
    return s[int(k)] if f==c else s[f]*(c-k)+s[c]*(k-f)

# ===== HOLIDAYS =====
NSE_HOLIDAYS = {"2026-05-01","2026-06-17","2026-08-27","2026-10-02",
                "2026-10-14","2026-11-05","2026-11-06","2026-12-25"}
def is_holiday(): return today_str() in NSE_HOLIDAYS
def is_weekend(): return now_ist().weekday()>4
def is_trading_day(): return not is_weekend() and not is_holiday()

# ===== UNDERLYINGS =====
# Dhan security IDs confirmed working
UNDERLYINGS = {
    "nifty": {
        "name": "NIFTY",
        "dhan_id": "13",           # confirmed working
        "dhan_seg": "IDX_I",
        "dhan_fo_seg": "NSE_FNO",
        "expiry_weekday": 1,       # Tuesday
        "lot_size": 75,
        "strike_gap": 50,
        "scalp_qty": 5*75,         # 375
        "sell_qty": 2*75,          # 150
    },
    "sensex": {
        "name": "SENSEX",
        "dhan_id": "51",           # confirmed working
        "dhan_seg": "IDX_I",
        "dhan_fo_seg": "IDX_I",    # expiry list uses IDX_I for sensex
        "expiry_weekday": 3,       # Thursday
        "lot_size": 20,
        "strike_gap": 100,
        "scalp_qty": 5*20,         # 100
        "sell_qty": 2*20,          # 40
    },
}
DAY_MAP = {0:"sensex",1:"sensex",2:"nifty",3:"nifty",4:"nifty"}

def get_underlying():
    k=DAY_MAP.get(now_ist().weekday(),"nifty")
    return k, UNDERLYINGS[k]

def is_expiry(key=None):
    if key is None: key,_=get_underlying()
    return now_ist().weekday()==UNDERLYINGS[key]["expiry_weekday"]

def oi_thresh(key):
    return (50_000,200_000,500_000) if key=="sensex" else (500_000,2_000_000,5_000_000)

# ===== PARAMETERS =====
# Day classification
TREND_ER=0.50;  CHOP_ER=0.25
TREND_ADX=25;   CHOP_ADX=20
TREND_OR=1.5;   CHOP_OR=0.8
TREND_GAP=0.5;  CHOP_GAP=0.3

# Scalp
SCALP_LOTS=5; SCALP_SL=20; SCALP_TGT=30; SCALP_TIME=10; MAX_SCALPS=3
L2_RATIO=2.0; ST_PERIOD=10; ST_MULT=3.0
SCALP_PREM_MIN=200; SCALP_PREM_MAX=500

# Sell
SELL_LOTS=2; SELL_MIN_SCORE=65; SELL_DTE_MIN=3; SELL_DTE_MAX=5
SELL_TGT_PCT=0.50; SELL_SL_MULT=1.5; MAX_SELLS=2
SELL_START=(9,15); SELL_EXIT=(14,30)

# Risk
DAILY_TARGET=5_000; DAILY_LOSS_LIMIT=15_000; KILL_SL=2; DEDUP=120

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
            if i<retries-1: time.sleep(5)
    return False

# ===== STATE =====
OR_S = {"date":None,"high":None,"low":None,"ticks":0,"locked":False,"announced":False,
         "gap_type":"UNKNOWN","gap_pct":0.0,"gap_fixed":False}
OR_L = threading.Lock()

DAY_S = {"date":None,"mode":None,"locked":False,"trend":0,"chop":0,
          "er":None,"adx":None,"or_ratio":None,"gap_pct":0.0,"vwap_dir":None}
DAY_L = threading.Lock()

REG = {"pcr":None,"top_ce":None,"top_pe":None,"ce_mult":0,"pe_mult":0,"time":None}
REG_L = threading.Lock()

RISK = {"date":None,"sl":0,"halted":False,"scalps":0,"sells":0,
         "pnl":0,"scalp_pnl":0,"sell_pnl":0}
RISK_L = threading.Lock()

LAST = {"time":None,"mode":None}
LAST_L = threading.Lock()

TRADE = {"active":False,"is_buy":False,"strategy":None,
          "short_strike":None,"short_side":None,
          "entry_short":None,"net_credit":None,"tgt_pct":None,"sl_mult":None,
          "entry_time":None,"lots":None,"qty":None,"key":None,"expiry":None,
          "buy_strike":None,"buy_side":None,"buy_entry":None,"buy_tgt":None,"buy_sl":None,
          "l1_trig":None,"l1_sl":None,"l2_trig":None,"l2_sl":None,
          "l1_done":False,"l2_done":False}
TRADE_L = threading.Lock()

OI_HIST={}; OI_L=threading.Lock()
ADAPT={}
API_L=threading.Lock()

def adapt(key):
    if key not in ADAPT: ADAPT[key]={"er":[],"pcr":[],"flow":[],"adx":[]}
    return ADAPT[key]

# ===== DAILY RESET =====
def reset_daily():
    today=now_ist().date()
    with RISK_L:
        if RISK["date"]!=today:
            RISK.update({"date":today,"sl":0,"halted":False,"scalps":0,"sells":0,
                          "pnl":0,"scalp_pnl":0,"sell_pnl":0})
            print(f"[Risk] Reset {today}")
    with LAST_L:
        if LAST["time"] and LAST["time"].date()<today:
            LAST["time"]=None; LAST["mode"]=None
    with TRADE_L:
        if TRADE.get("entry_time") and TRADE["entry_time"].date()<today:
            TRADE["active"]=False
    with DAY_L:
        if DAY_S["date"]!=today:
            DAY_S.update({"date":today,"mode":None,"locked":False,"trend":0,"chop":0,
                           "er":None,"adx":None,"or_ratio":None,"gap_pct":0.0,"vwap_dir":None})

def register_sl(mode="scalp", loss=0):
    reset_daily()
    with RISK_L:
        RISK["sl"]+=1; RISK["pnl"]-=abs(loss)
        if mode=="scalp": RISK["scalp_pnl"]-=abs(loss)
        else: RISK["sell_pnl"]-=abs(loss)
        hits=RISK["sl"]
        if hits>=KILL_SL or abs(RISK["pnl"])>=DAILY_LOSS_LIMIT:
            RISK["halted"]=True
            tg(f"🛑 <b>KILL SWITCH</b>\n{'2 SL hits' if hits>=KILL_SL else 'Daily loss limit'}\nNo more signals today.")
            return True
        tg(f"⚠️ <b>SL Hit #{hits}</b> ({mode}) | -₹{abs(loss):,.0f}")
        return False

def register_profit(amount, mode="scalp"):
    with RISK_L:
        RISK["pnl"]+=amount
        if mode=="scalp": RISK["scalp_pnl"]+=amount
        else: RISK["sell_pnl"]+=amount

def is_allowed():
    reset_daily(); n=now_ist(); key,_=get_underlying()
    if is_weekend(): return False,"Weekend"
    if is_holiday(): return False,"Holiday"
    if n.hour>=15: return False,"After 3PM"
    if is_expiry(key) and n.hour>=14 and n.minute>=30: return False,"Expiry cutoff"
    if n.hour<9 or (n.hour==9 and n.minute<30): return False,"Pre-market"
    with RISK_L:
        if RISK["halted"]: return False,"Halted"
    return True,"OK"

def time_ok(mode):
    m=now_mins()
    if m<9*60+45:     return 0.75
    elif m<=11*60+30: return 1.00
    elif m<=12*60+30: return 0.85
    elif m<=14*60+30: return 0.95
    elif m<=14*60+45: return 0.80 if mode=="BUY" else 0.75
    else:             return 0.50

# ===== DHAN DATA LAYER =====
def dhan_candles(key, mins=5, days=7):
    """Fetch intraday candles. Confirmed working."""
    u=UNDERLYINGS[key]; d=dhan()
    if not d: return None
    try:
        today=now_ist().strftime("%Y-%m-%d")
        start=(now_ist()-timedelta(days=days)).strftime("%Y-%m-%d")
        r=d.intraday_minute_data(
            security_id=u["dhan_id"],
            exchange_segment=u["dhan_seg"],
            instrument_type="INDEX",
            from_date=start, to_date=today,
            interval=mins)
        if r.get("status")!="success": return None
        data=r["data"]
        return {"open":data["open"],"high":data["high"],"low":data["low"],
                "close":data["close"],"volume":data.get("volume",[0]*len(data["close"])),
                "timestamp":data.get("start_Time",[])}
    except Exception as e:
        print(f"[Dhan] Candles error: {e}"); return None

def dhan_expiries(key):
    """Get sorted upcoming expiry dates."""
    u=UNDERLYINGS[key]; d=dhan()
    if not d: return []
    try:
        # Sensex uses IDX_I, Nifty uses NSE_FNO
        seg = u["dhan_fo_seg"]
        r=d.expiry_list(int(u["dhan_id"]), seg)
        if r.get("status")!="success": return []
        data=r.get("data",{})
        if isinstance(data,dict): dates=data.get("data",[])
        else: dates=data
        today=now_ist().date()
        future=sorted([e for e in dates
                       if datetime.strptime(e,"%Y-%m-%d").date()>=today])
        return future
    except Exception as e:
        print(f"[Dhan] Expiry error: {e}"); return []

def dhan_option_chain(key, expiry_str):
    """
    Fetch option chain via direct REST API.
    Returns parsed chain with greeks, OI, L2.
    Confirmed working for both Nifty and Sensex.
    """
    u=UNDERLYINGS[key]
    headers={
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }
    try:
        r=requests.post("https://api.dhan.co/v2/optionchain",
            headers=headers,
            json={"UnderlyingScrip": int(u["dhan_id"]),
                  "UnderlyingSeg": u["dhan_seg"],
                  "Expiry": expiry_str},
            timeout=15)
        if r.status_code!=200: return None
        data=r.json().get("data",{})
        spot=data.get("last_price")
        oc=data.get("oc",{})
        if not spot or not oc: return None

        # Parse strikes
        with OI_L: prev=OI_HIST.get(key,{})
        strikes=[]
        for s_str,legs in oc.items():
            try:
                strike=float(s_str)
                ce=legs.get("ce",{}) or {}
                pe=legs.get("pe",{}) or {}
                cg=ce.get("greeks",{}) or {}
                pg=pe.get("greeks",{}) or {}
                ce_oi=float(ce.get("oi",0) or 0)
                pe_oi=float(pe.get("oi",0) or 0)
                ce_ltp=float(ce.get("last_price",0) or 0)
                pe_ltp=float(pe.get("last_price",0) or 0)
                if ce_ltp==0 and pe_ltp==0: continue
                strikes.append({
                    "strike":strike,
                    "ce_ltp":ce_ltp,"ce_oi":ce_oi,
                    "ce_oi_change":ce_oi-prev.get(f"{strike}_ce",ce_oi),
                    "ce_volume":float(ce.get("volume",0) or 0),
                    "ce_iv":float(ce.get("implied_volatility",0) or 0),
                    "ce_delta":float(cg.get("delta",0) or 0),
                    "ce_theta":float(cg.get("theta",0) or 0),
                    "ce_gamma":float(cg.get("gamma",0) or 0),
                    "ce_vega":float(cg.get("vega",0) or 0),
                    "ce_top_bid":float(ce.get("top_bid_price",0) or 0),
                    "ce_top_ask":float(ce.get("top_ask_price",0) or 0),
                    "ce_bid_qty":float(ce.get("top_bid_quantity",0) or 0),
                    "ce_ask_qty":float(ce.get("top_ask_quantity",0) or 0),
                    "ce_sid":ce.get("security_id",0),
                    "pe_ltp":pe_ltp,"pe_oi":pe_oi,
                    "pe_oi_change":pe_oi-prev.get(f"{strike}_pe",pe_oi),
                    "pe_volume":float(pe.get("volume",0) or 0),
                    "pe_iv":float(pe.get("implied_volatility",0) or 0),
                    "pe_delta":float(pg.get("delta",0) or 0),
                    "pe_theta":float(pg.get("theta",0) or 0),
                    "pe_gamma":float(pg.get("gamma",0) or 0),
                    "pe_vega":float(pg.get("vega",0) or 0),
                    "pe_top_bid":float(pe.get("top_bid_price",0) or 0),
                    "pe_top_ask":float(pe.get("top_ask_price",0) or 0),
                    "pe_bid_qty":float(pe.get("top_bid_quantity",0) or 0),
                    "pe_ask_qty":float(pe.get("top_ask_quantity",0) or 0),
                    "pe_sid":pe.get("security_id",0),
                })
            except: continue

        # Update OI history
        new_oi={f"{s['strike']}_ce":s["ce_oi"] for s in strikes}
        new_oi.update({f"{s['strike']}_pe":s["pe_oi"] for s in strikes})
        with OI_L: OI_HIST[key]=new_oi

        return {"spot":spot,"strikes":strikes,"expiry":expiry_str}
    except Exception as e:
        print(f"[Dhan] Chain error: {e}"); return None

def dhan_spot(key):
    """Get current spot from candles (last close)."""
    candles=dhan_candles(key,mins=1,days=1)
    if candles and candles["close"]:
        return candles["close"][-1]
    return None

# ===== INDICATORS =====
def compute_atr(h,l,c,period=14):
    if len(h)<period+1: return None
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(h))]
    return round(sum(trs[-period:])/period,2) if len(trs)>=period else None

def compute_ema(closes, period):
    if len(closes)<period: return None
    k=2/(period+1); ema=sum(closes[:period])/period
    for p in closes[period:]: ema=p*k+ema*(1-k)
    return round(ema,2)

def get_today_bars(candles, from_hour=9, from_min=30):
    """Extract today's candles from a combined candle set."""
    if not candles: return [],[],[],[],[]
    today=now_ist().date()
    cutoff_ts=now_ist().replace(hour=from_hour,minute=from_min,second=0,microsecond=0).timestamp()
    o,h,l,c,v=[],[],[],[],[]
    timestamps=candles.get("timestamp",[])
    if not timestamps:
        # No timestamps — detect session start by overnight gap
        closes=candles.get("close",[])
        opens=candles.get("open",[])
        highs=candles.get("high",[])
        lows=candles.get("low",[])
        vols=candles.get("volume",[])
        n=len(closes)
        session_start=max(0,n-75)
        for i in range(n-1,1,-1):
            if i<n-76: break
            if closes[i-1]>0 and abs(closes[i]-closes[i-1])/closes[i-1]>0.005:
                session_start=i; break
        o=opens[session_start:]; h=highs[session_start:]
        l=lows[session_start:];  c=closes[session_start:]
        v=vols[session_start:] if vols else [0]*len(c)
        return o,h,l,c,v
    for i,ts in enumerate(timestamps):
        try:
            if isinstance(ts,str):
                dt=datetime.strptime(ts[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=IST)
            else:
                dt=datetime.fromtimestamp(float(ts),IST)
            if dt.date()!=today: continue
            if dt.timestamp()<cutoff_ts: continue
        except: continue
        if i<len(candles.get("close",[])):
            o.append(candles["open"][i]); h.append(candles["high"][i])
            l.append(candles["low"][i]);  c.append(candles["close"][i])
            v.append(candles.get("volume",[0]*len(candles["close"]))[i])
    return o,h,l,c,v

def compute_vwap(candles, last_n=78):
    """VWAP from today's candles."""
    _,h,l,c,v=get_today_bars(candles)
    if not c: return None
    pv=sum((h[i]+l[i]+c[i])/3*v[i] for i in range(len(c)))
    vol=sum(v)
    return round(pv/vol,2) if vol>0 else None

def compute_er(candles, period=10):
    """Efficiency Ratio for trend detection."""
    _,_,_,c,_=get_today_bars(candles)
    if len(c)<6: return 0.3,"Early"
    if len(c)<period+1: period=len(c)-1
    recent=c[-period:]
    net=abs(recent[-1]-recent[0])
    total=sum(abs(recent[i]-recent[i-1]) for i in range(1,len(recent)))
    if total==0: return 0.0,"Flat"
    er=round(net/total,3)
    return er,("CHOPPY" if er<CHOP_ER else "TRENDING" if er>TREND_ER else "NORMAL")

def compute_adx(candles_15m, period=14):
    """ADX on 15-min candles for day classification."""
    h=candles_15m.get("high",[]); l=candles_15m.get("low",[]); c=candles_15m.get("close",[])
    if len(h)<period*2+1: return None
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(h))]
    dmp=[max(h[i]-h[i-1],0) if h[i]-h[i-1]>l[i-1]-l[i] else 0 for i in range(1,len(h))]
    dmm=[max(l[i-1]-l[i],0) if l[i-1]-l[i]>h[i]-h[i-1] else 0 for i in range(1,len(h))]
    def wilder(data, p):
        if len(data)<p: return []
        r=[sum(data[:p])]
        for i in range(p,len(data)): r.append(r[-1]-r[-1]/p+data[i])
        return r
    atr_s=wilder(trs,period); dp_s=wilder(dmp,period); dm_s=wilder(dmm,period)
    if not atr_s: return None
    dx=[]
    for i in range(len(atr_s)):
        if atr_s[i]==0: continue
        pdi=100*dp_s[i]/atr_s[i]; mdi=100*dm_s[i]/atr_s[i]
        if pdi+mdi==0: continue
        dx.append(100*abs(pdi-mdi)/(pdi+mdi))
    return round(sum(dx[-period:])/period,2) if len(dx)>=period else None

def compute_supertrend(candles_5m, period=ST_PERIOD, mult=ST_MULT):
    """Supertrend(10,3) on 5-min candles."""
    h=candles_5m.get("high",[]); l=candles_5m.get("low",[]); c=candles_5m.get("close",[])
    if len(h)<period+5: return None,None
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(h))]
    # Wilder ATR
    atr=[sum(trs[:period])/period]
    for i in range(period,len(trs)): atr.append((atr[-1]*(period-1)+trs[i])/period)
    if not atr: return None,None
    st=[]; direction=[]
    offset=len(h)-len(atr)-1
    for i in range(len(atr)):
        idx=i+offset+1
        if idx>=len(h): break
        hl2=(h[idx]+l[idx])/2
        upper=hl2+mult*atr[i]; lower=hl2-mult*atr[i]
        if i==0:
            val=lower if c[idx]>upper else upper
            st.append(val); direction.append("BUY" if c[idx]>val else "SELL")
        else:
            prev_st=st[-1]; prev_dir=direction[-1]
            if prev_dir=="BUY":
                val=max(lower,prev_st) if c[idx]>lower else upper
            else:
                val=min(upper,prev_st) if c[idx]<upper else lower
            st.append(val); direction.append("BUY" if c[idx]>val else "SELL")
    if not direction: return None,None
    return direction[-1], round(st[-1],2)

def compute_pivots(ph,pl,pc):
    p=(ph+pl+pc)/3
    return {"pivot":round(p,2),"r1":round(2*p-pl,2),"r2":round(p+(ph-pl),2),
            "s1":round(2*p-ph,2),"s2":round(p-(ph-pl),2)}

def prev_ohlc(candles):
    """Get previous day OHLC from candle data."""
    if not candles: return None
    today=now_ist().date()
    closes=candles.get("close",[]); highs=candles.get("high",[])
    lows=candles.get("low",[]); timestamps=candles.get("timestamp",[])

    if not timestamps:
        # No timestamps — use daily data endpoint
        return None

    by={}
    for i,ts in enumerate(timestamps):
        try:
            if isinstance(ts,str):
                dt=datetime.strptime(ts[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=IST)
            else:
                dt=datetime.fromtimestamp(float(ts),IST)
            d=dt.date()
            if d>=today: continue
            if d not in by: by[d]={"h":[],"l":[],"c":[]}
            by[d]["h"].append(highs[i]); by[d]["l"].append(lows[i])
            by[d]["c"].append(closes[i])
        except: continue

    if not by: return None
    last=max(by.keys())
    return {"high":max(by[last]["h"]),"low":min(by[last]["l"]),"close":by[last]["c"][-1]}

def prev_ohlc_direct(key):
    """Get previous day OHLC using daily candles API."""
    u=UNDERLYINGS[key]; d=dhan()
    if not d: return None
    try:
        today=now_ist().strftime("%Y-%m-%d")
        week_ago=(now_ist()-timedelta(days=10)).strftime("%Y-%m-%d")
        r=d.historical_daily_data(
            security_id=u["dhan_id"],
            exchange_segment=u["dhan_seg"],
            instrument_type="INDEX",
            from_date=week_ago, to_date=today)
        if r.get("status")!="success": return None
        data=r["data"]
        closes=data.get("close",[]); highs=data.get("high",[])
        lows=data.get("low",[])
        if len(closes)<2: return None
        # Second to last = previous day
        return {"high":highs[-2],"low":lows[-2],"close":closes[-2]}
    except Exception as e:
        print(f"[Dhan] Daily OHLC error: {e}"); return None

def compute_dte(expiry_str):
    try: return (datetime.strptime(expiry_str,"%Y-%m-%d").date()-now_ist().date()).days
    except: return 5

def detect_gap(prev_close, spot):
    if not prev_close or not spot: return "UNKNOWN",0.0
    pct=(spot-prev_close)/prev_close*100
    if pct>1.75:  return "EXTREME_GAP_UP",round(pct,2)
    if pct>1.00:  return "LARGE_GAP_UP",round(pct,2)
    if pct>0.55:  return "GAP_UP",round(pct,2)
    if pct<-1.75: return "EXTREME_GAP_DOWN",round(pct,2)
    if pct<-1.00: return "LARGE_GAP_DOWN",round(pct,2)
    if pct<-0.55: return "GAP_DOWN",round(pct,2)
    return "FLAT_OPEN",round(pct,2)

# ===== IV RANK =====
def load_iv():
    try:
        if os.path.exists(IV_FILE):
            with open(IV_FILE) as f: return json.load(f)
    except: pass
    return {}

def save_iv(h):
    try:
        with open(IV_FILE,"w") as f: json.dump(h,f)
    except: pass

def store_eod_iv(key, atm_iv):
    h=load_iv()
    if key not in h: h[key]={}
    h[key][today_str()]=round(atm_iv,2)
    sd=sorted(h[key].keys())
    for old in sd[:-90]: del h[key][old]
    save_iv(h)

def compute_iv_rank(key, iv):
    d=load_iv().get(key,{})
    if len(d)<15: return None
    vals=list(d.values()); hi,lo=max(vals),min(vals)
    return 50 if hi==lo else round((iv-lo)/(hi-lo)*100,1)

# ===== MAX PAIN =====
def max_pain(strikes):
    best=None; bp=float("inf")
    for s in strikes:
        t=s["strike"]
        pain=sum((t-k["strike"])*k["ce_oi"] if t>k["strike"] else
                 (k["strike"]-t)*k["pe_oi"] if t<k["strike"] else 0 for k in strikes)
        if pain<bp: bp=pain; best=t
    return best

# ===== ANALYZE CHAIN =====
def analyze_chain(chain_data):
    spot=chain_data.get("spot"); strikes=chain_data.get("strikes",[])
    if not spot or not strikes: return None
    atm=min(strikes,key=lambda x:abs(x["strike"]-spot))
    top_ce=sorted(strikes,key=lambda x:x["ce_oi"],reverse=True)[:5]
    top_pe=sorted(strikes,key=lambda x:x["pe_oi"],reverse=True)[:5]
    tce=sum(s["ce_oi"] for s in strikes); tpe=sum(s["pe_oi"] for s in strikes)
    return {"spot":spot,"atm":atm,"top_ce_oi":top_ce,"top_pe_oi":top_pe,
            "pcr":round(tpe/tce,2) if tce>0 else 0,
            "max_pain":max_pain(strikes),
            "total_ce_oi":tce,"total_pe_oi":tpe,"all_strikes":strikes}

# ===== OPENING RANGE =====
def or_reset(key):
    today=now_ist().date()
    with OR_L:
        if OR_S["date"]!=today:
            OR_S.update({"date":today,"high":None,"low":None,"ticks":0,
                          "locked":False,"announced":False,
                          "gap_type":"UNKNOWN","gap_pct":0.0,"gap_fixed":False})

def or_track():
    if not is_trading_day(): return
    key,_=get_underlying(); or_reset(key)
    with OR_L:
        if OR_S["locked"]: return
    ltp=dhan_spot(key)
    if ltp is None: return
    with OR_L:
        OR_S["high"]=max(OR_S["high"] or ltp,ltp)
        OR_S["low"]=min(OR_S["low"] or ltp,ltp)
        OR_S["ticks"]=(OR_S["ticks"] or 0)+1

def or_lock():
    if not is_trading_day(): return
    key,u=get_underlying(); or_reset(key)
    with OR_L:
        if OR_S["locked"] and OR_S["announced"]: return
        if OR_S["high"] is None:
            tg("⚠️ <b>OR Lock Delayed</b>\nRetrying in 15s")
            threading.Timer(15,or_lock).start(); return
        OR_S["locked"]=True; OR_S["announced"]=True
        oh,ol=OR_S["high"],OR_S["low"]

    # Get ATR for classification
    c5=dhan_candles(key,5,7)
    atr_val=None; ratio=None
    if c5:
        atr_val=compute_atr(c5["high"],c5["low"],c5["close"])
        if atr_val:
            ratio=round((oh-ol)/atr_val,2)
            with DAY_L: DAY_S["or_ratio"]=ratio

    # Get prev OHLC for gap
    prev=prev_ohlc_direct(key)
    if prev:
        gap_type,gap_pct=detect_gap(prev["close"],(oh+ol)/2)
        with OR_L: OR_S["gap_type"]=gap_type; OR_S["gap_pct"]=gap_pct; OR_S["gap_fixed"]=True
        with DAY_L: DAY_S["gap_pct"]=abs(gap_pct)
    else:
        gap_type,gap_pct="UNKNOWN",0.0

    hint=""
    if ratio:
        if ratio<CHOP_OR:   hint="🔻 COMPRESSED — lean SELL"
        elif ratio>TREND_OR: hint="🔥 WIDE — lean SCALP"
        else:               hint="✅ NORMAL"

    gap_str=f"\nGap: {gap_type.replace('_',' ')} ({gap_pct:+.2f}%)" if gap_type not in ["FLAT_OPEN","UNKNOWN"] else ""
    tg(f"📊 <b>OR LOCKED — {u['name']}</b>\n09:30 IST | {today_str()}\n\n"
       f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
       f"Range: {oh-ol:.1f} pts | Ticks: {OR_S['ticks']}\n"
       f"{'ATR: '+str(atr_val)+' | R/ATR: '+str(ratio)+' → '+hint if atr_val else ''}"
       f"{gap_str}"
       f"{chr(10)+'⚡ EXPIRY DAY — exit 2:30 PM' if is_expiry(key) else ''}\n\n"
       f"<i>Classification at 9:45 (tentative) and 10:30 (final)</i>")

# ===== SNAPSHOT =====
def build_snapshot(key=None):
    if not API_L.acquire(timeout=45): return {"error":"API busy"}
    try:
        if key is None: key,u=get_underlying()
        else: u=UNDERLYINGS[key]

        # Get expiries
        expiries=dhan_expiries(key)
        if not expiries: return {"error":f"No expiries for {u['name']}"}
        nearest=expiries[0]; dte=compute_dte(nearest)

        # Option chain (with greeks + L2)
        time.sleep(1.0)  # rate limit: 1 req per 3 sec
        chain=dhan_option_chain(key,nearest)
        if not chain: return {"error":f"{u['name']} chain failed"}

        analysis=analyze_chain(chain)
        if not analysis: return {"error":"Chain parse failed"}

        # 5-min candles
        c5=dhan_candles(key,5,7)
        atr_val=compute_atr(c5["high"],c5["low"],c5["close"]) if c5 else None

        # 15-min candles for ADX
        c15=dhan_candles(key,15,10)

        # Prev OHLC
        prev=prev_ohlc_direct(key)
        pivots=compute_pivots(prev["high"],prev["low"],prev["close"]) if prev else None

        # Gap
        with OR_L:
            if OR_S["gap_fixed"]: gap_type,gap_pct=OR_S["gap_type"],OR_S["gap_pct"]
            else:
                gap_type,gap_pct="UNKNOWN",0.0
                if prev:
                    gap_type,gap_pct=detect_gap(prev["close"],analysis["spot"])

        # Supertrend
        st_signal,st_val=(None,None)
        if c5: st_signal,st_val=compute_supertrend(c5)

        # IV rank
        atm=analysis["atm"]
        atm_iv=(atm.get("ce_iv",0)+atm.get("pe_iv",0))/2
        iv_rank=compute_iv_rank(key,atm_iv)

        return {
            "analysis":analysis,"expiry":nearest,"dte":dte,"atr":atr_val,
            "pivots":pivots,"candles5":c5,"candles15":c15,
            "underlying_key":key,"underlying_name":u["name"],
            "lot_size":u["lot_size"],"strike_gap":u["strike_gap"],
            "scalp_qty":u["scalp_qty"],"sell_qty":u["sell_qty"],
            "gap_type":gap_type,"gap_pct":gap_pct,
            "is_expiry_day":is_expiry(key),
            "atm_iv":round(atm_iv,2),"iv_rank":iv_rank,
            "st_signal":st_signal,"st_val":st_val,
        }
    finally:
        API_L.release()

# ===== OI FLOW =====
def compute_oi_flow(analysis, atr, key):
    if not analysis: return 0,[],False
    spot=analysis["spot"]; strikes=analysis["all_strikes"]
    atr_val=atr if atr else 25
    _,oi_sig,oi_strong=oi_thresh(key)
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
            signals.append(f"PCR rising {prev_pcr:.2f}→{pcr:.2f} +{pts}")
            if chg>0.30: reversal=True
        elif chg<-0.15:
            pts=15 if chg<-0.3 else 8; flow-=pts
            signals.append(f"PCR falling {prev_pcr:.2f}→{pcr:.2f} -{pts}")
            if chg<-0.30: reversal=True
        else: signals.append(f"PCR stable {pcr:.2f}")
    else: signals.append(f"PCR: {pcr:.2f}")

    # Volume surge detection
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

    if not surge_ce and not surge_pe: signals.append("No unusual volume")

    # OI wall breaks
    top_ce=analysis["top_ce_oi"][0]["strike"] if analysis["top_ce_oi"] else None
    top_pe=analysis["top_pe_oi"][0]["strike"] if analysis["top_pe_oi"] else None
    wall=False
    if top_ce and prev_ce and spot>=top_ce and prev_ce>spot-atr_val:
        flow+=30; reversal=True; wall=True; signals.append(f"🧱 CALL WALL BROKEN {top_ce:,.0f}")
    if top_pe and prev_pe and not wall and spot<=top_pe and prev_pe<spot+atr_val:
        flow-=30; reversal=True; signals.append(f"🧱 PUT WALL BROKEN {top_pe:,.0f}")
    if not wall and top_ce and top_pe:
        signals.append(f"Walls: CE {top_ce:,.0f} | PE {top_pe:,.0f}")

    flow=max(-100,min(100,flow))
    with REG_L:
        REG["ce_mult"]=curr_ce_m; REG["pe_mult"]=curr_pe_m
        REG["pcr"]=pcr; REG["time"]=now_ist()
        REG["top_ce"]=top_ce; REG["top_pe"]=top_pe
    return flow,signals,reversal

# ===== L2 GATE =====
def l2_check(atm_strike, direction):
    """Hard gate — checks bid/ask depth before entry."""
    if direction=="CALL":
        bid=atm_strike.get("ce_bid_qty",0); ask=atm_strike.get("ce_ask_qty",0)
        if bid==0 or ask==0: return True,"No L2 data (pass)"
        ratio=bid/ask
        ok=ratio>=L2_RATIO
        return ok,f"CE bid/ask={ratio:.1f} {'✅' if ok else '❌ BLOCKED'}"
    else:
        bid=atm_strike.get("pe_bid_qty",0); ask=atm_strike.get("pe_ask_qty",0)
        if bid==0 or ask==0: return True,"No L2 data (pass)"
        ratio=bid/ask
        ok=ratio>=L2_RATIO
        return ok,f"PE bid/ask={ratio:.1f} {'✅' if ok else '❌ BLOCKED'}"

# ===== DAY CLASSIFICATION =====
def classify_day(snap):
    """
    Score 5 signals. Returns (mode, trend_pts, chop_pts, details).
    mode: SCALP / SELL / NO_TRADE
    """
    c5=snap.get("candles5"); c15=snap.get("candles15")
    atr=snap.get("atr",25)
    details={}; trend_pts=0; chop_pts=0

    # 1. ER
    er,_=compute_er(c5) if c5 else (0.3,"No data")
    details["er"]=round(er,3)
    if er>TREND_ER: trend_pts+=1
    elif er<CHOP_ER: chop_pts+=1

    # 2. ADX (15-min)
    adx=compute_adx(c15) if c15 else None
    details["adx"]=adx
    if adx:
        if adx>TREND_ADX: trend_pts+=1
        elif adx<CHOP_ADX: chop_pts+=1

    # 3. OR width
    with DAY_L: orr=DAY_S.get("or_ratio")
    details["or_ratio"]=orr
    if orr:
        if orr>TREND_OR: trend_pts+=1
        elif orr<CHOP_OR: chop_pts+=1

    # 4. Gap
    with DAY_L: gap=DAY_S.get("gap_pct",0)
    details["gap_pct"]=gap
    if gap>TREND_GAP: trend_pts+=1
    elif gap<CHOP_GAP: chop_pts+=1

    # 5. VWAP direction
    vwap=compute_vwap(c5) if c5 else None
    spot=snap["analysis"]["spot"]
    vwap_dir=None
    if vwap and spot:
        diff=abs(spot-vwap)/spot*100
        if diff>0.3:   vwap_dir="DIRECTIONAL"; trend_pts+=1
        elif diff<0.15: vwap_dir="OSCILLATING"; chop_pts+=1
        else:           vwap_dir="NEUTRAL"
    details["vwap_dir"]=vwap_dir; details["vwap"]=vwap

    # Classify
    if trend_pts>=4:   mode="SCALP"
    elif chop_pts>=4:  mode="SELL"
    else:              mode="NO_TRADE"

    with DAY_L:
        DAY_S["er"]=er; DAY_S["adx"]=adx
        DAY_S["vwap_dir"]=vwap_dir
        DAY_S["trend"]=trend_pts; DAY_S["chop"]=chop_pts

    return mode,trend_pts,chop_pts,details

def announce_day_mode(mode, trend_pts, chop_pts, details, is_final=True):
    with DAY_L:
        if is_final: DAY_S["locked"]=True
        DAY_S["mode"]=mode

    label="🔒 FINAL" if is_final else "⏳ TENTATIVE"
    er=details.get("er",0); adx=details.get("adx")
    orr=details.get("or_ratio"); gap=details.get("gap_pct",0)
    vd=details.get("vwap_dir","?")

    def score_icon(val, t_thresh, c_thresh, higher_is_trend=True):
        if val is None: return "–"
        if higher_is_trend:
            return "✅T" if val>t_thresh else "✅C" if val<c_thresh else "○"
        else:
            return "✅T" if val<t_thresh else "✅C" if val>c_thresh else "○"

    icon="⚡" if mode=="SCALP" else "📉" if mode=="SELL" else "💰"
    tg(f"{icon} <b>DAY MODE [{label}]</b>\n\n"
       f"<b>{mode}</b> — Trend: {trend_pts}/5 | Chop: {chop_pts}/5\n\n"
       f"ER:      {er:.3f} {score_icon(er,TREND_ER,CHOP_ER)}\n"
       f"ADX:     {adx or 'N/A'} {score_icon(adx,TREND_ADX,CHOP_ADX) if adx else '–'}\n"
       f"OR/ATR:  {orr or 'N/A'} {score_icon(orr,TREND_OR,CHOP_OR) if orr else '–'}\n"
       f"Gap:     {gap:.2f}% {score_icon(gap,TREND_GAP,CHOP_GAP)}\n"
       f"VWAP:    {vd} {'✅T' if vd=='DIRECTIONAL' else '✅C' if vd=='OSCILLATING' else '–'}\n\n"
       f"{'⚡ SCALP signals active' if mode=='SCALP' else '📉 SELL signals active after 10:30' if mode=='SELL' else '💰 No trade today — cash is a position'}\n"
       f"<i>v5.0 | {'📝 PAPER' if PAPER else '🔴 LIVE'}</i>")

# ===== SCALP SIGNAL CHECK =====
def check_scalp(snap):
    """
    Returns (direction, score, reasons) or (None, 0, reasons).
    Needs L2 (mandatory) + 3 of 4 other triggers.
    """
    analysis=snap["analysis"]; spot=analysis["spot"]
    atr=snap.get("atr",25); pivots=snap.get("pivots")
    c5=snap.get("candles5",{}); key=snap.get("underlying_key","nifty")
    st_signal=snap.get("st_signal")

    flow_score,flow_sigs,reversal=compute_oi_flow(analysis,atr,key)

    # Determine direction
    if st_signal=="BUY" and flow_score>=0:    direction="CALL"
    elif st_signal=="SELL" and flow_score<=0: direction="PUT"
    elif flow_score>20:                       direction="CALL"
    elif flow_score<-20:                      direction="PUT"
    else: return None,0,["No clear direction (ST and OI conflicting)"]

    triggers=0; reasons=[]
    strikes=sorted(analysis["all_strikes"],key=lambda x:x["strike"])
    atm_s=min(strikes,key=lambda x:abs(x["strike"]-spot))

    # T1: Supertrend
    if st_signal:
        ok=(st_signal=="BUY")==(direction=="CALL")
        if ok: triggers+=1; reasons.append(f"✅ ST: {st_signal}")
        else: reasons.append(f"❌ ST: {st_signal} (against direction)")
    else: reasons.append("⚠️ ST: no data")

    # T2: Pivot confluence
    piv_ok=False
    if pivots and atr:
        prox=atr*0.4
        if direction=="CALL":
            piv_ok=(abs(spot-pivots["s1"])<prox or
                    abs(spot-pivots["pivot"])<prox or
                    spot>pivots["r1"])
        else:
            piv_ok=(abs(spot-pivots["r1"])<prox or
                    abs(spot-pivots["pivot"])<prox or
                    spot<pivots["s1"])
    if piv_ok: triggers+=1; reasons.append("✅ Pivot confluence")
    else: reasons.append("❌ Pivot (not near key level)")

    # T3: OR breakout with volume
    with OR_L:
        or_locked=OR_S["locked"]; or_high=OR_S["high"]; or_low=OR_S["low"]
    or_ok=False
    if or_locked and c5:
        _,_,_,c,v=get_today_bars(c5)
        avg_vol=sum(v)/len(v) if v else 1
        last_vol=v[-1] if v else 0
        vol_surge=last_vol>avg_vol*2
        if direction=="CALL": or_ok=spot>or_high and vol_surge
        else: or_ok=spot<or_low and vol_surge
    if or_ok: triggers+=1; reasons.append("✅ OR breakout + volume")
    else: reasons.append("❌ OR break (no breakout or low volume)")

    # T4: VWAP + EMA alignment
    vwap=compute_vwap(c5) if c5 else None
    _,_,_,c_bars,_=get_today_bars(c5) if c5 else ([],[],[],[],[])
    ema9=compute_ema(c_bars,9) if len(c_bars)>=9 else None
    vwap_ok=False
    if direction=="CALL": vwap_ok=bool(vwap and spot>vwap and (ema9 is None or spot>ema9))
    else: vwap_ok=bool(vwap and spot<vwap and (ema9 is None or spot<ema9))
    if vwap_ok: triggers+=1; reasons.append("✅ VWAP+EMA aligned")
    else: reasons.append("❌ VWAP+EMA (not aligned)")

    # L2 HARD GATE (mandatory)
    l2_ok,l2_msg=l2_check(atm_s,direction)
    reasons.append(f"L2: {l2_msg}")
    if not l2_ok: return None,0,reasons+["🚫 L2 hard gate FAILED"]

    reasons.append(f"OI flow: {flow_score:+d}")
    if reversal: reasons.append("⚡ OI reversal detected")

    if triggers>=3: return direction,triggers,reasons
    return None,triggers,reasons+[f"Only {triggers}/4 triggers (need 3+)"]

# ===== SELL SIGNAL CHECK =====
def check_sell(snap):
    n=now_ist()
    if n.hour<SELL_START[0] or (n.hour==SELL_START[0] and n.minute<SELL_START[1]):
        return False,"Before 10:30 AM"
    with DAY_L:
        mode=DAY_S.get("mode"); chop_score=DAY_S.get("chop",0)
    if mode!="SELL": return False,f"Day mode is {mode}"

    dte=snap.get("dte",5)
    if dte<SELL_DTE_MIN or dte>SELL_DTE_MAX:
        return False,f"DTE {dte} outside range {SELL_DTE_MIN}-{SELL_DTE_MAX}"

    score=0
    if chop_score>=4: score+=30
    with DAY_L:
        er=DAY_S.get("er",0.5); adx=DAY_S.get("adx",25)
    if er<CHOP_ER: score+=20
    if adx and adx<CHOP_ADX: score+=20
    iv_rank=snap.get("iv_rank")
    if iv_rank and iv_rank>45: score+=15
    flow_score,_,_=compute_oi_flow(snap["analysis"],snap.get("atr"),snap.get("underlying_key","nifty"))
    if abs(flow_score)<30: score+=15

    if score>=SELL_MIN_SCORE:
        return True,f"Score {score}/100 | DTE {dte} | IV {iv_rank or 'N/A'}"
    return False,f"Score {score} < {SELL_MIN_SCORE}"

# ===== SIGNAL DEDUP =====
def can_fire(mode):
    reset_daily()
    with RISK_L:
        if mode=="BUY" and RISK["scalps"]>=MAX_SCALPS: return False,"Max scalps"
        elif mode=="SELL" and RISK["sells"]>=MAX_SELLS: return False,"Max sells"
        if RISK["halted"]: return False,"Halted"
    with LAST_L:
        lt=LAST["time"]; lm=LAST["mode"]
    if lt and lm==mode and (now_ist()-lt).total_seconds()<DEDUP:
        return False,"Dedup window"
    return True,""

def record_signal(mode):
    with LAST_L: LAST["time"]=now_ist(); LAST["mode"]=mode
    with RISK_L:
        if mode=="BUY": RISK["scalps"]+=1
        else: RISK["sells"]+=1

# ===== FIRE SCALP =====
def fire_scalp(snap, direction):
    allowed,_=is_allowed()
    if not allowed and not PAPER: return False

    a=snap["analysis"]; spot=a["spot"]
    strikes=sorted(a["all_strikes"],key=lambda x:x["strike"])
    key=snap.get("underlying_key","nifty"); u=UNDERLYINGS[key]
    expiry=snap.get("expiry","N/A"); dte=snap.get("dte",5)
    qty=u["scalp_qty"]; is_paper=PAPER or not allowed

    # Find ATM option
    if direction=="CALL":
        cands=[s for s in strikes if SCALP_PREM_MIN<s["ce_ltp"]<SCALP_PREM_MAX]
        if not cands: return False
        atm=min(cands,key=lambda x:abs(x["strike"]-spot))
        prem=atm["ce_ltp"]; side="ce"
        strategy="BUY CALL"; strike=atm["strike"]
    else:
        cands=[s for s in strikes if SCALP_PREM_MIN<s["pe_ltp"]<SCALP_PREM_MAX]
        if not cands: return False
        atm=min(cands,key=lambda x:abs(x["strike"]-spot))
        prem=atm["pe_ltp"]; side="pe"
        strategy="BUY PUT"; strike=atm["strike"]

    sl_price=round(prem-SCALP_SL,2); tgt_price=round(prem+SCALP_TGT,2)
    t1=round(prem+SCALP_TGT*0.5,2)  # trail 1: +50% → SL to breakeven
    t2=round(prem+SCALP_TGT*0.8,2)  # trail 2: +80% → lock partial
    t2_sl=round(prem+SCALP_TGT*0.4,2)

    win=round((tgt_price-prem)*qty,0); loss=round((prem-sl_price)*qty,0)

    # Greeks from chain
    delta=atm.get(f"{side}_delta",0); iv=atm.get(f"{side}_iv",0)
    theta=atm.get(f"{side}_theta",0)

    st=snap.get("st_signal","?")
    with RISK_L: realized=RISK["pnl"]
    pfx="📝 <b>PAPER</b> — " if is_paper else "🔴 <b>LIVE</b> — "

    msg=(f"⚡ {pfx}<b>{u['name']} {strategy}</b>\n"
         f"DTE: {dte} | Spot: {spot:,.2f}\n"
         f"ST: {'🟢' if st=='BUY' else '🔴'}{st} | OI flow: {compute_oi_flow(a,snap.get('atr'),key)[0]:+d}\n\n"
         f"<b>Strike: {strike:,.0f}</b>\n"
         f"Entry: ₹{prem:.2f} | Qty: {qty:,}\n"
         f"Δ={delta:.3f} | IV={iv:.1f}% | Θ={theta:.2f}\n\n"
         f"<b>SL: ₹{sl_price:.2f} (-₹{SCALP_SL})</b>\n"
         f"<b>Target: ₹{tgt_price:.2f} (+₹{SCALP_TGT}) | R:R 1:1.5</b>\n"
         f"Win: +₹{win:,.0f} | Loss: -₹{loss:,.0f}\n\n"
         f"<b>Trails:</b>\n"
         f"T1 @ ₹{t1:.2f} (+50%) → SL to breakeven ₹{prem:.2f}\n"
         f"T2 @ ₹{t2:.2f} (+80%) → SL to ₹{t2_sl:.2f}\n"
         f"⏰ Time stop: {SCALP_TIME} min\n\n"
         f"Daily P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
         f"<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v5.0</i>")

    if tg(msg):
        record_signal("BUY")
        with TRADE_L:
            TRADE.update({"active":True,"is_buy":True,"strategy":strategy,
                "buy_strike":strike,"buy_side":side,
                "buy_entry":prem,"buy_tgt":tgt_price,"buy_sl":sl_price,
                "l1_trig":t1,"l1_sl":prem,"l2_trig":t2,"l2_sl":t2_sl,
                "entry_time":now_ist(),"qty":qty,"lots":SCALP_LOTS,
                "key":key,"expiry":expiry,"l1_done":False,"l2_done":False})
        print(f"[Signal] Scalp fired — {strategy} {strike} @ ₹{prem}")
        return True
    return False

# ===== FIRE SELL =====
def fire_sell(snap, reason):
    allowed,_=is_allowed()
    if not allowed and not PAPER: return False

    a=snap["analysis"]; spot=a["spot"]
    strikes=sorted(a["all_strikes"],key=lambda x:x["strike"])
    key=snap.get("underlying_key","nifty"); u=UNDERLYINGS[key]
    expiry=snap.get("expiry","N/A"); dte=snap.get("dte",5)
    qty=u["sell_qty"]; sg=u["strike_gap"]
    is_paper=PAPER or not allowed

    flow_score,_,_=compute_oi_flow(a,snap.get("atr"),key)
    if flow_score>20:    spread_type="BULL_PUT"
    elif flow_score<-20: spread_type="BEAR_CALL"
    else:                spread_type="IC"

    delta=0.22 if dte<=3 else 0.26; width=2

    def find_delta_strike(target, side):
        cands=[s for s in strikes if 25<s[f"{side}_ltp"]<700]
        if not cands: cands=[s for s in strikes if s[f"{side}_ltp"]>10]
        return min(cands,key=lambda x:abs(abs(x.get(f"{side}_delta",0))-target),default=None) if cands else None

    def find_offset_strike(base,offset,side):
        ts=base+offset*sg
        cands=[s for s in strikes if s[f"{side}_ltp"]>0]
        return min(cands,key=lambda x:abs(x["strike"]-ts),default=None) if cands else None

    net=0; max_loss=0; width_pts=0; strategy=""; order_msg=""
    short_strike=0; short_side="ce"

    if spread_type=="BULL_PUT":
        ps=find_delta_strike(delta,"pe")
        if not ps: return False
        ph=find_offset_strike(ps["strike"],-width,"pe")
        if not ph: return False
        net=ps["pe_ltp"]-ph["pe_ltp"]
        if net<=0: return False
        max_loss=abs(ps["strike"]-ph["strike"])-net
        width_pts=abs(ps["strike"]-ph["strike"])
        strategy="BULL PUT SPREAD"; short_strike=ps["strike"]; short_side="pe"
        order_msg=(f"1. BUY  {ph['strike']:,.0f} Put @ ₹{ph['pe_ltp']:.2f} × {qty}\n"
                   f"2. SELL {ps['strike']:,.0f} Put @ ₹{ps['pe_ltp']:.2f} × {qty}\n"
                   f"   Δ={ps.get('pe_delta',0):.2f} | IV={ps.get('pe_iv',0):.1f}% | Θ={ps.get('pe_theta',0):.2f}")

    elif spread_type=="BEAR_CALL":
        cs=find_delta_strike(delta,"ce")
        if not cs: return False
        ch=find_offset_strike(cs["strike"],width,"ce")
        if not ch: return False
        net=cs["ce_ltp"]-ch["ce_ltp"]
        if net<=0: return False
        max_loss=abs(ch["strike"]-cs["strike"])-net
        width_pts=abs(ch["strike"]-cs["strike"])
        strategy="BEAR CALL SPREAD"; short_strike=cs["strike"]; short_side="ce"
        order_msg=(f"1. BUY  {ch['strike']:,.0f} Call @ ₹{ch['ce_ltp']:.2f} × {qty}\n"
                   f"2. SELL {cs['strike']:,.0f} Call @ ₹{cs['ce_ltp']:.2f} × {qty}\n"
                   f"   Δ={cs.get('ce_delta',0):.2f} | IV={cs.get('ce_iv',0):.1f}% | Θ={cs.get('ce_theta',0):.2f}")

    else:  # IC
        cs=find_delta_strike(delta,"ce"); ps=find_delta_strike(delta,"pe")
        if not cs or not ps: return False
        ch=find_offset_strike(cs["strike"],width,"ce"); ph=find_offset_strike(ps["strike"],-width,"pe")
        if not ch or not ph: return False
        net=cs["ce_ltp"]+ps["pe_ltp"]-ch["ce_ltp"]-ph["pe_ltp"]
        if net<=0: return False
        max_loss=abs(ch["strike"]-cs["strike"])-net
        width_pts=abs(ch["strike"]-cs["strike"])
        strategy="IRON CONDOR"; short_strike=cs["strike"]; short_side="ce"
        order_msg=(f"1. BUY  {ch['strike']:,.0f} Call @ ₹{ch['ce_ltp']:.2f} × {qty}\n"
                   f"2. BUY  {ph['strike']:,.0f} Put  @ ₹{ph['pe_ltp']:.2f} × {qty}\n"
                   f"3. SELL {cs['strike']:,.0f} Call @ ₹{cs['ce_ltp']:.2f} × {qty}\n"
                   f"4. SELL {ps['strike']:,.0f} Put  @ ₹{ps['pe_ltp']:.2f} × {qty}")

    total_credit=round(net*qty,0)
    target_total=round(net*SELL_TGT_PCT*qty,0)
    sl_total=round(net*SELL_SL_MULT*qty,0)
    eff=round(net/(net+max_loss)*100,1) if (net+max_loss)>0 else 0

    with RISK_L: realized=RISK["pnl"]
    pfx="📝 <b>PAPER</b> — " if is_paper else "🔴 <b>LIVE</b> — "

    msg=(f"📉 {pfx}<b>{u['name']} {strategy}</b>\n"
         f"DTE: {dte} | Spot: {spot:,.2f}\n"
         f"{reason}\n\n"
         f"<b>{eff:.0f}% credit | {100-eff:.0f}% risk | {width_pts:.0f}pts wide</b>\n\n"
         f"<b>⚠️ Hedges FIRST always:</b>\n"
         f"{order_msg}\n\n"
         f"Credit: ₹{net:.2f}/lot | Total: ₹{total_credit:,.0f}\n"
         f"Target (50%): ₹{target_total:,.0f}\n"
         f"SL (1.5×): ₹{sl_total:,.0f}\n"
         f"Hard exit: 2:30 PM\n\n"
         f"Daily P&L: {'+'if realized>=0 else ''}₹{realized:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
         f"<i>{'📝 PAPER' if is_paper else '🔴 LIVE'} | v5.0</i>")

    if tg(msg):
        record_signal("SELL")
        with TRADE_L:
            TRADE.update({"active":True,"is_buy":False,"strategy":strategy,
                "short_strike":short_strike,"short_side":short_side,
                "entry_short":net,"net_credit":net,
                "tgt_pct":SELL_TGT_PCT,"sl_mult":SELL_SL_MULT,
                "entry_time":now_ist(),"lots":SELL_LOTS,"qty":qty,
                "key":key,"expiry":expiry})
        print(f"[Signal] Sell fired — {strategy} @ ₹{net:.2f} credit")
        return True
    return False

# ===== TRADE MONITOR =====
def monitor_trade():
    with TRADE_L:
        if not TRADE["active"]: return
        is_buy=TRADE["is_buy"]; key=TRADE["key"]
        entry_time=TRADE["entry_time"]
    if not is_trading_day(): return
    n=now_ist()
    if n<n.replace(hour=9,minute=30) or n>=n.replace(hour=15,minute=0): return

    # Hard exit sells at 2:30 PM
    if not is_buy and n.hour>=SELL_EXIT[0] and n.minute>=SELL_EXIT[1]:
        with TRADE_L: TRADE["active"]=False
        tg("⏰ <b>SELL HARD EXIT 2:30 PM</b>\nClose all spread legs now.\n→ /tradesquared")
        return

    # Fetch fresh chain
    expiries=dhan_expiries(key)
    if not expiries: return
    chain=dhan_option_chain(key,expiries[0])
    if not chain: return
    strikes=chain["strikes"]; spot=chain["spot"]
    elapsed=int((n-entry_time).total_seconds()/60)

    if is_buy: _monitor_buy(strikes,elapsed)
    else: _monitor_sell(strikes,spot,elapsed)

def _monitor_sell(strikes,spot,elapsed):
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
        tg(f"🎯 <b>TARGET HIT — EXIT NOW</b>\n{strategy}\n"
           f"₹{ep:.2f}→₹{current:.2f} | {captured:.0%} captured\n<b>+₹{pnl:,.0f}</b>\n→ /tradesquared")
        register_profit(pnl,"sell")
        with TRADE_L: TRADE["active"]=False; return
    if current>=ep*sm:
        loss=round((current-ep)*qty,0)
        tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n{strategy}\n"
           f"₹{ep:.2f}→₹{current:.2f}\n<b>-₹{loss:,.0f}</b>\n→ /sl")
        with TRADE_L: TRADE["active"]=False
        register_sl("sell",loss); return
    if elapsed>0 and elapsed%30==0:
        tg(f"📊 Sell | {elapsed}min | {sd.upper()} {ss:,.0f}\n"
           f"₹{ep:.2f}→₹{current:.2f} | Captured {captured:.0%} | {'+'if pnl>=0 else ''}₹{pnl:,.0f}")

def _monitor_buy(strikes,elapsed):
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

    if elapsed>=SCALP_TIME:
        tg(f"⏰ <b>TIME STOP {SCALP_TIME}min — EXIT NOW</b>\n"
           f"{bd.upper()} {bs:,.0f} | ₹{entry:.2f}→₹{current:.2f}\n"
           f"{'+'if pnl>=0 else ''}₹{pnl:,.0f}\n→ /tradesquared")
        if pnl>0: register_profit(pnl,"scalp")
        else: register_sl("scalp",abs(pnl))
        with TRADE_L: TRADE["active"]=False; return

    if current>=tgt:
        tg(f"🎯 <b>SCALP TARGET — BOOK NOW</b>\n"
           f"{bd.upper()} {bs:,.0f} | ₹{entry:.2f}→₹{current:.2f}\n"
           f"<b>+₹{pnl:,.0f} (+₹{SCALP_TGT}/unit)</b>\n→ /tradesquared")
        register_profit(pnl,"scalp")
        with TRADE_L: TRADE["active"]=False; return

    if current<=csl:
        tg(f"🛑 <b>SL HIT — EXIT NOW</b>\n"
           f"{bd.upper()} {bs:,.0f} | ₹{entry:.2f}→₹{current:.2f}\n"
           f"-₹{abs(pnl):,.0f}\n→ /sl")
        with TRADE_L: TRADE["active"]=False
        register_sl("scalp",abs(pnl)); return

    if not l2d and current>=l2t:
        tg(f"⭐ <b>TRAIL T2 — Move SL to ₹{l2s:.2f}</b>\n"
           f"Premium ₹{current:.2f} | Locked: +₹{round((l2s-entry)*qty,0):,.0f}")
        with TRADE_L: TRADE["buy_sl"]=l2s; TRADE["l2_done"]=True; return

    if not l1d and current>=l1t:
        tg(f"✅ <b>TRAIL T1 — SL to breakeven ₹{l1s:.2f}</b>\n"
           f"Premium ₹{current:.2f} | Cannot lose now")
        with TRADE_L: TRADE["buy_sl"]=l1s; TRADE["l1_done"]=True

# ===== JOBS =====
def job_login():
    if not is_trading_day(): return
    print("[Login] Auto-login 8:30 AM...")
    if neo_login(): tg(f"🔑 <b>Kotak Neo Connected</b>\n{now_ist().strftime('%H:%M:%S')} IST")
    else: tg("🚨 <b>Kotak Neo Login Failed</b>\nSend /login to retry.")

def job_premarket():
    if not is_trading_day(): return
    key,u=get_underlying(); reset_daily(); or_reset(key)
    expiries=dhan_expiries(key)
    dte_str=""
    if expiries:
        dte=compute_dte(expiries[0])
        sweet="⭐ SWEET SPOT" if 3<=dte<=5 else "⚡ GAMMA RISK" if dte<=2 else "📅 Early week"
        dte_str=f"DTE: {dte} — {sweet}\n"
    prev=prev_ohlc_direct(key)
    pivot_str=""; gap_str=""
    if prev:
        piv=compute_pivots(prev["high"],prev["low"],prev["close"])
        pivot_str=f"Prev: H={prev['high']:,.2f} L={prev['low']:,.2f} C={prev['close']:,.2f}\nPivot: {piv['pivot']:,.2f} | R1: {piv['r1']:,.2f} | S1: {piv['s1']:,.2f}\n"
        spot=dhan_spot(key)
        if spot:
            gp=(spot-prev["close"])/prev["close"]*100
            gi="⬆️" if gp>0 else "⬇️"
            gn="🚀 EXTREME" if abs(gp)>1.75 else "🔥 LARGE" if abs(gp)>1.00 else "⚠️ GAP" if abs(gp)>0.55 else ""
            gap_str=f"Pre-open: {spot:,.2f} {gi} ({gp:+.2f}%) {gn}\n"
    tg(f"☀️ <b>PRE-MARKET — {u['name']}</b>{' ⚡ EXPIRY' if is_expiry(key) else ''}\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | v5.0 Dhan+Kotak\n\n"
       f"{dte_str}{gap_str}{pivot_str}\n"
       f"Target: ₹{DAILY_TARGET:,.0f} | Scalp: {SCALP_LOTS}L | Sell: {SELL_LOTS}L\n"
       f"9:15→OR | 9:30→Lock | 9:45→Tentative | 10:30→LOCKED\n"
       f"<i>Bot silent until mode confirmed.</i>")

def job_or_track():
    if not is_trading_day(): return
    or_track()

def job_or_lock():
    if not is_trading_day(): return
    or_lock()

def job_classify(is_final=False):
    if not is_trading_day(): return
    n=now_ist()
    if n<n.replace(hour=9,minute=15): return
    with DAY_L:
        if DAY_S["locked"]: return
    key,_=get_underlying()
    snap=build_snapshot(key)
    if "error" in snap: print(f"[Classify] {snap['error']}"); return
    mode,trend_pts,chop_pts,details=classify_day(snap)
    # Always announce — no minimum score required
    announce_day_mode(mode,trend_pts,chop_pts,details,is_final)
    if mode!="NO_TRADE": job_signal_check()

def job_signal_check():
    if not is_trading_day(): return
    n=now_ist()
    if n<n.replace(hour=9,minute=30) or n>n.replace(hour=14,minute=55): return
    with RISK_L:
        if RISK["halted"]: return
    with TRADE_L:
        if TRADE["active"]: return
    with DAY_L:
        mode=DAY_S.get("mode"); locked=DAY_S.get("locked",False)
    if not mode or mode=="NO_TRADE": return
    pass  # no time lock

    key,_=get_underlying()
    snap=build_snapshot(key)
    if "error" in snap: print(f"[Signal] {snap['error']}"); return

    if mode=="SCALP":
        ok,_=can_fire("BUY")
        if not ok: return
        if time_ok("BUY")<0.70: return
        direction,score,reasons=check_scalp(snap)
        if direction:
            print(f"[Signal] Scalp {direction} — {score}/4 — {reasons[-3:]}")
            fire_scalp(snap,direction)
        else:
            print(f"[Signal] Scalp skipped — {reasons[-1]}")

    elif mode=="SELL":
        ok,_=can_fire("SELL")
        if not ok: return
        sell_ok,sell_reason=check_sell(snap)
        if sell_ok:
            print(f"[Signal] Sell — {sell_reason}")
            fire_sell(snap,sell_reason)
        else:
            print(f"[Signal] Sell skipped — {sell_reason}")

def job_pre_close():
    if not is_trading_day(): return
    with RISK_L: s=RISK["scalps"]; sv=RISK["sells"]; p=RISK["pnl"]
    with TRADE_L: ta=TRADE["active"]; TRADE["active"]=False
    tg(f"⏰ <b>PRE-CLOSE 2:55 PM</b>\nClose ALL positions NOW.\n"
       f"⚡ Scalps: {s} | 📉 Sells: {sv}\n"
       f"P&L: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
       f"{'⚠️ Active trade — CLOSE NOW' if ta else ''}")

def job_eod():
    if not is_trading_day(): return
    key,u=get_underlying()
    with TRADE_L: TRADE["active"]=False
    snap=build_snapshot(key)
    if "error" not in snap and snap.get("atm_iv",0)>0:
        store_eod_iv(key,snap["atm_iv"])
    with RISK_L:
        sl=RISK["sl"]; s=RISK["scalps"]; sv=RISK["sells"]
        p=RISK["pnl"]; sp=RISK["scalp_pnl"]; svp=RISK["sell_pnl"]
    with DAY_L: mode=DAY_S.get("mode","?")
    iv_days=len(load_iv().get(key,{}))
    icon="✅" if p>=DAILY_TARGET else "⚠️" if p>0 else "❌"
    tg(f"🌙 <b>EOD — {u['name']} | v5.0</b>\n\n"
       f"{icon} <b>Total: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}</b>\n\n"
       f"⚡ Scalps: {s} | {'+'if sp>=0 else ''}₹{sp:,.0f}\n"
       f"📉 Sells:  {sv} | {'+'if svp>=0 else ''}₹{svp:,.0f}\n\n"
       f"Mode: {mode} | SL: {sl}/2\n"
       f"IV days: {iv_days}/15\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

def job_health():
    _,u=get_underlying()
    print(f"[Health] {u['name']} {now_ist().strftime('%H:%M')} | Dhan: {dhan() is not None} | Neo: {neo() is not None}")

# ===== TELEGRAM COMMANDS =====
def tg_updates(offset=None, timeout=30):
    params={"timeout":timeout}
    if offset: params["offset"]=offset
    try:
        r=requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                       params=params,timeout=timeout+5)
        if r.status_code==200: return r.json().get("result",[])
    except Exception as e: print(f"[TG] {e}")
    return []

def handle_cmd(text, chat_id):
    text=text.strip().lower().split("@")[0]
    if str(chat_id)!=str(TG_CHAT): return
    print(f"[TG] {text}")

    if text=="/login":
        tg("⏳ Logging in to Kotak Neo...")
        if neo_login(): tg("✅ <b>Kotak Neo Connected</b>")
        else: tg("❌ Login failed. Check TOTP + MPIN in env.vars.")

    elif text in ["/signal","/trade"]:
        with DAY_L: mode=DAY_S.get("mode"); locked=DAY_S.get("locked",False)
        if False:  # removed lock
            tg(f"ℹ️ Day mode not locked yet (locks 10:30 AM).\nCurrent: {mode or 'pending'}")
            return
        tg(f"⏳ Checking {mode} signal...")
        job_signal_check()

    elif text in ["/classify","/mode","/regime"]:
        with DAY_L:
            mode=DAY_S.get("mode","?"); locked=DAY_S.get("locked",False)
            ts=DAY_S.get("trend",0); cs=DAY_S.get("chop",0)
            er=DAY_S.get("er"); adx=DAY_S.get("adx")
            vd=DAY_S.get("vwap_dir","?"); orr=DAY_S.get("or_ratio")
            gap=DAY_S.get("gap_pct",0)
        def si(v,t,c): return "✅T" if v and v>t else "✅C" if v and v<c else "–"
        tg(f"🧠 <b>Day Classification</b>\n\n"
           f"Mode: <b>{mode}</b> {'🔒 LOCKED' if locked else '⏳ pending'}\n"
           f"Trend: {ts}/5 | Chop: {cs}/5\n\n"
           f"ER:     {f'{er:.3f}' if er else 'N/A'} {si(er,TREND_ER,CHOP_ER)}\n"
           f"ADX:    {f'{adx:.1f}' if adx else 'N/A'} {si(adx,TREND_ADX,CHOP_ADX)}\n"
           f"OR/ATR: {f'{orr:.2f}' if orr else 'N/A'} {si(orr,TREND_OR,CHOP_OR)}\n"
           f"Gap:    {gap:.2f}% {si(gap,TREND_GAP,CHOP_GAP)}\n"
           f"VWAP:   {vd} {'✅T' if vd=='DIRECTIONAL' else '✅C' if vd=='OSCILLATING' else '–'}")

    elif text in ["/snapshot","/snap"]:
        tg("⏳ Fetching...")
        key,u=get_underlying()
        snap=build_snapshot(key)
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        a=snap["analysis"]; spot=a["spot"]; atm=a["atm"]
        st=snap.get("st_signal","?"); stv=snap.get("st_val")
        iv_rank=snap.get("iv_rank")
        c5=snap.get("candles5",{}); vwap=compute_vwap(c5) if c5 else None
        msg=f"📸 <b>{u['name']}</b> | {now_ist().strftime('%H:%M:%S')}\n"
        msg+=f"Spot: <b>{spot:,.2f}</b> | DTE: {snap.get('dte',5)}\n"
        msg+=f"ATM: {atm['strike']:,.0f} | PCR: {a['pcr']:.2f}\n"
        msg+=f"Max Pain: {a.get('max_pain',0):,.0f}\n"
        gap_type=snap.get("gap_type","FLAT_OPEN"); gap_pct=snap.get("gap_pct",0)
        if gap_type not in ["FLAT_OPEN","UNKNOWN"]:
            msg+=f"Gap: {gap_type.replace('_',' ')} ({gap_pct:+.2f}%)\n"
        if snap.get("is_expiry_day"): msg+="⚡ EXPIRY DAY\n"
        msg+=f"\n<b>Indicators:</b>\n"
        msg+=f"ST(10,3): {'🟢 BUY' if st=='BUY' else '🔴 SELL' if st=='SELL' else '❓'}"
        if stv: msg+=f" @ {stv:,.2f}"
        msg+="\n"
        if vwap: msg+=f"VWAP: {vwap:,.2f} ({'✅' if spot>vwap else '❌'})\n"
        if iv_rank is not None: msg+=f"IV Rank: {iv_rank:.0f}/100\n"
        with OR_L:
            if OR_S["locked"] and OR_S["high"]:
                oh=OR_S["high"]; ol=OR_S["low"]
                msg+=f"OR: {ol:,.2f}–{oh:,.2f} "
                if spot>oh: msg+=f"⬆️ (+{spot-oh:.0f})\n"
                elif spot<ol: msg+=f"⬇️ (-{ol-spot:.0f})\n"
                else: msg+="🎯 Inside\n"
        p=snap.get("pivots")
        if p: msg+=f"Pivot: {p['pivot']:,.2f} | R1: {p['r1']:,.2f} | S1: {p['s1']:,.2f}\n"
        msg+=f"\n<b>ATM:</b>\n"
        msg+=f"CE: ₹{atm['ce_ltp']:.2f} | IV: {atm['ce_iv']:.1f}% | Δ: {atm['ce_delta']:.3f}\n"
        msg+=f"PE: ₹{atm['pe_ltp']:.2f} | IV: {atm['pe_iv']:.1f}% | Δ: {atm['pe_delta']:.3f}\n"
        cb=atm.get("ce_bid_qty",0); ca=atm.get("ce_ask_qty",0)
        if cb or ca: msg+=f"CE L2: bid={cb:.0f} ask={ca:.0f} ratio={cb/ca:.1f}\n" if ca>0 else ""
        msg+=f"\n<b>🔴 Top CE OI:</b>\n"
        for s in a["top_ce_oi"][:3]:
            msg+=f"  {s['strike']:,.0f}: {s['ce_oi']:,.0f} ({s['ce_oi_change']:+,.0f})\n"
        msg+=f"<b>🟢 Top PE OI:</b>\n"
        for s in a["top_pe_oi"][:3]:
            msg+=f"  {s['strike']:,.0f}: {s['pe_oi']:,.0f} ({s['pe_oi_change']:+,.0f})\n"
        tg(msg)

    elif text=="/nifty":
        tg("⏳ Fetching Nifty...")
        snap=build_snapshot("nifty")
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        a=snap["analysis"]; spot=a["spot"]; atm=a["atm"]
        st=snap.get("st_signal","?")
        tg(f"📸 <b>NIFTY</b> | {now_ist().strftime('%H:%M:%S')}\n"
           f"Spot: <b>{spot:,.2f}</b> | DTE: {snap.get('dte',5)}\n"
           f"ATM: {atm['strike']:,.0f} | PCR: {a['pcr']:.2f}\n"
           f"ST: {'🟢 BUY' if st=='BUY' else '🔴 SELL' if st=='SELL' else '❓'}\n"
           f"CE: ₹{atm['ce_ltp']:.2f} | IV: {atm['ce_iv']:.1f}% | Δ: {atm['ce_delta']:.3f}\n"
           f"PE: ₹{atm['pe_ltp']:.2f} | IV: {atm['pe_iv']:.1f}% | Δ: {atm['pe_delta']:.3f}")

    elif text=="/sensex":
        tg("⏳ Fetching Sensex...")
        snap=build_snapshot("sensex")
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        a=snap["analysis"]; spot=a["spot"]; atm=a["atm"]
        st=snap.get("st_signal","?")
        tg(f"📸 <b>SENSEX</b> | {now_ist().strftime('%H:%M:%S')}\n"
           f"Spot: <b>{spot:,.2f}</b> | DTE: {snap.get('dte',5)}\n"
           f"ATM: {atm['strike']:,.0f} | PCR: {a['pcr']:.2f}\n"
           f"ST: {'🟢 BUY' if st=='BUY' else '🔴 SELL' if st=='SELL' else '❓'}\n"
           f"CE: ₹{atm['ce_ltp']:.2f} | IV: {atm['ce_iv']:.1f}% | Δ: {atm['ce_delta']:.3f}\n"
           f"PE: ₹{atm['pe_ltp']:.2f} | IV: {atm['pe_iv']:.1f}% | Δ: {atm['pe_delta']:.3f}")

    elif text=="/oi":
        tg("⏳ Fetching OI...")
        key,u=get_underlying()
        snap=build_snapshot(key)
        if "error" in snap: tg(f"❌ {snap['error']}"); return
        a=snap["analysis"]; spot=a["spot"]
        top_ce=a["top_ce_oi"][0]["strike"] if a["top_ce_oi"] else None
        top_pe=a["top_pe_oi"][0]["strike"] if a["top_pe_oi"] else None
        msg=f"📊 <b>OI — {u['name']}</b>\nSpot: {spot:,.2f} | PCR: {a['pcr']:.2f}\nMax Pain: {a.get('max_pain',0):,.0f}\n\n"
        msg+="<b>🔴 Call OI (resistance):</b>\n"
        for s in a["top_ce_oi"][:5]:
            dist=s["strike"]-spot
            msg+=f"  {s['strike']:,.0f} ({dist:+.0f}): {s['ce_oi']:,.0f} ({s['ce_oi_change']:+,.0f})\n"
        msg+="<b>🟢 Put OI (support):</b>\n"
        for s in a["top_pe_oi"][:5]:
            dist=s["strike"]-spot
            msg+=f"  {s['strike']:,.0f} ({dist:+.0f}): {s['pe_oi']:,.0f} ({s['pe_oi_change']:+,.0f})\n"
        if top_ce and top_pe:
            msg+=f"\nCall wall: {top_ce:,.0f} | Put wall: {top_pe:,.0f}\n"
            msg+=f"Range: {top_pe:,.0f}–{top_ce:,.0f} ({top_ce-top_pe:.0f} pts)"
        tg(msg)

    elif text in ["/sl","/slhit"]:
        with TRADE_L:
            mode="scalp" if TRADE.get("is_buy") else "sell"
            TRADE["active"]=False
        register_sl(mode)

    elif text in ["/tradesquared","/closed"]:
        with TRADE_L: was=TRADE["active"]; TRADE["active"]=False
        tg("✅ Trade cleared." if was else "ℹ️ No active trade.")

    elif text in ["/monitor","/trade_status"]:
        with TRADE_L:
            if not TRADE["active"]: tg("ℹ️ No active trade."); return
            elapsed=int((now_ist()-TRADE["entry_time"]).total_seconds()/60)
            if TRADE["is_buy"]:
                tg(f"📊 <b>SCALP | {elapsed} min</b>\n"
                   f"Strike: {TRADE['buy_strike']:,.0f} {TRADE['buy_side'].upper()}\n"
                   f"Entry: ₹{TRADE['buy_entry']:.2f} | SL: ₹{TRADE['buy_sl']:.2f}\n"
                   f"Target: ₹{TRADE['buy_tgt']:.2f}\n"
                   f"T1: {'✅' if TRADE['l1_done'] else '⏳'} | T2: {'✅' if TRADE['l2_done'] else '⏳'}\n"
                   f"Time stop: {SCALP_TIME} min")
            else:
                tg(f"📊 <b>SELL | {elapsed} min</b>\n"
                   f"{TRADE['strategy']}\n"
                   f"Short: {TRADE['short_side'].upper()} {TRADE['short_strike']:,.0f}\n"
                   f"Credit: ₹{TRADE['net_credit']:.2f}/lot\n"
                   f"Target: {TRADE['tgt_pct']:.0%} | Hard exit: 2:30 PM")

    elif text=="/or":
        with OR_L:
            if not OR_S["locked"]:
                tg("⏳ OR not locked yet (locks at 9:30 AM)."); return
            oh=OR_S["high"]; ol=OR_S["low"]
            gt=OR_S["gap_type"]; gp=OR_S["gap_pct"]; ticks=OR_S["ticks"]
        spot=dhan_spot(get_underlying()[0])
        pos=""
        if spot:
            if spot>oh: pos=f"⬆️ ABOVE (+{spot-oh:.0f} pts)"
            elif spot<ol: pos=f"⬇️ BELOW (-{ol-spot:.0f} pts)"
            else: pos="🎯 INSIDE"
        tg(f"📊 <b>Opening Range</b>\n"
           f"High: {oh:,.2f} | Low: {ol:,.2f}\n"
           f"Range: {oh-ol:.1f} pts | Ticks: {ticks}\n"
           f"Gap: {gt.replace('_',' ')} ({gp:+.2f}%)\n"
           f"{'Spot '+str(round(spot,2))+' → '+pos if spot else ''}")

    elif text in ["/spot","/ltp"]:
        key,u=get_underlying()
        ltp=dhan_spot(key)
        if ltp: tg(f"💰 <b>{u['name']}:</b> {ltp:,.2f} | {now_ist().strftime('%H:%M:%S')}")
        else: tg("❌ Could not fetch spot")

    elif text=="/levels":
        tg("⏳ Fetching levels...")
        key,u=get_underlying()
        prev=prev_ohlc_direct(key)
        if not prev: tg("❌ Could not fetch previous OHLC.\nSend /login and retry."); return
        p=compute_pivots(prev["high"],prev["low"],prev["close"])
        spot=dhan_spot(key)
        def here(v): return "  ← HERE" if spot and abs(spot-v)<15 else ""
        tg(f"📐 <b>Levels — {u['name']}</b>\n"
           f"Prev: H={prev['high']:,.2f} L={prev['low']:,.2f} C={prev['close']:,.2f}\n\n"
           f"R2: <b>{p['r2']:,.2f}</b>{here(p['r2'])}\n"
           f"R1: <b>{p['r1']:,.2f}</b>{here(p['r1'])}\n"
           f"<b>Pivot: {p['pivot']:,.2f}</b>{here(p['pivot'])}\n"
           f"S1: <b>{p['s1']:,.2f}</b>{here(p['s1'])}\n"
           f"S2: <b>{p['s2']:,.2f}</b>{here(p['s2'])}\n"
           f"{'Spot: '+str(round(spot,2)) if spot else ''}")

    elif text in ["/expiries","/expiry"]:
        key,u=get_underlying()
        exps=dhan_expiries(key)
        if not exps: tg("❌ No expiry data."); return
        msg=f"📅 <b>Expiries — {u['name']}</b>\n"
        for i,e in enumerate(exps[:6]):
            dte=compute_dte(e)
            sweet="⭐ SWEET" if 3<=dte<=5 else "⚡ GAMMA" if dte<=2 else "📅"
            msg+=f"  {i+1}. {e} (DTE {dte}) {sweet}\n"
        tg(msg)

    elif text in ["/ivrank","/iv"]:
        key,u=get_underlying(); d=load_iv().get(key,{}); days=len(d)
        if days<15:
            tg(f"📊 IV Rank — {u['name']}\n{days}/15 days | Need {15-days} more")
        else:
            vals=list(d.values())
            tg(f"📊 IV Rank — {u['name']}\n"
               f"{days} days | High: {max(vals):.1f}% | Low: {min(vals):.1f}%")

    elif text=="/today":
        key,u=get_underlying()
        with RISK_L:
            sl=RISK["sl"]; h=RISK["halted"]
            s=RISK["scalps"]; sv=RISK["sells"]
            p=RISK["pnl"]; sp=RISK["scalp_pnl"]; svp=RISK["sell_pnl"]
        with DAY_L: mode=DAY_S.get("mode","?"); locked=DAY_S.get("locked",False)
        with TRADE_L: ta="✅ ACTIVE" if TRADE["active"] else "None"
        market="🏖️" if is_holiday() else "🔴" if is_weekend() else "✅ Trading"
        tg(f"📅 <b>{now_ist().strftime('%A %d %b %Y')}</b>\n"
           f"Market: {market} | <b>{u['name']}</b>\n\n"
           f"Mode: <b>{mode}</b> {'🔒' if locked else '⏳'}\n\n"
           f"⚡ Scalps: {s}/{MAX_SCALPS} | {'+'if sp>=0 else ''}₹{sp:,.0f}\n"
           f"📉 Sells:  {sv}/{MAX_SELLS} | {'+'if svp>=0 else ''}₹{svp:,.0f}\n"
           f"<b>Total: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}</b>\n\n"
           f"Monitor: {ta}\n"
           f"SL: {sl}/2 | {'🛑 HALTED' if h else '✅ Active'}\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

    elif text in ["/status","/ping"]:
        _,u=get_underlying()
        with RISK_L:
            sl=RISK["sl"]; h=RISK["halted"]
            s=RISK["scalps"]; sv=RISK["sells"]; p=RISK["pnl"]
        with DAY_L: mode=DAY_S.get("mode","?"); locked=DAY_S.get("locked",False)
        with TRADE_L: ta=TRADE["active"]
        with REG_L: rt=REG.get("time")
        dhan_ok=dhan() is not None; neo_ok=neo() is not None
        market="🏖️" if is_holiday() else "🔴" if is_weekend() else "✅"
        tg(f"✅ <b>Mahakaal v5.0</b>\n"
           f"{now_ist().strftime('%H:%M:%S')} IST | {market} {u['name']}\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
           f"Dhan: {'✅' if dhan_ok else '❌'} | Neo: {'✅' if neo_ok else '❌ /login'}\n\n"
           f"Mode: <b>{mode}</b> {'🔒' if locked else '⏳'}\n"
           f"⚡ Scalps: {s}/{MAX_SCALPS} | 📉 Sells: {sv}/{MAX_SELLS}\n"
           f"P&L: {'+'if p>=0 else ''}₹{p:,.0f} / ₹{DAILY_TARGET:,.0f}\n"
           f"Monitor: {'✅' if ta else 'None'}\n"
           f"SL: {sl}/2 | {'🛑 HALTED' if h else '✅ Active'}\n"
           f"Last OI: {rt.strftime('%H:%M') if rt else 'N/A'}")

    elif text in ["/help","/start"]:
        _,u=get_underlying()
        tg(f"🤖 <b>Mahakaal v5.0</b>\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | {u['name']}\n"
           f"Data: Dhan | Execution: Kotak Neo\n\n"
           f"<b>Strategy:</b>\n"
           f"⚡ SCALP → Trend | 5L | SL₹20 TGT₹30 | 10min\n"
           f"   ST+Pivot+OR+VWAP+L2 gate\n"
           f"📉 SELL → Chop | 2L | Spreads | After 10:30\n"
           f"💰 NO TRADE → Mixed → silence\n\n"
           f"<b>Commands:</b>\n"
           f"/signal — force signal check\n"
           f"/classify — day mode + scores\n"
           f"/snapshot — full market data\n"
           f"/nifty /sensex — index snapshot\n"
           f"/oi — OI walls + PCR\n"
           f"/spot — live LTP\n"
           f"/or — opening range\n"
           f"/levels — pivot levels\n"
           f"/expiries — upcoming expiries\n"
           f"/ivrank — IV rank history\n"
           f"/monitor — active trade\n"
           f"/tradesquared — clear trade\n"
           f"/sl — register SL hit\n"
           f"/today — day summary\n"
           f"/status — bot health\n"
           f"/login — Kotak Neo login")

    else:
        tg(f"❓ Unknown: <code>{text}</code>\nSend /help")

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
    print(f"MAHAKAAL v5.0 | Paper={PAPER}")
    print(f"Data: Dhan | Execution: Kotak Neo")
    print(f"Target: ₹{DAILY_TARGET:,.0f} | Scalp: {SCALP_LOTS}L | Sell: {SELL_LOTS}L")
    print(f"Started: {now_ist()}")
    print("="*60)

    reset_daily()
    neo_ok=neo_login()

    key,u=get_underlying()
    dow_n={0:"Monday",1:"Tuesday",2:"Wednesday",3:"Thursday",
           4:"Friday",5:"Saturday",6:"Sunday"}
    market="🏖️ HOLIDAY" if is_holiday() else "🔴 WEEKEND" if is_weekend() else "✅ Trading"
    iv_days=len(load_iv().get(key,{}))

    tg(f"🚀 <b>Mahakaal v5.0</b>\n"
       f"{now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'} | {dow_n.get(now_ist().weekday(),'?')} → {u['name']}\n"
       f"Market: {market}\n"
       f"Dhan: ✅ | Neo: {'✅' if neo_ok else '⚠️ /login'}\n\n"
       f"<b>v5.0 Architecture:</b>\n"
       f"📊 Data: Dhan (chain+greeks+candles+OI+L2)\n"
       f"⚡ SCALP: 5 lots | SL ₹20 | TGT ₹30 | 10min\n"
       f"   ST(10,3) + Pivot + OR + VWAP + L2 gate\n"
       f"📉 SELL: 2 lots | Spreads | After 10:30 AM\n"
       f"💰 NO TRADE: Mixed signals → cash\n\n"
       f"Day classification: 9:45 tentative | 10:30 final\n"
       f"Kill switch: {KILL_SL} SL hits OR ₹{DAILY_LOSS_LIMIT:,.0f} loss\n"
       f"IV history: {iv_days}/15 days\n"
       f"/help for commands")

    scheduler=BlockingScheduler(timezone=IST)
    scheduler.add_job(job_login,
        CronTrigger(day_of_week="mon-fri",hour=8,minute=30,timezone=IST),id="login")
    scheduler.add_job(job_premarket,
        CronTrigger(day_of_week="mon-fri",hour=9,minute=0,timezone=IST),id="premarket")
    scheduler.add_job(job_or_track,
        CronTrigger(day_of_week="mon-fri",hour=9,minute="15-29",second="*/30",timezone=IST),
        id="or_track",max_instances=1,coalesce=True)
    scheduler.add_job(job_or_lock,
        CronTrigger(day_of_week="mon-fri",hour=9,minute=30,timezone=IST),id="or_lock")
    scheduler.add_job(lambda: job_classify(False),
        CronTrigger(day_of_week="mon-fri",hour=9,minute=45,timezone=IST),id="classify_tentative")
    scheduler.add_job(lambda: job_classify(True),
        CronTrigger(day_of_week="mon-fri",hour=10,minute=30,timezone=IST),id="classify_final")
    scheduler.add_job(job_signal_check,
        CronTrigger(day_of_week="mon-fri",hour="10-14",minute="*/5",timezone=IST),
        id="signals",max_instances=1,coalesce=True)
    scheduler.add_job(monitor_trade,
        CronTrigger(day_of_week="mon-fri",hour="9-14",minute="*/5",timezone=IST),
        id="monitor",max_instances=1,coalesce=True)
    scheduler.add_job(job_pre_close,
        CronTrigger(day_of_week="mon-fri",hour=14,minute=55,timezone=IST),id="preclose")
    scheduler.add_job(job_eod,
        CronTrigger(day_of_week="mon-fri",hour=15,minute=30,timezone=IST),id="eod")
    scheduler.add_job(job_health,
        CronTrigger(minute=0,timezone=IST),id="health")

    print(f"[Scheduler] {len(scheduler.get_jobs())} jobs")
    threading.Thread(target=tg_listener,daemon=True).start()
    print("[Main] Running — bot silent until signals...")

    try:
        scheduler.start()
    except (KeyboardInterrupt,SystemExit):
        print("[Main] Stopped")

if __name__=="__main__":
    main()
