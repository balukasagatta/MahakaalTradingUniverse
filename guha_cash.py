"""
Guha Cash Trade Bot
===================
Simple execution bot for cash equity trades.
You spot the trade → send command → bot executes.

Broker:    Groww (cash equity, MIS intraday)
Telegram:  Guha bot
Strategy:  Manual signals from you
Target:    ₹500-600/day | Max loss: ₹500/day

Commands:
  /buy SYMBOL QTY TGT SL   → buy with OCO
  /sell SYMBOL QTY TGT SL  → sell/short with OCO
  /exit SYMBOL              → exit position now
  /exit all                 → exit all positions
  /positions                → open positions
  /pnl                      → today's P&L
  /journal                  → today's trades
  /journal week             → weekly summary
  /brief                    → manual pre-market brief
  /status                   → bot health
  /help                     → all commands
"""

import os, json, time, sqlite3, threading, requests, pyotp, math
from datetime import datetime, timedelta
from growwapi import GrowwAPI
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ===== CONVERSATION STATE =====
# Tracks multi-step buy/sell flow
CONV = {
    "step": None,      # None, "symbol", "capital", "target", "sl", "confirm"
    "side": None,      # BUY or SELL
    "symbol": None,
    "ltp": None,
    "capital": None,
    "qty": None,
    "target": None,
    "sl": None,
}
CONV_L = threading.Lock()

# ===== ENV =====
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env.vars")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ===== CREDENTIALS =====
GROWW_API_KEY    = os.getenv("GROWW_API_KEY", "")
GROWW_SECRET     = os.getenv("GROWW_SECRET", "")
TG_TOKEN         = os.getenv("GUHA_BOT_TOKEN", "")
TG_CHAT          = os.getenv("TELEGRAM_CHAT_ID", "")
IST              = pytz.timezone("Asia/Kolkata")
DB_PATH          = "guha_journal.db"
MAX_LOSS_DAY     = 500   # ₹ max loss per day
PAPER            = os.getenv("GUHA_PAPER", "true").lower() == "true"

# ===== STATE =====
GROWW_CLIENT = None
GROWW_TOKEN  = None
GROWW_LOCK   = threading.Lock()

RISK = {
    "date": None,
    "pnl": 0.0,
    "trades": 0,
    "halted": False,
}
RISK_L = threading.Lock()

# ===== UTILS =====
def now_ist():   return datetime.now(IST)
def today_str(): return now_ist().strftime("%Y-%m-%d")

# ===== TELEGRAM =====
def tg(msg, retries=3):
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

# ===== GROWW LOGIN =====
def groww_login():
    global GROWW_CLIENT, GROWW_TOKEN
    try:
        token = GrowwAPI.get_access_token(
            api_key=GROWW_API_KEY,
            secret=GROWW_SECRET)
        client = GrowwAPI(token)
        profile = client.get_user_profile()
        with GROWW_LOCK:
            GROWW_CLIENT = client
            GROWW_TOKEN = token
        print(f"[Groww] ✅ Connected: {profile.get('ucc')}")
        return True
    except Exception as e:
        print(f"[Groww] Login error: {e}")
        return False

