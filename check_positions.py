#!/usr/bin/env python3
"""Daily position check — RAVE SHORT + GUN LONG."""

import urllib.request, json, math
from datetime import datetime

def fetch_futures(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def fetch_spot(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

base_f = "https://fapi.binance.com"

with open("/Users/roman_devops/Downloads/binance/positions.json") as f:
    state = json.load(f)

W = 65
print("=" * W)
print(f"  POSITION CHECK — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
print("=" * W)

W = 65
digits_map = {"RAVEUSDT": 6, "GUNUSDT": 8}

for pos in state["positions"]:
    sym = pos["symbol"]
    side = pos["side"]
    entry = pos["entry_price"]
    digits = digits_map.get(sym, 6)
    fmt = lambda v: f"${v:.{digits}f}"

    # Get current price
    ticker = fetch_futures(f"{base_f}/fapi/v1/ticker/24hr?symbol={sym}")
    price = float(ticker['lastPrice'])
    chg_24h = float(ticker['priceChangePercent'])

    # PnL
    if side == "LONG":
        pnl_pct = (price / entry - 1) * 100
    else:
        pnl_pct = (entry / price - 1) * 100 * (-1)
        # Short: profit when price drops
        pnl_pct = (entry - price) / entry * 100

    # klines for context
    klines = fetch_futures(f"{base_f}/fapi/v1/klines?symbol={sym}&interval=1d&limit=20")
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    # Quick RSI
    def calc_rsi(d, p=14):
        if len(d) < p+1: return 50
        g, l = [], []
        for i in range(1, len(d)):
            df = d[i]-d[i-1]; g.append(max(df, 0)); l.append(max(-df, 0))
        ag, al = sum(g[:p])/p, sum(l[:p])/p
        rv = [100-100/(1+ag/max(al,1e-10))]
        for i in range(p, len(g)):
            ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
            rv.append(100-100/(1+ag/max(al,1e-10)))
        return rv[-1]

    r = calc_rsi(closes)

    # ATR
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    atr14 = sum(trs[-14:])/14 if len(trs) >= 14 else 0

    # 7-day high/low
    high_7d = max(highs[-7:])
    low_7d = min(lows[-7:])

    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
    print(f"\n  {sym} — {side}")
    print(f"  Entry:   {fmt(entry)}  →  Now: {fmt(price)}  ({chg_24h:+.2f}% 24h)")
    print(f"  PnL:     {pnl_emoji} {pnl_pct:+.2f}%")
    print(f"  RSI(14): {r:.1f}  |  ATR: {fmt(atr14)}  |  7d range: {fmt(low_7d)} — {fmt(high_7d)}")

    # Recommendations based on side
    print(f"  Action:  ", end="")

    if side == "LONG":
        if pnl_pct > 15:
            print(f"TAKE PROFIT — +{pnl_pct:.1f}% gained. Consider closing 50%+")
        elif pnl_pct < -10:
            print(f"⚠️  STOP LOSS ZONE — down {pnl_pct:.1f}%. Tighten SL or close.")
        elif r > 75:
            print(f"OVERBOUGHT (RSI {r:.0f}) — partial TP, move SL to entry")
        elif r < 30:
            print(f"OVERSOLD (RSI {r:.0f}) — potential bounce, hold")
        else:
            print(f"HOLD — RSI neutral. Trail stop at {fmt(price - atr14 * 1.5)}")

    elif side == "SHORT":
        if pnl_pct > 15:
            print(f"TAKE PROFIT — +{pnl_pct:.1f}% gained. Consider closing 50%+")
        elif pnl_pct < -10:
            print(f"⚠️  STOP LOSS ZONE — price rallied {abs(pnl_pct):.1f}%. Tighten SL or close.")
        elif r < 25:
            print(f"OVERSOLD (RSI {r:.0f}) — bounce risk. Partial TP, tighten SL")
        elif r > 65:
            print(f"RALLYING (RSI {r:.0f}) — if breaks above {fmt(high_7d)}, consider closing")
        else:
            print(f"HOLD — RSI neutral. Trail stop at {fmt(price + atr14 * 1.5)}")

# Funding rates
print(f"\n{'─'*W}")
print("  FUNDING RATES (8h)")
for pos in state["positions"]:
    sym = pos["symbol"]
    try:
        fr = fetch_futures(f"{base_f}/fapi/v1/fundingRate?symbol={sym}&limit=3")
        rates = [float(f['fundingRate'])*100 for f in fr]
        avg = sum(rates)/len(rates)
        annual = avg * 3 * 365
        emoji = "📈" if avg > 0 else "📉"
        print(f"    {sym}: {avg:+.4f}% per 8h  ({annual:+.1f}% ann.) {emoji}")
    except:
        print(f"    {sym}: fetch error")

# Update last_check
state["last_check"] = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
with open("/Users/roman_devops/Downloads/binance/positions.json", "w") as f:
    json.dump(state, f, indent=2)

print(f"\n  Next check: tomorrow")
print()
