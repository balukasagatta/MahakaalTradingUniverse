"""
Mahakaal Journal Fetcher + AI Trade Coach
Runs at 3:30 PM IST — fetches full orderbook, analyses, generates AI coach report
Runs at 9:00 AM IST — morning reminder with yesterday's summary
"""
import sqlite3, os, sys, requests, json, time
from datetime import datetime, date, timedelta
import pytz

IST      = pytz.timezone("Asia/Kolkata")
BASE     = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE, "journal.db")
ENV_PATH = os.path.join(BASE, "env.vars")

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

ENV = load_env()
TG_TOKEN    = ENV.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT     = ENV.get("TELEGRAM_CHAT_ID", "935391809")
DHAN_TOKEN  = ENV.get("DHAN_ACCESS_TOKEN", "")
DHAN_CLIENT = ENV.get("DHAN_CLIENT_ID", "1000709103")
GROWW_TOKEN = ENV.get("GROWW_API_KEY", "")
GROQ_KEY    = ENV.get("GROQ_API_KEY", "")

CAPITAL = {
    "Kotak Neo": 150000,
    "Dhan":      350000,
    "Groww":      50000,
    "Flattrade":      0,
}
BOT_TARGETS = {
    "Kotak Neo": 2500,   # daily
    "Dhan":      1200,
    "Groww":      400,
}

