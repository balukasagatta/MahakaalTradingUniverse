"""
Alakh Real Backtest — uses actual Upstox OHLC data
Simulates real filter logic: VWAP, PDH/PDL, ST, EMA
Clearly labeled as approximation — not tick-level accuracy
"""
import os, requests, json
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

env = {}
with open("env.vars") as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

TOKEN = env.get("UPSTOX_ACCESS_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

CAPITAL     = 150000
LOTS        = 3
QTY         = LOTS * 20  # 60qty
DAILY_TARGET = 2500
DAILY_SL    = 2000
LOCK_PTS    = 20
SL_PTS_MIN  = 15
SL_PTS_MAX  = 30  # new SL filter
SCORE_THRESHOLD = 7

def get_candles(instrument_key, from_date, to_date):
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{to_date}/{from_date}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    d = r.json()
    if d.get("status") == "success":
        return sorted(d["data"]["candles"], key=lambda x: x[0])
    return []

def compute_ema(closes, period):
    if len(closes) < period: return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def compute_vwap(candles):
    pv = v = 0
    for c in candles:
        typical = (c[2] + c[3] + c[4]) / 3
        vol = c[5] if len(c) > 5 and c[5] else 1
        pv += typical * vol; v += vol
    return pv / v if v > 0 else 0

def simulate_supertrend(candles, period=10, mult=3.0):
    """Approximate ST signal from daily candles."""
    if len(candles) < period + 2: return None
    last = candles[-1]; prev = candles[-2]
    # Simple proxy: if close > EMA21 = BUY, else SELL
    closes = [c[4] for c in candles]
    ema21 = compute_ema(closes, 21)
    if not ema21: return None
    return "BUY" if last[4] > ema21 else "SELL"

def backtest_alakh(from_date, to_date):
    print("\n" + "="*60)
    print("ALAKH REAL BACKTEST — Upstox Daily OHLC Data")
    print("NOTE: Daily candle approximation — not tick-level")
    print(f"Period: {from_date} to {to_date}")
    print(f"Capital: ₹{CAPITAL:,} | Lots: {LOTS} | Qty: {QTY}")
    print(f"Filters: Score≥{SCORE_THRESHOLD} | SL≤{SL_PTS_MAX}pts | VWAP+PDH/PDL")
    print("="*60)

    # Fetch real data
    print("\nFetching Sensex data...")
    sensex = get_candles("BSE_INDEX|SENSEX", from_date, to_date)
    print(f"Got {len(sensex)} trading days")

    if not sensex:
        print("❌ No data — check token")
        return

    trades = []
    total_pnl = 0
    wins = losses = 0
    skipped_rratio = 0
    skipped_vwap = 0
    monthly_pnl = {}

    for i, candle in enumerate(sensex):
        dt_str = candle[0][:10]
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
        if dt.weekday() > 4: continue

        day_open  = candle[1]
        day_high  = candle[2]
        day_low   = candle[3]
        day_close = candle[4]
        day_range = day_high - day_low

        # PDH/PDL from previous day
        if i == 0: continue
        prev = sensex[i-1]
        pdh = prev[2]  # prev day high
        pdl = prev[3]  # prev day low
        prev_close = prev[4]

        # Use last 5 days for VWAP approximation
        recent = sensex[max(0,i-4):i+1]
        vwap = compute_vwap(recent)

        # ST approximation from last 21 closes
        last21 = sensex[max(0,i-20):i+1]
        st_signal = simulate_supertrend(last21)
        if not st_signal: continue

        # Score simulation based on real OHLC
        call_pts = put_pts = 0

        # 1. Price vs prev close (±1)
        if day_close > prev_close: call_pts += 1
        else: put_pts += 1

        # 2. ST direction (±2)
        if st_signal == "BUY": call_pts += 2
        else: put_pts += 2

        # 3. Day range strength (±1)
        if day_close > day_open: call_pts += 1
        else: put_pts += 1

        # 4. VWAP position (±1)
        if day_close > vwap: call_pts += 1
        else: put_pts += 1

        # 5. PDH/PDL breakout (±1)
        if day_close > pdh: call_pts += 1
        elif day_close < pdl: put_pts += 1

        # 6. EMA trend
        closes = [c[4] for c in sensex[max(0,i-20):i+1]]
        ema9 = compute_ema(closes, 9)
        ema21_val = compute_ema(closes, 21)
        if ema9 and ema21_val:
            if ema9 > ema21_val: call_pts += 1
            else: put_pts += 1

        # Determine direction
        if call_pts > put_pts and call_pts >= SCORE_THRESHOLD:
            direction = "CALL"; score = call_pts
        elif put_pts > call_pts and put_pts >= SCORE_THRESHOLD:
            direction = "PUT"; score = put_pts
        else:
            continue  # No signal

        # ── VWAP + PDH/PDL FILTER ─────────────────────────
        above_vwap = day_close > vwap
        above_pdh  = day_close > pdh
        below_pdl  = day_close < pdl

        if direction == "CALL":
            if not above_vwap and below_pdl:
                skipped_vwap += 1; continue
            if not above_vwap and not above_pdh:
                if score < 10: skipped_vwap += 1; continue

        elif direction == "PUT":
            if above_vwap and above_pdh:
                skipped_vwap += 1; continue
            if above_vwap and not below_pdl:
                if score < 10: skipped_vwap += 1; continue

        # ── SL FILTER (≤30pts) ────────────────────────────
        # Approximate SL from day range × delta
        delta_approx = 0.45
        sl_pts = round(day_range * 0.08 * delta_approx, 1)
        sl_pts = max(SL_PTS_MIN, min(50, sl_pts))

        if sl_pts > SL_PTS_MAX:
            skipped_rratio += 1; continue

        # ── SIMULATE OUTCOME ──────────────────────────────
        # Based on real day structure:
        # Win if price moved in signal direction by LOCK_PTS equivalent
        # Approximate: if day moved > 150pts in signal direction = win

        if direction == "CALL":
            move = day_close - day_open
            won = move > 100  # Sensex moved up > 100pts
        else:
            move = day_open - day_close
            won = move > 100  # Sensex moved down > 100pts

        if won:
            pnl = LOCK_PTS * QTY  # +₹1,200
            wins += 1
        else:
            pnl = -sl_pts * QTY  # -₹900 to -₹1,800
            losses += 1

        total_pnl += pnl
        month_key = dt_str[:7]
        monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + pnl

        trades.append({
            "date": dt_str, "dir": direction, "score": score,
            "sl_pts": sl_pts, "pnl": pnl,
            "above_vwap": above_vwap, "above_pdh": above_pdh,
        })

    # Results
    total = wins + losses
    win_rate = wins/total*100 if total > 0 else 0
    avg_win  = sum(t["pnl"] for t in trades if t["pnl"] > 0) / max(wins, 1)
    avg_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0) / max(losses, 1)
    pf = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 else 999

    print(f"\nTotal Trading Days Analysed: {len(sensex)}")
    print(f"Signals Generated: {total}")
    print(f"Skipped (SL>30pts): {skipped_rratio}")
    print(f"Skipped (VWAP+PDH/PDL): {skipped_vwap}")
    print(f"\nWins: {wins} | Losses: {losses}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total P&L: ₹{total_pnl:,.0f}")
    print(f"Avg Win: ₹{avg_win:,.0f} | Avg Loss: ₹{avg_loss:,.0f}")
    print(f"Profit Factor: {pf:.2f}")
    print(f"ROC on ₹{CAPITAL:,}: {total_pnl/CAPITAL*100:.1f}%")
    print(f"Monthly Avg: ₹{total_pnl/12:,.0f}")

    print(f"\n{'Month':<10} {'P&L':>10} {'Cumulative':>12}")
    print("-"*34)
    cum = 0
    for month, pnl in sorted(monthly_pnl.items()):
        cum += pnl
        print(f"{month:<10} {'✅' if pnl>0 else '❌'} ₹{pnl:>7,.0f}  ₹{cum:>9,.0f}")

if __name__ == "__main__":
    backtest_alakh("2025-06-01", "2026-05-30")
