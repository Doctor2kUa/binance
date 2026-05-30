#!/usr/bin/env python3
"""Monitor CAKE/USDT price and alert when it reaches likely support (bottom) levels.
   Levels are based on recent technical analysis:
   • $1.30  – around Bollinger Lower band & 50‑day support region
   • $1.20  – strong 100‑day support
   • $1.10  – historic low (≈ one‑year low)
   The script stores which alerts have already been sent in a small JSON file
   so you get each alert only once.
"""

import os, json, urllib.request
from pathlib import Path

# ---- Config ----
ENV_PATH   = Path(__file__).parent / ".env"
CHAT_PATH  = Path(__file__).parent / ".chat_id"
STATE_PATH = Path(__file__).parent / "cake_bottom_state.json"

# Load Telegram credentials
TOKEN = None
CHAT_ID = None
for line in ENV_PATH.read_text().splitlines():
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        TOKEN = line.split("=", 1)[1].strip()
for line in CHAT_PATH.read_text().splitlines():
    CHAT_ID = line.strip()

if not TOKEN or not CHAT_ID:
    raise SystemExit("Telegram bot token or chat_id not found in .env/.chat_id")

# ---- Support / Bottom levels (USDT) ----
TARGETS = [1.30, 1.20, 1.10]

# Load persisted state (which alerts already sent)
if STATE_PATH.exists():
    state = json.loads(STATE_PATH.read_text())
else:
    state = {"sent": []}

def send_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        # If Telegram fails we still want the script to continue
        print(f"Telegram error: {e}")

def fetch_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=CAKEUSDT"
    data = json.loads(urllib.request.urlopen(url, timeout=10).read())
    return float(data["price"])

price = fetch_price()

alerts = []
for lvl in TARGETS:
    if price <= lvl and lvl not in state["sent"]:
        alerts.append(lvl)
        state["sent"].append(lvl)

if alerts:
    # Build a friendly message
    levels_msg = ", ".join([f"${l:.2f}" for l in alerts])
    msg = f"🔔 *CAKE/USDT* достиг(ли) уровня(ов) поддержки: {levels_msg}\n"
    msg += f"Текущая цена: `${price:.4f}`"
    send_telegram(msg)
    # Persist state so we do not spam repeatedly
    STATE_PATH.write_text(json.dumps(state, indent=2))

# End of script