# ── DB ───────────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS daily_pnl (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        account     TEXT NOT NULL,
        gross       REAL DEFAULT 0,
        net         REAL DEFAULT 0,
        charges     REAL DEFAULT 0,
        trades      INTEGER DEFAULT 0,
        auto_gross  INTEGER DEFAULT 0,
        auto_trades INTEGER DEFAULT 0,
        notes       TEXT DEFAULT '',
        merit       INTEGER DEFAULT 0,
        overtrade   INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(date, account)
    );
    CREATE TABLE IF NOT EXISTS trade_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        account     TEXT NOT NULL,
        symbol      TEXT,
        side        TEXT,
        qty         INTEGER DEFAULT 0,
        price       REAL DEFAULT 0,
        order_time  TEXT,
        status      TEXT,
        pnl         REAL DEFAULT 0,
        raw         TEXT
    );
    CREATE TABLE IF NOT EXISTS ai_reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        report      TEXT NOT NULL,
        metrics     TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(date)
    );
    CREATE TABLE IF NOT EXISTS outflow (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        label  TEXT NOT NULL,
        amount REAL NOT NULL,
        cat    TEXT DEFAULT 'Other',
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS config (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    cur.execute("SELECT COUNT(*) FROM outflow")
    if cur.fetchone()[0] == 0:
        outflows = [
            ('Home Loan EMI',45000,'EMI'),('Car Loan EMI',8500,'EMI'),
            ('Navi',13300,'EMI'),('LIC',4500,'Insurance'),
            ('Term Insurance',2200,'Insurance'),('Groceries',12000,'Living'),
            ('Fuel',4000,'Living'),('Electricity',1800,'Utilities'),
            ('Mobile/Internet',1200,'Utilities'),('OTT/Subscriptions',800,'Subscriptions'),
            ('Gym',1500,'Health'),('Parents',10000,'Family'),('Misc',5000,'Other'),
        ]
        cur.executemany("INSERT INTO outflow(label,amount,cat) VALUES(?,?,?)", outflows)
    cur.execute("SELECT COUNT(*) FROM config")
    if cur.fetchone()[0] == 0:
        configs = [
            ('salary','80000'),('target_alakh','52000'),
            ('target_srimhatre','26972'),('target_guha','8500'),
        ]
        cur.executemany("INSERT OR IGNORE INTO config(key,value) VALUES(?,?)", configs)
    con.commit(); con.close()

# ── TELEGRAM ─────────────────────────────────────────────────────────────────
def tg(msg, parse_mode="HTML"):
    if not TG_TOKEN:
        print(f"[TG] {msg}"); return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": parse_mode},
            timeout=10)
    except Exception as e:
        print(f"[TG ERROR] {e}")

# ── BROKER FETCHERS ──────────────────────────────────────────────────────────
def fetch_dhan():
    """Returns (gross, trades, trade_list)"""
    try:
        h = {"access-token": DHAN_TOKEN, "client-id": DHAN_CLIENT, "Content-Type": "application/json"}
        # Positions for MTM
        r = requests.get("https://api.dhan.co/v2/positions", headers=h, timeout=10)
        positions = r.json() if r.ok else []
        gross = sum(
            float(p.get("unrealizedProfit", 0)) + float(p.get("realizedProfit", 0))
            for p in (positions if isinstance(positions, list) else [])
        )
        # Full orderbook
        r2 = requests.get("https://api.dhan.co/v2/orders", headers=h, timeout=10)
        orders = r2.json() if r2.ok else []
        trade_list = []
        if isinstance(orders, list):
            for o in orders:
                if o.get("orderStatus") in ("TRADED", "PART_TRADED"):
                    trade_list.append({
                        "symbol":     o.get("tradingSymbol", ""),
                        "side":       o.get("transactionType", ""),
                        "qty":        int(o.get("filledQty", o.get("quantity", 0))),
                        "price":      float(o.get("averageTradedPrice", o.get("price", 0))),
                        "order_time": o.get("createTime", o.get("exchangeTime", "")),
                        "status":     o.get("orderStatus", ""),
                        "pnl":        0,
                        "raw":        json.dumps(o),
                    })
        return round(gross, 2), len(trade_list), trade_list
    except Exception as e:
        print(f"[Dhan] Error: {e}")
        return 0, 0, []

def fetch_kotak():
    """Returns (gross, trades, trade_list)"""
    try:
        import pyotp
        from neo_api_client import NeoAPI
        client = NeoAPI(
            consumer_key=ENV.get("KOTAK_CONSUMER_KEY",""),
            environment="prod", access_token=None, neo_fin_key=None)
        totp = pyotp.TOTP(ENV.get("KOTAK_TOTP_SECRET","")).now()
        r1 = client.totp_login(
            mobile_number=ENV.get("KOTAK_MOBILE",""),
            ucc=ENV.get("KOTAK_UCC",""), totp=totp)
        if r1.get("data",{}).get("status") != "success":
            print(f"[Kotak] Login failed: {r1}"); return 0, 0, []
        r2 = client.totp_validate(mpin=ENV.get("KOTAK_MPIN",""))
        if r2.get("data",{}).get("status") != "success":
            print(f"[Kotak] Validate failed"); return 0, 0, []
        # MTM from positions
        pos = client.positions()
        gross = 0
        if isinstance(pos, dict) and "data" in pos:
            for p in pos["data"]:
                buy  = float(p.get("buyAmt", 0))
                sell = float(p.get("sellAmt", 0))
                if p.get("sqrFlg") == "Y":
                    gross += sell - buy
                else:
                    gross += float(p.get("unrealisedMtm", sell - buy))
        # Trade book
        tb = client.trade_report()
        trade_list = []
        if isinstance(tb, dict) and "data" in tb:
            for t in tb["data"]:
                trade_list.append({
                    "symbol":     t.get("trdSym", t.get("sym", "")),
                    "side":       t.get("trnsTp", t.get("side", "")),
                    "qty":        int(float(t.get("qty", t.get("flQty", 0)))),
                    "price":      float(t.get("trdPrc", t.get("avgPrc", 0))),
                    "order_time": t.get("ordTm", t.get("trdTm", "")),
                    "status":     "TRADED",
                    "pnl":        0,
                    "raw":        json.dumps(t),
                })
        return round(gross, 2), len(trade_list), trade_list
    except Exception as e:
        print(f"[Kotak] Error: {e}")
        return 0, 0, []

def fetch_groww():
    """Returns (gross, trades, trade_list)"""
    try:
        from growwapi import GrowwAPI
        g = GrowwAPI(GROWW_TOKEN)
        # Positions
        pos = g.get_positions_for_user()
        gross = 0
        pos_list = pos if isinstance(pos, list) else pos.get("data", pos.get("positions", []))
        for p in pos_list:
            gross += float(p.get("pnl", p.get("unrealisedPnl", 0)))
        # Orders
        orders = g.get_order_list()
        order_list = orders if isinstance(orders, list) else orders.get("data", orders.get("orders", []))
        trade_list = []
        for o in order_list:
            if str(o.get("status","")).upper() in ("COMPLETE","EXECUTED","TRADED"):
                trade_list.append({
                    "symbol":     o.get("tradingSymbol", o.get("symbol", "")),
                    "side":       o.get("transactionType", o.get("orderType", "")),
                    "qty":        int(o.get("quantity", o.get("qty", 0))),
                    "price":      float(o.get("price", o.get("averagePrice", 0))),
                    "order_time": o.get("orderTimestamp", o.get("createdAt", "")),
                    "status":     "TRADED",
                    "pnl":        float(o.get("pnl", 0)),
                    "raw":        json.dumps(o),
                })
        return round(gross, 2), len(trade_list), trade_list
    except Exception as e:
        print(f"[Groww] Error: {e}")
        return 0, 0, []

# ── METRICS ENGINE ────────────────────────────────────────────────────────────
def compute_metrics(today, all_trades, account_results):
    """Build a rich metrics dict for AI analysis"""
    total_gross  = sum(v[0] for v in account_results.values())
    total_trades = sum(v[1] for v in account_results.values())
    total_capital = sum(CAPITAL.values())

    # Capital efficiency: gross / capital deployed
    cap_efficiency = (total_gross / total_capital * 100) if total_capital > 0 else 0

    # Per-account metrics
    account_metrics = {}
    for acc, (gross, trades, _) in account_results.items():
        cap = CAPITAL.get(acc, 1)
        target = BOT_TARGETS.get(acc, 0)
        account_metrics[acc] = {
            "gross":          gross,
            "trades":         trades,
            "capital":        cap,
            "target":         target,
            "target_hit":     gross >= target if target > 0 else None,
            "cap_efficiency": round(gross / cap * 100, 3) if cap > 0 else 0,
            "avg_per_trade":  round(gross / trades, 2) if trades > 0 else 0,
        }

    # Trade timing analysis
    time_slots = {"pre_open": 0, "morning": 0, "midday": 0, "afternoon": 0, "close": 0}
    symbols_traded = {}
    for t in all_trades:
        tm = t.get("order_time", "")
        try:
            if "09:0" in tm or "09:1" in tm: time_slots["pre_open"] += 1
            elif any(x in tm for x in ["09:2","09:3","09:4","09:5","10:","11:"]): time_slots["morning"] += 1
            elif any(x in tm for x in ["11:3","12:","13:"]): time_slots["midday"] += 1
            elif any(x in tm for x in ["14:","15:0","15:1","15:2"]): time_slots["afternoon"] += 1
            elif "15:3" in tm: time_slots["close"] += 1
        except: pass
        sym = t.get("symbol","")
        if sym: symbols_traded[sym] = symbols_traded.get(sym, 0) + 1

    # Overtrading detection
    overtrade = total_trades > 10
    overtrade_accounts = [acc for acc, (_, trades, _) in account_results.items() if trades > 10]

    # Revenge trade detection: multiple trades in same symbol within short window
    revenge_signals = []
    for acc, (_, _, trades) in account_results.items():
        sorted_trades = sorted(trades, key=lambda x: x.get("order_time",""))
        for i in range(1, len(sorted_trades)):
            if sorted_trades[i].get("symbol") == sorted_trades[i-1].get("symbol"):
                revenge_signals.append(f"{acc}:{sorted_trades[i].get('symbol')}")

    return {
        "date":              today,
        "total_gross":       total_gross,
        "total_trades":      total_trades,
        "total_capital":     total_capital,
        "cap_efficiency":    round(cap_efficiency, 3),
        "account_metrics":   account_metrics,
        "time_slots":        time_slots,
        "symbols_traded":    symbols_traded,
        "overtrade":         overtrade,
        "overtrade_accounts":overtrade_accounts,
        "revenge_signals":   revenge_signals,
        "peak_time":         max(time_slots, key=time_slots.get),
    }

# ── AI COACH ─────────────────────────────────────────────────────────────────
def run_ai_coach(metrics):
    """Send metrics to Groq, get trader coaching report"""
    prompt = f"""You are a professional trading coach and risk analyst reviewing a trader's daily performance for the Mahakaal Trading Universe (MTU) — a fully automated Indian F&O trading system.

Today's Date: {metrics['date']}
Total Capital Deployed: ₹{metrics['total_capital']:,}

PERFORMANCE DATA:
- Total Gross MTM: ₹{metrics['total_gross']:+,.0f}
- Total Trades: {metrics['total_trades']}
- Capital Efficiency: {metrics['cap_efficiency']:.3f}%

ACCOUNT BREAKDOWN:
{json.dumps(metrics['account_metrics'], indent=2)}

TRADING PATTERNS:
- Time slot distribution: {json.dumps(metrics['time_slots'])}
- Peak trading period: {metrics['peak_time']}
- Symbols traded: {json.dumps(metrics['symbols_traded'])}

RISK FLAGS:
- Overtrading detected: {metrics['overtrade']} {('(Accounts: ' + ', '.join(metrics['overtrade_accounts']) + ')') if metrics['overtrade_accounts'] else ''}
- Potential revenge trade signals: {len(metrics['revenge_signals'])} ({', '.join(metrics['revenge_signals'][:3]) if metrics['revenge_signals'] else 'None'})

SYSTEM CONTEXT:
- Alakh (Kotak Neo): Sensex options scalping, target ₹2,500/day, max 2 SL hits
- SriMhatre (Dhan): Nifty options selling (Iron Condor/spreads), target ₹1,200/day
- Guha (Groww): Cash equity mentor signals, ₹10,000 per trade

Provide a structured coaching report with these EXACT sections:
1. PERFORMANCE VERDICT (1 line — Pass/Partial/Fail with reason)
2. WHAT WORKED (specific, data-backed observations)
3. RISK CONCERNS (specific flags with numbers, not generic advice)
4. CAPITAL EFFICIENCY ANALYSIS (how well ₹{metrics['total_capital']:,} was used today)
5. PATTERN INSIGHTS (time-of-day, symbol concentration, trade clustering)
6. TOMORROW'S FOCUS (3 specific actionable points based on today's data)
7. COACH SCORE: X/10 (with one-line justification)

Be brutally honest. Use actual numbers from the data. No generic trading advice — everything must reference today's specific metrics. Keep total response under 400 words."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.3,
            },
            timeout=30)
        if r.ok:
            return r.json()["choices"][0]["message"]["content"]
        else:
            print(f"[Groq] Error: {r.status_code} {r.text}")
            return None
    except Exception as e:
        print(f"[Groq] Exception: {e}")
        return None

# ── STORE RESULTS ─────────────────────────────────────────────────────────────
def store_results(today, account_results, metrics, ai_report):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    for account, (gross, trades, trade_list) in account_results.items():
        merit = 2 if trades <= 3 else 1 if trades <= 10 else 0
        overtrade = 1 if trades > 10 else 0
        cur.execute("""
            INSERT INTO daily_pnl(date,account,gross,trades,auto_gross,auto_trades,merit,overtrade)
            VALUES(?,?,?,?,1,1,?,?)
            ON CONFLICT(date,account) DO UPDATE SET
                gross=excluded.gross, trades=excluded.trades,
                auto_gross=1, auto_trades=1,
                merit=excluded.merit, overtrade=excluded.overtrade,
                updated_at=datetime('now')
        """, (today, account, gross, trades, merit, overtrade))

        # Store individual trades
        cur.execute("DELETE FROM trade_log WHERE date=? AND account=?", (today, account))
        for t in trade_list:
            cur.execute("""INSERT INTO trade_log(date,account,symbol,side,qty,price,order_time,status,pnl,raw)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (today, account, t["symbol"], t["side"], t["qty"],
                        t["price"], t["order_time"], t["status"], t["pnl"], t["raw"]))

    # Store AI report
    if ai_report:
        cur.execute("""INSERT INTO ai_reports(date,report,metrics) VALUES(?,?,?)
                      ON CONFLICT(date) DO UPDATE SET report=excluded.report, metrics=excluded.metrics""",
                   (today, ai_report, json.dumps(metrics)))

    con.commit(); con.close()

