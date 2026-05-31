"""
T023: Dispersion-Based Regime Signal
Compare Nifty IV vs top constituent stock IVs
"""
import requests, os
from datetime import date, timedelta

# Top 10 Nifty constituents by weight with their instrument keys
NIFTY_TOP10 = {
    "RELIANCE":  "NSE_EQ|INE002A01018",
    "HDFC BANK": "NSE_EQ|INE040A01034",
    "ICICI BANK":"NSE_EQ|INE090A01021",
    "INFY":      "NSE_EQ|INE009A01021",
    "TCS":       "NSE_EQ|INE467B01029",
}

def get_stock_atm_iv(instrument_key, token):
    """Get ATM IV for a stock option."""
    try:
        h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        
        # Get expiry
        r = requests.get("https://api.upstox.com/v2/option/contract",
            headers=h, params={"instrument_key": instrument_key}, timeout=8)
        d = r.json()
        if not d.get("data"): return None
        expiry = d["data"][0]["expiry"]
        
        # Get chain
        r2 = requests.get("https://api.upstox.com/v2/option/chain",
            headers=h,
            params={"instrument_key": instrument_key, "expiry_date": expiry},
            timeout=8)
        d2 = r2.json()
        data = d2.get("data", [])
        if not data: return None
        
        # Get spot
        spot = next((x["underlying_spot_price"] for x in data 
                    if x.get("underlying_spot_price", 0) > 0), 0)
        if not spot: return None
        
        # ATM strike
        atm = min(data, key=lambda x: abs(x["strike_price"] - spot))
        ce_iv = atm.get("call_options", {}).get("option_greeks", {}).get("iv", 0)
        pe_iv = atm.get("put_options", {}).get("option_greeks", {}).get("iv", 0)
        return round((ce_iv + pe_iv) / 2, 2) if ce_iv and pe_iv else None
    except Exception as e:
        print(f"[Dispersion] {instrument_key}: {e}")
        return None

def get_dispersion_signal(nifty_atm_iv, token):
    """
    Calculate dispersion = Nifty IV - avg stock IVs
    Returns: (dispersion, signal, details)
    """
    stock_ivs = {}
    for name, key in NIFTY_TOP10.items():
        iv = get_stock_atm_iv(key, token)
        if iv: stock_ivs[name] = iv
    
    if not stock_ivs:
        return 0, "NEUTRAL", {}
    
    avg_stock_iv = sum(stock_ivs.values()) / len(stock_ivs)
    dispersion = round(nifty_atm_iv - avg_stock_iv, 2)
    
    # India-calibrated thresholds
    # Stock IVs always > Nifty IV due to diversification
    # Less negative = Nifty IV relatively expensive = better edge
    if dispersion > -5.0:
        signal = "STRONG_EDGE"  # Nifty IV close to stock IVs = overpriced
    elif dispersion > -10.0:
        signal = "EDGE"         # Normal dispersion = normal edge
    elif dispersion < -12.0:
        signal = "NO_EDGE"      # Stocks extremely volatile vs index = skip
    else:
        signal = "NEUTRAL"
    
    return dispersion, signal, {
        "nifty_iv": nifty_atm_iv,
        "avg_stock_iv": round(avg_stock_iv, 2),
        "dispersion": dispersion,
        "stock_ivs": stock_ivs,
        "signal": signal
    }

if __name__ == "__main__":
    env = {}
    with open("env.vars") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    token = env.get("UPSTOX_ACCESS_TOKEN", "")
    disp, sig, details = get_dispersion_signal(15.0, token)
    print(f"Dispersion: {disp}%")
    print(f"Signal: {sig}")
    print(f"Details: {details}")
