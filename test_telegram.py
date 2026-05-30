#!/usr/bin/env python3
"""Quick test — send a message to Telegram."""

import urllib.request, json
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
CHAT_FILE = Path(__file__).parent / ".chat_id"

token = None
for line in ENV_FILE.read_text().splitlines():
    line = line.strip()
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        token = line.split("=", 1)[1].strip()
        break

chat_id = CHAT_FILE.read_text().strip()

print(f"Token: {token[:10]}...")
print(f"Chat ID: {chat_id}")

msg = "Telegram bot connected! Position reports will be sent here daily."

api_url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = json.dumps({
    "chat_id": chat_id,
    "text": msg
}).encode()

req = urllib.request.Request(api_url, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=15) as resp:
    result = json.loads(resp.read())
    print(f"Result: {result}")
    if result.get("ok"):
        print("SUCCESS!")
    else:
        print(f"FAILED: {result}")
