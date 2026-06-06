"""
NSE F&O Bhavcopy Downloader & Parser
Downloads daily option settlement prices from NSE
Free data going back 3+ years
"""
import os, requests, zipfile, io, csv
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{year}/{month}/fo{date}bhav.csv.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/"
}

def download_bhavcopy(date):
    """Download and parse NSE F&O bhavcopy for a given date."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    year  = dt.strftime("%Y")
    month = dt.strftime("%b").upper()
    day   = dt.strftime("%d%b%Y").upper()

    url = BHAVCOPY_URL.format(year=year, month=month, date=day)

    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        # Get cookies — NSE requires this
        s.get("https://www.nseindia.com", timeout=10)
        import time; time.sleep(1)
        s.get("https://www.nseindia.com/market-data/securities-available-for-trading", timeout=10)
        time.sleep(1)
        r = s.get(url, timeout=15)
        print(f"  URL: {url}")
        print(f"  Status: {r.status_code}")

        if r.status_code != 200:
            return None

        # Unzip
        z = zipfile.ZipFile(io.BytesIO(r.content))
        csv_name = z.namelist()[0]
        data = z.read(csv_name).decode("utf-8")

        # Parse CSV
        reader = csv.DictReader(io.StringIO(data))
        records = []
        for row in reader:
            # Filter Nifty weekly options only
            if (row.get("INSTRUMENT") in ["OPTIDX"] and
                row.get("SYMBOL") in ["NIFTY", "BANKNIFTY", "FINNIFTY"]):
                records.append({
                    "symbol":   row.get("SYMBOL", "").strip(),
                    "expiry":   row.get("EXPIRY_DT", "").strip(),
                    "strike":   float(row.get("STRIKE_PR", 0)),
                    "opttype":  row.get("OPTION_TYP", "").strip(),
                    "open":     float(row.get("OPEN", 0) or 0),
                    "high":     float(row.get("HIGH", 0) or 0),
                    "low":      float(row.get("LOW", 0) or 0),
                    "close":    float(row.get("CLOSE", 0) or 0),
                    "settle":   float(row.get("SETTLE_PR", 0) or 0),
                    "oi":       int(float(row.get("OPEN_INT", 0) or 0)),
                    "volume":   int(float(row.get("CONTRACTS", 0) or 0)),
                    "date":     date
                })
        return records

    except Exception as e:
        print(f"[Bhavcopy] {date}: {e}")
        return None

def download_range(from_date, to_date, save_dir="~/mahakaal/bhavcopy_data"):
    """Download bhavcopy for a date range."""
    save_dir = os.path.expanduser(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    start = datetime.strptime(from_date, "%Y-%m-%d")
    end   = datetime.strptime(to_date, "%Y-%m-%d")

    all_records = []
    current = start
    downloaded = 0
    failed = 0

    while current <= end:
        # Skip weekends
        if current.weekday() > 4:
            current += timedelta(days=1)
            continue

        date_str = current.strftime("%Y-%m-%d")
        save_path = os.path.join(save_dir, f"{date_str}.json")

        if os.path.exists(save_path):
            import json
            with open(save_path) as f:
                records = json.load(f)
            all_records.extend(records)
            downloaded += 1
        else:
            records = download_bhavcopy(date_str)
            if records:
                import json
                with open(save_path, "w") as f:
                    json.dump(records, f)
                all_records.extend(records)
                downloaded += 1
                print(f"  ✅ {date_str}: {len(records)} records")
            else:
                failed += 1
                print(f"  ❌ {date_str}: No data")

        current += timedelta(days=1)

    print(f"\nDownloaded: {downloaded} days | Failed: {failed}")
    print(f"Total records: {len(all_records)}")
    return all_records

def get_nifty_option_price(records, date, strike, opttype, expiry=None):
    """Get option price for a specific date/strike/type."""
    matches = [r for r in records
               if r["date"] == date
               and r["symbol"] == "NIFTY"
               and r["strike"] == strike
               and r["opttype"] == opttype]
    if expiry:
        matches = [r for r in matches if expiry in r["expiry"]]
    if matches:
        return matches[0]
    return None

def get_nearest_expiry_options(records, date, spot, otm_pts=300):
    """Get ATM+OTM call and put prices for nearest weekly expiry."""
    day_records = [r for r in records
                   if r["date"] == date and r["symbol"] == "NIFTY"]
    if not day_records:
        return None

    # Find nearest expiry
    expiries = sorted(set(r["expiry"] for r in day_records))
    if not expiries:
        return None

    nearest = expiries[0]

    # Find ATM strike
    atm = round(spot / 50) * 50
    call_short = atm + otm_pts
    put_short  = atm - otm_pts
    call_long  = call_short + 100
    put_long   = put_short  - 100

    def find_price(strike, opttype):
        matches = [r for r in day_records
                   if r["expiry"] == nearest
                   and r["strike"] == float(strike)
                   and r["opttype"] == opttype]
        return matches[0]["close"] if matches else 0

    cs = find_price(call_short, "CE")
    cl = find_price(call_long,  "CE")
    ps = find_price(put_short,  "PE")
    pl = find_price(put_long,   "PE")

    if not cs or not ps:
        return None

    return {
        "expiry": nearest,
        "atm": atm,
        "call_short": call_short, "call_short_price": cs,
        "call_long":  call_long,  "call_long_price":  cl,
        "put_short":  put_short,  "put_short_price":  ps,
        "put_long":   put_long,   "put_long_price":   pl,
        "net_credit": round((cs - cl) + (ps - pl), 2)
    }

if __name__ == "__main__":
    # Test single day first
    print("Testing single day download...")
    records = download_bhavcopy("2026-05-28")
    if records:
        print(f"✅ Got {len(records)} records")
        # Show sample
        nifty = [r for r in records if r["symbol"] == "NIFTY"][:3]
        for r in nifty:
            print(f"  {r['symbol']} {r['expiry']} {r['strike']} {r['opttype']} Close={r['close']}")
    else:
        print("❌ No data — trying older date")
        records = download_bhavcopy("2026-05-27")
        if records:
            print(f"✅ Got {len(records)} records")
