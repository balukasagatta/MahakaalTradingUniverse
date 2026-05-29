"""
Mahakaal Trading Universe — Dashboard v2.0
Clean rewrite with bottom navigation.
"""
import streamlit as st
import requests, json, os, sqlite3, time, subprocess, hashlib
from datetime import datetime, date, timedelta
import pytz

IST      = pytz.timezone("Asia/Kolkata")
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.vars")
GUHA_DB  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guha_journal.db")
MAIN_DB  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mahakaal.db")

def load_env():
    env = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

ENV          = load_env()
UPSTOX_TOKEN = ENV.get("UPSTOX_ACCESS_TOKEN", "")
DHAN_TOKEN   = ENV.get("DHAN_ACCESS_TOKEN", "")
DHAN_CLIENT  = ENV.get("DHAN_CLIENT_ID", "")

USERNAME      = "balu"
PASSWORD_HASH = hashlib.sha256("mahakaal123".encode()).hexdigest()
def check_password(p): return hashlib.sha256(p.encode()).hexdigest() == PASSWORD_HASH

st.set_page_config(page_title="MTU", page_icon="🔱", layout="wide",
                   initial_sidebar_state="collapsed")

for k, v in [("authenticated", False), ("theme", "dark"), ("tab", "dashboard"), ("sidebar_open", False), ("pro_unlocked", False)]:
    if k not in st.session_state: st.session_state[k] = v

# Read tab from query params (set by HTML drawer navigation)
_qp = st.query_params
if "tab" in _qp:
    st.session_state.tab = _qp["tab"]
    st.query_params.clear()

