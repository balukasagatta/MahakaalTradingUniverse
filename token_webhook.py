"""
Upstox Token Webhook Receiver
Upstox sends access token to this endpoint after you approve on phone.
Runs on port 8502.
"""
from flask import Flask, request, jsonify
import subprocess, os, json
from datetime import datetime
import pytz

app = Flask(__name__)
IST = pytz.timezone("Asia/Kolkata")
ENV_PATH = os.path.expanduser("~/mahakaal/env.vars")

def log(msg):
    t = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def save_token(token):
    subprocess.run(["sed", "-i", "/UPSTOX_ACCESS_TOKEN/d", ENV_PATH])
    with open(ENV_PATH, "a") as f:
        f.write(f"\nUPSTOX_ACCESS_TOKEN={token}\n")
    log(f"Token saved: {token[:20]}...")

    # Restart all bots
    subprocess.run(["sudo", "systemctl", "restart", "alakh", "srimhatre", "guha"])
    log("All bots restarted with new token")

    # Send Telegram alert
    try:
        import requests as req
        env = {}
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
        bot_token = env.get("TELEGRAM_BOT_TOKEN")
        chat_id = env.get("TELEGRAM_CHAT_ID")
        if bot_token and chat_id:
            req.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id,
                      "text": "✅ Upstox token auto-refreshed!\nAll bots restarted.",
                      "parse_mode": "HTML"})
    except: pass

@app.route("/upstox/token", methods=["POST"])
def token_webhook():
    try:
        log(f"Headers: {dict(request.headers)}")
        log(f"Raw body: {request.get_data()[:500]}")
        data = request.json or {}
        log(f"Webhook received: {json.dumps(data)[:200]}")

        # Upstox sends token in different fields
        token = (data.get("access_token") or
                 data.get("accessToken") or
                 data.get("token"))

        if token:
            save_token(token)
            return jsonify({"status": "success"}), 200
        else:
            log(f"No token in payload: {data}")
            return jsonify({"status": "no_token", "data": data}), 400
    except Exception as e:
        log(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    log("Token webhook receiver started on port 8502")
    app.run(host="0.0.0.0", port=8502, debug=False)
