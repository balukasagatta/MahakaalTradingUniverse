"""
Call this at 8:30 AM daily.
Sends token request to Upstox → you get WhatsApp notification → tap Approve → token auto-saved.
"""
import requests, os

def load_env():
    env = {}
    with open(os.path.expanduser("~/mahakaal/env.vars")) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

def request_token():
    env = load_env()
    client_id     = env.get("UPSTOX_API_KEY")
    client_secret = env.get("UPSTOX_API_SECRET")

    r = requests.post(
        f"https://api.upstox.com/v3/login/auth/token/request/{client_id}",
        headers={"accept": "application/json", "Content-Type": "application/json"},
        json={"client_secret": client_secret})

    print("Status:", r.status_code)
    print("Response:", r.json())

    # Send Telegram alert
    bot_token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id   = env.get("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id,
                  "text": "🔑 Upstox token requested!\nCheck WhatsApp and tap APPROVE.",
                  "parse_mode": "HTML"})

if __name__ == "__main__":
    request_token()
