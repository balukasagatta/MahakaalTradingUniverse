"""
VAJRA Scalping Board v2.0
Ultra-fast scalp terminal · PRAGNYA discipline engine built-in
Light theme · Mobile + Desktop optimised
"""
import streamlit as st
import json, os
from datetime import datetime, date
from pragnya_engine import (
    get_state, update_state, check_rules, log_violation,
    trigger_kill, trigger_cooling, record_sl_hit,
    add_trade, close_trade, get_today_trades, get_today_violations,
    get_daily_quote, save_eod_emotion, get_eod_emotion,
    add_reward, get_total_rewards,
)
import pytz

IST      = pytz.timezone("Asia/Kolkata")
PRODUCT  = "VAJRA"
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vajra_config.json")

DEFAULT_CFG = {
    "max_trades_per_day": 4,
    "daily_loss_limit": -2500,
    "daily_target": 5000,
    "max_sl_hits": 2,
    "cooling_minutes_after_sl": 15,
    "cooling_minutes_after_target": 30,
    "position_size_lots": 2,
    "sl_points": 20,
    "target_points": 40,
    "enable_pre_trade_breathe": True,
    "breathe_seconds": 10,
    "auto_kill_switch": True,
    "revenge_trade_threshold": 2,
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

def save_cfg(cfg):
    json.dump(cfg, open(CFG_PATH, "w"), indent=2)

CFG = load_cfg()

# ── PAGE SETUP ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VAJRA | MTU Terminal",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

for k, v in [
    ("tab", "board"),
    ("breathe_active", False),
    ("breathe_triggered_by", None),
    ("show_kill_overlay", False),
    ("show_win_overlay", False),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── DESIGN TOKENS ──────────────────────────────────────────────────────────────
st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* ── Reset ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; }
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section.main { background: #F5F4F0 !important; }
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
#MainMenu, footer { display: none !important; }
[data-testid="block-container"] {
    padding: 0 16px 80px !important;
    max-width: 1200px !important;
    margin: 0 auto !important;
}

/* ── Typography ── */
body, .stMarkdown, .stText { font-family: 'IBM Plex Sans', sans-serif !important; }

/* ── Cards ── */
.card {
    background: #FFFFFF;
    border: 1px solid #E2E0D8;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.card-sm { padding: 10px 14px; }
.card-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #9B9689;
    margin-bottom: 8px;
}

/* ── Tape numbers ── */
.tape {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 26px;
    font-weight: 700;
    color: #1A1916;
    line-height: 1;
}
.tape-sm { font-size: 18px; }
.tape-xs { font-size: 13px; }
.up   { color: #1A7F4B !important; }
.down { color: #C0392B !important; }
.amber { color: #B45309 !important; }

/* ── Status badge ── */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 8px;
    border-radius: 4px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.badge-green  { background: #D1FAE5; color: #065F46; }
.badge-red    { background: #FEE2E2; color: #991B1B; }
.badge-amber  { background: #FEF3C7; color: #92400E; }
.badge-blue   { background: #DBEAFE; color: #1E40AF; }
.badge-gray   { background: #F3F2EE; color: #5C5A54; }

/* ── Progress bar ── */
.prog-wrap { background: #ECEAE4; border-radius: 100px; height: 5px; overflow: hidden; margin-top: 4px; }
.prog-fill  { height: 100%; border-radius: 100px; transition: width .3s; }

/* ── Trigger row ── */
.trig-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid #ECEAE4;
    font-size: 12px;
}
.trig-row:last-child { border-bottom: none; }
.trig-dot {
    width: 8px; height: 8px; border-radius: 50%;
    margin-top: 3px; flex-shrink: 0;
}

/* ── Header ── */
.header-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0 10px;
    border-bottom: 2px solid #1A1916;
    margin-bottom: 14px;
}
.logo {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 20px;
    font-weight: 700;
    color: #1A1916;
    letter-spacing: -0.5px;
}
.logo span { color: #E8540A; }

/* ── Stat block ── */
.stat-block { text-align: right; }
.stat-block .lbl {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 8px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #9B9689;
}
.stat-block .val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 15px;
    font-weight: 700;
    color: #1A1916;
    line-height: 1.1;
}

/* ── Warning banner ── */
.warn-banner {
    background: #FEF9EC;
    border: 1px solid #F6D860;
    border-left: 3px solid #F6A800;
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 8px;
    font-size: 12px;
    color: #7A4F00;
    font-weight: 500;
}
.err-banner {
    background: #FEF2F2;
    border: 1px solid #FECACA;
    border-left: 3px solid #C0392B;
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 8px;
    font-size: 12px;
    color: #991B1B;
    font-weight: 500;
}

/* ── Locked screen ── */
.locked-screen {
    background: #FFFBF5;
    border: 1.5px solid #FECACA;
    border-radius: 14px;
    padding: 40px 24px;
    text-align: center;
    margin: 24px 0;
}
.locked-screen .icon { font-size: 48px; margin-bottom: 12px; }
.locked-screen .title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 22px;
    font-weight: 700;
    color: #C0392B;
    margin-bottom: 6px;
}
.locked-screen .reason {
    font-size: 14px;
    color: #9B9689;
    margin-bottom: 20px;
}
.quote-box {
    background: #F5F4F0;
    border-radius: 8px;
    padding: 16px;
    text-align: left;
    margin-top: 16px;
}
.quote-text { font-size: 13px; color: #3D3B35; font-style: italic; line-height: 1.6; }
.quote-src  { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: #9B9689; margin-top: 6px; letter-spacing: 1px; }

/* ── Overlay ── */
.overlay {
    position: fixed; inset: 0;
    background: rgba(245,244,240,0.96);
    z-index: 99999;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 32px;
}
.breathe-ring {
    width: 120px; height: 120px;
    border: 3px solid #E8540A;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 36px; font-weight: 700;
    color: #E8540A;
    animation: pulse 4s ease-in-out infinite;
}
@keyframes pulse {
    0%,100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(232,84,10,0.3); }
    50%      { transform: scale(1.08); box-shadow: 0 0 0 20px rgba(232,84,10,0); }
}

/* ── Trade row ── */
.trade-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #ECEAE4;
    font-size: 12px;
}
.trade-row:last-child { border-bottom: none; }

/* ── Bottom nav ── */
[data-testid="block-container"] { padding-bottom: 72px !important; }
.st-key-nav_board,
.st-key-nav_journal,
.st-key-nav_config {
    position: fixed !important;
    bottom: 0 !important;
    z-index: 9999 !important;
    height: 56px !important;
}
.st-key-nav_board   { left: 0 !important;        width: 33.33vw !important; }
.st-key-nav_journal { left: 33.33vw !important;  width: 33.33vw !important; }
.st-key-nav_config  { left: 66.66vw !important;  width: 33.33vw !important; }
.st-key-nav_board button,
.st-key-nav_journal button,
.st-key-nav_config button {
    background: #FFFFFF !important;
    border: none !important;
    border-top: 1px solid #E2E0D8 !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    width: 100% !important;
    height: 56px !important;
    min-height: 56px !important;
    padding: 0 !important;
    color: #9B9689 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
}
.st-key-nav_board button:hover,
.st-key-nav_journal button:hover,
.st-key-nav_config button:hover {
    color: #E8540A !important;
    border-top: 2px solid #E8540A !important;
}

/* ── Buttons ── */
.stButton > button {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 7px !important;
    border: 1.5px solid #E2E0D8 !important;
    background: #FFFFFF !important;
    color: #1A1916 !important;
    font-size: 13px !important;
    padding: 8px 16px !important;
    transition: all .15s !important;
}
.stButton > button:hover {
    border-color: #1A1916 !important;
    background: #F5F4F0 !important;
}

/* Execute button */
.st-key-btn_execute > button {
    background: #1A7F4B !important;
    color: #FFFFFF !important;
    border-color: #1A7F4B !important;
    font-size: 14px !important;
    padding: 12px !important;
    font-weight: 700 !important;
}
/* Kill button */
.st-key-btn_kill > button {
    background: #C0392B !important;
    color: #FFFFFF !important;
    border-color: #C0392B !important;
    font-weight: 700 !important;
}
/* Breathe button */
.st-key-btn_breathe > button {
    background: #E8540A !important;
    color: #FFFFFF !important;
    border-color: #E8540A !important;
    font-weight: 700 !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-thumb { background: #D1CFC8; border-radius: 2px; }

/* ── Number inputs / selects ── */
.stNumberInput input, .stTextInput input, .stSelectbox select {
    border: 1.5px solid #E2E0D8 !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 13px !important;
    background: #FFFFFF !important;
}
.stToggle label { font-family: 'IBM Plex Sans', sans-serif !important; }
</style>
""", unsafe_allow_html=True)

# ── RUNTIME ────────────────────────────────────────────────────────────────────
now   = datetime.now(IST)
state = get_state(PRODUCT)
can_trade, warnings, lock = check_rules(PRODUCT, CFG)

quote_text, quote_src = get_daily_quote()

dscore = state["discipline_score"]
d_col  = "up" if dscore >= 80 else "amber" if dscore >= 50 else "down"
pnl    = state["daily_pnl"]
pnl_col = "up" if pnl >= 0 else "down"

# ── HEADER ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="header-bar">
  <div>
    <div class="logo">⚡ <span>VAJRA</span></div>
    <div style="font-size:10px;color:#9B9689;font-family:'IBM Plex Mono',monospace;
                letter-spacing:1px;margin-top:1px">
      SCALPING BOARD · {now.strftime('%d %b %Y · %H:%M:%S')} IST
    </div>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <div class="stat-block">
      <div class="lbl">PRAGNYA</div>
      <div class="val {d_col}">{dscore}<span style="font-size:10px;color:#9B9689">/100</span></div>
    </div>
    <div class="stat-block">
      <div class="lbl">TRADES</div>
      <div class="val {'up' if state['trades_taken'] < CFG['max_trades_per_day'] else 'down'}">{state['trades_taken']}<span style="font-size:10px;color:#9B9689">/{CFG['max_trades_per_day']}</span></div>
    </div>
    <div class="stat-block">
      <div class="lbl">DAY P&L</div>
      <div class="val {pnl_col}">{'+'if pnl>=0 else ''}₹{pnl:,.0f}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── BREATHE OVERLAY ────────────────────────────────────────────────────────────
if st.session_state.breathe_active:
    triggered_by = st.session_state.breathe_triggered_by or "Pre-trade check"
    st.markdown(f"""
    <div class="overlay">
      <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:3px;
                  color:#9B9689;margin-bottom:28px;text-transform:uppercase">PRAGNYA MIND</div>
      <div class="breathe-ring">🌬️</div>
      <div style="margin-top:24px;font-size:15px;font-weight:600;color:#1A1916;text-align:center">
        Take 3 deep breaths
      </div>
      <div style="margin-top:8px;font-size:13px;color:#9B9689;text-align:center;max-width:280px;line-height:1.6">
        {triggered_by}<br>Step away for 5 minutes. Come back fresh.
      </div>
      <div class="quote-box" style="max-width:360px;margin-top:24px">
        <div class="quote-text">"{quote_text}"</div>
        <div class="quote-src">— {quote_src}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✓ I'm ready to trade", use_container_width=True, key="breathe_ok"):
            st.session_state.breathe_active = False
            st.session_state.breathe_triggered_by = None
            st.rerun()
    with col_b:
        if st.button("✗ Skip for now", use_container_width=True, key="breathe_skip"):
            log_violation(PRODUCT, "BREATHE_SKIPPED", "Pre-trade breathe skipped", "WARNING")
            st.session_state.breathe_active = False
            st.rerun()
    st.stop()

# ── KILL SWITCH GITA OVERLAY ───────────────────────────────────────────────────
if st.session_state.show_kill_overlay:
    st.markdown(f"""
    <div class="overlay">
      <div style="font-size:48px;margin-bottom:16px">🕉️</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:700;
                  color:#C0392B;margin-bottom:8px">KILL SWITCH ACTIVE</div>
      <div style="font-size:13px;color:#9B9689;margin-bottom:32px">Trading is stopped for today.</div>
      <div class="quote-box" style="max-width:400px">
        <div class="quote-text">"{quote_text}"</div>
        <div class="quote-src">— {quote_src}</div>
      </div>
      <div style="margin-top:20px;font-size:12px;color:#9B9689;text-align:center;max-width:320px;line-height:1.6">
        Your capital is protected. Rest. Review. Come back stronger tomorrow.
      </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Close", key="kill_overlay_close"):
        st.session_state.show_kill_overlay = False
        st.rerun()
    st.stop()

# ── WIN OVERLAY ────────────────────────────────────────────────────────────────
if st.session_state.show_win_overlay:
    st.markdown(f"""
    <div class="overlay">
      <div style="font-size:52px;margin-bottom:12px">🎯</div>
      <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;font-weight:700;
                  color:#1A7F4B;margin-bottom:8px">TARGET HIT!</div>
      <div style="font-size:15px;color:#1A1916;font-weight:600;margin-bottom:4px">
        ₹{CFG['daily_target']:,.0f} target achieved today.
      </div>
      <div style="font-size:13px;color:#9B9689;margin-bottom:28px">
        A good trader knows when to stop.
      </div>
      <div style="background:#D1FAE5;border-radius:10px;padding:16px 24px;text-align:center">
        <div style="font-size:13px;color:#065F46;font-weight:600">Log off now. Protect your gains.</div>
        <div style="font-size:11px;color:#065F46;margin-top:4px">Every extra trade after target is a risk trade.</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✓ Log off for today", use_container_width=True, key="win_stop"):
            trigger_kill(PRODUCT)
            add_reward(PRODUCT, "TARGET_STOP")
            st.session_state.show_win_overlay = False
            st.rerun()
    with c2:
        if st.button("Continue (I know the risk)", use_container_width=True, key="win_continue"):
            log_violation(PRODUCT, "POST_TARGET_TRADE", "Continued trading after target hit", "WARNING")
            st.session_state.show_win_overlay = False
            st.rerun()
    st.stop()

# ── LOCKED SCREEN ──────────────────────────────────────────────────────────────
if lock["locked"]:
    trades_today = get_today_trades(PRODUCT)
    total_today  = sum(t["pnl"] for t in trades_today)

    st.markdown(f"""
    <div class="locked-screen">
      <div class="icon">🛑</div>
      <div class="title">TERMINAL LOCKED</div>
      <div class="reason">{lock['reason']}</div>
      {'<div style="font-family:IBM Plex Mono,monospace;font-size:22px;font-weight:700;color:' +
       ('#1A7F4B' if total_today >= 0 else '#C0392B') + '">' +
       ('+' if total_today >= 0 else '') + f'₹{total_today:,.0f}</div>' if trades_today else ''}
      <div class="quote-box">
        <div class="quote-text">"{quote_text}"</div>
        <div class="quote-src">— {quote_src}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # EOD emotion capture
    eod = get_eod_emotion(PRODUCT)
    if not eod:
        st.markdown('<div class="card"><div class="card-label">How did you feel today?</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        emotions = [("😌 Calm", "Calm"), ("😰 Anxious", "Anxious"),
                    ("😤 Frustrated", "Frustrated"), ("🎯 Focused", "Focused")]
        for col, (label, val) in zip(cols, emotions):
            with col:
                if st.button(label, use_container_width=True, key=f"emo_{val}"):
                    save_eod_emotion(PRODUCT, val)
                    add_reward(PRODUCT, "EMOTION_LOGGED")
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="card" style="text-align:center">
          <div class="card-label">Today's emotion logged</div>
          <div style="font-size:20px;margin-top:4px">{eod['emotion']}</div>
        </div>
        """, unsafe_allow_html=True)

    # Today's trades summary
    if trades_today:
        st.markdown('<div class="card"><div class="card-label">Today\'s Trades</div>', unsafe_allow_html=True)
        for t in trades_today:
            pc = "up" if t["pnl"] >= 0 else "down"
            st.markdown(f"""
            <div class="trade-row">
              <span style="font-weight:600;color:#1A1916">{t['instrument']}</span>
              <span style="color:#9B9689">{t['direction']} · {t['time'][:5]}</span>
              <span class="{pc}" style="font-family:'IBM Plex Mono',monospace;font-weight:700">
                {'+'if t['pnl']>=0 else ''}₹{t['pnl']:,.0f}
              </span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ── WARNING BANNERS ────────────────────────────────────────────────────────────
for w in warnings:
    st.markdown(f'<div class="warn-banner">⚠️ {w}</div>', unsafe_allow_html=True)

# ── TABS ───────────────────────────────────────────────────────────────────────
tab = st.session_state.tab

# ══════════════════════════════════════════════════════════════════════════════
if tab == "board":
# ══════════════════════════════════════════════════════════════════════════════

    col_left, col_right = st.columns([3, 2], gap="medium")

    # ── LEFT: Market + Triggers ──────────────────────────────────────────────
    with col_left:

        # Market Pulse card
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-label">Market Pulse</div>', unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        tickers = [
            ("SENSEX", "74,839", "+318", "+0.43%", True),
            ("NIFTY",  "23,456", "+89",  "+0.38%", True),
            ("ATM IV", "14.2%",  "IN RANGE", "", True),
            ("VIX",    "12.8",   "LOW", "", True),
        ]
        for col, (label, val, change, pct, up) in zip([m1, m2, m3, m4], tickers):
            with col:
                color = "#1A7F4B" if up else "#C0392B"
                st.markdown(f"""
                <div>
                  <div style="font-family:'IBM Plex Mono',monospace;font-size:9px;
                              letter-spacing:1.5px;color:#9B9689;text-transform:uppercase">{label}</div>
                  <div style="font-family:'IBM Plex Mono',monospace;font-size:20px;
                              font-weight:700;color:#1A1916;line-height:1.1;margin-top:2px">{val}</div>
                  <div style="font-size:10px;color:{color};font-weight:600;margin-top:2px">
                    {change} {pct}
                  </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid #ECEAE4;
                    display:flex;gap:16px;flex-wrap:wrap">
          <span style="font-size:11px;color:#9B9689">ORB: <b style="color:#1A7F4B">BULLISH</b></span>
          <span style="font-size:11px;color:#9B9689">Volume: <b style="color:#1A1916">1.4× avg</b></span>
          <span style="font-size:11px;color:#9B9689">ATR: <b style="color:#1A1916">42 pts</b></span>
          <span style="font-size:11px;color:#9B9689">Trend: <b style="color:#1A7F4B">3-EMA ↑</b></span>
          <span style="font-size:11px;color:#9B9689">PDH: <b style="color:#1A1916">47,920</b></span>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Entry Triggers card
        triggers = [
            ("Price > ORB High (47,720)",     True,  "47,842 > 47,720 ✓"),
            ("Volume > 1.5× Average",          False, "1.4× — marginal"),
            ("RSI not overbought (<70)",        False, "RSI 73.8 — wait"),
            ("3-EMA aligned bullish",           True,  "9 > 21 > 50 EMA ✓"),
            ("PRAGNYA clear to trade",          can_trade, "No violations" if can_trade else "Check PRAGNYA"),
        ]
        met = sum(1 for _, ok, _ in triggers if ok)
        needed = 4

        st.markdown(f'<div class="card">', unsafe_allow_html=True)
        st.markdown(f"""
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <div class="card-label" style="margin-bottom:0">Entry Triggers</div>
          <div class="badge {'badge-green' if met>=needed else 'badge-amber' if met>=3 else 'badge-red'}">
            {met}/{len(triggers)} met {'· READY' if met>=needed else '· WAIT'}
          </div>
        </div>
        """, unsafe_allow_html=True)

        for name, ok, detail in triggers:
            dot_color = "#1A7F4B" if ok else "#E2E0D8"
            name_color = "#1A1916" if ok else "#9B9689"
            st.markdown(f"""
            <div class="trig-row">
              <div class="trig-dot" style="background:{dot_color}"></div>
              <div style="flex:1">
                <div style="font-weight:600;color:{name_color};font-size:12px">{name}</div>
                <div style="font-size:10px;color:#9B9689;margin-top:1px">{detail}</div>
              </div>
              <div style="font-size:12px;font-weight:700;color:{'#1A7F4B' if ok else '#C8C6BF'}">
                {'✓' if ok else '✗'}
              </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<div style="margin-top:12px">', unsafe_allow_html=True)
        if met >= needed and can_trade:
            if CFG["enable_pre_trade_breathe"] and not st.session_state.breathe_active:
                if st.button("🌬️  Breathe check before executing", key="btn_breathe", use_container_width=True):
                    st.session_state.breathe_active = True
                    st.session_state.breathe_triggered_by = "Pre-trade ritual"
                    st.rerun()
            if st.button("⚡  Execute Long — BANKNIFTY", key="btn_execute", use_container_width=True):
                tid = add_trade(PRODUCT, "ORB_LONG", "BANKNIFTY",
                                "LONG", 47842, 47822, 47882)
                update_state(PRODUCT,
                             trades_taken=state["trades_taken"] + 1,
                             last_trade_time=now.strftime("%H:%M:%S"))
                if state["daily_pnl"] + 2000 >= CFG["daily_target"]:
                    st.session_state.show_win_overlay = True
                st.rerun()
        else:
            st.markdown(f"""
            <div style="background:#F5F4F0;border:1px solid #E2E0D8;border-radius:7px;
                        padding:12px;text-align:center;color:#9B9689;font-size:12px">
              Waiting for {needed - met} more trigger{'s' if needed-met!=1 else ''} …
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div></div>', unsafe_allow_html=True)

    # ── RIGHT: Discipline + Positions ────────────────────────────────────────
    with col_right:

        # Discipline Guard
        trade_pct = min(100, state["trades_taken"] / CFG["max_trades_per_day"] * 100)
        loss_pct  = min(100, abs(pnl) / abs(CFG["daily_loss_limit"]) * 100) if CFG["daily_loss_limit"] else 0
        sl_pct    = min(100, state["sl_hits"] / CFG["max_sl_hits"] * 100) if CFG["max_sl_hits"] else 0

        def bar_color(pct):
            return "#1A7F4B" if pct < 50 else "#B45309" if pct < 80 else "#C0392B"

        st.markdown(f"""
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div class="card-label" style="margin-bottom:0">Discipline Guard</div>
            <div class="badge {'badge-green' if dscore>=80 else 'badge-amber' if dscore>=50 else 'badge-red'}">
              PRAGNYA {dscore}/100
            </div>
          </div>

          <div style="margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#5C5A54;margin-bottom:4px">
              <span>Trades used</span><span style="font-family:'IBM Plex Mono',monospace">{state['trades_taken']}/{CFG['max_trades_per_day']}</span>
            </div>
            <div class="prog-wrap"><div class="prog-fill" style="width:{trade_pct}%;background:{bar_color(trade_pct)}"></div></div>
          </div>

          <div style="margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#5C5A54;margin-bottom:4px">
              <span>Loss used</span><span style="font-family:'IBM Plex Mono',monospace">₹{abs(pnl):,.0f} / ₹{abs(CFG['daily_loss_limit']):,.0f}</span>
            </div>
            <div class="prog-wrap"><div class="prog-fill" style="width:{loss_pct}%;background:{bar_color(loss_pct)}"></div></div>
          </div>

          <div style="margin-bottom:14px">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#5C5A54;margin-bottom:4px">
              <span>SL hits</span><span style="font-family:'IBM Plex Mono',monospace">{state['sl_hits']}/{CFG['max_sl_hits']}</span>
            </div>
            <div class="prog-wrap"><div class="prog-fill" style="width:{sl_pct}%;background:{bar_color(sl_pct)}"></div></div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🛑  Kill Switch", key="btn_kill", use_container_width=True):
            trigger_kill(PRODUCT)
            st.session_state.show_kill_overlay = True
            st.rerun()

        # Daily Gita quote card
        st.markdown(f"""
        <div class="card" style="margin-top:4px">
          <div class="card-label">Today's Gita</div>
          <div style="font-size:12px;color:#3D3B35;font-style:italic;line-height:1.6">"{quote_text}"</div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#9B9689;
                      margin-top:8px;letter-spacing:1px">— {quote_src}</div>
        </div>
        """, unsafe_allow_html=True)

        # Open Positions
        open_trades = [t for t in get_today_trades(PRODUCT) if t["status"] == "OPEN"]
        st.markdown('<div class="card"><div class="card-label">Open Positions</div>', unsafe_allow_html=True)
        if not open_trades:
            st.markdown('<div style="color:#9B9689;font-size:12px;padding:8px 0">No open positions</div>',
                        unsafe_allow_html=True)
        for t in open_trades:
            unrealised = (47842 - t["entry"]) * 20 * CFG["position_size_lots"]
            u_col = "#1A7F4B" if unrealised >= 0 else "#C0392B"
            st.markdown(f"""
            <div style="border:1px solid #ECEAE4;border-radius:8px;padding:10px;margin-bottom:8px">
              <div style="display:flex;justify-content:space-between;margin-bottom:6px">
                <div>
                  <div style="font-weight:700;font-size:13px;color:#1A1916">{t['instrument']}</div>
                  <div style="font-size:10px;color:#9B9689">{t['direction']} · Entry {t['entry']:.0f} · SL {t['sl']:.0f}</div>
                </div>
                <div style="text-align:right">
                  <div style="font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:700;color:{u_col}">
                    {'+'if unrealised>=0 else ''}₹{unrealised:,.0f}
                  </div>
                  <div class="badge badge-blue" style="margin-top:4px">OPEN</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            bc, cc = st.columns(2)
            with bc:
                if st.button("🎯 Book Profit", key=f"book_{t['id']}", use_container_width=True):
                    close_trade(t["id"], 47882, unrealised, "TARGET", 8)
                    update_state(PRODUCT, daily_pnl=pnl + unrealised,
                                 target_hits=state["target_hits"] + 1)
                    if pnl + unrealised >= CFG["daily_target"]:
                        st.session_state.show_win_overlay = True
                    st.rerun()
            with cc:
                if st.button("✗ Cut Loss", key=f"cut_{t['id']}", use_container_width=True):
                    cut_pnl = (t["sl"] - t["entry"]) * 20 * CFG["position_size_lots"]
                    close_trade(t["id"], t["sl"], cut_pnl, "SL", 5)
                    update_state(PRODUCT, daily_pnl=pnl + cut_pnl)
                    record_sl_hit(PRODUCT, CFG)
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # PRAGNYA REWARDS
        total_pts = get_total_rewards()
        st.markdown(f"""
        <div class="card" style="margin-top:4px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div class="card-label" style="margin-bottom:0">PRAGNYA REWARDS</div>
            <div class="badge badge-amber">{total_pts} pts</div>
          </div>
          <div style="font-size:11px;color:#9B9689;margin-top:8px;line-height:1.5">
            No revenge trade: <b style="color:#1A1916">+50</b> ·
            Stop at target: <b style="color:#1A1916">+100</b> ·
            5-day streak: <b style="color:#1A1916">+500</b>
          </div>
        </div>
        """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
elif tab == "journal":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;
                color:#1A1916;margin-bottom:14px">📊 Trade Journal</div>
    """, unsafe_allow_html=True)

    trades    = get_today_trades(PRODUCT)
    total_pnl = sum(t["pnl"] for t in trades)
    wins      = sum(1 for t in trades if t["pnl"] > 0)
    losses    = sum(1 for t in trades if t["pnl"] < 0)

    c1, c2, c3, c4 = st.columns(4)
    stats = [
        ("Trades", str(len(trades)), "#1A1916"),
        ("Day P&L", f"{'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}",
         "#1A7F4B" if total_pnl >= 0 else "#C0392B"),
        ("Wins", str(wins), "#1A7F4B"),
        ("Losses", str(losses), "#C0392B"),
    ]
    for col, (label, val, color) in zip([c1, c2, c3, c4], stats):
        with col:
            st.markdown(f"""
            <div class="card" style="text-align:center;padding:12px">
              <div class="card-label">{label}</div>
              <div style="font-family:'IBM Plex Mono',monospace;font-size:24px;
                          font-weight:700;color:{color}">{val}</div>
            </div>
            """, unsafe_allow_html=True)

    if trades:
        st.markdown('<div class="card"><div class="card-label">Today\'s Trades</div>',
                    unsafe_allow_html=True)
        for t in trades:
            pc = "#1A7F4B" if t["pnl"] >= 0 else "#C0392B"
            badge_cls = "badge-green" if t["status"] == "CLOSED" else "badge-blue"
            st.markdown(f"""
            <div class="trade-row">
              <div>
                <div style="font-weight:700;font-size:13px;color:#1A1916">{t['instrument']}</div>
                <div style="font-size:10px;color:#9B9689">
                  {t['strategy']} · {t['direction']} · {t['time'][:5]}
                  {' · Exit: ' + t['exit_reason'] if t['exit_reason'] else ''}
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                <div class="badge {badge_cls}">{t['status']}</div>
                <div style="font-family:'IBM Plex Mono',monospace;font-size:14px;
                            font-weight:700;color:{pc};min-width:70px;text-align:right">
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
          <div style="color:#9B9689;font-size:13px">No trades today yet.</div>
        </div>
        """, unsafe_allow_html=True)

    # Violations log
    viols = get_today_violations(PRODUCT)
    if viols:
        st.markdown('<div class="card"><div class="card-label">Violations Today</div>',
                    unsafe_allow_html=True)
        for v in viols:
            sev_cls = ("badge-red" if v["severity"] == "LOCK"
                       else "badge-amber" if v["severity"] == "CRITICAL"
                       else "badge-gray")
            st.markdown(f"""
            <div class="trade-row">
              <div>
                <div style="font-weight:600;font-size:12px;color:#1A1916">{v['message']}</div>
                <div style="font-size:10px;color:#9B9689">{v['type']} · {v['time']}</div>
              </div>
              <div class="badge {sev_cls}">{v['severity']}</div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
elif tab == "config":
# ══════════════════════════════════════════════════════════════════════════════

    st.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:700;
                color:#1A1916;margin-bottom:14px">⚙️ VAJRA Configuration</div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="card-label">Discipline Rules</div>',
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        max_t  = st.number_input("Max Trades / Day",   value=CFG["max_trades_per_day"],  min_value=1, max_value=20)
        d_loss = st.number_input("Daily Loss Limit ₹", value=CFG["daily_loss_limit"],     max_value=0)
    with c2:
        d_tgt  = st.number_input("Daily Target ₹",     value=CFG["daily_target"],         min_value=500)
        max_sl = st.number_input("Max SL Hits",        value=CFG["max_sl_hits"],          min_value=1, max_value=5)
    with c3:
        cool_sl  = st.number_input("Cooling After SL (min)",  value=CFG["cooling_minutes_after_sl"],     min_value=5)
        cool_tgt = st.number_input("Cooling After Target (min)", value=CFG["cooling_minutes_after_target"], min_value=0)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="card-label">Execution Settings</div>',
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        lots   = st.number_input("Lots",         value=CFG["position_size_lots"], min_value=1)
        sl_pts = st.number_input("SL Points",    value=CFG["sl_points"],          min_value=5)
    with c2:
        tgt_pts = st.number_input("Target Points", value=CFG["target_points"],     min_value=10)
    with c3:
        breathe   = st.toggle("Pre-trade breathe check", value=CFG["enable_pre_trade_breathe"])
        auto_kill = st.toggle("Auto kill on loss limit",  value=CFG["auto_kill_switch"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card"><div class="card-label">Time Restrictions</div>',
                unsafe_allow_html=True)
    t1, t2, t3, t4 = st.columns(4)
    with t1: no_before = st.text_input("No trade before", value=CFG["time_restrictions"]["no_trade_before"])
    with t2: no_after  = st.text_input("No trade after",  value=CFG["time_restrictions"]["no_trade_after"])
    with t3: l_start   = st.text_input("Lunch start",     value=CFG["time_restrictions"]["lunch_break_start"])
    with t4: l_end     = st.text_input("Lunch end",       value=CFG["time_restrictions"]["lunch_break_end"])
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("💾  Save Configuration", use_container_width=True, key="save_cfg"):
        new_cfg = {
            "max_trades_per_day": max_t,
            "daily_loss_limit": d_loss,
            "daily_target": d_tgt,
            "max_sl_hits": max_sl,
            "cooling_minutes_after_sl": cool_sl,
            "cooling_minutes_after_target": cool_tgt,
            "position_size_lots": lots,
            "sl_points": sl_pts,
            "target_points": tgt_pts,
            "enable_pre_trade_breathe": breathe,
            "auto_kill_switch": auto_kill,
            "time_restrictions": {
                "no_trade_before": no_before,
                "no_trade_after": no_after,
                "lunch_break_start": l_start,
                "lunch_break_end": l_end,
            },
        }
        save_cfg(new_cfg)
        st.success("Saved. Refresh to apply.")

# ── BOTTOM NAV ──────────────────────────────────────────────────────────────────
if st.button("⚡  Board",   key="nav_board",   use_container_width=True): st.session_state.tab = "board";   st.rerun()
if st.button("📊  Journal", key="nav_journal", use_container_width=True): st.session_state.tab = "journal"; st.rerun()
if st.button("⚙️  Config",  key="nav_config",  use_container_width=True): st.session_state.tab = "config";  st.rerun()
