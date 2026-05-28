"""
SriMhatre Backtest
==================
Tests option selling strategy on Nifty
for last 3 years using Yahoo Finance data.

Capital: ₹3,50,000
Target: ₹40,000/month consistently

Run on VM:
  cd ~/mahakaal && source venv/bin/activate
  pip install yfinance pandas numpy --break-system-packages -q
  python3 srimhatre_backtest.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ===== PARAMETERS =====
CAPITAL      = 400000    # ₹3.5L
LOT_SIZE     = 65        # Nifty lot size
LOTS         = 6         # 4 lots
SPREAD_WIDTH = 100       # 100pt wide spread
MIN_IV       = 11        # Lower threshold
MAX_IV       = 20        # Reduce size if VIX > 25
TARGET_MONTH = 40000     # ₹40,000 monthly target

# ===== DOWNLOAD DATA =====
print("Downloading 3 years of data...")
print("This may take 30-60 seconds...")

nifty_df = yf.Ticker('^NSEI').history(period='3y')[
    ['Open', 'High', 'Low', 'Close', 'Volume']]
vix_df = yf.Ticker('^INDIAVIX').history(period='3y')[
    ['Close']].rename(columns={'Close': 'VIX'})

# Clean timezone
nifty_df.index = nifty_df.index.tz_localize(None)
vix_df.index   = vix_df.index.tz_localize(None)

# Join
df = nifty_df.join(vix_df, how='left')
df['VIX'] = df['VIX'].ffill()
df = df.dropna()

print(f"✅ Data loaded: {len(df)} trading days")
print(f"   Period: {df.index[0].date()} → {df.index[-1].date()}")
print(f"   Nifty range: {df['Low'].min():.0f} - {df['High'].max():.0f}")
print(f"   VIX range: {df['VIX'].min():.1f} - {df['VIX'].max():.1f}")

# ===== CREDIT ESTIMATOR =====
def estimate_credit(spot, vix, spread_width=100):
    """
    Estimate net credit for OTM spread.
    Based on IV and distance from spot.
    Conservative estimate.
    """
    iv_daily = vix / 100 / np.sqrt(252)
    otm_dist = spread_width

    # Credit as fraction of spread width
    # Higher VIX = more credit
    # Approximate for DTE 5-7
    base_credit_pct = (vix / 100) * np.sqrt(5 / 365) * 0.4
    credit = spread_width * min(0.35, max(0.12, base_credit_pct))
    return round(credit, 1)

# ===== REGIME DETECTOR =====
def detect_regime(row, prev_row, prev_prev_row=None):
    """
    Detect market regime using price structure.
    No indicators — pure price action.
    """
    vix = row['VIX']

    # Skip conditions
    if vix < MIN_IV:
        return 'SKIP_LOW_IV'

    # Previous day structure
    prev_range = prev_row['High'] - prev_row['Low']
    if prev_range == 0:
        return 'SKIP_NO_DATA'

    prev_close_str = (prev_row['Close'] - prev_row['Low']) / prev_range
    prev_body_pct  = abs(prev_row['Close'] - prev_row['Open']) / prev_range

    # Today's gap
    gap_pct = (row['Open'] - prev_row['Close']) / prev_row['Close'] * 100

    # Today's intraday structure (proxy for 10:30 AM)
    # Using High-Low range and Close position
    today_range = row['High'] - row['Low']
    if today_range > 0:
        today_close_str = (row['Close'] - row['Low']) / today_range
    else:
        today_close_str = 0.5

    # Day's move from open
    day_move_pct = (row['Close'] - row['Open']) / row['Open'] * 100

    # Higher high / higher low check (if prev_prev available)
    hh_hl = False
    lh_ll = False
    if prev_prev_row is not None:
        hh_hl = (prev_row['High'] > prev_prev_row['High'] and
                 prev_row['Low'] > prev_prev_row['Low'])
        lh_ll = (prev_row['High'] < prev_prev_row['High'] and
                 prev_row['Low'] < prev_prev_row['Low'])

    # Score signals
    bull = 0
    bear = 0

    # Signal 1: Previous day close strength
    if prev_close_str > 0.65: bull += 2
    elif prev_close_str < 0.35: bear += 2

    # Signal 2: Previous day body (conviction)
    if prev_body_pct > 0.6:
        if prev_row['Close'] > prev_row['Open']: bull += 1
        else: bear += 1

    # Signal 3: Gap
    if gap_pct > 0.4: bull += 1
    elif gap_pct < -0.4: bear += 1

    # Signal 4: Day move
    if day_move_pct > 0.5: bull += 1
    elif day_move_pct < -0.5: bear += 1

    # Signal 5: Higher highs/lows structure
    if hh_hl: bull += 1
    elif lh_ll: bear += 1

    # Signal 6: Today close strength
    if today_close_str > 0.65: bull += 1
    elif today_close_str < 0.35: bear += 1

    # Classification
    if bull >= 4:
        return 'TRENDING_UP'
    elif bear >= 4:
        return 'TRENDING_DOWN'
    elif vix > 18:
        return 'HIGH_IV_CHOPPY'
    else:
        return 'CHOPPY'

# ===== STRATEGY SELECTOR =====
def select_strategy(regime, vix):
    strategies = {
        'TRENDING_UP':    'Bull Put Spread',
        'TRENDING_DOWN':  'Bear Call Spread',
        'CHOPPY':         'Iron Condor',
        'HIGH_IV_CHOPPY': 'Wide Iron Condor',
    }
    return strategies.get(regime, 'Skip')

# ===== WIN/LOSS CHECKER =====
def check_outcome(regime, row, trade):
    """
    Simulate trade outcome based on day's price action.
    Uses OHLC as proxy for intraday movement.
    """
    day_move_pct = (row['Close'] - row['Open']) / row['Open'] * 100
    day_range_pct = (row['High'] - row['Low']) / row['Open'] * 100
    qty = trade['qty']

    if regime == 'TRENDING_UP':
        # Bull Put Spread: profit if market flat or up
        # Loss if market drops hard
        if day_move_pct >= -0.4:
            return 'WIN', trade['target'] * qty
        elif day_move_pct < -1.2:
            return 'LOSS', -trade['sl'] * qty
        else:
            return 'SCRATCH', trade['target'] * qty * 0.25

    elif regime == 'TRENDING_DOWN':
        # Bear Call Spread: profit if market flat or down
        if day_move_pct <= 0.4:
            return 'WIN', trade['target'] * qty
        elif day_move_pct > 1.2:
            return 'LOSS', -trade['sl'] * qty
        else:
            return 'SCRATCH', trade['target'] * qty * 0.25

    elif regime in ['CHOPPY', 'HIGH_IV_CHOPPY']:
        # Iron Condor: profit if market stays in range
        if day_range_pct < 1.0:
            return 'WIN', trade['target'] * qty
        elif day_range_pct > 1.8:
            return 'LOSS', -trade['sl'] * qty * 0.6  # IC partial loss
        else:
            return 'SCRATCH', trade['target'] * qty * 0.3

    return 'SKIP', 0

# ===== RUN BACKTEST =====
print()
print("Running backtest...")

results = []
df_reset = df.reset_index()

for i in range(2, len(df_reset)):
    row           = df_reset.iloc[i]
    prev_row      = df_reset.iloc[i-1]
    prev_prev_row = df_reset.iloc[i-2]

    date  = pd.to_datetime(row['Date']).date()
    month = date.strftime('%Y-%m')
    spot  = row['Open']
    vix   = row['VIX']

    # Detect regime
    regime = detect_regime(row, prev_row, prev_prev_row)

    if regime.startswith('SKIP'):
        results.append({
            'date': date, 'month': month,
            'regime': regime, 'strategy': 'Skip',
            'result': 'SKIP', 'pnl': 0,
            'spot': spot, 'vix': vix
        })
        continue

    # Calculate trade parameters
    credit    = estimate_credit(spot, vix, SPREAD_WIDTH)
    max_loss  = SPREAD_WIDTH - credit
    target    = round(credit * 0.50, 1)   # 50% credit capture
    sl        = round(credit * 2.0, 1)    # 2x credit SL
    qty       = LOTS * LOT_SIZE

    trade = {
        'credit': credit,
        'max_loss': max_loss,
        'target': target,
        'sl': sl,
        'qty': qty,
    }

    strategy = select_strategy(regime, vix)
    result, pnl = check_outcome(regime, row, trade)

    results.append({
        'date':     date,
        'month':    month,
        'regime':   regime,
        'strategy': strategy,
        'credit':   credit,
        'target':   target,
        'sl':       sl,
        'result':   result,
        'pnl':      round(pnl, 0),
        'spot':     spot,
        'vix':      vix,
    })

results_df = pd.DataFrame(results)

# ===== ANALYSIS =====
print()
print("=" * 65)
print("  SRIMHATRE BACKTEST RESULTS")
print(f"  Capital: ₹{CAPITAL:,} | Lots: {LOTS} | Spread: {SPREAD_WIDTH}pts")
print(f"  Target: ₹{TARGET_MONTH:,}/month")
print("=" * 65)

# Overall stats
traded  = results_df[results_df['result'] != 'SKIP']
wins    = traded[traded['result'] == 'WIN']
losses  = traded[traded['result'] == 'LOSS']
scratch = traded[traded['result'] == 'SCRATCH']
skipped = results_df[results_df['result'] == 'SKIP']

total_pnl = traded['pnl'].sum()
win_rate  = len(wins) / len(traded) * 100 if len(traded) > 0 else 0

print(f"\nOVERALL STATS:")
print(f"  Total trading days:     {len(results_df)}")
print(f"  Trades taken:           {len(traded)}")
print(f"  Skipped (low IV):       {len(skipped)}")
print(f"  Wins:                   {len(wins)} ({win_rate:.1f}%)")
print(f"  Losses:                 {len(losses)}")
print(f"  Scratch:                {len(scratch)}")
print(f"  Total P&L (3 years):    ₹{total_pnl:,.0f}")
print(f"  Avg P&L per trade:      ₹{traded['pnl'].mean():,.0f}")
print(f"  Best trade:             ₹{traded['pnl'].max():,.0f}")
print(f"  Worst trade:            ₹{traded['pnl'].min():,.0f}")

# Strategy breakdown
print(f"\nSTRATEGY BREAKDOWN:")
for strat in traded['strategy'].unique():
    s = traded[traded['strategy'] == strat]
    w = s[s['result'] == 'WIN']
    wr = len(w) / len(s) * 100 if len(s) > 0 else 0
    print(f"  {strat:25s}: {len(s):3d} trades | "
          f"WR {wr:.0f}% | P&L ₹{s['pnl'].sum():,.0f}")

# Regime breakdown
print(f"\nREGIME BREAKDOWN:")
for regime in traded['regime'].unique():
    r = traded[traded['regime'] == regime]
    w = r[r['result'] == 'WIN']
    wr = len(w) / len(r) * 100 if len(r) > 0 else 0
    print(f"  {regime:25s}: {len(r):3d} trades | "
          f"WR {wr:.0f}% | P&L ₹{r['pnl'].sum():,.0f}")

# Monthly P&L
print(f"\nMONTHLY P&L:")
monthly = results_df.groupby('month')['pnl'].sum()

good_months  = (monthly >= TARGET_MONTH).sum()
ok_months    = ((monthly >= 20000) & (monthly < TARGET_MONTH)).sum()
bad_months   = (monthly < 0).sum()
avg_monthly  = monthly.mean()
best_month   = monthly.max()
worst_month  = monthly.min()

for month, pnl in monthly.items():
    icon = ("✅" if pnl >= TARGET_MONTH else
            "🔶" if pnl >= 20000 else
            "⚠️" if pnl >= 0 else "❌")
    bar = "█" * min(20, max(0, int(pnl / 5000)))
    print(f"  {icon} {month}: ₹{pnl:>8,.0f}  {bar}")

# Final verdict
print()
print("=" * 65)
print("  VERDICT")
print("=" * 65)
print(f"  Good months (≥₹40k):         {good_months}")
print(f"  Average months (₹20-40k):     {ok_months}")
print(f"  Loss months (<₹0):            {bad_months}")
print(f"  Monthly average P&L:          ₹{avg_monthly:,.0f}")
print(f"  Best month:                   ₹{best_month:,.0f}")
print(f"  Worst month:                  ₹{worst_month:,.0f}")
print(f"  Return on capital:            {avg_monthly/CAPITAL*100:.1f}%/month")
print()

if avg_monthly >= TARGET_MONTH:
    print(f"  🏆 TARGET ₹{TARGET_MONTH:,}/month: ACHIEVED")
elif avg_monthly >= TARGET_MONTH * 0.75:
    print(f"  ⚠️  TARGET ₹{TARGET_MONTH:,}/month: CLOSE")
    print(f"     Increase to {int(LOTS * TARGET_MONTH/avg_monthly)+1} lots to hit target")
else:
    print(f"  ❌ TARGET ₹{TARGET_MONTH:,}/month: NOT ACHIEVED")
    lots_needed = int(LOTS * TARGET_MONTH / avg_monthly) + 1
    margin_needed = lots_needed * 17500
    print(f"     Need {lots_needed} lots (₹{margin_needed:,} margin)")

print()
print(f"  Win rate:    {win_rate:.1f}%")
print(f"  Trades/month: {len(traded)/36:.1f} avg")
print("=" * 65)
