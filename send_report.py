#!/usr/bin/env python3
"""Monitor CAKE/USDT spot position and alert on exit points.
   Entry: $1.37, Target: 1.40+
   Rules: No selling in minus. Wait stable profit. Trail SL after 1.40.
"""

import urllib.request, json, os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path("/Users/roman_devops/Downloads/binance")
ENV_FILE = BASE_DIR / ".env"
CHAT_FILE = BASE_DIR / ".chat_id"

token = chat_id = None
for line in ENV_FILE.read_text().splitlines():
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        token = line.split("=", 1)[1].strip()
for line in CHAT_FILE.read_text().splitlines():
    chat_id = line.strip()

if not token or not chat_id:
    raise SystemExit("Missing token or chat_id")

def send(msg):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

# ── CAKE position ──
ENTRY = 1.37
TP_1 = 1.40  # first take-profit zone
TP_2 = 1.45  # second zone
TP_3 = 1.48  # SMA20 resistance

# Fetch price
tk = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=CAKEUSDT")
px = float(tk['lastPrice'])
ch = float(tk['priceChangePercent'])
hi = float(tk['highPrice'])
lo = float(tk['lowPrice'])
vol = float(tk['quoteVolume'])

# Fetch daily klines for indicators
kl = fetch("https://fapi.binance.com/fapi/v1/klines?symbol=CAKEUSDT&interval=1d&limit=30")
closes = [float(k[4]) for k in kl]
highs  = [float(k[2]) for k in kl]
lows   = [float(k[3]) for k in kl]
dates  = [datetime.utcfromtimestamp(k[0]/1000).strftime('%Y-%m-%d') for k in kl]

# RSI
def calc_rsi(data, p=14):
    if len(data) < p+1: return 50
    g, l = [], []
    for i in range(1, len(data)):
        df = data[i]-data[i-1]; g.append(max(df,0)); l.append(max(-df,0))
    ag, al = sum(g[:p])/p, sum(l[:p])/p
    rv = [100-100/(1+ag/max(al,1e-10))]
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
        rv.append(100-100/(1+ag/max(al,1e-10)))
    return rv[-1]

# SMA
def sma(d, p):
    return sum(d[-p:])/p if len(d) >= p else d[-1]

rsi_v = calc_rsi(closes)
sma7  = sma(closes, 7)
sma20 = sma(closes, 20)
atr14 = sum(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(closes)))/14

# PnL
pnl = (px / ENTRY - 1) * 100
pnl_usd = f"+{pnl:.1f}%" if pnl > 0 else f"{pnl:.1f}%"

# ── Build message ──
lines = [
    f"*CAKE/USDT* — Spot Position",
    f"Entry: `${ENTRY}` → Current: `${px:.4f}`",
    f"PnL: *{pnl_usd}*  ({ch:+.2f}% 24h)",
    f"",
    f"RSI: {rsi_v:.0f}  |  SMA7: `${sma7:.4f}`  |  SMA20: `${sma20:.4f}`",
    f"ATR: ${atr14:.4f}  |  Vol: ${vol:,.0f}",
    f"",
]

# ── Exit logic ──
alert = None

if px >= TP_3:
    alert = f"🔴 *CAKE TP3 HIT* `${px:.4f}` (+{pnl:.1f}%)\nClose **100%** or trail SL to $1.45. Lock profits!"
elif px >= TP_2:
    alert = f"🟡 *CAKE TP2 HIT* `${px:.4f}` (+{pnl:.1f}%)\nClose **50%**. Trail SL to $1.40 for rest."
elif px >= TP_1:
    # Check if stable (RSI not overbought, no huge spike)
    if rsi_v < 65:
        alert = f"🟢 *CAKE TP1 HIT* `${px:.4f}` (+{pnl:.1f}%)\nClose **30%**. Move SL to break-even ($1.37). Target $1.45+"
    else:
        alert = f"⚠️ *CAKE at TP1* `${px:.4f}` but RSI {rsi_v:.0f} high. Take 30% off, wait for pullback to add."

# ── Trend check for rest of watchlist ──
zec = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=ZECUSDT")
eden = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=EDENUSDT")
trump = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=TRUMPUSDT")

lines.append(f"*Watchlist* (waiting for trend):")

zec_px = float(zec['lastPrice']); zec_ch = float(zec['priceChangePercent'])
eden_px = float(eden['lastPrice']); eden_ch = float(eden['priceChangePercent'])
trump_px = float(trump['lastPrice']); trump_ch = float(trump['priceChangePercent'])

# ZEC trend check
zec_trend = "🟢 LONG if holds $520" if zec_px > 520 else "🔴 Wait — below $520"
lines.append(f"  ZEC: ${zec_px:.2f} ({zec_ch:+.1f}%) — {zec_trend}")

# EDEN trend check
eden_trend = "🟢 SHORT if rejects $0.065" if eden_px < 0.065 else "🔴 Wait — above $0.065"
lines.append(f"  EDEN: ${eden_px:.4f} ({eden_ch:+.1f}%) — {eden_trend}")

# TRUMP trend check
trump_trend = "🟢 LONG ZONE" if trump_px < 2.0 else "🔴 Wait — not in buy zone"
lines.append(f"  TRUMP: ${trump_px:.3f} ({trump_ch:+.1f}%) — {trump_trend}")

# HOME trend check
home = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=HOMEUSDT")
home_px = float(home['lastPrice']); home_ch = float(home['priceChangePercent'])
if home_px > 0.030: home_trend = "🔴 ATH zone — don't chase"
elif home_px > 0.025: home_trend = "🟡 Overbought (RSI 83) — wait pullback"
else: home_trend = "🟢 Pullback zone — consider long"
lines.append(f"  HOME: ${home_px:.4f} ({home_ch:+.1f}%) — {home_trend}")

# DASH trend check
dash = fetch("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=DASHUSDT")
dash_px = float(dash['lastPrice']); dash_ch = float(dash['priceChangePercent'])
if dash_px > 42: dash_trend = "🟢 LONG confirmed (above SMA50)"
elif dash_px < 39: dash_trend = "🟢 SHORT zone (below swing low)"
else: dash_trend = "⚪ Neutral — wait for direction"
lines.append(f"  DASH: ${dash_px:.2f} ({dash_ch:+.1f}%) — {dash_trend}")

# ── Send ──
if alert:
    send(f"🚨 ALERT ({datetime.utcnow().strftime('%H:%M UTC')})\n\n{alert}")

msg = "\n".join(lines) + f"\n\n_{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_"
send(msg)
print("Sent")