# ── TELEGRAM REPORT ──────────────────────────────────────────────────────────
def send_tg_report(today, metrics, ai_report):
    lines = [f"🔱 <b>MTU Daily Report — {today}</b>\n"]

    for acc, m in metrics["account_metrics"].items():
        clr = "✅" if m["gross"] >= 0 else "🔴"
        tgt = f" {'✅' if m.get('target_hit') else '❌'} vs ₹{m['target']:,} target" if m['target'] else ""
        lines.append(f"{clr} <b>{acc}:</b> ₹{m['gross']:+,.0f} | {m['trades']} trades{tgt}")

    lines.append(f"\n💰 <b>Total: ₹{metrics['total_gross']:+,.0f}</b>")
    lines.append(f"📊 Cap efficiency: {metrics['cap_efficiency']:.3f}%")

    if metrics["overtrade"]:
        lines.append(f"\n⚠️ <b>OVERTRADE:</b> {metrics['total_trades']} trades today!")
    if metrics["revenge_signals"]:
        lines.append(f"⚠️ <b>Revenge signals:</b> {len(metrics['revenge_signals'])} detected")

    if ai_report:
        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🤖 <b>AI Coach Report</b>")
        lines.append(ai_report)
        lines.append(f"\n👉 <a href='https://mtutrade.in'>mtutrade.in</a> → Journal → Update Net P&L")

    tg("\n".join(lines))

