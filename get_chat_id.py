#!/usr/bin/env python3
"""Get chat_id from Telegram bot. Send any message to the bot first, then run this."""

import urllib.request, json
from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"
token = None
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break

if not token:
    print("ERROR: No TELEGRAM_BOT_TOKEN in .env")
    exit(1)

print(f"Fetching updates from bot...")

url = f"https://api.telegram.org/bot{token}/getUpdates"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())

if not data.get("ok"):
    print(f"Error: {data}")
    exit(1)

result = data.get("result", [])
if not result:
    print("No messages found. Send any message to your bot on Telegram first, then run this again.")
    exit(0)

print(f"\nFound {len(result)} update(s):\n")
for update in result:
    msg = update.get("message", {})
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    username = chat.get("username", "N/A")
    text = msg.get("text", "")
    print(f"  chat_id: {chat_id}  |  username: {username}  |  text: {text}")

# Save the last chat_id
last_chat_id = result[-1]["message"]["chat"]["id"]
chat_file = Path(__file__).parent / ".chat_id"
chat_file.write_text(str(last_chat_id))
print(f"\n✅ Saved chat_id {last_chat_id} to .chat_id")
print(f"Now send_report.py will deliver to your Telegram.")
