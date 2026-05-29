"""
Dhan Auto Token Generator - using official DhanLogin SDK
"""
import os, subprocess, pyotp
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")
ENV_PATH = os.path.expanduser("~/mahakaal/env.vars")

def log(msg):
    t = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def load_env():
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

def save_dhan_token(token):
    subprocess.run(["sed", "-i", "/^DHAN_ACCESS_TOKEN/d", ENV_PATH])
    with open(ENV_PATH, "a") as f:
        f.write(f"\nDHAN_ACCESS_TOKEN={token}\n")
    log("Dhan token saved to env.vars")

def send_telegram(msg):
    try:
        import requests
        env = load_env()
        bot  = env.get("TELEGRAM_BOT_TOKEN")
        chat = env.get("TELEGRAM_CHAT_ID")
        if bot and chat:
            requests.post(
                f"https://api.telegram.org/bot{bot}/sendMessage",
                json={"chat_id": chat, "text": msg})
    except:
        pass

def get_dhan_token():
    env         = load_env()
    client_id   = env.get("DHAN_CLIENT_ID", "")
    pin         = env.get("DHAN_PIN", "")
    totp_secret = env.get("DHAN_TOTP_SECRET", "")

    if not all([client_id, pin, totp_secret]):
        log("Missing DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET")
        return False

    try:
        from dhanhq import DhanLogin

        totp = pyotp.TOTP(totp_secret).now()
        log(f"TOTP generated: {totp}")

        dhan_login = DhanLogin(client_id)
        result = dhan_login.generate_token(pin, totp)
        log(f"Result: {result}")

        token = None
        if isinstance(result, dict):
            token = result.get("accessToken") or result.get("access_token") or result.get("token")
        elif isinstance(result, str) and len(result) > 50:
            token = result

        if token:
            save_dhan_token(token)
            subprocess.run(["sudo", "systemctl", "restart", "srimhatre"])
            send_telegram("✅ Dhan token auto-refreshed! SriMhatre restarted.")
            log("SUCCESS")
            return True
        else:
            log(f"Token not found in result: {result}")
            send_telegram(f"❌ Dhan auto-login failed: {str(result)[:100]}")
            return False

    except Exception as e:
        import traceback
        traceback.print_exc()
        send_telegram(f"❌ Dhan auto-login error: {str(e)[:100]}")
        return False

if __name__ == "__main__":
    get_dhan_token()
