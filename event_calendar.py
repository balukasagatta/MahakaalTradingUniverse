"""
T024: Economic Announcement Filter
Fetches RBI/Fed/NSE event calendar and flags high-impact events.
"""
import requests, json, os
from datetime import datetime, date, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

# Known high-impact recurring events (IST times)
RECURRING_EVENTS = [
    {"name": "RBI Monetary Policy", "months": [2,4,6,8,10,12], "day_range": (1,10), "time": "10:00"},
    {"name": "US Fed FOMC", "months": [1,3,5,6,7,9,11,12], "day_range": (1,31), "time": "23:30"},
    {"name": "India CPI", "months": list(range(1,13)), "day": 12, "time": "17:30"},
    {"name": "India GDP", "months": [2,5,8,11], "day": 28, "time": "17:30"},
    {"name": "US CPI", "months": list(range(1,13)), "day_range": (10,15), "time": "18:30"},
    {"name": "US NFP", "months": list(range(1,13)), "day_range": (1,7), "weekday": 4, "time": "18:30"},
]

def get_events_today():
    """Return list of high-impact events today with their IST times."""
    now = datetime.now(IST)
    today = now.date()
    events = []

    # Check Investing.com economic calendar API (free)
    try:
        r = requests.get(
            "https://api.investing.com/api/financialdata/economic_calendar",
            headers={
                "User-Agent": "Mozilla/5.0",
                "domain-id": "in",
                "Accept": "application/json"
            },
            params={
                "dateFrom": today.strftime("%Y-%m-%d"),
                "dateTo": today.strftime("%Y-%m-%d"),
                "timeZone": "Asia/Kolkata",
                "timeFilter": "timeRemain",
                "currentTab": "today",
                "importance[]": [3]  # high importance only
            },
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            for ev in data.get("data", []):
                events.append({
                    "name": ev.get("name", "Unknown"),
                    "time": ev.get("time", ""),
                    "importance": ev.get("importance", 0),
                    "country": ev.get("country", "")
                })
    except:
        pass

    # Fallback: check NSE announcements
    try:
        r = requests.get(
            "https://www.nseindia.com/api/corporates-corporateActions",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com"},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            for item in data.get("data", []):
                if item.get("purpose", "").lower() in ["agm", "results", "dividend"]:
                    events.append({
                        "name": f"NSE: {item.get('symbol')} {item.get('purpose')}",
                        "time": "09:15",
                        "importance": 2
                    })
    except:
        pass

    return events

def is_high_impact_window(minutes_ahead=30):
    """
    Check if a high-impact economic event is within the next N minutes.
    Returns (True, event_name) or (False, None)
    """
    now = datetime.now(IST)
    events = get_events_today()

    for ev in events:
        try:
            ev_time_str = ev.get("time", "")
            if not ev_time_str:
                continue
            ev_time = IST.localize(datetime.strptime(
                f"{now.date()} {ev_time_str}", "%Y-%m-%d %H:%M"))
            diff = (ev_time - now).total_seconds() / 60
            if 0 <= diff <= minutes_ahead:
                return True, ev["name"]
            # Also check if we're within 5 mins AFTER event (vol spike zone)
            if -5 <= diff < 0:
                return True, f"{ev['name']} (just released)"
        except:
            continue

    return False, None

def get_event_summary():
    """Get today's events as a formatted string for pre-market brief."""
    events = get_events_today()
    if not events:
        return "📅 No major events today"

    lines = ["📅 <b>Key Events Today:</b>"]
    for ev in events[:5]:
        imp = "🔴" if ev.get("importance", 0) >= 3 else "🟡"
        lines.append(f"  {imp} {ev.get('time','')} — {ev.get('name','')}")
    return "\n".join(lines)

if __name__ == "__main__":
    print(get_event_summary())
    hit, name = is_high_impact_window(30)
    print(f"Event in next 30 min: {hit} — {name}")