# ── MAIN MODES ────────────────────────────────────────────────────────────────
def run_fetch():
    init_db()
    today = date.today().strftime("%Y-%m-%d")
    now   = datetime.now(IST).strftime("%H:%M")
    print(f"[{now}] Fetching full orderbook for {today}...")

    account_results = {}
    all_trades = []

    dhan_g,  dhan_t,  dhan_trades  = fetch_dhan()
    kotak_g, kotak_t, kotak_trades = fetch_kotak()
    groww_g, groww_t, groww_trades = fetch_groww()

    account_results["Dhan"]      = (dhan_g,  dhan_t,  dhan_trades)
    account_results["Kotak Neo"] = (kotak_g, kotak_t, kotak_trades)
    account_results["Groww"]     = (groww_g, groww_t, groww_trades)

    all_trades = dhan_trades + kotak_trades + groww_trades

    print(f"[Fetch] Dhan: ₹{dhan_g:+,.0f} / {dhan_t} trades")
    print(f"[Fetch] Kotak: ₹{kotak_g:+,.0f} / {kotak_t} trades")
    print(f"[Fetch] Groww: ₹{groww_g:+,.0f} / {groww_t} trades")

    # Compute metrics
    metrics = compute_metrics(today, all_trades, account_results)
    print(f"[Metrics] Cap efficiency: {metrics['cap_efficiency']:.3f}% | Overtrade: {metrics['overtrade']}")

    # AI Coach
    print("[AI] Generating coach report...")
    ai_report = run_ai_coach(metrics)
    if ai_report:
        print("[AI] Report generated ✅")
    else:
        print("[AI] Report failed ❌")

    # Store everything
    store_results(today, account_results, metrics, ai_report)

    # Send Telegram
    send_tg_report(today, metrics, ai_report)
    print("[DONE] All done.")

