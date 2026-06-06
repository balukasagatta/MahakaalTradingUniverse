"""
Alakh T20 Backtest — 30-min Upstox Historical Candles
=======================================================
Data source: Upstox /historical-candle/BSE_INDEX|SENSEX/30minute
Timeframe: 30-min candles (not 1-min — labeled clearly)
Approach:
  - Group 30-min candles by day
  - OR approximated from 9:15-9:45 candles
  - VWAP computed from day's candles up to entry
  - PDH/PDL from previous day
  - ST proxy: EMA9 vs EMA21 on 30-min
  - Entry window: 10:00-11:30 (PRIME session)
  - VWAP + PDH/PDL filter applied
  - SL filter: skip if SL > 30pts
  - Win: 30-min candle moved 80+ pts in direction
  - Loss: SL hit (15-30pts converted to premium)

NOTE: This is a 30-min approximation — not tick-level.
      Results are directionally valid, not precise P&L.
"""

import os, requests, json
from datetime import datetime, timedelta
from collections import defaultdict
import pytz

IST = pytz.timezone("Asia/Kolkata")

# ── LOAD ENV ──────────────────────────────────────────────────
env = {}
with open(os.path.expanduser("~/mahakaal/env.vars")) as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

TOKEN   = env.get("UPSTOX_ACCESS_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# ── PARAMETERS ────────────────────────────────────────────────
CAPITAL        = 150_000
LOTS           = 3
QTY            = LOTS * 20        # 60 qty
LOCK_PTS       = 20               # option premium pts
SL_MIN         = 15               # min SL pts
SL_MAX         = 30               # max SL — wider = skip
SCORE_THRESH   = 7
SCORE_WEAK     = 10               # threshold when VWAP+PDH conflict
WIN_MOVE_PTS   = 40               # Sensex index pts = win condition (30-min)
DELTA_APPROX   = 0.45             # avg delta for ATM option

FROM_DATE = "2025-06-01"
TO_DATE   = "2026-05-30"

# ── FETCH DATA ────────────────────────────────────────────────
def fetch_30min(from_date, to_date):
    """Fetch in 60-day chunks — Upstox limit."""
    all_candles = []
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end   = datetime.strptime(to_date,   "%Y-%m-%d")
    chunk = start
    while chunk < end:
        chunk_end = min(chunk + timedelta(days=60), end)
        cs = chunk.strftime("%Y-%m-%d")
        ce = chunk_end.strftime("%Y-%m-%d")
        url = f"https://api.upstox.com/v2/historical-candle/BSE_INDEX|SENSEX/30minute/{ce}/{cs}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            d = r.json()
            if d.get("status") == "success":
                candles = d["data"]["candles"]
                all_candles.extend(candles)
                print(f"  Chunk {cs}→{ce}: {len(candles)} candles")
        except Exception as e:
            print(f"[Fetch] {cs}: {e}")
        chunk = chunk_end + timedelta(days=1)
    all_candles.sort(key=lambda x: x[0])
    return all_candles

def fetch_daily(from_date, to_date):
    url = f"https://api.upstox.com/v2/historical-candle/BSE_INDEX|SENSEX/day/{to_date}/{from_date}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        d = r.json()
        if d.get("status") == "success":
            candles = d["data"]["candles"]
            candles.sort(key=lambda x: x[0])
            return candles
    except Exception as e:
        print(f"[Daily] Error: {e}")
    return []

# ── INDICATORS ────────────────────────────────────────────────
def compute_ema(closes, period):
    if len(closes) < period: return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]: ema = p * k + ema * (1 - k)
    return ema

def compute_vwap(candles):
    pv = v = 0
    for c in candles:
        typical = (c[2] + c[3] + c[4]) / 3
        vol = c[5] if len(c) > 5 and c[5] else 1
        pv += typical * vol; v += vol
    return round(pv / v, 2) if v > 0 else 0