is_dark = st.session_state.theme == "dark"
BG      = "#080c12" if is_dark else "#f0f2f5"
SURFACE = "rgba(255,255,255,0.03)" if is_dark else "#ffffff"
BORDER  = "rgba(255,255,255,0.07)" if is_dark else "rgba(0,0,0,0.08)"
TEXT    = "#ffffff" if is_dark else "#0f172a"
SUBTEXT = "rgba(255,255,255,0.35)" if is_dark else "rgba(0,0,0,0.45)"
ACCENT  = "#f97316"

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@600;700;800&display=swap');
*{{box-sizing:border-box}}
html,body,[data-testid="stAppViewContainer"]{{background:{BG}!important;font-family:'Syne',sans-serif}}
#MainMenu,footer,header{{visibility:hidden}}
[data-testid="stToolbar"]{{display:none}}
[data-testid="stSidebar"]{{display:block}}
.card{{background:{SURFACE};border:1px solid {BORDER};border-radius:16px;padding:18px;margin-bottom:12px}}
.card-title{{font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:{SUBTEXT};margin-bottom:14px}}
.bot-row{{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid {BORDER}}}
.bot-row:last-child{{border-bottom:none}}
.bot-name{{font-size:14px;font-weight:600;color:{TEXT}}}
.bot-sub{{font-size:11px;color:{SUBTEXT};margin-top:2px}}
.big-num{{font-family:'Space Mono',monospace;font-size:34px;font-weight:700;color:{TEXT};line-height:1}}
.big-num.positive{{color:#22c55e}}
.big-num.negative{{color:#ef4444}}
.sub-label{{font-size:12px;color:{SUBTEXT};font-family:'Space Mono',monospace}}
.progress-wrap{{background:rgba(255,255,255,0.06);border-radius:99px;height:6px;margin-top:12px;overflow:hidden}}
.progress-fill{{height:100%;border-radius:99px;background:linear-gradient(90deg,#f97316,#fb923c)}}
.section-label{{font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:{SUBTEXT};margin:24px 0 16px;display:flex;align-items:center;gap:12px}}
.section-label::after{{content:'';flex:1;height:1px;background:{BORDER}}}
.trade-row{{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-family:'Space Mono',monospace;font-size:12px}}
.trade-row:last-child{{border-bottom:none}}
.stButton button{{background:rgba(249,115,22,0.1)!important;border:1px solid rgba(249,115,22,0.3)!important;color:#f97316!important;border-radius:8px!important;font-family:'Syne',sans-serif!important;font-weight:600!important}}
.stTextInput input{{background:{SURFACE}!important;border:1px solid {BORDER}!important;color:{TEXT}!important;border-radius:8px!important}}
::-webkit-scrollbar{{width:4px}}
::-webkit-scrollbar-thumb{{background:rgba(255,255,255,0.1);border-radius:2px}}
</style>""", unsafe_allow_html=True)

def now_ist(): return datetime.now(IST)
def today_str(): return now_ist().strftime("%Y-%m-%d")
def get_main_db():
    if os.path.exists(MAIN_DB): return sqlite3.connect(MAIN_DB)
    return None

def theme_toggle(key):
    BD = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.12)"
    FG = "#ffffff" if is_dark else "#1a1a1a"
    icon = "\u2600\ufe0f" if is_dark else "\U0001f319"
    st.markdown(f"""
    <style>
    .st-key-{key} button {{ background:transparent !important; border:1px solid {BD} !important; color:{FG} !important; border-radius:50% !important; width:40px !important; height:40px !important; min-height:40px !important; padding:0 !important; font-size:17px !important; box-shadow:none !important; }}
    .st-key-{key} button:hover {{ background:rgba(249,115,22,0.12) !important; border-color:#f97316 !important; }}
    </style>""", unsafe_allow_html=True)
    if st.button(icon, key=key, help="Toggle light / dark mode"):
        st.session_state.theme = "light" if is_dark else "dark"
        st.rerun()


def login_page():
    is_light = not is_dark
    TEXT      = "#ffffff" if is_dark else "#111111"
    SUBTEXT   = "rgba(255,255,255,0.45)" if is_dark else "rgba(0,0,0,0.4)"
    PAGE_BG   = "#080c12" if is_dark else "#ffffff"
    FIELD_BG  = "#1a2035" if is_dark else "#f7f8fa"
    FIELD_BD  = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.1)"
    CARD_BG   = "#0f1621" if is_dark else "#ffffff"
    GBTN_BG   = "#1a2035" if is_dark else "#f3f4f6"
    BTN_BG    = "#f97316" if is_dark else "#111111"
    BTN_HV    = "#ea670c" if is_dark else "#333333"
    BTN_BD    = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.15)"
    EYE_FILT  = "none" if is_dark else "invert(1) grayscale(1) brightness(0)"
    icon      = "\u2600\ufe0f" if is_dark else "\U0001f319"

    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Syne:wght@800&display=swap');

        .stApp, [data-testid="stAppViewContainer"] {{ background:{PAGE_BG} !important; }}
        [data-testid="block-container"] {{ padding:0 24px !important; max-width:480px !important; margin:0 auto !important; }}

        /* Toggle */
        .st-key-tt_login {{ position:fixed !important; top:16px !important; right:16px !important; z-index:99999 !important; }}
        .st-key-tt_login button {{
            background:transparent !important; border:1.5px solid {BTN_BD} !important;
            border-radius:50% !important; width:42px !important; height:42px !important;
            min-height:42px !important; padding:0 !important; font-size:18px !important; box-shadow:none !important; }}
        .st-key-tt_login button:hover {{ border-color:#f97316 !important; }}

        /* Title */
        .mtu-title {{ text-align:center; margin:16px 0 24px; }}
        .mtu-title .brand {{ font-family:'Syne',sans-serif; font-size:44px; font-weight:800;
            color:{TEXT}; letter-spacing:-2px; line-height:1; margin-bottom:4px; }}
        .mtu-title .tagline {{ font-size:11px; color:{SUBTEXT}; letter-spacing:4px;
            text-transform:uppercase; font-family:'Inter',sans-serif; }}

        /* Google button */
        .g-btn {{
            display:flex; align-items:center; justify-content:center; gap:10px;
            width:100%; padding:14px 0; margin-bottom:0;
            background:{GBTN_BG}; color:{TEXT};
            border:1px solid {FIELD_BD}; border-radius:50px;
            font-size:15px; font-weight:500; font-family:'Inter',sans-serif;
            cursor:pointer; box-sizing:border-box; transition:opacity 0.15s;
        }}
        .g-btn:hover {{ opacity:0.85; }}

        /* OR divider */
        .ldiv {{ display:flex; align-items:center; gap:14px; margin:20px 0; }}
        .ldiv::before, .ldiv::after {{ content:""; flex:1; height:1px; background:{FIELD_BD}; }}
        .ldiv span {{ color:{SUBTEXT}; font-size:12px; font-family:'Inter',sans-serif; }}

        /* Inputs */
        .stTextInput label, .stTextInput label p {{
            color:{SUBTEXT} !important; font-family:'Inter',sans-serif !important;
            font-size:13px !important; font-weight:400 !important;
            text-transform:none !important; letter-spacing:0 !important; }}
        [data-testid="stTextInputRootElement"] {{
            background:{FIELD_BG} !important;
            border-radius:14px !important;
            border:1.5px solid {FIELD_BD} !important;
            overflow:hidden !important;
            transition:border-color 0.2s !important;
        }}
        [data-testid="stTextInputRootElement"]:focus-within {{
            border-color:#f97316 !important;
        }}
        [data-testid="stTextInputRootElement"] > div {{
            background:{FIELD_BG} !important; border-radius:14px !important; }}
        .stTextInput input {{
            background:transparent !important; color:{TEXT} !important;
            font-family:'Inter',sans-serif !important; font-size:15px !important;
            border:none !important; outline:none !important; box-shadow:none !important;
            padding:16px 16px !important; width:100% !important; box-sizing:border-box !important; }}
        .stTextInput input::placeholder {{ color:{SUBTEXT} !important; opacity:1 !important; }}
        .stTextInput input:focus {{ box-shadow:none !important; outline:none !important; }}

        /* Eye button */
        [data-testid="stTextInputRootElement"] button {{
            background:transparent !important; border:none !important; box-shadow:none !important; }}
        [data-testid="stTextInputRootElement"] button svg {{
            filter:{EYE_FILT} !important; opacity:0.5 !important; }}

        /* Sign In button */
        .st-key-lb button {{
            background:{BTN_BG} !important; color:#ffffff !important;
            border:none !important; border-radius:50px !important;
            padding:16px 0 !important; font-weight:600 !important;
            font-size:15px !important; font-family:'Inter',sans-serif !important;
            width:100% !important; box-shadow:none !important;
            letter-spacing:0.3px !important; margin-top:8px !important;
            transition:background 0.15s !important;
        }}
        .st-key-lb button:hover {{ background:{BTN_HV} !important; }}

        .placeholder-note {{
            text-align:center; margin-top:16px;
            color:{SUBTEXT}; font-size:11px; font-family:'Inter',sans-serif;
        }}
    </style>

    <div class="mtu-title">
        <div class="brand">MTU <span style="color:#f97316">\U0001f531</span></div>
        <div class="tagline">Mahakaal Trading Universe</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button(icon, key="tt_login", help="Toggle theme"):
        st.session_state.theme = "light" if is_dark else "dark"; st.rerun()

    st.markdown(f"""
    <div class="g-btn">
        <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
        Continue with Google
    </div>
    <div class="ldiv"><span>or</span></div>
    """, unsafe_allow_html=True)

    u = st.text_input("Username", placeholder="Username", key="lu")
    p = st.text_input("Password", type="password", placeholder="Password", key="lp")
    if st.button("Sign In", use_container_width=True, key="lb"):
        if u == USERNAME and check_password(p):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Wrong credentials")
    st.markdown('<div class="placeholder-note">Google sign-in · not yet active</div>', unsafe_allow_html=True)


if not st.session_state.authenticated:
    login_page(); st.stop()

@st.cache_data(ttl=30)
def fetch_ltp(symbol):
    try:
        r = requests.get("https://api.upstox.com/v2/market-quote/ltp",
            headers={"Authorization": f"Bearer {UPSTOX_TOKEN}", "Accept": "application/json"},
            params={"instrument_key": symbol}, timeout=8)
        d = r.json()
        if d.get("status") == "success":
            k = list(d["data"].keys())[0]
            return d["data"][k]["last_price"]
    except: pass
    return None

@st.cache_data(ttl=60)
def fetch_chain():
    try:
        today = date.today()
        days = (1 - today.weekday()) % 7
        if days == 0: days = 7
        expiry = (today + timedelta(days=days)).strftime("%Y-%m-%d")
        r = requests.post("https://api.dhan.co/v2/optionchain",
            headers={"access-token": DHAN_TOKEN, "client-id": DHAN_CLIENT,
                     "Content-Type": "application/json"},
            json={"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I", "Expiry": expiry},
            timeout=10)
        d = r.json()
        if d.get("status") == "success": return d["data"]
    except: pass
    return None

def get_atm_iv(chain):
    if not chain: return None
    spot = chain["last_price"]; oc = chain["oc"]
    atm = min(oc.keys(), key=lambda x: abs(float(x)-spot))
    ce = oc[atm]["ce"].get("implied_volatility", 0)
    pe = oc[atm]["pe"].get("implied_volatility", 0)
    return round((ce+pe)/2, 2) if ce and pe else None

def get_guha_trades():
    if not os.path.exists(GUHA_DB): return []
    try:
        conn = sqlite3.connect(GUHA_DB)
        rows = conn.execute(
            "SELECT symbol,side,qty,entry_price,exit_price,pnl,status,entry_time "
            "FROM trades WHERE date=? ORDER BY id", (today_str(),)).fetchall()
        conn.close(); return rows
    except: return []

def get_alakh_data():
    conn = get_main_db()
    if not conn: return [], None
    try:
        sigs = conn.execute(
            "SELECT time,direction,score,entry_price,sl_price,result,pnl,session,atm_iv,strike "
            "FROM alakh_signals WHERE date=? ORDER BY id DESC LIMIT 10",
            (today_str(),)).fetchall()
        daily = conn.execute(
            "SELECT total_signals,trades_taken,wins,losses,pnl,sl_hits "
            "FROM alakh_daily WHERE date=?", (today_str(),)).fetchone()
        conn.close(); return sigs, daily
    except: return [], None

def get_sri_data():
    conn = get_main_db()
    if not conn: return [], None
    try:
        pos = conn.execute(
            "SELECT entry_time,strategy,expiry,dte,net_credit,qty,atm_iv,"
            "short_strike,short_option,regime,result "
            "FROM sri_positions WHERE date=? ORDER BY id DESC", (today_str(),)).fetchall()
        daily = conn.execute(
            "SELECT trades,wins,losses,pnl FROM sri_daily WHERE date=?",
            (today_str(),)).fetchone()
        conn.close(); return pos, daily
    except: return [], None

def get_events():
    conn = get_main_db()
    if not conn: return []
    try:
        rows = conn.execute(
            "SELECT timestamp,bot,event_type,message "
            "FROM events ORDER BY id DESC LIMIT 12").fetchall()
        conn.close(); return rows
    except: return []

def fetch_dhan_funds():
    try:
        # Re-read token fresh to avoid load_env = split issues
        token, client_id = None, None
        with open(ENV_PATH) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DHAN_ACCESS_TOKEN="):
                    token = line[len("DHAN_ACCESS_TOKEN="):]
                elif line.startswith("DHAN_CLIENT_ID="):
                    client_id = line[len("DHAN_CLIENT_ID="):]
        if not token or not client_id: return None
        r = __import__("requests").get("https://api.dhan.co/v2/fundlimit",
            headers={"access-token": token, "client-id": client_id,
                     "Content-Type": "application/json"},
            timeout=8)
        if r.status_code != 200: return None
        d = r.json()
        print(f"[Dhan] fundlimit: {d}")
        return float(d.get("availabelBalance") or d.get("availableBalance") or 0) or None
    except Exception as e:
        print(f"[Dhan] Error: {e}"); return None

def fetch_kotak_funds():
    try:
        import pyotp
        from neo_api_client import NeoAPI
        env = load_env()
        client = NeoAPI(consumer_key=env.get("KOTAK_CONSUMER_KEY",""), environment="prod")
        client.totp_login(
            mobile_number=env.get("KOTAK_MOBILE",""),
            ucc=env.get("KOTAK_UCC",""),
            totp=pyotp.TOTP(env.get("KOTAK_TOTP_SECRET","")).now())
        client.totp_validate(mpin=env.get("KOTAK_MPIN",""))
        lim = client.limits()
        if isinstance(lim, dict):
            return float(lim.get("Net") or lim.get("CollateralValue") or 0) or None
    except Exception as e:
        print(f"[Kotak] Error: {e}"); return None

def fetch_groww_funds():
    try:
        from growwapi import GrowwAPI
        env = load_env()
        token = GrowwAPI.get_access_token(
            api_key=env.get("GROWW_API_KEY",""),
            secret=env.get("GROWW_SECRET",""))
        client = GrowwAPI(token)
        m = client.get_available_margin_details()
        eq = m.get("equity_margin_details", {})
        val = (float(m.get("clear_cash") or 0) +
               float(eq.get("cnc_balance_available") or 0) +
               float(eq.get("mis_balance_available") or 0))
        return float(val) if val > 0 else float(m.get("clear_cash") or 0) or None
    except Exception as e:
        print(f"[Groww] Error: {e}"); return None

# HEADER
n = now_ist()
BTN_BD = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.15)"
icon   = "☀️" if is_dark else "🌙"
st.markdown(f"""
<style>
    [data-testid="block-container"] {{ padding-top:8px !important; }}
    .st-key-tt_home {{ position:fixed !important; top:14px !important; right:14px !important; z-index:99999 !important; }}
    .st-key-tt_home button {{
        background:transparent !important; border:1.5px solid {BTN_BD} !important;
        border-radius:50% !important; width:42px !important; height:42px !important;
        min-height:42px !important; padding:0 !important; font-size:18px !important;
        box-shadow:none !important; cursor:pointer !important; }}
    .st-key-tt_home button:hover {{ border-color:#f97316 !important; background:rgba(249,115,22,0.08) !important; }}
</style>
<div style="display:flex;align-items:center;justify-content:space-between;
            padding:8px 0 10px;border-bottom:1px solid {BORDER};margin-bottom:16px">
    <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:{TEXT};letter-spacing:-0.5px">
        MTU <span style="color:{ACCENT}">🔱</span></div>
    <div style="font-family:'Space Mono',monospace;font-size:11px;color:{SUBTEXT};
                background:{SURFACE};border:1px solid {BORDER};padding:5px 12px;border-radius:6px">
        {n.strftime('%a %d %b')} | {n.strftime('%H:%M')} IST
    </div>
</div>""", unsafe_allow_html=True)
if st.button(icon, key="tt_home", help="Toggle theme"):
    st.session_state.theme = "light" if is_dark else "dark"; st.rerun()

tab = st.session_state.tab

# ── DASHBOARD ──
if tab == "dashboard":
    sensex = fetch_ltp("BSE_INDEX|SENSEX")
    nifty  = fetch_ltp("NSE_INDEX|Nifty 50")
    chain  = fetch_chain()
    atm_iv = get_atm_iv(chain)
    gt     = get_guha_trades()
    gpnl   = sum(t[5] or 0 for t in gt if t[6]=="CLOSED")
    gopen  = [t for t in gt if t[6]=="OPEN"]
    asigs, adaily = get_alakh_data()
    spos, sdaily  = get_sri_data()
    evts   = get_events()
    apnl   = adaily[4] if adaily else 0
    spnl   = sdaily[3] if sdaily else 0
    cpnl   = (apnl or 0)+(spnl or 0)+gpnl
    ivc    = "#22c55e" if atm_iv and 11<=atm_iv<=20 else "#ef4444" if atm_iv else TEXT
    ivs    = "TRADE" if atm_iv and 11<=atm_iv<=20 else "SKIP" if atm_iv else "—"

    c1,c2,c3 = st.columns([2,1,1])
    with c1:
        st.markdown(f"""<div class="card">
        <div class="card-title">Market</div>
        <div style="display:flex;gap:24px;flex-wrap:wrap">
            <div><div style="font-size:10px;letter-spacing:1.5px;color:{SUBTEXT}">SENSEX</div>
                <div style="font-family:'Space Mono';font-size:18px;font-weight:700;color:{TEXT}">{f'{sensex:,.2f}' if sensex else '—'}</div></div>
            <div><div style="font-size:10px;letter-spacing:1.5px;color:{SUBTEXT}">NIFTY</div>
                <div style="font-family:'Space Mono';font-size:18px;font-weight:700;color:{TEXT}">{f'{nifty:,.2f}' if nifty else '—'}</div></div>
            <div><div style="font-size:10px;letter-spacing:1.5px;color:{SUBTEXT}">ATM IV</div>
                <div style="font-family:'Space Mono';font-size:18px;font-weight:700;color:{ivc}">{f'{atm_iv:.1f}%' if atm_iv else '—'}</div></div>
            <div><div style="font-size:10px;letter-spacing:1.5px;color:{SUBTEXT}">IV STATUS</div>
                <div style="font-size:14px;font-weight:700;color:{ivc};margin-top:4px">{ivs}</div></div>
        </div></div>""", unsafe_allow_html=True)
    with c2:
        tgt=69200; pct=min(100,max(0,cpnl/tgt*100)) if tgt>0 else 0
        cls="positive" if cpnl>0 else "negative" if cpnl<0 else ""
        st.markdown(f"""<div class="card">
        <div class="card-title">Today P&L</div>
        <div class="big-num {cls}">{'+'if cpnl>=0 else ''}Rs{cpnl:,.0f}</div>
        <div class="sub-label" style="margin-top:4px">Target Rs{tgt:,}</div>
        <div class="progress-wrap"><div class="progress-fill" style="width:{pct}%"></div></div>
        <div class="sub-label" style="margin-top:8px">{pct:.0f}% captured</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        h,m = n.hour,n.minute
        if h<9 or (h==9 and m<15): ne,mi="Market Open",(9*60+15)-(h*60+m)
        elif h==9 and m<20: ne,mi="ORB Lock",(9*60+20)-(h*60+m)
        elif h<10 or (h==10 and m<30): ne,mi="SriMhatre",(10*60+30)-(h*60+m)
        elif h<15: ne,mi="Mkt Close",(15*60)-(h*60+m)
        else: ne,mi="Closed",0
        sess=('Pre-Mkt' if h<9 else 'Opening' if h==9 and m<20 else 'Prime' if h<11 else 'Bonus' if h<15 else 'Closed')
        st.markdown(f"""<div class="card">
        <div class="card-title">Next Event</div>
        <div class="big-num" style="font-size:28px">{f'{mi}m' if mi>0 else '—'}</div>
        <div class="sub-label" style="margin-top:4px">{ne}</div>
        <div style="margin-top:14px"><div class="sub-label">Session</div>
        <div style="color:{TEXT};font-size:13px;font-weight:600;margin-top:4px">{sess}</div></div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-label">Bot Status</div>', unsafe_allow_html=True)
    b1,b2,b3 = st.columns(3)
    with b1:
        at,aw,al_,asl,ap=(adaily[1],adaily[2],adaily[3],adaily[5],adaily[4]) if adaily else (0,0,0,0,0)
        pc="#22c55e" if ap>=0 else "#ef4444"
        st.markdown(f"""<div class="card">
        <div style="font-size:15px;font-weight:700;color:{TEXT};margin-bottom:14px">Alakh T20</div>
        <div class="bot-row"><div><div class="bot-name">P&L</div><div class="bot-sub">{at} trades | {aw}W {al_}L</div></div>
            <div style="font-family:'Space Mono';color:{pc};font-size:15px;font-weight:700">{'+'if ap>=0 else ''}Rs{ap:,.0f}</div></div>
        <div class="bot-row"><div><div class="bot-name">SL Hits</div><div class="bot-sub">Kill at 2</div></div>
            <div style="font-family:'Space Mono';color:{'#ef4444' if asl>=2 else TEXT};font-size:14px">{asl}/2</div></div>
        <div class="bot-row"><div><div class="bot-name">Target</div></div>
            <div style="font-family:'Space Mono';color:{ACCENT};font-size:14px">Rs2,500</div></div>
        </div>""", unsafe_allow_html=True)
    with b2:
        st_,sw_,sp_=(sdaily[0],sdaily[1],sdaily[3]) if sdaily else (0,0,0)
        so=[p for p in spos if p[10]=="OPEN"]
        spc="#22c55e" if sp_>=0 else "#ef4444"
        ivlabel="TRADE" if atm_iv and 11<=atm_iv<=20 else "SKIP" if atm_iv else "—"
        est="Wait 10:30" if n.hour<10 or (n.hour==10 and n.minute<30) else "Open" if n.hour<15 else "Closed"
        st.markdown(f"""<div class="card">
        <div style="font-size:15px;font-weight:700;color:{TEXT};margin-bottom:14px">SriMhatre</div>
        <div class="bot-row"><div><div class="bot-name">P&L</div><div class="bot-sub">{st_} trades | {sw_} wins</div></div>
            <div style="font-family:'Space Mono';color:{spc};font-size:15px;font-weight:700">{'+'if sp_>=0 else ''}Rs{sp_:,.0f}</div></div>
        <div class="bot-row"><div><div class="bot-name">Positions</div><div class="bot-sub">{est}</div></div>
            <div style="font-family:'Space Mono';color:{TEXT};font-size:14px">{len(so)}</div></div>
        <div class="bot-row"><div><div class="bot-name">IV Status</div></div>
            <div style="font-family:'Space Mono';color:{ivc};font-size:14px">{f'{atm_iv:.1f}% {ivlabel}' if atm_iv else '—'}</div></div>
        </div>""", unsafe_allow_html=True)
    with b3:
        gpc="#22c55e" if gpnl>=0 else "#ef4444"
        st.markdown(f"""<div class="card">
        <div style="font-size:15px;font-weight:700;color:{TEXT};margin-bottom:14px">Guha Cash</div>
        <div class="bot-row"><div><div class="bot-name">Realized P&L</div><div class="bot-sub">Closed trades</div></div>
            <div style="font-family:'Space Mono';color:{gpc};font-size:15px;font-weight:700">{'+'if gpnl>=0 else ''}Rs{gpnl:,.0f}</div></div>
        <div class="bot-row"><div><div class="bot-name">Open</div></div>
            <div style="font-family:'Space Mono';color:{TEXT};font-size:14px">{len(gopen)}</div></div>
        <div class="bot-row"><div><div class="bot-name">SL / Target</div></div>
            <div style="font-family:'Space Mono';color:{ACCENT};font-size:12px">Signal-based</div></div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div class="section-label">Signals & Chain</div>', unsafe_allow_html=True)
    d1,d2=st.columns(2)
    with d1:
        st.markdown(f'<div class="card"><div class="card-title">Alakh Signals</div>', unsafe_allow_html=True)
        if not asigs:
            st.markdown(f'<div style="color:{SUBTEXT};text-align:center;padding:20px 0">No signals today</div>', unsafe_allow_html=True)
        for sig in asigs:
            t,direction,score,entry,sl,result,pnl,session,iv,strike=sig
            pnl=pnl or 0
            ri="win" if result=="WIN" else "loss" if result=="LOSS" else "open"
            dc="#22c55e" if direction=="CALL" else "#ef4444"
            pc2="#22c55e" if pnl>0 else "#ef4444" if pnl<0 else SUBTEXT
            st.markdown(f"""<div class="trade-row">
            <div><span style="color:{dc};font-weight:700">{direction}</span>
                <span style="color:{SUBTEXT};margin:0 6px">{strike:,.0f}</span>
                <span style="color:{SUBTEXT};font-size:11px">{score}/15</span></div>
            <div><span style="color:{pc2}">{'+'if pnl>=0 else ''}Rs{pnl:.0f}</span></div>
            </div>""", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with d2:
        st.markdown(f'<div class="card"><div class="card-title">Nifty Chain ATM+-3</div>', unsafe_allow_html=True)
        if chain:
            spot=chain["last_price"]; oc=chain["oc"]
            strikes=sorted(oc.keys(), key=lambda x: float(x))
            atm_k=min(strikes, key=lambda x: abs(float(x)-spot))
            ai=strikes.index(atm_k)
            nearby=strikes[max(0,ai-3):ai+4]
            for k in nearby:
                ce=oc[k]["ce"]; pe=oc[k]["pe"]; iatm=k==atm_k
                bg="rgba(249,115,22,0.1)" if iatm else "transparent"
                fw="700" if iatm else "400"
                fc="#f97316" if iatm else TEXT
                st.markdown(f'<div style="font-family:Space Mono;font-size:11px;display:flex;justify-content:space-between;padding:5px 4px;background:{bg};border-radius:6px;margin:2px 0"><span style="color:#22c55e">{ce.get("last_price",0):.0f}</span><span style="color:{fc};font-weight:{fw}">{float(k):,.0f}</span><span style="color:#ef4444">{pe.get("last_price",0):.0f}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="color:{SUBTEXT};text-align:center;padding:20px 0">Market closed</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""<script>setTimeout(function(){window.location.reload();},30000);</script>""", unsafe_allow_html=True)

# ── TOKENS ──
elif tab == "tokens":
    st.markdown('<div class="section-label">Token Refresh</div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="card">
    <div style="font-size:13px;color:{SUBTEXT};line-height:2.2">
        Kotak Neo - Auto via TOTP<br>
        Groww - Auto via SECRET<br>
        Dhan - Paste fresh token daily<br>
        Upstox - Paste fresh token daily
    </div></div>""", unsafe_allow_html=True)
    dt=st.text_input("Dhan Token", placeholder="Paste Dhan token...", type="password", key="tok_dhan")
    ut=st.text_input("Upstox Token", placeholder="Paste Upstox token...", type="password", key="tok_upstox")
    if st.button("Save Tokens and Restart All Bots", use_container_width=True, key="tok_save"):
        updated=[]
        try:
            if dt.strip():
                subprocess.run(["sed","-i","/DHAN_ACCESS_TOKEN/d",ENV_PATH])
                open(ENV_PATH,"a").write(f"\nDHAN_ACCESS_TOKEN={dt.strip()}\n")
                updated.append("Dhan")
            if ut.strip():
                subprocess.run(["sed","-i","/UPSTOX_ACCESS_TOKEN/d",ENV_PATH])
                open(ENV_PATH,"a").write(f"\nUPSTOX_ACCESS_TOKEN={ut.strip()}\n")
                updated.append("Upstox")
            if updated:
                subprocess.run(["sudo","systemctl","restart","alakh","srimhatre","guha"])
                st.success(f"Saved {', '.join(updated)} - Bots restarted!")
            else: st.warning("Paste at least one token first")
        except Exception as e: st.error(f"Error: {e}")

# ── SETTINGS ──
elif tab == "settings":
    st.markdown('<div class="section-label">System</div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="card">
    <div style="font-size:13px;color:{SUBTEXT};line-height:2.2">
        Theme: <b style="color:{TEXT}">{'Dark' if is_dark else 'Light'}</b><br>
        System: <b style="color:{TEXT}">MTU v1.0</b><br>
        Bots: <b style="color:#22c55e">3 Active</b>
    </div></div>""", unsafe_allow_html=True)
    if st.button("Logout", use_container_width=True, key="set_logout"):
        st.session_state.authenticated=False; st.session_state.tab="dashboard"; st.rerun()
    st.markdown('<div class="section-label">Capital</div>', unsafe_allow_html=True)
    with st.spinner("Fetching live balances..."):
        kotak_bal = fetch_kotak_funds()
        dhan_bal  = fetch_dhan_funds()
        groww_bal = fetch_groww_funds()
    def fmt(v): return f"Rs{v:,.0f}" if v is not None else "\u2014"
    def clr(v): return TEXT if v is not None else "#ef4444"
    total = (kotak_bal or 0)+(dhan_bal or 0)+(groww_bal or 0)
    st.markdown(f"""<div class="card"><div style="font-family:'Space Mono';font-size:12px;color:{SUBTEXT}">
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid {BORDER}">
        <span>Alakh (Kotak)</span><span style="color:{clr(kotak_bal)}">{fmt(kotak_bal)}</span></div>
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid {BORDER}">
        <span>SriMhatre (Dhan)</span><span style="color:{clr(dhan_bal)}">{fmt(dhan_bal)}</span></div>
    <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid {BORDER}">
        <span>Guha (Groww)</span><span style="color:{clr(groww_bal)}">{fmt(groww_bal)}</span></div>
    <div style="display:flex;justify-content:space-between;padding:10px 0 4px">
        <span style="color:{TEXT};font-weight:700">Total Available</span>
        <span style="color:{ACCENT};font-weight:700">{fmt(total) if total>0 else "—"}</span></div>
    </div></div>""", unsafe_allow_html=True)
# ── PRO TAB ──
elif tab == "pro":
    PRO_KEY_HASH = __import__("hashlib").sha256("MAHAKAAL-PRO-2024".encode()).hexdigest()
    if not st.session_state.pro_unlocked:
        LOCK_FBG = "#1a2035" if is_dark else "#f7f8fa"
        LOCK_BD  = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.1)"
        st.markdown(f"""
        <style>
            .st-key-pro_unlock_btn button {{
                background:linear-gradient(135deg,#f97316,#ea670c) !important;
                color:#fff !important; border:none !important;
                border-radius:50px !important; padding:14px 0 !important;
                font-weight:700 !important; font-size:15px !important;
                width:100% !important;
                box-shadow:0 4px 16px rgba(249,115,22,0.35) !important;
            }}
            .st-key-pro_key_input [data-testid="stTextInputRootElement"] {{
                background:{LOCK_FBG} !important;
                border-radius:14px !important;
                border:1.5px solid {LOCK_BD} !important;
            }}
            .st-key-pro_key_input input {{
                background:transparent !important;
                color:{TEXT} !important;
                font-size:15px !important;
                padding:16px !important;
                border:none !important;
            }}
        </style>
        <div style="margin:32px 0 24px;text-align:center">
            <div style="display:inline-flex;align-items:center;justify-content:center;
                        width:72px;height:72px;background:rgba(249,115,22,0.12);
                        border-radius:50%;margin-bottom:20px">
                <span style="font-size:32px">⚡</span>
            </div>
            <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;
                        color:{TEXT};margin-bottom:8px">Unlock Pro</div>
            <div style="font-size:13px;color:{SUBTEXT};line-height:1.7;max-width:260px;margin:0 auto">
                Live bot alerts · Real-time feed · Advanced monitoring
            </div>
        </div>""", unsafe_allow_html=True)
        pro_key = st.text_input("", placeholder="Enter Pro key", type="password", key="pro_key_input")
        if st.button("Unlock Pro ⚡", use_container_width=True, key="pro_unlock_btn"):
            import hashlib
            if hashlib.sha256(pro_key.encode()).hexdigest() == PRO_KEY_HASH:
                st.session_state.pro_unlocked = True
                st.rerun()
            else:
                st.error("Invalid Pro key")
    else:
        # ── LIVE FEED ──
        import sqlite3 as _sq
        BOT_COLORS = {"alakh": "#f97316", "srimhatre": "#3b82f6", "guha": "#22c55e"}
        BOT_NAMES  = {"alakh": "Alakh T20", "srimhatre": "SriMhatre", "guha": "Guha"}

        st.markdown(f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:8px 0 12px;border-bottom:1px solid {BORDER}">
            <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:{TEXT}">
                ⚡ Live Feed</div>
            <div style="font-size:11px;color:{SUBTEXT};font-family:'Space Mono',monospace">
                Auto-refresh 5s</div>
        </div>""", unsafe_allow_html=True)

        # Filter
        bot_filter = st.selectbox("Filter by bot", ["All", "Alakh T20", "SriMhatre"], key="pro_filter")
        bot_map = {"All": None, "Alakh T20": "alakh", "SriMhatre": "srimhatre"}
        selected_bot = bot_map[bot_filter]

        try:
            conn = _sq.connect("/home/balukasagatta1709/mahakaal/mahakaal.db", timeout=5)
            if selected_bot:
                rows = conn.execute(
                    "SELECT timestamp, bot, category, message FROM alerts "
                    "WHERE bot=? AND date(timestamp)=date('now','localtime') "
                    "ORDER BY id DESC LIMIT 50", (selected_bot,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT timestamp, bot, category, message FROM alerts "
                    "WHERE date(timestamp)=date('now','localtime') "
                    "ORDER BY id DESC LIMIT 50").fetchall()
            conn.close()
        except: rows = []

        if not rows:
            st.markdown(f"""
            <div style="text-align:center;padding:40px 0;color:{SUBTEXT}">
                <div style="font-size:32px;margin-bottom:12px">📡</div>
                <div>No alerts today yet. Bots will send alerts during market hours.</div>
            </div>""", unsafe_allow_html=True)
        else:
            for row in rows:
                ts, bot, cat, msg = row
                bc = BOT_COLORS.get(bot, ACCENT)
                bn = BOT_NAMES.get(bot, bot)
                time_str = ts[11:16] if ts else ""
                clean_msg = msg.replace("<b>","").replace("</b>","").replace("<i>","").replace("</i>","")
                st.markdown(f"""
                <div style="background:{SURFACE};border:1px solid {BORDER};border-left:3px solid {bc};
                            border-radius:10px;padding:12px 14px;margin-bottom:8px">
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                        <span style="font-size:11px;font-weight:700;color:{bc};font-family:'Syne',sans-serif">{bn}</span>
                        <span style="font-size:10px;color:{SUBTEXT};font-family:'Space Mono',monospace">{time_str}</span>
                    </div>
                    <div style="font-size:12px;color:{TEXT};line-height:1.5;font-family:'Space Mono',monospace">{clean_msg}</div>
                </div>""", unsafe_allow_html=True)

        st.markdown("""<script>setTimeout(function(){window.location.reload();},5000);</script>""",
                    unsafe_allow_html=True)

        # Lock button
        if st.button("🔒 Lock Pro", key="pro_lock", use_container_width=False):
            st.session_state.pro_unlocked = False; st.rerun()

# ── BOTTOM TAB BAR ──
cur_tab = st.session_state.tab
TAB_BG  = "#0d1117" if is_dark else "#ffffff"
TAB_BD  = "rgba(255,255,255,0.08)" if is_dark else "rgba(0,0,0,0.08)"
TAB_TX  = "rgba(255,255,255,0.35)" if is_dark else "rgba(0,0,0,0.3)"

st.markdown(f"""
<style>
    [data-testid="stSidebar"] {{ display:none !important; }}
    [data-testid="block-container"] {{ padding-bottom:72px !important; }}
    .st-key-nav_dashboard, .st-key-nav_tokens, .st-key-nav_pro, .st-key-nav_settings {{
        position:fixed !important; bottom:0 !important; z-index:99999 !important; height:60px !important;
    }}
    .st-key-nav_dashboard {{ left:0 !important; width:25vw !important; }}
    .st-key-nav_tokens    {{ left:25vw !important; width:25vw !important; }}
    .st-key-nav_pro       {{ left:50vw !important; width:25vw !important; }}
    .st-key-nav_settings  {{ left:75vw !important; width:25vw !important; }}
    .st-key-nav_dashboard button, .st-key-nav_tokens button,
    .st-key-nav_pro button, .st-key-nav_settings button {{
        background:{TAB_BG} !important; border:none !important;
        border-top:1px solid {TAB_BD} !important;
        box-shadow:none !important; border-radius:0 !important;
        width:100% !important; height:60px !important; min-height:60px !important;
        padding:0 !important; color:{TAB_TX} !important;
        font-family:Syne,sans-serif !important; font-size:11px !important;
        font-weight:700 !important; letter-spacing:0.5px !important;
        text-transform:uppercase !important;
    }}
    .st-key-nav_{cur_tab} button {{
        color:#f97316 !important; border-top:2px solid #f97316 !important;
    }}
</style>
""", unsafe_allow_html=True)

if st.button("📊 Dashboard", key="nav_dashboard", use_container_width=True):
    st.session_state.tab = "dashboard"; st.rerun()
if st.button("🔑 Tokens", key="nav_tokens", use_container_width=True):
    st.session_state.tab = "tokens"; st.rerun()
if st.button("👑 Live Algo", key="nav_pro", use_container_width=True):
    st.session_state.tab = "pro"; st.rerun()
if st.button("⚙️ Settings", key="nav_settings", use_container_width=True):
    st.session_state.tab = "settings"; st.rerun()
