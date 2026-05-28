"""
Mahakaal Shared Database
========================
Single SQLite DB for all 3 bots.
All signals, trades, positions logged here.
Dashboard reads from this DB.
"""

import sqlite3
import os
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mahakaal.db")

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    
    # Alakh T20 signals
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alakh_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            direction TEXT,
            score INTEGER,
            threshold INTEGER,
            strike REAL,
            entry_price REAL,
            sl_price REAL,
            lock_price REAL,
            qty INTEGER,
            lots INTEGER,
            expiry TEXT,
            dte INTEGER,
            atm_iv REAL,
            session TEXT,
            entry_type TEXT,
            result TEXT DEFAULT 'OPEN',
            exit_price REAL,
            exit_time TEXT,
            pnl REAL DEFAULT 0,
            sl_index REAL,
            spot_at_entry REAL
        )
    """)

    # Alakh T20 daily summary
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alakh_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            total_signals INTEGER DEFAULT 0,
            trades_taken INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            sl_hits INTEGER DEFAULT 0,
            pnl REAL DEFAULT 0,
            target REAL DEFAULT 3500,
            halted INTEGER DEFAULT 0
        )
    """)

    # SriMhatre positions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sri_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            entry_time TEXT,
            expiry TEXT,
            dte INTEGER,
            strategy TEXT,
            regime TEXT,
            short_strike REAL,
            short_option TEXT,
            long_strike REAL,
            short_ltp REAL,
            long_ltp REAL,
            net_credit REAL,
            qty INTEGER,
            lots INTEGER,
            target_pct REAL DEFAULT 0.5,
            sl_mult REAL DEFAULT 2.0,
            atm_iv REAL,
            pcr_vol REAL,
            pcr_oi REAL,
            iv_skew REAL,
            max_pain REAL,
            ce_wall REAL,
            pe_wall REAL,
            result TEXT DEFAULT 'OPEN',
            exit_time TEXT,
            exit_premium REAL,
            pnl REAL DEFAULT 0
        )
    """)

    # SriMhatre daily summary
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sri_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            trades INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            pnl REAL DEFAULT 0,
            skipped TEXT DEFAULT ''
        )
    """)

    # Guha cash trades (already in guha_journal.db, mirror here)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS guha_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            entry_price REAL,
            exit_price REAL,
            target REAL,
            sl REAL,
            pnl REAL DEFAULT 0,
            status TEXT DEFAULT 'OPEN'
        )
    """)

    # Bot events log
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            bot TEXT,
            event_type TEXT,
            message TEXT
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialized: {DB_PATH}")

def now_ist():
    return datetime.now(IST)

def today():
    return now_ist().strftime("%Y-%m-%d")

def ts():
    return now_ist().strftime("%H:%M:%S")

# ===== ALAKH LOGGING =====
def log_alakh_signal(direction, score, threshold, strike,
                     entry_price, sl_price, lock_price,
                     qty, lots, expiry, dte, atm_iv,
                     session, entry_type, sl_index, spot):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO alakh_signals
        (date, time, direction, score, threshold, strike,
         entry_price, sl_price, lock_price, qty, lots,
         expiry, dte, atm_iv, session, entry_type,
         sl_index, spot_at_entry)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (today(), ts(), direction, score, threshold, strike,
          entry_price, sl_price, lock_price, qty, lots,
          expiry, dte, atm_iv, session, entry_type,
          sl_index, spot))
    signal_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Update daily
    upsert_alakh_daily(signals=1)
    return signal_id

def update_alakh_signal(signal_id, result, exit_price, pnl):
    conn = get_conn()
    conn.execute("""
        UPDATE alakh_signals
        SET result=?, exit_price=?, exit_time=?, pnl=?
        WHERE id=?
    """, (result, exit_price, ts(), pnl, signal_id))
    conn.commit()
    conn.close()
    if result == "WIN":
        upsert_alakh_daily(wins=1, pnl=pnl)
    elif result == "LOSS":
        upsert_alakh_daily(losses=1, sl_hits=1, pnl=pnl)

def upsert_alakh_daily(signals=0, trades=0, wins=0,
                        losses=0, sl_hits=0, pnl=0):
    conn = get_conn()
    conn.execute("""
        INSERT INTO alakh_daily (date) VALUES (?)
        ON CONFLICT(date) DO NOTHING
    """, (today(),))
    conn.execute("""
        UPDATE alakh_daily SET
            total_signals = total_signals + ?,
            trades_taken = trades_taken + ?,
            wins = wins + ?,
            losses = losses + ?,
            sl_hits = sl_hits + ?,
            pnl = pnl + ?
        WHERE date = ?
    """, (signals, trades, wins, losses, sl_hits, pnl, today()))
    conn.commit()
    conn.close()

# ===== SRIMHATRE LOGGING =====
def log_sri_position(expiry, dte, strategy, regime,
                     short_strike, short_option, long_strike,
                     short_ltp, long_ltp, net_credit, qty, lots,
                     atm_iv, pcr_vol, pcr_oi, iv_skew,
                     max_pain, ce_wall, pe_wall):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO sri_positions
        (date, entry_time, expiry, dte, strategy, regime,
         short_strike, short_option, long_strike,
         short_ltp, long_ltp, net_credit, qty, lots,
         atm_iv, pcr_vol, pcr_oi, iv_skew,
         max_pain, ce_wall, pe_wall)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (today(), ts(), expiry, dte, strategy, regime,
          short_strike, short_option, long_strike,
          short_ltp, long_ltp, net_credit, qty, lots,
          atm_iv, pcr_vol, pcr_oi, iv_skew,
          max_pain, ce_wall, pe_wall))
    pos_id = cur.lastrowid
    conn.commit()
    conn.close()
    upsert_sri_daily(trades=1)
    return pos_id

def update_sri_position(pos_id, result, exit_premium, pnl):
    conn = get_conn()
    conn.execute("""
        UPDATE sri_positions
        SET result=?, exit_time=?, exit_premium=?, pnl=?
        WHERE id=?
    """, (result, ts(), exit_premium, pnl, pos_id))
    conn.commit()
    conn.close()
    if result == "WIN":
        upsert_sri_daily(wins=1, pnl=pnl)
    elif result == "LOSS":
        upsert_sri_daily(losses=1, pnl=pnl)

def upsert_sri_daily(trades=0, wins=0, losses=0,
                      pnl=0, skipped=""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO sri_daily (date) VALUES (?)
        ON CONFLICT(date) DO NOTHING
    """, (today(),))
    conn.execute("""
        UPDATE sri_daily SET
            trades = trades + ?,
            wins = wins + ?,
            losses = losses + ?,
            pnl = pnl + ?
        WHERE date = ?
    """, (trades, wins, losses, pnl, today()))
    conn.commit()
    conn.close()