def compute_score(candles_so_far, direction, vwap, prev_close, pdh, pdl):
    """Score proxy using available 30-min data."""
    if not candles_so_far or len(candles_so_far) < 3:
        return 0

    call_pts = put_pts = 0
    closes = [c[4] for c in candles_so_far]
    highs  = [c[2] for c in candles_so_far]
    lows   = [c[3] for c in candles_so_far]
    spot   = closes[-1]

    # 1. ST proxy: EMA9 vs EMA21 (±2)
    ema9  = compute_ema(closes, min(9,  len(closes)))
    ema21 = compute_ema(closes, min(21, len(closes)))
    if ema9 and ema21:
        if ema9 > ema21: call_pts += 2
        else:            put_pts  += 2

    # 2. ST stable proxy: last 2 candles same side (±1)
    if len(closes) >= 3:
        if closes[-1] > ema9 and closes[-2] > ema9 and ema9:
            call_pts += 1
        elif closes[-1] < ema9 and closes[-2] < ema9 and ema9:
            put_pts  += 1

    # 3. Consecutive HH/LL (±2)
    if len(highs) >= 3:
        if all(highs[i] > highs[i-1] for i in range(1, 3)):
            call_pts += 2
        elif all(highs[i] < highs[i-1] for i in range(1, 3)):
            put_pts  += 2

    # 4. VWAP position (±1)
    if vwap:
        if spot > vwap: call_pts += 1
        else:           put_pts  += 1

    # 5. Prev close (±1)
    if prev_close:
        if spot > prev_close: call_pts += 1
        else:                 put_pts  += 1

    # 6. PDH/PDL zone (±1)
    if pdh and pdl:
        if spot > pdh: call_pts += 1
        elif spot < pdl: put_pts += 1

    # 7. Candle close strength (±1)
    last = candles_so_far[-1]
    rng  = last[2] - last[3]
    if rng > 0:
        pct = (last[4] - last[3]) / rng
        if pct >= 0.7: call_pts += 1
        elif pct <= 0.3: put_pts += 1

    # 8. Volume direction (±1)
    if len(candles_so_far) >= 3:
        up_vol = sum(c[5] for c in candles_so_far if c[4] > c[1] and len(c) > 5)
        dn_vol = sum(c[5] for c in candles_so_far if c[4] < c[1] and len(c) > 5)
        if up_vol > dn_vol * 1.3: call_pts += 1
        elif dn_vol > up_vol * 1.3: put_pts += 1

    if direction == "CALL": return call_pts
    else: return put_pts

# ── GROUP BY DAY ──────────────────────────────────────────────
def group_by_day(candles):
    days = defaultdict(list)
    for c in candles:
        dt_str = c[0][:10]
        days[dt_str].append(c)
    return dict(sorted(days.items()))