def run_reminder():
    init_db()
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT account, gross, net, trades FROM daily_pnl WHERE date=?", (yesterday,))
    rows = cur.fetchall()
    # Get AI report
    cur.execute("SELECT report FROM ai_reports WHERE date=?", (yesterday,))
    rep = cur.fetchone()
    con.close()

    if not rows: return

    pending_net = [r for r in rows if r[2] == 0]
    total_gross = sum(r[1] for r in rows)

    lines = [f"🌅 <b>Good Morning! MTU Update for {yesterday}</b>\n"]
    lines.append(f"💰 Gross MTM: ₹{total_gross:+,.0f}")
    if pending_net:
        lines.append(f"📝 Net P&L pending for: {', '.join(r[0] for r in pending_net)}")
        lines.append(f"\n👉 <a href='https://mtutrade.in'>Update at mtutrade.in</a> → Journal")
    if rep:
        # Extract score line
        for line in rep[0].split("\n"):
            if "COACH SCORE" in line.upper() or "/10" in line:
                lines.append(f"\n⭐ Yesterday's score: {line.strip()}")
                break
    tg("\n".join(lines))
    print(f"[REMINDER] Sent for {yesterday}")

def run_ondemand():
    """On-demand analysis — re-fetch and re-analyse right now"""
    print("[ON-DEMAND] Running fresh analysis...")
    run_fetch()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if mode == "fetch":       run_fetch()
    elif mode == "reminder":  run_reminder()
    elif mode == "ondemand":  run_ondemand()
    else: print("Usage: python3 journal_fetcher.py [fetch|reminder|ondemand]")