def groww():
    with GROWW_LOCK:
        return GROWW_CLIENT

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            entry_price REAL,
            exit_price REAL,
            target REAL,
            sl REAL,
            pnl REAL,
            status TEXT,
            entry_time TEXT,
            exit_time TEXT,
            order_id TEXT,
            oco_id TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_trade(symbol, side, qty, entry, target, sl, order_id="", oco_id=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO trades
        (date, symbol, side, qty, entry_price, target, sl,
         status, entry_time, order_id, oco_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (today_str(), symbol, side, qty, entry, target, sl,
          "OPEN", now_ist().strftime("%H:%M:%S"), order_id, oco_id))
    conn.commit()
    conn.close()

def close_trade(symbol, exit_price, pnl):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE trades SET
            exit_price=?, pnl=?,
            status='CLOSED',
            exit_time=?
        WHERE symbol=? AND status='OPEN'
        AND date=?
    """, (exit_price, pnl,
          now_ist().strftime("%H:%M:%S"),
          symbol, today_str()))
    conn.commit()
    conn.close()

def get_today_trades():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT symbol, side, qty, entry_price,
               exit_price, target, sl, pnl, status,
               entry_time, exit_time
        FROM trades WHERE date=?
        ORDER BY id
    """, (today_str(),))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_week_trades():
    week_ago = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT date, symbol, side, qty, entry_price,
               exit_price, pnl, status
        FROM trades WHERE date >= ?
        ORDER BY date, id
    """, (week_ago,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ===== DAILY RESET =====
def reset_daily():
    today = now_ist().date()
    with RISK_L:
        if RISK["date"] != today:
            RISK.update({
                "date": today,
                "pnl": 0.0,
                "trades": 0,
                "halted": False,
            })

# ===== GROWW HELPERS =====
def get_ltp(symbol):
    try:
        g = groww()
        if not g: return None
        r = g.get_ltp(
            exchange_trading_symbols=(f"NSE_{symbol}",),
            segment=g.SEGMENT_CASH)
        return r.get(f"NSE_{symbol}")
    except Exception as e:
        print(f"[LTP] {e}")
        return None

def get_positions():
    try:
        g = groww()
        if not g: return []
        r = g.get_positions_for_user(segment=g.SEGMENT_CASH)
        return r.get("positions", [])
    except Exception as e:
        print(f"[Positions] {e}")
        return []

def place_mis_order(symbol, side, qty):
    """Place MIS market order."""
    try:
        g = groww()
        if not g: return None, "Not connected"
        if PAPER:
            ltp = get_ltp(symbol)
            return f"PAPER_{int(time.time())}", None
        r = g.place_order(
            validity=g.VALIDITY_DAY,
            exchange=g.EXCHANGE_NSE,
            order_type=g.ORDER_TYPE_MARKET,
            product=g.PRODUCT_MIS,
            quantity=qty,
            segment=g.SEGMENT_CASH,
            trading_symbol=symbol,
            transaction_type=g.TRANSACTION_TYPE_BUY
                if side == "BUY" else g.TRANSACTION_TYPE_SELL,
        )
        return r.get("order_id"), None
    except Exception as e:
        return None, str(e)

def place_oco_order(symbol, side, qty, target, sl):
    """Place OCO smart order for target + SL."""
    try:
        g = groww()
        if not g: return None, "Not connected"
        if PAPER:
            return f"PAPER_OCO_{symbol}", None
        # OCO: exit side is opposite of entry
        exit_side = g.TRANSACTION_TYPE_SELL \
            if side == "BUY" else g.TRANSACTION_TYPE_BUY
        r = g.create_smart_order(
            smart_order_type=g.SMART_ORDER_TYPE_OCO,
            exchange=g.EXCHANGE_NSE,
            trading_symbol=symbol,
            segment=g.SEGMENT_CASH,
            quantity=qty,
            transaction_type=exit_side,
            product=g.PRODUCT_MIS,
            upper_trigger_price=target if side == "BUY" else sl,
            lower_trigger_price=sl if side == "BUY" else target,
            upper_limit_price=target if side == "BUY" else sl,
            lower_limit_price=sl if side == "BUY" else target,
        )
        return r.get("smart_order_id"), None
    except Exception as e:
        return None, str(e)

def exit_position(symbol, qty, side):
    """Exit position at market."""
    try:
        g = groww()
        if not g: return None, "Not connected"
        if PAPER:
            ltp = get_ltp(symbol)
            return f"PAPER_EXIT_{symbol}", ltp
        exit_side = g.TRANSACTION_TYPE_SELL \
            if side == "BUY" else g.TRANSACTION_TYPE_BUY
        r = g.place_order(
            validity=g.VALIDITY_DAY,
            exchange=g.EXCHANGE_NSE,
            order_type=g.ORDER_TYPE_MARKET,
            product=g.PRODUCT_MIS,
            quantity=qty,
            segment=g.SEGMENT_CASH,
            trading_symbol=symbol,
            transaction_type=exit_side,
        )
        return r.get("order_id"), None
    except Exception as e:
        return None, str(e)

# ===== PRE-MARKET BRIEF =====
def fetch_brief():
    """Build pre-market brief using available data."""
    try:
        # Nifty and Sensex LTP
        nifty_ltp  = get_ltp("NIFTY 50") or "N/A"
        sensex_ltp = get_ltp("SENSEX") or "N/A"

        # India VIX
        vix = get_ltp("INDIA VIX") or "N/A"

        # Top movers from holdings/watchlist
        watchlist = load_watchlist()
        movers = []
        for sym in watchlist[:5]:
            ltp = get_ltp(sym)
            if ltp:
                movers.append(f"  {sym}: ₹{ltp:,.2f}")

        movers_str = "\n".join(movers) if movers else "  No watchlist set\n  Add with /watchlist add SYMBOL"

        msg = (f"☀️ <b>GUHA — PRE-MARKET BRIEF</b>\n"
               f"{now_ist().strftime('%d %b %Y | %H:%M')} IST\n"
               f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
               f"<b>Market:</b>\n"
               f"  Nifty: {nifty_ltp}\n"
               f"  Sensex: {sensex_ltp}\n"
               f"  VIX: {vix}\n\n"
               f"<b>Watchlist LTPs:</b>\n"
               f"{movers_str}\n\n"
               f"<b>Today's limits:</b>\n"
               f"  Max loss: Signal-based\n"
               f"  Target: Signal-based\n\n"
               f"<i>Send /buy to start a trade</i>")
        return msg
    except Exception as e:
        return f"⚠️ Brief error: {e}"

# ===== WATCHLIST =====
WATCHLIST_FILE = "guha_watchlist.json"

def load_watchlist():
    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE) as f:
                return json.load(f)
    except: pass
    return []

def save_watchlist(wl):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f)

# ===== POSITION MONITOR =====
def monitor_positions():
    """Check open positions and update P&L."""
    if now_ist().weekday() > 4: return
    positions = get_positions()
    if not positions: return

    total_pnl = 0
    for pos in positions:
        pnl = pos.get("unrealised_pnl", 0) or 0
        total_pnl += pnl

    with RISK_L:
        RISK["pnl"] = total_pnl
        if total_pnl <= -MAX_LOSS_DAY and not RISK["halted"]:
            RISK["halted"] = True
            tg(f"🛑 <b>GUHA — MAX LOSS HIT</b>\n"
               f"Loss: -₹{abs(total_pnl):,.0f}\n"
               f"Limit: ₹{MAX_LOSS_DAY:,}\n"
               f"<b>Exit all positions NOW</b>\n"
               f"Send /exit all")

# ===== JOBS =====
def job_login():
    if now_ist().weekday() > 4: return
    print("[Guha] Auto-login 8:30 AM...")
    if groww_login():
        tg(f"🔑 <b>Guha — Groww Connected</b>\n"
           f"{now_ist().strftime('%H:%M:%S')} IST\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")
    else:
        tg("🚨 <b>Guha — Groww Login Failed</b>\nSend /login")

def job_brief():
    if now_ist().weekday() > 4: return
    reset_daily()
    tg(fetch_brief())

def job_monitor():
    if now_ist().weekday() > 4: return
    monitor_positions()

def job_eod():
    if now_ist().weekday() > 4: return
    trades = get_today_trades()
    closed = [t for t in trades if t[8] == "CLOSED"]
    open_t = [t for t in trades if t[8] == "OPEN"]
    total_pnl = sum(t[7] or 0 for t in closed)
    wins = sum(1 for t in closed if (t[7] or 0) > 0)
    losses = sum(1 for t in closed if (t[7] or 0) <= 0)

    icon = "✅" if total_pnl >= 500 else "⚠️" if total_pnl > 0 else "❌"
    msg = (f"🌙 <b>GUHA EOD</b>\n\n"
           f"{icon} P&L: {'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}\n\n"
           f"Trades: {len(closed)} closed | {len(open_t)} open\n"
           f"Wins: {wins} | Losses: {losses}\n")
    if open_t:
        msg += f"\n⚠️ <b>{len(open_t)} positions still open!</b>\n"
        for t in open_t:
            msg += f"  {t[1]} {t[2]} {t[3]}qty\n"
        msg += "Close manually or send /exit all"
    tg(msg)

def job_force_exit():
    """Force exit all MIS positions at 3:15 PM."""
    if now_ist().weekday() > 4: return
    positions = get_positions()
    if not positions:
        tg("⏰ <b>3:15 PM — No open positions</b>")
        return
    tg(f"⏰ <b>3:15 PM — AUTO EXIT ALL</b>\n"
       f"{len(positions)} positions being closed...")
    for pos in positions:
        sym = pos.get("trading_symbol", "")
        qty = abs(pos.get("quantity", 0))
        side = "BUY" if pos.get("quantity", 0) > 0 else "SELL"
        if qty > 0:
            exit_position(sym, qty, side)

# ===== COMMAND PARSER =====
def parse_trade_cmd(parts):
    """
    Parse: /buy SYMBOL QTY TGT SL
    Returns (symbol, qty, tgt, sl) or None
    """
    if len(parts) < 5: return None
    try:
        symbol = parts[1].upper()
        qty = int(parts[2])
        tgt = float(parts[3])
        sl = float(parts[4])
        return symbol, qty, tgt, sl
    except: return None

# ===== COMMAND HANDLER =====
def handle_cmd(text, chat_id):
    text = text.strip()
    if str(chat_id) != str(TG_CHAT): return
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    print(f"[Guha] {text}")

    if cmd == "/login":
        tg("⏳ Connecting to Groww...")
        if groww_login(): tg("✅ <b>Groww Connected</b>")
        else: tg("❌ Login failed")

    elif cmd in ["/buy", "/sell"]:
        side = "BUY" if cmd == "/buy" else "SELL"
        reset_daily()
        with RISK_L:
            if RISK["halted"]:
                tg("🛑 Max loss hit today. No more trades."); return
        with CONV_L:
            CONV.update({
                "step": "symbol", "side": side,
                "symbol": None, "ltp": None,
                "capital": None, "qty": None,
                "target": None, "sl": None,
            })
        tg(f"{'🟢 BUY' if side == 'BUY' else '🔴 SELL'} trade started.\n\n"
           f"Which stock? (enter symbol)\n"
           f"Example: RELIANCE")

    elif cmd == "/cancel":
        with CONV_L:
            CONV["step"] = None
        tg("❌ Trade cancelled.")

    elif cmd == "/confirm":
        with CONV_L:
            if CONV["step"] != "confirm":
                tg("ℹ️ Nothing to confirm."); return
            symbol = CONV["symbol"]
            side   = CONV["side"]
            qty    = CONV["qty"]
            ltp    = CONV["ltp"]
            target = CONV["target"]
            sl     = CONV["sl"]
            capital = CONV["capital"]
            CONV["step"] = None

        tg(f"⏳ Placing {side} order for {symbol}...")

        order_id, err = place_mis_order(symbol, side, qty)
        if err:
            tg(f"❌ Order failed: {err}"); return

        oco_id, err2 = place_oco_order(symbol, side, qty, target, sl)
        if err2:
            tg(f"⚠️ OCO failed: {err2}\nManage exit manually")

        log_trade(symbol, side, qty, ltp, target, sl,
                  str(order_id), str(oco_id or ""))

        with RISK_L: RISK["trades"] += 1

        max_gain = abs(target - ltp) * qty
        max_loss = abs(ltp - sl) * qty

        tg(f"✅ <b>ORDER PLACED</b>\n"
           f"{side} {symbol} {qty}qty @ ₹{ltp:,.2f}\n"
           f"Target: ₹{target:,.2f} | SL: ₹{sl:,.2f}\n"
           f"Max gain: +₹{max_gain:,.0f} | Max loss: -₹{max_loss:,.0f}\n"
           f"OCO active — Groww monitors automatically\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

    elif cmd == "/exit":
        if len(parts) < 2:
            tg("❌ Format: /exit SYMBOL or /exit all"); return

        target = parts[1].upper()
        positions = get_positions()

        if target == "ALL":
            if not positions:
                tg("ℹ️ No open positions"); return
            tg(f"⏳ Exiting {len(positions)} positions...")
            for pos in positions:
                sym = pos.get("trading_symbol", "")
                qty = abs(pos.get("quantity", 0))
                side = "BUY" if pos.get("quantity", 0) > 0 else "SELL"
                ltp = get_ltp(sym)
                if qty > 0:
                    exit_position(sym, qty, side)
                    pnl = ((ltp or 0) - pos.get("average_price", 0)) * qty
                    if side == "SELL": pnl = -pnl
                    close_trade(sym, ltp or 0, pnl)
            tg("✅ All positions exited")
        else:
            pos = next((p for p in positions
                       if p.get("trading_symbol") == target), None)
            if not pos:
                tg(f"ℹ️ No open position for {target}"); return
            qty = abs(pos.get("quantity", 0))
            side = "BUY" if pos.get("quantity", 0) > 0 else "SELL"
            ltp = get_ltp(target)
            exit_position(target, qty, side)
            pnl = ((ltp or 0) - pos.get("average_price", 0)) * qty
            if side == "SELL": pnl = -pnl
            close_trade(target, ltp or 0, pnl)
            tg(f"✅ <b>EXITED {target}</b>\n"
               f"Exit: ₹{ltp:,.2f}\n"
               f"P&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f}")

    elif cmd == "/positions":
        if PAPER:
            # In paper mode show from journal DB
            trades = get_today_trades()
            open_t = [t for t in trades if t[8] == "OPEN"]
            if not open_t:
                tg("ℹ️ No open positions"); return
            msg = f"📊 <b>Open Positions (PAPER)</b>\n{now_ist().strftime('%H:%M:%S')}\n\n"
            total_unreal = 0
            for t in open_t:
                sym, side, qty, entry, _, tgt, sl, _, status, etime, _ = t
                ltp = get_ltp(sym) or entry
                unreal = (ltp - entry) * qty if side == "BUY" else (entry - ltp) * qty
                total_unreal += unreal
                msg += (f"<b>{sym}</b> {side} {qty}qty\n"
                       f"  Entry: ₹{entry:,.2f} | LTP: ₹{ltp:,.2f}\n"
                       f"  Target: ₹{tgt:,.2f} | SL: ₹{sl:,.2f}\n"
                       f"  P&L: {'+'if unreal>=0 else ''}₹{unreal:,.0f}\n\n")
            msg += f"<b>Total Unrealized: {'+'if total_unreal>=0 else ''}₹{total_unreal:,.0f}</b>"
            tg(msg)
            return
        positions = get_positions()
        if not positions:
            tg("ℹ️ No open positions"); return
        msg = f"📊 <b>Open Positions</b>\n{now_ist().strftime('%H:%M:%S')}\n\n"
        total_pnl = 0
        for pos in positions:
            sym = pos.get("trading_symbol", "")
            qty = pos.get("quantity", 0)
            avg = pos.get("average_price", 0)
            ltp = pos.get("last_price", 0)
            pnl = pos.get("unrealised_pnl", 0) or 0
            total_pnl += pnl
            side = "BUY" if qty > 0 else "SELL"
            msg += (f"<b>{sym}</b> {side} {abs(qty)}qty\n"
                   f"  Avg: ₹{avg:,.2f} | LTP: ₹{ltp:,.2f}\n"
                   f"  P&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f}\n\n")
        msg += f"<b>Total P&L: {'+'if total_pnl>=0 else ''}₹{total_pnl:,.0f}</b>"
        tg(msg)

    elif cmd == "/pnl":
        trades = get_today_trades()
        closed = [t for t in trades if t[8] == "CLOSED"]
        open_t = [t for t in trades if t[8] == "OPEN"]
        realized = sum(t[7] or 0 for t in closed)
        with RISK_L: unrealized = RISK["pnl"]
        total = realized + unrealized
        icon = "✅" if total >= 500 else "⚠️" if total > 0 else "❌"
        tg(f"💰 <b>GUHA P&L — {today_str()}</b>\n\n"
           f"{icon} Realized: {'+'if realized>=0 else ''}₹{realized:,.0f}\n"
           f"📊 Unrealized: {'+'if unrealized>=0 else ''}₹{unrealized:,.0f}\n"
           f"─────────────────\n"
           f"<b>Total: {'+'if total>=0 else ''}₹{total:,.0f}</b>\n\n"
           f"Closed: {len(closed)} | Open: {len(open_t)}\n"
           f"Target: Signal-based | Limit: -₹{MAX_LOSS_DAY:,}\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}")

    elif cmd == "/journal":
        period = parts[1].lower() if len(parts) > 1 else "today"

        if period == "week":
            trades = get_week_trades()
            if not trades:
                tg("ℹ️ No trades this week"); return
            by_date = {}
            for t in trades:
                d = t[0]
                if d not in by_date: by_date[d] = []
                by_date[d].append(t)
            msg = "📒 <b>GUHA — Weekly Journal</b>\n\n"
            weekly_pnl = 0
            for date, day_trades in sorted(by_date.items()):
                day_pnl = sum(t[6] or 0 for t in day_trades if t[7] == "CLOSED")
                weekly_pnl += day_pnl
                icon = "✅" if day_pnl >= 0 else "❌"
                msg += (f"{icon} <b>{date}</b>: "
                       f"{'+'if day_pnl>=0 else ''}₹{day_pnl:,.0f} "
                       f"({len(day_trades)} trades)\n")
            msg += f"\n<b>Week total: {'+'if weekly_pnl>=0 else ''}₹{weekly_pnl:,.0f}</b>"
            tg(msg)

        else:  # today
            trades = get_today_trades()
            if not trades:
                tg(f"ℹ️ No trades today yet"); return
            msg = f"📒 <b>GUHA Journal — {today_str()}</b>\n\n"
            for t in trades:
                sym, side, qty, entry, exit_p, tgt, sl, pnl, status, etime, xtime = t
                icon = "✅" if (pnl or 0) > 0 else "❌" if status == "CLOSED" else "⏳"
                msg += (f"{icon} <b>{sym}</b> {side} {qty}qty\n"
                       f"  Entry: ₹{entry:,.2f} @ {etime}\n")
                if status == "CLOSED":
                    msg += (f"  Exit: ₹{exit_p:,.2f} @ {xtime}\n"
                           f"  P&L: {'+'if(pnl or 0)>=0 else ''}₹{pnl:,.0f}\n\n")
                else:
                    ltp = get_ltp(sym) or entry
                    unreal = (ltp - entry) * qty if side == "BUY" else (entry - ltp) * qty
                    msg += (f"  Status: OPEN | LTP: ₹{ltp:,.2f}\n"
                           f"  Unrealized: {'+'if unreal>=0 else ''}₹{unreal:,.0f}\n\n")
            total = sum(t[7] or 0 for t in trades if t[8] == "CLOSED")
            msg += f"<b>Realized P&L: {'+'if total>=0 else ''}₹{total:,.0f}</b>"
            tg(msg)

    elif cmd in ["/watchlist"]:
        if len(parts) < 2:
            wl = load_watchlist()
            if not wl:
                tg("ℹ️ Watchlist empty\nAdd: /watchlist add RELIANCE"); return
            msg = "📋 <b>Watchlist</b>\n\n"
            for sym in wl:
                ltp = get_ltp(sym)
                msg += f"  {sym}: {'₹'+str(ltp) if ltp else 'N/A'}\n"
            tg(msg)
        elif parts[1].lower() == "add" and len(parts) > 2:
            sym = parts[2].upper()
            wl = load_watchlist()
            if sym not in wl:
                wl.append(sym)
                save_watchlist(wl)
            tg(f"✅ {sym} added to watchlist")
        elif parts[1].lower() == "remove" and len(parts) > 2:
            sym = parts[2].upper()
            wl = load_watchlist()
            if sym in wl:
                wl.remove(sym)
                save_watchlist(wl)
            tg(f"✅ {sym} removed from watchlist")

    elif cmd == "/brief":
        tg("⏳ Fetching brief...")
        tg(fetch_brief())

    elif cmd == "/status":
        g = groww()
        connected = g is not None
        positions = get_positions()
        with RISK_L:
            pnl = RISK["pnl"]
            trades = RISK["trades"]
            halted = RISK["halted"]
        tg(f"✅ <b>Guha Cash Bot</b>\n"
           f"{now_ist().strftime('%H:%M:%S')} IST\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
           f"Groww: {'✅' if connected else '❌ /login'}\n"
           f"Open positions: {len(positions)}\n"
           f"Today trades: {trades}\n"
           f"P&L: {'+'if pnl>=0 else ''}₹{pnl:,.0f}\n"
           f"Status: {'🛑 HALTED' if halted else '✅ Active'}\n"
           f"Max loss limit: ₹{MAX_LOSS_DAY:,}")

    elif cmd in ["/help", "/start"]:
        tg(f"🤖 <b>Guha Cash Bot</b>\n"
           f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n"
           f"Groww equity intraday (MIS)\n\n"
           f"<b>Trade commands:</b>\n"
           f"/buy SYMBOL QTY TGT SL\n"
           f"/sell SYMBOL QTY TGT SL\n"
           f"/exit SYMBOL\n"
           f"/exit all\n\n"
           f"<b>Info commands:</b>\n"
           f"/positions — open trades\n"
           f"/pnl — today's P&L\n"
           f"/journal — today's journal\n"
           f"/journal week — weekly summary\n"
           f"/watchlist — view watchlist\n"
           f"/watchlist add SYMBOL\n"
           f"/watchlist remove SYMBOL\n"
           f"/brief — pre-market brief\n"
           f"/status — bot health\n"
           f"/login — reconnect Groww\n\n"
           f"<b>Example:</b>\n"
           f"/buy RELIANCE 10 1400 1310\n"
           f"→ Buy 10 Reliance, target ₹1400, SL ₹1310")

    else:
        # Handle conversational flow (non-command messages)
        with CONV_L:
            step = CONV["step"]
            side = CONV["side"]

        if step == "symbol":
            symbol = text.upper().strip()
            ltp = get_ltp(symbol)
            if not ltp:
                tg(f"❌ Could not find {symbol}. Try again.\n"
                   f"Example: RELIANCE"); return
            with CONV_L:
                CONV["symbol"] = symbol
                CONV["ltp"] = ltp
                CONV["step"] = "entry"
            tg(f"<b>{symbol}</b> — LTP: ₹{ltp:,.2f}\n\n"
               f"Entry price? (trigger price from signal)\n"
               f"Example: {ltp:.2f}")


        elif step == "entry":
            try:
                entry = float(text.strip().replace(",", ""))
                with CONV_L:
                    CONV["ltp"] = entry
                    CONV["step"] = "capital"
                tg(f"Entry: ₹{entry:,.2f} ✅\n\n"
                   f"How much capital to allocate? (₹)\n"
                   f"Example: 10000")
            except:
                tg("❌ Enter a valid price. Example: 157.85")
        elif step == "capital":
            try:
                capital = float(text.strip().replace(",", ""))
                with CONV_L:
                    ltp = CONV["ltp"]
                    symbol = CONV["symbol"]
                # Calculate max qty
                qty = int(capital / ltp)
                if qty < 1:
                    tg(f"❌ ₹{capital:,.0f} not enough to buy 1 share of "
                       f"{symbol} at ₹{ltp:,.2f}"); return
                actual_cost = qty * ltp
                with CONV_L:
                    CONV["capital"] = capital
                    CONV["qty"] = qty
                    CONV["step"] = "target"
                tg(f"Qty: <b>{qty} shares</b> @ ₹{ltp:,.2f}\n"
                   f"Cost: ₹{actual_cost:,.2f}\n\n"
                   f"Target price?")
            except:
                tg("❌ Enter a valid amount. Example: 10000")

        elif step == "target":
            try:
                target = float(text.strip().replace(",", ""))
                with CONV_L:
                    ltp = CONV["ltp"]
                    side = CONV["side"]
                # Validate
                if side == "BUY" and target <= ltp:
                    tg(f"❌ Target must be above LTP ₹{ltp:,.2f}"); return
                if side == "SELL" and target >= ltp:
                    tg(f"❌ Target must be below LTP ₹{ltp:,.2f}"); return
                with CONV_L:
                    CONV["target"] = target
                    CONV["step"] = "sl"
                tg(f"Target: ₹{target:,.2f} ✅\n\nStop loss price?")
            except:
                tg("❌ Enter a valid price. Example: 1400")

        elif step == "sl":
            try:
                sl = float(text.strip().replace(",", ""))
                with CONV_L:
                    ltp = CONV["ltp"]
                    side = CONV["side"]
                    target = CONV["target"]
                    symbol = CONV["symbol"]
                    qty = CONV["qty"]
                # Validate
                if side == "BUY" and sl >= ltp:
                    tg(f"❌ SL must be below LTP ₹{ltp:,.2f}"); return
                if side == "SELL" and sl <= ltp:
                    tg(f"❌ SL must be above LTP ₹{ltp:,.2f}"); return
                with CONV_L:
                    CONV["sl"] = sl
                    CONV["step"] = "confirm"

                max_gain = abs(target - ltp) * qty
                max_loss = abs(ltp - sl) * qty
                rr = round(max_gain / max_loss, 2) if max_loss > 0 else 0
                pfx = "📝 PAPER" if PAPER else "🔴 LIVE"

                tg(f"{'🟢' if side=='BUY' else '🔴'} <b>{pfx} — {side} {symbol}</b>\n"
                   f"{now_ist().strftime('%H:%M:%S')}\n\n"
                   f"Qty: {qty} shares @ ₹{ltp:,.2f}\n"
                   f"Target: ₹{target:,.2f}\n"
                   f"SL: ₹{sl:,.2f}\n\n"
                   f"Max gain: +₹{max_gain:,.0f}\n"
                   f"Max loss: -₹{max_loss:,.0f}\n"
                   f"R:R = 1:{rr}\n\n"
                   f"Send /confirm to execute\n"
                   f"Send /cancel to abort")
            except:
                tg("❌ Enter a valid price. Example: 1310")

        elif step is None and not cmd.startswith("/"):
            tg("ℹ️ Send /buy or /sell to start a trade\n/help for all commands")

        else:
            tg(f"❓ Unknown: <code>{text}</code>\n/help")

# ===== TG LISTENER =====
def tg_listener():
    print("[Guha] Telegram listener starting...")
    last_id = None
    processed = set()
    while True:
        try:
            params = {"timeout": 30}
            if last_id: params["offset"] = last_id
            r = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params=params, timeout=35)
            if r.status_code == 200:
                for upd in r.json().get("result", []):
                    uid = upd["update_id"]
                    last_id = uid + 1
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
            print(f"[TG] Error: {e}")
            time.sleep(5)

# ===== MAIN =====
def main():
    print("=" * 50)
    print(f"GUHA CASH BOT | Paper={PAPER}")
    print(f"Broker: Groww | MIS intraday")
    print(f"Max loss/day: No cap")
    print(f"Started: {now_ist()}")
    print("=" * 50)

    init_db()
    reset_daily()
    groww_login()

    tg(f"🚀 <b>Guha Cash Bot Started</b>\n"
       f"{now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST\n"
       f"{'📝 PAPER' if PAPER else '🔴 LIVE'}\n\n"
       f"Broker: Groww (MIS intraday)\n"
       f"Max loss/day: No cap\n"
       f"Target: Signal-based\n\n"
       f"/help for commands")

    scheduler = BlockingScheduler(timezone=IST)

    scheduler.add_job(job_login,
        CronTrigger(day_of_week="mon-fri",
                    hour=8, minute=30, timezone=IST),
        id="login")

    scheduler.add_job(job_brief,
        CronTrigger(day_of_week="mon-fri",
                    hour=8, minute=45, timezone=IST),
        id="brief")

    scheduler.add_job(job_monitor,
        CronTrigger(day_of_week="mon-fri",
                    hour="9-15", minute="*/5",
                    timezone=IST),
        id="monitor",
        max_instances=1, coalesce=True)

    scheduler.add_job(job_force_exit,
        CronTrigger(day_of_week="mon-fri",
                    hour=15, minute=15, timezone=IST),
        id="force_exit")

    scheduler.add_job(job_eod,
        CronTrigger(day_of_week="mon-fri",
                    hour=15, minute=30, timezone=IST),
        id="eod")

    threading.Thread(target=tg_listener, daemon=True).start()
    print("[Guha] Running...")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[Guha] Stopped")

if __name__ == "__main__":
    main()