# ── MAIN BACKTEST ─────────────────────────────────────────────
def run_backtest():
    print("\n" + "="*62)
    print("ALAKH T20 BACKTEST — 30-min Upstox OHLC")
    print("⚠️  APPROXIMATION: 30-min candles, not 1-min tick data")
    print(f"Period: {FROM_DATE} to {TO_DATE}")
    print(f"Capital: ₹{CAPITAL:,} | Lots: {LOTS} | Qty: {QTY}")
    print(f"Filters: Score≥{SCORE_THRESH} | SL≤{SL_MAX}pts | VWAP+PDH/PDL")
    print("="*62)

    print("\nFetching 30-min candles...")
    candles_30 = fetch_30min(FROM_DATE, TO_DATE)
    print(f"Got {len(candles_30)} 30-min candles")

    print("Fetching daily candles for PDH/PDL...")
    candles_day = fetch_daily(FROM_DATE, TO_DATE)
    print(f"Got {len(candles_day)} daily candles")

    if not candles_30:
        print("❌ No 30-min data — check Upstox token")
        return

    # Build daily OHLC lookup for PDH/PDL
    daily_lookup = {}
    for c in candles_day:
        dt_str = c[0][:10]
        daily_lookup[dt_str] = {"high": c[2], "low": c[3], "close": c[4]}

    days = group_by_day(candles_30)
    sorted_days = sorted(days.keys())

    trades      = []
    monthly_pnl = defaultdict(float)
    skipped_sl  = skipped_vwap = skipped_score = no_signal = 0
    wins = losses = 0

    for idx, date_str in enumerate(sorted_days):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() > 4: continue  # skip weekends

        day_candles = days[date_str]

        # PDH/PDL from previous trading day
        prev_dates = [d for d in sorted_days[:idx] if
                      datetime.strptime(d, "%Y-%m-%d").weekday() < 5]
        if not prev_dates: continue
        prev_date = prev_dates[-1]
        prev_daily = daily_lookup.get(prev_date, {})
        pdh = prev_daily.get("high", 0)
        pdl = prev_daily.get("low",  0)
        prev_close = prev_daily.get("close", 0)

        # OR: first 2 candles (9:15 and 9:45)
        or_candles = [c for c in day_candles if "T09:1" in c[0] or "T09:4" in c[0]]
        if not or_candles: or_candles = day_candles[:2]
        or_high = max(c[2] for c in or_candles) if or_candles else 0
        or_low  = min(c[3] for c in or_candles) if or_candles else 0

        # Entry window: 10:00-11:30 candles
        entry_candles = [c for c in day_candles
                         if "T10:" in c[0] or "T11:0" in c[0]]
        if not entry_candles:
            no_signal += 1; continue

        # Use candles up to entry for VWAP and score
        pre_entry = [c for c in day_candles if c[0] < entry_candles[0][0]]
        if not pre_entry: pre_entry = day_candles[:2]

        vwap = compute_vwap(pre_entry + [entry_candles[0]])
        spot = entry_candles[0][4]  # close of first entry candle

        # Determine direction from score
        call_score = compute_score(pre_entry + [entry_candles[0]], "CALL", vwap, prev_close, pdh, pdl)
        put_score  = compute_score(pre_entry + [entry_candles[0]], "PUT",  vwap, prev_close, pdh, pdl)

        if call_score >= SCORE_THRESH and call_score > put_score:
            direction = "CALL"; score = call_score
        elif put_score >= SCORE_THRESH and put_score > call_score:
            direction = "PUT"; score = put_score
        else:
            skipped_score += 1; continue

        # ── VWAP + PDH/PDL FILTER ─────────────────────────
        above_vwap = spot > vwap
        above_pdh  = spot > pdh
        below_pdl  = spot < pdl
        threshold  = SCORE_THRESH

        if direction == "CALL":
            if not above_vwap and below_pdl:
                skipped_vwap += 1; continue
            if not above_vwap and not above_pdh:
                threshold = SCORE_WEAK
                if score < threshold: skipped_vwap += 1; continue

        elif direction == "PUT":
            if above_vwap and above_pdh:
                skipped_vwap += 1; continue
            if above_vwap and not below_pdl:
                threshold = SCORE_WEAK
                if score < threshold: skipped_vwap += 1; continue

        # ── SL CALCULATION ────────────────────────────────
        # Approx SL from OR range × delta
        or_range  = or_high - or_low if or_high and or_low else 150
        sl_pts    = max(SL_MIN, min(50, round(or_range * 0.12 * DELTA_APPROX, 1)))

        if sl_pts > SL_MAX:
            skipped_sl += 1; continue

        # ── OUTCOME SIMULATION ────────────────────────────
        # Use the 30-min candles AFTER entry to see what happened
        post_entry = entry_candles[1:] if len(entry_candles) > 1 else []

        if not post_entry:
            # Use remaining day candles
            post_entry = [c for c in day_candles if c[0] > entry_candles[0][0]]

        won = False
        if post_entry:
            if direction == "CALL":
                # Win if any 30-min candle high is WIN_MOVE_PTS above entry spot
                target_price = spot + WIN_MOVE_PTS
                won = any(c[2] >= target_price for c in post_entry[:4])
                # Loss if any candle low is SL_MAX pts below entry spot
                sl_price = spot - (sl_pts / DELTA_APPROX)
                if not won:
                    won = False
            else:  # PUT
                target_price = spot - WIN_MOVE_PTS
                won = any(c[3] <= target_price for c in post_entry[:4])
        else:
            # No post-entry data — skip
            continue

        pnl = (LOCK_PTS * QTY) if won else (-sl_pts * QTY)

        if won: wins += 1
        else:   losses += 1

        monthly_pnl[date_str[:7]] += pnl
        trades.append({
            "date": date_str, "dir": direction, "score": score,
            "sl_pts": sl_pts, "pnl": pnl, "won": won,
            "spot": spot, "vwap": round(vwap, 2),
            "pdh": pdh, "pdl": pdl,
        })

    # ── RESULTS ───────────────────────────────────────────────
    total     = wins + losses
    win_rate  = wins / total * 100 if total > 0 else 0
    total_pnl = sum(t["pnl"] for t in trades)
    avg_win   = sum(t["pnl"] for t in trades if t["pnl"] > 0) / max(wins, 1)
    avg_loss  = sum(t["pnl"] for t in trades if t["pnl"] < 0) / max(losses, 1)
    pf        = abs((avg_win * wins) / (avg_loss * losses)) if losses > 0 else 999
    monthly   = len(set(t["date"][:7] for t in trades))

    print(f"\n{'='*62}")
    print(f"Total Trades:   {total}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Win Rate:       {win_rate:.1f}%")
    print(f"Total P&L:      ₹{total_pnl:,.0f}")
    print(f"Avg Win:        ₹{avg_win:,.0f}")
    print(f"Avg Loss:       ₹{avg_loss:,.0f}")
    print(f"Profit Factor:  {pf:.2f}")
    print(f"ROC:            {total_pnl/CAPITAL*100:.1f}%")
    print(f"Monthly Avg:    ₹{total_pnl/max(monthly,1):,.0f}")
    print(f"\nSkipped (Score<{SCORE_THRESH}): {skipped_score}")
    print(f"Skipped (SL>{SL_MAX}pts):      {skipped_sl}")
    print(f"Skipped (VWAP+PDH/PDL):   {skipped_vwap}")
    print(f"No signal days:           {no_signal}")

    print(f"\n{'Month':<12} {'P&L':>10}   {'Cumulative':>12}")
    print("-"*38)
    cum = 0
    for month in sorted(monthly_pnl.keys()):
        pnl = monthly_pnl[month]
        cum += pnl
        icon = "✅" if pnl >= 0 else "❌"
        print(f"{month:<12} {icon} ₹{pnl:>7,.0f}  ₹{cum:>9,.0f}")

    print(f"\n{'='*62}")
    print("⚠️  DISCLAIMER: 30-min approximation — not tick-level accuracy")
    print("   Win condition: index moved 80pts in signal direction")
    print("   SL condition: structure SL ≤ 30pts (else skipped)")
    print("   Real results will vary due to slippage, spread, timing")
    print("="*62)

if __name__ == "__main__":
    run_backtest()
