#!/usr/bin/env python3
"""
Upstox Token Auto-Refresh — Custom implementation
curl-cffi + pyotp (Python 3.11 compatible)
"""
import os, sys, json, subprocess, logging, pyotp
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from curl_cffi import requests as cf

load_dotenv(Path.home() / "mahakaal" / ".env.upstox")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('/var/log/upstox_token_refresh.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

ENV_FILE      = Path.home() / "mahakaal" / "env.vars"
TOKEN_CACHE   = Path.home() / "mahakaal" / ".upstox_token_cache.json"
CLIENT_ID     = "92c6ea83-b7dc-44f3-b286-f89b1d9f5f6e"
CLIENT_SECRET = "9xk7ym6j0n"
REDIRECT_URI  = "https://127.0.0.1"
BOT_SERVICES  = ["alakh.service", "srimhatre.service", "guha.service"]

TELEGRAM_CHAT = "935391809"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

def send_telegram(msg):
    if not TELEGRAM_TOKEN:
        logger.warning("No Telegram token set, skipping alert")
        return
    try:
        import urllib.request
        data = json.dumps({"chat_id": TELEGRAM_CHAT, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")

def get_totp():
    secret = os.getenv("UPSTOX_TOTP_SECRET", "").strip()
    return pyotp.TOTP(secret).now()

def generate_token():
    username = os.getenv("UPSTOX_USERNAME", "").strip()
    password = os.getenv("UPSTOX_PASSWORD", "").strip()
    pin      = os.getenv("UPSTOX_PIN", "").strip()

    session = cf.Session(impersonate="chrome110")

    try:
        # Step 1: Load auth dialog
        auth_url = (
            f"https://api.upstox.com/v2/login/authorization/dialog"
            f"?response_type=code&client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}&state="
        )
        r = session.get(auth_url, allow_redirects=True)
        logger.info(f"[1] Auth dialog: {r.status_code}")

        # Step 2: Submit mobile number
        r = session.post(
            "https://api.upstox.com/v2/login/authorization/dialog",
            data={"mobile_number": username},
            allow_redirects=True
        )
        logger.info(f"[2] Mobile submit: {r.status_code}")

        # Step 3: Submit TOTP
        totp = get_totp()
        logger.info(f"[3] TOTP generated: {totp}")
        r = session.post(
            "https://api.upstox.com/v2/login/authorization/dialog",
            data={"otp": totp},
            allow_redirects=True
        )
        logger.info(f"[3] TOTP submit: {r.status_code}")

        # Step 4: Submit PIN
        r = session.post(
            "https://api.upstox.com/v2/login/authorization/dialog",
            data={"pin": pin},
            allow_redirects=True
        )
        logger.info(f"[4] PIN submit: {r.status_code} | Final URL: {r.url}")

        # Step 5: Extract auth code
        parsed = urlparse(str(r.url))
        params = parse_qs(parsed.query)

        if 'code' not in params:
            raise Exception(f"Auth code missing. Final URL: {r.url}\nResponse: {r.text[:500]}")

        auth_code = params['code'][0]
        logger.info(f"[5] Auth code captured: {auth_code[:20]}...")

        # Step 6: Exchange code for access token
        token_resp = session.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code": auth_code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code"
            }
        )
        token_data = token_resp.json()
        logger.info(f"[6] Token exchange: {token_resp.status_code}")

        if "access_token" not in token_data:
            raise Exception(f"Token exchange failed: {token_data}")

        token = token_data["access_token"]

        # Cache it
        with open(TOKEN_CACHE, 'w') as f:
            json.dump({
                "access_token": token,
                "generated_at": datetime.now().isoformat(),
                "user_id": token_data.get("user_id", "")
            }, f, indent=2)

        logger.info("✅ Token generated and cached")
        return token

    except Exception as e:
        logger.error(f"Token generation failed: {e}")
        send_telegram(f"🔴 MTU: Upstox token FAILED!\nError: {e}")
        return None

def update_env_file(token):
    env_content = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env_content[k.strip()] = v.strip()
    env_content['UPSTOX_ACCESS_TOKEN'] = token
    env_content['UPSTOX_TOKEN_GENERATED_AT'] = datetime.now().isoformat()
    with open(ENV_FILE, 'w') as f:
        f.write("# Auto-generated -- DO NOT EDIT MANUALLY\n")
        for k, v in env_content.items():
            f.write(f"{k}={v}\n")
    logger.info("✅ env.vars updated")

def restart_bots():
    for service in BOT_SERVICES:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", service],
            capture_output=True, text=True, timeout=30
        )
        status = "OK" if result.returncode == 0 else f"FAILED: {result.stderr.strip()}"
        logger.info(f"Restart {service}: {status}")

def main():
    logger.info("=== Upstox Token Refresh Started ===")
    token = generate_token()
    if not token:
        sys.exit(1)
    update_env_file(token)
    restart_bots()
    send_telegram("✅ MTU: Upstox token refreshed & all bots restarted!")
    logger.info("=== Token Refresh Complete ===")

if __name__ == "__main__":
    main()
