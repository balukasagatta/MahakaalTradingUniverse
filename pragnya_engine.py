"""
PRAGNYA Engine v2.0
Shared discipline microservice for VAJRA · SUTRA · TARK
Single SQLite DB, per-product state, shared violations log.
"""
import sqlite3, json, os
from datetime import datetime, date, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pragnya.db")

# ── GITA QUOTES ────────────────────────────────────────────────────────────────
GITA_QUOTES = [
    ("You have a right to perform your duty but never to the fruits of action.",
     "Bhagavad Gita 2.47"),
    ("The mind is restless, turbulent and very strong. To subdue it is harder than controlling the wind.",
     "Bhagavad Gita 6.34"),
    ("A person can rise through the efforts of his own mind; or draw himself down, in the same manner.",
     "Bhagavad Gita 6.5"),
    ("Better than mechanical practice is knowledge. Better than knowledge is meditation.",
     "Bhagavad Gita 12.12"),
    ("One who has control over the mind is steady in heat and cold, pleasure and pain, honor and dishonor.",
     "Bhagavad Gita 6.7"),
    ("Perform your duty equipoised, abandoning all attachment to success or failure.",
     "Bhagavad Gita 2.48"),
    ("Let right deeds be thy motive, not the fruit which comes from them.",
     "Bhagavad Gita 2.47"),
    ("He who has no attachments can really love others, for his love is pure and divine.",
     "Bhagavad Gita 3.19"),
]

def get_daily_quote():
    idx = date.today().day % len(GITA_QUOTES)
    return GITA_QUOTES[idx]