# ===== GUHA LOGGING =====
def log_guha_trade(symbol, side, qty, entry_price, target, sl):
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO guha_trades
        (date, time, symbol, side, qty, entry_price, target, sl)
        VALUES (?,?,?,?,?,?,?,?)
    """, (today(), ts(), symbol, side, qty, entry_price, target, sl))
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def update_guha_trade(trade_id, exit_price, pnl):
    conn = get_conn()
    conn.execute("""
        UPDATE guha_trades
        SET exit_price=?, pnl=?, status='CLOSED'
        WHERE id=?
    """, (exit_price, pnl, trade_id))
    conn.commit()
    conn.close()

# ===== EVENT LOGGING =====
def log_event(bot, event_type, message):
    conn = get_conn()
    conn.execute("""
        INSERT INTO events (timestamp, bot, event_type, message)
        VALUES (?,?,?,?)
    """, (now_ist().strftime("%Y-%m-%d %H:%M:%S"),
          bot, event_type, message))
    conn.commit()
    conn.close()

# ===== DASHBOARD QUERIES =====
def get_today_summary():
    conn = get_conn()

    # Alakh
    alakh = conn.execute("""
        SELECT total_signals, trades_taken, wins, losses, pnl, sl_hits
        FROM alakh_daily WHERE date=?
    """, (today(),)).fetchone()

    # SriMhatre
    sri = conn.execute("""
        SELECT trades, wins, losses, pnl
        FROM sri_daily WHERE date=?
    """, (today(),)).fetchone()

    # Guha
    guha = conn.execute("""
        SELECT COUNT(*), SUM(CASE WHEN status='CLOSED' THEN pnl ELSE 0 END),
               COUNT(CASE WHEN status='OPEN' THEN 1 END)
        FROM guha_trades WHERE date=?
    """, (today(),)).fetchone()

    conn.close()
    return {
        "alakh": alakh or (0,0,0,0,0,0),
        "sri": sri or (0,0,0,0),
        "guha": guha or (0,0,0),
    }

def get_recent_alakh_signals(limit=10):
    conn = get_conn()
    rows = conn.execute("""
        SELECT time, direction, score, entry_price,
               sl_price, result, pnl, session, atm_iv, strike
        FROM alakh_signals
        WHERE date=?
        ORDER BY id DESC LIMIT ?
    """, (today(), limit)).fetchall()
    conn.close()
    return rows

def get_open_sri_positions():
    conn = get_conn()
    rows = conn.execute("""
        SELECT entry_time, strategy, expiry, dte,
               net_credit, qty, atm_iv, short_strike,
               short_option, regime
        FROM sri_positions
        WHERE date=? AND result='OPEN'
        ORDER BY id DESC
    """, (today(),)).fetchall()
    conn.close()
    return rows

def get_recent_events(limit=20):
    conn = get_conn()
    rows = conn.execute("""
        SELECT timestamp, bot, event_type, message
        FROM events
        ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows

def get_guha_trades_today():
    conn = get_conn()
    rows = conn.execute("""
        SELECT time, symbol, side, qty, entry_price,
               exit_price, pnl, status, target, sl
        FROM guha_trades WHERE date=?
        ORDER BY id
    """, (today(),)).fetchall()
    conn.close()
    return rows

# ===== MONTHLY STATS =====
def get_monthly_stats(months=3):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            substr(a.date,1,7) as month,
            SUM(a.pnl) as alakh_pnl,
            SUM(s.pnl) as sri_pnl
        FROM alakh_daily a
        LEFT JOIN sri_daily s ON a.date = s.date
        GROUP BY month
        ORDER BY month DESC
        LIMIT ?
    """, (months,)).fetchall()
    conn.close()
    return rows

if __name__ == "__main__":
    init_db()
    print("✅ Database initialized")
