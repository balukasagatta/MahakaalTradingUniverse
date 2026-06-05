"""
SUTRA Options Strategy Terminal v1.0
Guided strategies + Strategy Builder + Payoff Graph
Light theme · PRAGNYA discipline engine built-in
"""
import streamlit as st
import json, math
from datetime import datetime, date
from pragnya_engine import (
    get_state, update_state, check_rules, trigger_kill,
    get_daily_quote, save_eod_emotion, get_eod_emotion,
    add_reward, get_total_rewards, get_today_trades,
    add_trade, log_violation,
)
import pytz

IST     = pytz.timezone("Asia/Kolkata")
PRODUCT = "SUTRA"

# ── MOCK OPTION CHAIN ──────────────────────────────────────────────────────────
INDICES = {
    "NIFTY":   {"spot": 23456, "lot": 75,  "step": 50,  "expiries": ["12 Jun", "19 Jun", "26 Jun", "31 Jul"]},
    "BANKNIFTY":{"spot": 51230, "lot": 35,  "step": 100, "expiries": ["12 Jun", "19 Jun", "26 Jun", "31 Jul"]},
    "SENSEX":  {"spot": 77842, "lot": 20,  "step": 100, "expiries": ["13 Jun", "20 Jun", "27 Jun", "31 Jul"]},
    "MIDCPNIFTY":{"spot": 12340,"lot": 75, "step": 25,  "expiries": ["26 Jun", "31 Jul"]},
}

def get_atm(spot, step):
    return round(spot / step) * step

def mock_premium(spot, strike, otype, dte, iv=15):
    """Black-Scholes approximation for mock premiums"""
    S, K, T, r, sigma = spot, strike, dte/365, 0.05, iv/100
    if T <= 0: return max(0, (S-K) if otype=="CE" else (K-S))
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    def N(x):
        a = abs(x)
        t = 1/(1+0.2316419*a)
        k = t*(0.319381530+t*(-0.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))))
        return 1 - (1/math.sqrt(2*math.pi))*math.exp(-a**2/2)*k if x>0 else (1/math.sqrt(2*math.pi))*math.exp(-a**2/2)*k
    if otype == "CE":
        return round(max(0.1, S*N(d1) - K*math.exp(-r*T)*N(d2)), 1)
    else:
        return round(max(0.1, K*math.exp(-r*T)*N(-d2) - S*N(-d1)), 1)

def get_chain(index, expiry_idx=0, iv=15):
    info = INDICES[index]
    spot = info["spot"]
    step = info["step"]
    atm  = get_atm(spot, step)
    dte  = [10, 17, 24, 52][expiry_idx]
    strikes = [atm + i*step for i in range(-6, 7)]
    chain = []
    for k in strikes:
        chain.append({
            "strike": k,
            "ce_premium": mock_premium(spot, k, "CE", dte, iv),
            "pe_premium": mock_premium(spot, k, "PE", dte, iv),
            "ce_delta":   round(0.5 - (k-spot)/(spot*0.15), 2),
            "pe_delta":   round(-0.5 + (k-spot)/(spot*0.15), 2),
            "dte": dte,
        })
    return chain, atm, spot