# ── DB INIT ────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_state (
            date        TEXT NOT NULL,
            product     TEXT NOT NULL,
            trades_taken    INTEGER DEFAULT 0,
            sl_hits         INTEGER DEFAULT 0,
            target_hits     INTEGER DEFAULT 0,
            daily_pnl       REAL    DEFAULT 0,
            cooling_until   TEXT,
            killed_at       TEXT,
            last_trade_time TEXT,
            last_sl_time    TEXT,
            discipline_score INTEGER DEFAULT 100,
            PRIMARY KEY (date, product)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS violations (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            date     TEXT,
            time     TEXT,
            product  TEXT,
            type     TEXT,
            message  TEXT,
            severity TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT,
            time         TEXT,
            product      TEXT,
            strategy     TEXT,
            instrument   TEXT,
            direction    TEXT,
            entry        REAL,
            exit_price   REAL,
            sl           REAL,
            target_price REAL,
            pnl          REAL DEFAULT 0,
            status       TEXT DEFAULT 'OPEN',
            exit_reason  TEXT,
            hold_minutes INTEGER,
            extra_json   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_emotion (
            date     TEXT,
            product  TEXT,
            emotion  TEXT,
            note     TEXT,
            PRIMARY KEY (date, product)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rewards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT,
            product     TEXT,
            event       TEXT,
            points      INTEGER,
            description TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ── STATE HELPERS ──────────────────────────────────────────────────────────────
def _conn(): return sqlite3.connect(DB_PATH)

def get_state(product: str) -> dict:
    conn = _conn()
    today = date.today().isoformat()
    conn.execute("INSERT OR IGNORE INTO daily_state (date, product) VALUES (?,?)", (today, product))
    conn.commit()
    row = conn.execute(
        "SELECT date,product,trades_taken,sl_hits,target_hits,daily_pnl,"
        "cooling_until,killed_at,last_trade_time,last_sl_time,discipline_score "
        "FROM daily_state WHERE date=? AND product=?", (today, product)
    ).fetchone()
    conn.close()
    return {
        "date": row[0], "product": row[1],
        "trades_taken": row[2] or 0, "sl_hits": row[3] or 0,
        "target_hits": row[4] or 0, "daily_pnl": float(row[5] or 0),
        "cooling_until": row[6], "killed_at": row[7],
        "last_trade_time": row[8], "last_sl_time": row[9],
        "discipline_score": row[10] or 100,
    }

def update_state(product: str, **kwargs):
    conn = _conn()
    today = date.today().isoformat()
    for k, v in kwargs.items():
        conn.execute(
            f"UPDATE daily_state SET {k}=? WHERE date=? AND product=?", (v, today, product)
        )
    conn.commit()
    conn.close()

def log_violation(product: str, vtype: str, message: str, severity: str = "WARNING"):
    conn = _conn()
    now = datetime.now(IST)
    today = today = date.today().isoformat()
    conn.execute(
        "INSERT INTO violations (date,time,product,type,message,severity) VALUES (?,?,?,?,?,?)",
        (today, now.strftime("%H:%M:%S"), product, vtype, message, severity)
    )
    conn.commit()
    conn.close()
    # deduct discipline score
    state = get_state(product)
    penalty = {"WARNING": 5, "CRITICAL": 15, "LOCK": 20}.get(severity, 5)
    new_score = max(0, state["discipline_score"] - penalty)
    update_state(product, discipline_score=new_score)

def add_trade(product: str, strategy: str, instrument: str, direction: str,
              entry: float, sl: float, target: float, extra: dict = None, status: str = "OPEN") -> int:
    conn = _conn()
    now = datetime.now(IST)
    cur = conn.execute(
        """INSERT INTO trades
           (date,time,product,strategy,instrument,direction,entry,sl,target_price,extra_json,status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), product, strategy,
         instrument, direction, entry, sl, target,
         json.dumps(extra or {}), status)
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid

def close_trade(trade_id: int, exit_price: float, pnl: float,
                exit_reason: str, hold_minutes: int = None):
    conn = _conn()
    conn.execute(
        """UPDATE trades SET exit_price=?,pnl=?,status=?,exit_reason=?,hold_minutes=?
           WHERE id=?""",
        (exit_price, pnl, "CLOSED", exit_reason, hold_minutes, trade_id)
    )
    conn.commit()
    conn.close()

def get_today_trades(product: str) -> list:
    conn = _conn()
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT id,date,time,product,strategy,instrument,direction,entry,exit_price,"
        "sl,target_price,pnl,status,exit_reason,hold_minutes,extra_json "
        "FROM trades WHERE date=? AND product=? ORDER BY time DESC",
        (today, product)
    ).fetchall()
    conn.close()
    keys = ["id","date","time","product","strategy","instrument","direction","entry",
            "exit_price","sl","target_price","pnl","status","exit_reason","hold_minutes","extra_json"]
    return [dict(zip(keys, r)) for r in rows]

def get_today_violations(product: str) -> list:
    conn = _conn()
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT id,date,time,product,type,message,severity "
        "FROM violations WHERE date=? AND product=? ORDER BY time DESC",
        (today, product)
    ).fetchall()
    conn.close()
    keys = ["id","date","time","product","type","message","severity"]
    return [dict(zip(keys, r)) for r in rows]

def save_eod_emotion(product: str, emotion: str, note: str = ""):
    conn = _conn()
    today = date.today().isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO eod_emotion (date,product,emotion,note) VALUES (?,?,?,?)",
        (today, product, emotion, note)
    )
    conn.commit()
    conn.close()

def get_eod_emotion(product: str) -> dict | None:
    conn = _conn()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM eod_emotion WHERE date=? AND product=?", (today, product)
    ).fetchone()
    conn.close()
    if row:
        return {"emotion": row[2], "note": row[3]}
    return None

# ── REWARDS ───────────────────────────────────────────────────────────────────
REWARD_EVENTS = {
    "NO_REVENGE":      ("No revenge trade today", 50),
    "TARGET_STOP":     ("Stopped after hitting target", 100),
    "FIVE_DAY_STREAK": ("5-day discipline streak", 500),
    "FULL_RULES":      ("Followed all rules today", 75),
    "EMOTION_LOGGED":  ("Logged EOD emotion", 10),
}

def add_reward(product: str, event: str):
    if event not in REWARD_EVENTS:
        return
    desc, pts = REWARD_EVENTS[event]
    conn = _conn()
    today = date.today().isoformat()
    # prevent duplicate for same event same day
    existing = conn.execute(
        "SELECT id FROM rewards WHERE date=? AND product=? AND event=?",
        (today, product, event)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO rewards (date,product,event,points,description) VALUES (?,?,?,?,?)",
            (today, product, event, pts, desc)
        )
        conn.commit()
    conn.close()

def get_total_rewards() -> int:
    conn = _conn()
    row = conn.execute("SELECT SUM(points) FROM rewards").fetchone()
    conn.close()
    return row[0] or 0

def get_rewards_history(limit=30) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM rewards ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(rewards)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

# ── PRAGNYA RULE CHECKER ───────────────────────────────────────────────────────
def check_rules(product: str, cfg: dict) -> tuple[bool, list[str], dict]:
    """
    Returns (can_trade, warnings, lock_status)
    lock_status = {"locked": bool, "reason": str, "cooling_remaining": int}
    """
    state = get_state(product)
    now = datetime.now(IST)
    warnings = []
    lock = {"locked": False, "reason": None, "cooling_remaining": 0}

    # 1. Daily loss limit
    if state["daily_pnl"] <= cfg["daily_loss_limit"]:
        if not state["killed_at"]:
            update_state(product, killed_at=now.strftime("%H:%M:%S"))
            log_violation(product, "DAILY_SL_HIT",
                          f"Loss ₹{abs(state['daily_pnl']):.0f} hit limit ₹{abs(cfg['daily_loss_limit']):.0f}",
                          "LOCK")
        return False, ["DAILY LOSS LIMIT HIT — Terminal locked"], {
            "locked": True, "reason": "Daily loss limit", "cooling_remaining": 0
        }

    # 2. Manual kill
    if state["killed_at"]:
        return False, ["Kill switch active"], {
            "locked": True, "reason": "Kill switch", "cooling_remaining": 0
        }

    # 3. Max trades
    if state["trades_taken"] >= cfg["max_trades_per_day"]:
        return False, [f"Max {cfg['max_trades_per_day']} trades done today"], {
            "locked": True, "reason": "Max trades", "cooling_remaining": 0
        }

    # 4. Cooling period
    if state["cooling_until"]:
        try:
            cool_end = IST.localize(
                datetime.strptime(state["cooling_until"], "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
            )
            if now < cool_end:
                rem = int((cool_end - now).total_seconds() / 60) + 1
                return False, [f"Cooling period: {rem} min remaining"], {
                    "locked": True, "reason": "Cooling", "cooling_remaining": rem
                }
        except Exception:
            pass

    # 5. Time restrictions
    tr = cfg.get("time_restrictions", {})
    cur_t = now.strftime("%H:%M")
    if cur_t < tr.get("no_trade_before", "09:15"):
        return False, [f"Market opens at {tr.get('no_trade_before','09:15')}"], {
            "locked": True, "reason": "Pre-market", "cooling_remaining": 0
        }
    if cur_t > tr.get("no_trade_after", "15:15"):
        return False, [f"Market closed at {tr.get('no_trade_after','15:15')}"], {
            "locked": True, "reason": "Post-market", "cooling_remaining": 0
        }
    ls, le = tr.get("lunch_break_start", "12:00"), tr.get("lunch_break_end", "13:15")
    if ls <= cur_t <= le:
        return False, [f"Lunch break {ls}–{le}"], {
            "locked": True, "reason": "Lunch break", "cooling_remaining": 0
        }

    # 6. Soft warnings
    if state["daily_pnl"] >= cfg.get("daily_target", 99999):
        warnings.append(f"🎯 Target ₹{cfg['daily_target']:.0f} hit! Consider stopping.")

    if state["sl_hits"] > 0 and state["last_sl_time"]:
        try:
            last_sl = IST.localize(
                datetime.strptime(state["last_sl_time"], "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
            )
            gap = (now - last_sl).total_seconds()
            if gap < 600:
                warnings.append("⚠️ REVENGE PATTERN: Last SL was <10 min ago. Take a breath.")
        except Exception:
            pass

    if state["sl_hits"] >= cfg.get("max_sl_hits", 2):
        warnings.append(f"⚠️ {state['sl_hits']}/{cfg['max_sl_hits']} SL hits today — one more = cooling lock")

    return True, warnings, lock

# ── COOLING TRIGGER ────────────────────────────────────────────────────────────
def trigger_cooling(product: str, minutes: int):
    until = (datetime.now(IST) + timedelta(minutes=minutes)).strftime("%H:%M:%S")
    update_state(product, cooling_until=until)

def trigger_kill(product: str):
    now = datetime.now(IST)
    update_state(product, killed_at=now.strftime("%H:%M:%S"))
    log_violation(product, "MANUAL_KILL", "Kill switch activated by user", "CRITICAL")

def record_sl_hit(product: str, cfg: dict):
    now = datetime.now(IST)
    state = get_state(product)
    new_hits = state["sl_hits"] + 1
    update_state(product, sl_hits=new_hits, last_sl_time=now.strftime("%H:%M:%S"))
    if new_hits >= cfg.get("max_sl_hits", 2):
        trigger_cooling(product, cfg.get("cooling_minutes_after_sl", 15))
        log_violation(product, "SL_STREAK",
                      f"{new_hits} SL hits — cooling {cfg.get('cooling_minutes_after_sl',15)} min", "CRITICAL")