# ── STRATEGIES ─────────────────────────────────────────────────────────────────
STRATEGIES = {
    "BULLISH": [
        {"name": "Bull Put Spread",    "desc": "Sell OTM put, buy further OTM put. Profit if market stays above short strike.", "legs": [("PE","SELL",-1),("PE","BUY",-2)], "regime": "Bullish"},
        {"name": "Naked Put",          "desc": "Sell OTM put. High premium, unlimited downside risk.", "legs": [("PE","SELL",-1)], "regime": "Bullish"},
        {"name": "Call Ratio Spread",  "desc": "Buy ATM call, sell 2 OTM calls. Works in slow bullish moves.", "legs": [("CE","BUY",0),("CE","SELL",1),("CE","SELL",2)], "regime": "Bullish"},
    ],
    "BEARISH": [
        {"name": "Bear Call Spread",   "desc": "Sell OTM call, buy further OTM call. Profit if market stays below short strike.", "legs": [("CE","SELL",1),("CE","BUY",2)], "regime": "Bearish"},
        {"name": "Naked Call",         "desc": "Sell OTM call. High premium, unlimited upside risk.", "legs": [("CE","SELL",1)], "regime": "Bearish"},
        {"name": "Put Ratio Spread",   "desc": "Buy ATM put, sell 2 OTM puts. Works in slow bearish moves.", "legs": [("PE","BUY",0),("PE","SELL",-1),("PE","SELL",-2)], "regime": "Bearish"},
    ],
    "RANGEBOUND": [
        {"name": "Iron Condor",        "desc": "Sell OTM call + put, buy further OTM call + put. Classic range strategy.", "legs": [("CE","SELL",1),("CE","BUY",2),("PE","SELL",-1),("PE","BUY",-2)], "regime": "Rangebound"},
        {"name": "Iron Butterfly",     "desc": "Sell ATM call + put, buy OTM wings. Higher premium, tighter range.", "legs": [("CE","SELL",0),("PE","SELL",0),("CE","BUY",1),("PE","BUY",-1)], "regime": "Rangebound"},
        {"name": "Short Strangle",     "desc": "Sell OTM call + put. No wing protection — high premium, unlimited risk.", "legs": [("CE","SELL",1),("PE","SELL",-1)], "regime": "Rangebound"},
    ],
    "VOLATILE": [
        {"name": "Long Strangle",      "desc": "Buy OTM call + put. Profit on big moves either direction.", "legs": [("CE","BUY",1),("PE","BUY",-1)], "regime": "Volatile"},
        {"name": "Long Straddle",      "desc": "Buy ATM call + put. Maximum sensitivity to movement.", "legs": [("CE","BUY",0),("PE","BUY",0)], "regime": "Volatile"},
    ],
}

def build_legs(strategy, chain, atm, step, lots):
    legs = []
    atm_idx = next(i for i,c in enumerate(chain) if c["strike"]==atm)
    for otype, action, offset in strategy["legs"]:
        idx = max(0, min(len(chain)-1, atm_idx + offset))
        row = chain[idx]
        prem = row["ce_premium"] if otype=="CE" else row["pe_premium"]
        legs.append({
            "type": otype, "action": action,
            "strike": row["strike"], "premium": prem,
            "lots": lots,
        })
    return legs

def calc_payoff(legs, spot_range, lot_size):
    payoffs = []
    for s in spot_range:
        pnl = 0
        for leg in legs:
            if leg["type"] == "CE":
                intrinsic = max(0, s - leg["strike"])
            else:
                intrinsic = max(0, leg["strike"] - s)
            if leg["action"] == "SELL":
                pnl += (leg["premium"] - intrinsic) * lot_size * leg["lots"]
            else:
                pnl += (intrinsic - leg["premium"]) * lot_size * leg["lots"]
        payoffs.append(round(pnl))
    return payoffs

def net_credit(legs, lot_size):
    total = 0
    for leg in legs:
        mult = 1 if leg["action"]=="SELL" else -1
        total += mult * leg["premium"] * lot_size * leg["lots"]
    return round(total)

# ── PAGE SETUP ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SUTRA | MTU Terminal",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="collapsed",
)

for k, v in [
    ("tab", "guided"),
    ("selected_strategy", None),
    ("builder_legs", []),
    ("show_kill_overlay", False),
]:
    if k not in st.session_state:
        st.session_state[k] = v

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0}
html,body,[data-testid="stAppViewContainer"],[data-testid="stMain"],section.main{background:#F5F4F0!important}
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],#MainMenu,footer{display:none!important}
[data-testid="block-container"]{padding:0 16px 80px!important;max-width:1280px!important;margin:0 auto!important}
body,.stMarkdown,.stText{font-family:'IBM Plex Sans',sans-serif!important}

.card{background:#fff;border:1px solid #E2E0D8;border-radius:10px;padding:14px 16px;margin-bottom:10px}
.card-label{font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:#9B9689;margin-bottom:8px}

.header-bar{display:flex;align-items:center;justify-content:space-between;padding:12px 0 10px;border-bottom:2px solid #1A1916;margin-bottom:14px}
.logo{font-family:'IBM Plex Mono',monospace;font-size:20px;font-weight:700;color:#1A1916}
.logo span{color:#E8540A}

.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:4px;font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600}
.badge-green{background:#D1FAE5;color:#065F46}
.badge-red{background:#FEE2E2;color:#991B1B}
.badge-amber{background:#FEF3C7;color:#92400E}
.badge-blue{background:#DBEAFE;color:#1E40AF}
.badge-gray{background:#F3F2EE;color:#5C5A54}
.badge-purple{background:#EDE9FE;color:#5B21B6}

.stat-block{text-align:right}
.stat-block .lbl{font-family:'IBM Plex Mono',monospace;font-size:8px;letter-spacing:1.5px;text-transform:uppercase;color:#9B9689}
.stat-block .val{font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:700;color:#1A1916;line-height:1.1}
.up{color:#1A7F4B!important}.down{color:#C0392B!important}

.strat-card{background:#fff;border:1.5px solid #E2E0D8;border-radius:10px;padding:14px;margin-bottom:8px;cursor:pointer;transition:all .15s}
.strat-card:hover{border-color:#1A1916;background:#FAFAF8}
.strat-card.selected{border-color:#E8540A;background:#FFF8F5}
.strat-name{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:700;color:#1A1916;margin-bottom:4px}
.strat-desc{font-size:11px;color:#9B9689;line-height:1.5}

.leg-row{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-radius:6px;margin-bottom:6px;font-size:12px}
.leg-sell{background:#FEF2F2;border:1px solid #FECACA}
.leg-buy{background:#F0FDF4;border:1px solid #BBF7D0}
.leg-label{font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:11px}

.payoff-wrap{background:#fff;border:1px solid #E2E0D8;border-radius:10px;padding:14px;margin-top:10px}
.chain-row{display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border-radius:4px;font-size:11px;font-family:'IBM Plex Mono',monospace}
.chain-row.atm{background:#FFF8F5;border:1px solid #FED7AA;font-weight:700}
.chain-row:not(.atm):hover{background:#F5F4F0}

.regime-btn{display:flex;flex-direction:column;align-items:center;padding:12px 8px;border:1.5px solid #E2E0D8;border-radius:8px;cursor:pointer;background:#fff;transition:all .15s;text-align:center}
.regime-btn:hover{border-color:#1A1916}
.regime-btn.active{border-color:#E8540A;background:#FFF8F5}
.regime-icon{font-size:20px;margin-bottom:4px}
.regime-label{font-family:'IBM Plex Mono',monospace;font-size:9px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#5C5A54}

.metric-box{text-align:center;padding:10px;background:#F5F4F0;border-radius:8px}
.metric-val{font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;color:#1A1916}
.metric-lbl{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:#9B9689;margin-top:2px}

.overlay{position:fixed;inset:0;background:rgba(245,244,240,0.96);z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px}
.quote-box{background:#F5F4F0;border-radius:8px;padding:16px;text-align:left;margin-top:16px}
.quote-text{font-size:13px;color:#3D3B35;font-style:italic;line-height:1.6}
.quote-src{font-family:'IBM Plex Mono',monospace;font-size:10px;color:#9B9689;margin-top:6px;letter-spacing:1px}

.warn-banner{background:#FEF9EC;border:1px solid #F6D860;border-left:3px solid #F6A800;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:12px;color:#7A4F00;font-weight:500}

[data-testid="block-container"]{padding-bottom:72px!important}
.st-key-nav_guided,.st-key-nav_builder,.st-key-nav_chain,.st-key-nav_journal{position:fixed!important;bottom:0!important;z-index:9999!important;height:56px!important}
.st-key-nav_guided  {left:0!important;width:25vw!important}
.st-key-nav_builder {left:25vw!important;width:25vw!important}
.st-key-nav_chain   {left:50vw!important;width:25vw!important}
.st-key-nav_journal {left:75vw!important;width:25vw!important}
.st-key-nav_guided button,.st-key-nav_builder button,.st-key-nav_chain button,.st-key-nav_journal button{
    background:#fff!important;border:none!important;border-top:1px solid #E2E0D8!important;
    box-shadow:none!important;border-radius:0!important;width:100%!important;height:56px!important;
    min-height:56px!important;padding:0!important;color:#9B9689!important;
    font-family:'IBM Plex Mono',monospace!important;font-size:9px!important;
    font-weight:600!important;letter-spacing:1px!important;text-transform:uppercase!important}
.st-key-nav_guided button:hover,.st-key-nav_builder button:hover,.st-key-nav_chain button:hover,.st-key-nav_journal button:hover{color:#E8540A!important;border-top:2px solid #E8540A!important}

.stButton>button{font-family:'IBM Plex Sans',sans-serif!important;font-weight:600!important;border-radius:7px!important;border:1.5px solid #E2E0D8!important;background:#fff!important;color:#1A1916!important;font-size:13px!important;padding:8px 16px!important;transition:all .15s!important}
.stButton>button:hover{border-color:#1A1916!important;background:#F5F4F0!important}
.st-key-btn_kill>button{background:#C0392B!important;color:#fff!important;border-color:#C0392B!important;font-weight:700!important}
.st-key-btn_execute_strat>button{background:#1A7F4B!important;color:#fff!important;border-color:#1A7F4B!important;font-weight:700!important;font-size:14px!important;padding:12px!important}
.stSelectbox>div>div,.stNumberInput input{border:1.5px solid #E2E0D8!important;border-radius:6px!important;font-family:'IBM Plex Mono',monospace!important;font-size:13px!important;background:#fff!important}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#D1CFC8;border-radius:2px}
</style>
""", unsafe_allow_html=True)

# ── RUNTIME ────────────────────────────────────────────────────────────────────
now   = datetime.now(IST)
state = get_state(PRODUCT)
quote_text, quote_src = get_daily_quote()
dscore = state["discipline_score"]

# ── KILL OVERLAY ───────────────────────────────────────────────────────────────
if st.session_state.show_kill_overlay:
    st.markdown(f"""
    <div class="overlay">
      <div style="font-size:48px;margin-bottom:16px">🕉️</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:700;color:#C0392B;margin-bottom:8px">KILL SWITCH ACTIVE</div>
      <div style="font-size:13px;color:#9B9689;margin-bottom:32px">Options trading stopped for today.</div>
      <div class="quote-box" style="max-width:400px">
        <div class="quote-text">"{quote_text}"</div>
        <div class="quote-src">— {quote_src}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Close", key="kill_close"):
        st.session_state.show_kill_overlay = False
        st.rerun()
    st.stop()

# ── HEADER ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="header-bar">
  <div>
    <div class="logo">📐 <span>SUTRA</span></div>
    <div style="font-size:10px;color:#9B9689;font-family:'IBM Plex Mono',monospace;letter-spacing:1px;margin-top:1px">
      OPTIONS STRATEGY TERMINAL · {now.strftime('%d %b %Y · %H:%M')} IST
    </div>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <div class="stat-block">
      <div class="lbl">PRAGNYA</div>
      <div class="val {'up' if dscore>=80 else 'amber' if dscore>=50 else 'down'}">{dscore}<span style="font-size:10px;color:#9B9689">/100</span></div>
    </div>
    <div class="stat-block">
      <div class="lbl">POSITIONS</div>
      <div class="val">{sum(1 for t in get_today_trades(PRODUCT) if t['status']=='OPEN')}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── INDEX + EXPIRY SELECTOR (persistent) ──────────────────────────────────────
c1, c2, c3, c4 = st.columns([2,2,2,2])
with c1:
    index = st.selectbox("Index", list(INDICES.keys()), key="sel_index")
with c2:
    info = INDICES[index]
    expiry = st.selectbox("Expiry", info["expiries"], key="sel_expiry")
    expiry_idx = info["expiries"].index(expiry)
with c3:
    iv = st.number_input("IV %", value=15, min_value=5, max_value=60, key="sel_iv")
with c4:
    lots = st.number_input("Lots", value=1, min_value=1, max_value=50, key="sel_lots")

chain, atm, spot = get_chain(index, expiry_idx, iv)
lot_size = info["lot"]
step = info["step"]

tab = st.session_state.tab

# ══════════════════════════════════════════════════════════════════════════════
if tab == "guided":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown(f"""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#9B9689;
                margin-bottom:12px">{index} SPOT <b style="color:#1A1916;font-size:16px">{spot:,}</b>
    &nbsp;·&nbsp; ATM <b style="color:#E8540A">{atm:,}</b>
    &nbsp;·&nbsp; Expiry <b style="color:#1A1916">{expiry}</b></div>
    """, unsafe_allow_html=True)

    # Regime selector
    st.markdown('<div class="card"><div class="card-label">Market Regime</div>', unsafe_allow_html=True)
    regimes = [
        ("📈", "BULLISH",    "Market trending up"),
        ("📉", "BEARISH",    "Market trending down"),
        ("↔️",  "RANGEBOUND","Sideways consolidation"),
        ("⚡",  "VOLATILE",  "High movement expected"),
    ]
    r1,r2,r3,r4 = st.columns(4)
    sel_regime = st.session_state.get("sel_regime", "RANGEBOUND")
    for col, (icon, label, desc) in zip([r1,r2,r3,r4], regimes):
        with col:
            active = "active" if sel_regime == label else ""
            st.markdown(f"""
            <div class="regime-btn {active}">
              <div class="regime-icon">{icon}</div>
              <div class="regime-label">{label}</div>
              <div style="font-size:9px;color:#9B9689;margin-top:2px">{desc}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(label, key=f"regime_{label}", use_container_width=True):
                st.session_state.sel_regime = label
                st.session_state.selected_strategy = None
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    sel_regime = st.session_state.get("sel_regime", "RANGEBOUND")
    strategies = STRATEGIES.get(sel_regime, [])

    col_left, col_right = st.columns([2, 3], gap="medium")

    with col_left:
        st.markdown('<div class="card"><div class="card-label">Recommended Strategies</div>', unsafe_allow_html=True)
        for i, s in enumerate(strategies):
            selected = st.session_state.selected_strategy == i
            cls = "strat-card selected" if selected else "strat-card"
            st.markdown(f"""
            <div class="{cls}">
              <div class="strat-name">{s['name']}</div>
              <div class="strat-desc">{s['desc']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"Select", key=f"sel_strat_{i}", use_container_width=True):
                st.session_state.selected_strategy = i
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with col_right:
        sel_idx = st.session_state.selected_strategy
        if sel_idx is not None and sel_idx < len(strategies):
            strategy = strategies[sel_idx]
            legs = build_legs(strategy, chain, atm, step, lots)
            credit = net_credit(legs, lot_size)
            credit_per_lot = round(credit / lots) if lots else credit

            # Metrics
            max_profit = max(0, credit)
            max_loss_legs = []
            for leg in legs:
                if leg["action"] == "BUY":
                    max_loss_legs.append(leg["premium"] * lot_size * leg["lots"])
            max_loss = -sum(max_loss_legs) if max_loss_legs else -abs(credit) * 3

            m1,m2,m3,m4 = st.columns(4)
            metrics = [
                ("Net Credit", f"₹{credit:,}", "#1A7F4B" if credit>0 else "#C0392B"),
                ("Max Profit", f"₹{max_profit:,}", "#1A7F4B"),
                ("Max Loss",   f"₹{max_loss:,}", "#C0392B"),
                ("BEP Approx", f"{atm + (credit//lot_size if credit>0 else 0):,}", "#1A1916"),
            ]
            for col, (lbl, val, col_c) in zip([m1,m2,m3,m4], metrics):
                with col:
                    st.markdown(f"""
                    <div class="metric-box">
                      <div class="metric-val" style="color:{col_c}">{val}</div>
                      <div class="metric-lbl">{lbl}</div>
                    </div>
                    """, unsafe_allow_html=True)

            # Legs
            st.markdown('<div class="card" style="margin-top:10px"><div class="card-label">Strategy Legs</div>', unsafe_allow_html=True)
            for leg in legs:
                cls = "leg-sell" if leg["action"]=="SELL" else "leg-buy"
                color = "#C0392B" if leg["action"]=="SELL" else "#1A7F4B"
                st.markdown(f"""
                <div class="leg-row {cls}">
                  <div>
                    <span class="leg-label" style="color:{color}">{leg['action']}</span>
                    <span style="margin-left:8px;font-weight:600">{leg['strike']} {leg['type']}</span>
                  </div>
                  <div style="display:flex;gap:16px;font-family:'IBM Plex Mono',monospace">
                    <span>₹{leg['premium']}</span>
                    <span style="color:#9B9689">{leg['lots']}L × {lot_size}</span>
                    <span style="font-weight:700;color:{color}">
                      {'+'if leg['action']=='SELL' else '-'}₹{round(leg['premium']*lot_size*leg['lots']):,}
                    </span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

            # Payoff graph using st.line_chart
            spot_range = list(range(
                int(spot * 0.92), int(spot * 1.08), int(spot * 0.002)
            ))
            payoffs = calc_payoff(legs, spot_range, lot_size)
            chart_data = {"P&L (₹)": payoffs}
            st.markdown('<div class="payoff-wrap"><div class="card-label">Payoff at Expiry</div>', unsafe_allow_html=True)
            st.line_chart(chart_data, height=180, use_container_width=True)
            zero_line = [0] * len(spot_range)
            st.markdown(f"""
            <div style="display:flex;gap:16px;font-size:10px;font-family:'IBM Plex Mono',monospace;
                        color:#9B9689;margin-top:4px">
              <span>Range: {spot_range[0]:,} – {spot_range[-1]:,}</span>
              <span>ATM: {atm:,}</span>
              <span>Credit: ₹{credit:,}</span>
            </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"⚡  Paper Trade — {strategy['name']}", key="btn_execute_strat", use_container_width=True):
                add_trade(PRODUCT, strategy["name"], f"{index} {expiry}",
                          "SELL" if credit>0 else "BUY",
                          credit, credit*0.5, credit*2,
                          extra={"legs": legs, "index": index, "expiry": expiry})
                update_state(PRODUCT, trades_taken=state["trades_taken"]+1)
                st.success(f"✓ {strategy['name']} paper traded. Credit: ₹{credit:,}")

        else:
            st.markdown("""
            <div class="card" style="text-align:center;padding:60px 20px">
              <div style="font-size:32px;margin-bottom:8px">📐</div>
              <div style="color:#9B9689;font-size:13px">Select a strategy from the left to see details, legs and payoff graph.</div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
elif tab == "builder":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;
                color:#1A1916;margin-bottom:14px">🔧 Strategy Builder</div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([2,3], gap="medium")

    with col_left:
        st.markdown('<div class="card"><div class="card-label">Add Leg</div>', unsafe_allow_html=True)
        strike_options = [c["strike"] for c in chain]
        l1,l2 = st.columns(2)
        with l1:
            b_type   = st.selectbox("Type",   ["CE","PE"],        key="b_type")
            b_action = st.selectbox("Action", ["SELL","BUY"],     key="b_action")
        with l2:
            b_strike = st.selectbox("Strike", strike_options,     key="b_strike")
            b_lots   = st.number_input("Lots", value=1, min_value=1, key="b_lots")

        prem_row = next((c for c in chain if c["strike"]==b_strike), chain[0])
        prem = prem_row["ce_premium"] if b_type=="CE" else prem_row["pe_premium"]
        st.markdown(f"""
        <div style="background:#F5F4F0;border-radius:6px;padding:8px 12px;margin:8px 0;
                    font-family:'IBM Plex Mono',monospace;font-size:12px">
          Premium: <b>₹{prem}</b> &nbsp;·&nbsp; Value: <b>₹{round(prem*lot_size*b_lots):,}</b>
        </div>
        """, unsafe_allow_html=True)

        if st.button("+ Add Leg", use_container_width=True, key="add_leg"):
            st.session_state.builder_legs.append({
                "type": b_type, "action": b_action,
                "strike": b_strike, "premium": prem, "lots": b_lots,
            })
            st.rerun()

        if st.button("🗑 Clear All", use_container_width=True, key="clear_legs"):
            st.session_state.builder_legs = []
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # Current legs
        if st.session_state.builder_legs:
            st.markdown('<div class="card"><div class="card-label">Your Legs</div>', unsafe_allow_html=True)
            for i, leg in enumerate(st.session_state.builder_legs):
                cls = "leg-sell" if leg["action"]=="SELL" else "leg-buy"
                color = "#C0392B" if leg["action"]=="SELL" else "#1A7F4B"
                st.markdown(f"""
                <div class="leg-row {cls}">
                  <span class="leg-label" style="color:{color}">{leg['action']} {leg['strike']} {leg['type']}</span>
                  <span style="font-family:'IBM Plex Mono',monospace;font-size:11px">
                    ₹{leg['premium']} × {leg['lots']}L
                  </span>
                </div>
                """, unsafe_allow_html=True)
                if st.button("Remove", key=f"rm_leg_{i}", use_container_width=True):
                    st.session_state.builder_legs.pop(i)
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    with col_right:
        legs = st.session_state.builder_legs
        if legs:
            credit = net_credit(legs, lot_size)
            m1,m2,m3 = st.columns(3)
            for col,(lbl,val,c) in zip([m1,m2,m3],[
                ("Net Credit", f"₹{credit:,}", "#1A7F4B" if credit>0 else "#C0392B"),
                ("Legs",       str(len(legs)), "#1A1916"),
                ("Lot Size",   str(lot_size),  "#1A1916"),
            ]):
                with col:
                    st.markdown(f'<div class="metric-box"><div class="metric-val" style="color:{c}">{val}</div><div class="metric-lbl">{lbl}</div></div>', unsafe_allow_html=True)

            spot_range = list(range(int(spot*0.92), int(spot*1.08), int(spot*0.002)))
            payoffs    = calc_payoff(legs, spot_range, lot_size)
            st.markdown('<div class="payoff-wrap"><div class="card-label">Custom Payoff Graph</div>', unsafe_allow_html=True)
            st.line_chart({"P&L (₹)": payoffs}, height=220, use_container_width=True)
            st.markdown(f"""
            <div style="font-size:10px;font-family:'IBM Plex Mono',monospace;color:#9B9689;margin-top:4px">
              Range: {spot_range[0]:,} – {spot_range[-1]:,} &nbsp;·&nbsp; ATM: {atm:,}
            </div></div>
            """, unsafe_allow_html=True)

            name = st.text_input("Strategy name (optional)", placeholder="My Custom Strategy", key="custom_name")
            if st.button("⚡  Paper Trade This Strategy", key="btn_execute_custom", use_container_width=True):
                sname = name or "Custom Strategy"
                add_trade(PRODUCT, sname, f"{index} {expiry}", "SELL" if credit>0 else "BUY",
                          credit, credit*0.5, credit*2, extra={"legs": legs})
                update_state(PRODUCT, trades_taken=state["trades_taken"]+1)
                st.success(f"✓ {sname} paper traded.")
        else:
            st.markdown("""
            <div class="card" style="text-align:center;padding:60px 20px">
              <div style="font-size:32px;margin-bottom:8px">🔧</div>
              <div style="color:#9B9689;font-size:13px">Add legs on the left to build your strategy and see the payoff graph.</div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
elif tab == "chain":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown(f"""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;
                color:#1A1916;margin-bottom:14px">Option Chain — {index} {expiry}</div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="chain-row" style="font-weight:700;border-bottom:2px solid #1A1916;margin-bottom:6px;padding-bottom:8px">
      <span style="width:80px">CE PREM</span>
      <span style="width:60px">CE Δ</span>
      <span style="width:80px;text-align:center;color:#E8540A">STRIKE</span>
      <span style="width:60px;text-align:right">PE Δ</span>
      <span style="width:80px;text-align:right">PE PREM</span>
    </div>
    """, unsafe_allow_html=True)

    for row in chain:
        is_atm = row["strike"] == atm
        cls = "chain-row atm" if is_atm else "chain-row"
        atm_marker = " ◀ ATM" if is_atm else ""
        ce_color = "#1A7F4B" if row["ce_delta"] > 0.4 else "#1A1916"
        pe_color = "#C0392B" if abs(row["pe_delta"]) > 0.4 else "#1A1916"
        st.markdown(f"""
        <div class="{cls}">
          <span style="width:80px;color:{ce_color};font-weight:{'700' if is_atm else '400'}">₹{row['ce_premium']}</span>
          <span style="width:60px;color:#9B9689">{row['ce_delta']:.2f}</span>
          <span style="width:80px;text-align:center;font-weight:700;color:{'#E8540A' if is_atm else '#1A1916'}">{row['strike']:,}{atm_marker}</span>
          <span style="width:60px;text-align:right;color:#9B9689">{row['pe_delta']:.2f}</span>
          <span style="width:80px;text-align:right;color:{pe_color};font-weight:{'700' if is_atm else '400'}">₹{row['pe_premium']}</span>
        </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size:10px;font-family:'IBM Plex Mono',monospace;color:#9B9689;margin-top:8px">
      Spot: {spot:,} · ATM: {atm:,} · IV: {iv}% · DTE: {[10,17,24,52][expiry_idx]} · Lot: {lot_size} · Data: Simulated
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
elif tab == "journal":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;
                color:#1A1916;margin-bottom:14px">📊 SUTRA Journal</div>
    """, unsafe_allow_html=True)

    trades    = get_today_trades(PRODUCT)
    total_pnl = sum(t["pnl"] for t in trades)
    open_pos  = sum(1 for t in trades if t["status"]=="OPEN")

    c1,c2,c3 = st.columns(3)
    for col,(lbl,val,c) in zip([c1,c2,c3],[
        ("Strategies Today", str(len(trades)), "#1A1916"),
        ("Open Positions",   str(open_pos),   "#1E40AF"),
        ("Realised P&L",     f"{'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}", "#1A7F4B" if total_pnl>=0 else "#C0392B"),
    ]):
        with col:
            st.markdown(f'<div class="metric-box"><div class="metric-val" style="color:{c}">{val}</div><div class="metric-lbl">{lbl}</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='margin-top:10px'>", unsafe_allow_html=True)
    if trades:
        st.markdown('<div class="card"><div class="card-label">Today\'s Positions</div>', unsafe_allow_html=True)
        for t in trades:
            pc = "#1A7F4B" if t["pnl"]>=0 else "#C0392B"
            badge = "badge-blue" if t["status"]=="OPEN" else "badge-green"
            extra = json.loads(t["extra_json"] or "{}")
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;align-items:center;
                        padding:10px 0;border-bottom:1px solid #ECEAE4;font-size:12px">
              <div>
                <div style="font-weight:700;font-size:13px;color:#1A1916">{t['strategy']}</div>
                <div style="font-size:10px;color:#9B9689">{t['instrument']} · {t['time'][:5]} · {len(extra.get('legs',[]))} legs</div>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                <div class="badge {badge}">{t['status']}</div>
                <div style="font-family:'IBM Plex Mono',monospace;font-weight:700;color:{pc}">
                  {'+'if t['pnl']>=0 else ''}₹{t['pnl']:,.0f}
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="card" style="text-align:center;padding:40px">
          <div style="font-size:32px;margin-bottom:8px">📭</div>
          <div style="color:#9B9689;font-size:13px">No strategies traded today.</div>
        </div>
        """, unsafe_allow_html=True)

    # EOD emotion
    eod = get_eod_emotion(PRODUCT)
    if not eod:
        st.markdown('<div class="card"><div class="card-label">EOD — How did you feel?</div>', unsafe_allow_html=True)
        ec1,ec2,ec3,ec4 = st.columns(4)
        for col,(label,val) in zip([ec1,ec2,ec3,ec4],[("😌 Calm","Calm"),("😰 Anxious","Anxious"),("😤 Frustrated","Frustrated"),("🎯 Focused","Focused")]):
            with col:
                if st.button(label, use_container_width=True, key=f"eod_{val}"):
                    save_eod_emotion(PRODUCT, val)
                    add_reward(PRODUCT, "EMOTION_LOGGED")
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # Kill switch
    if st.button("🛑  Kill Switch — Stop Options Trading", key="btn_kill", use_container_width=True):
        trigger_kill(PRODUCT)
        st.session_state.show_kill_overlay = True
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# ── BOTTOM NAV ─────────────────────────────────────────────────────────────────
if st.button("📐 Guided",  key="nav_guided",  use_container_width=True): st.session_state.tab="guided";  st.rerun()
if st.button("🔧 Builder", key="nav_builder", use_container_width=True): st.session_state.tab="builder"; st.rerun()
if st.button("📊 Chain",   key="nav_chain",   use_container_width=True): st.session_state.tab="chain";   st.rerun()
if st.button("📓 Journal", key="nav_journal", use_container_width=True): st.session_state.tab="journal"; st.rerun()
