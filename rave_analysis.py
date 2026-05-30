#!/usr/bin/env python3
"""RAVE/USDT Futures — technical analysis & 3-week forecast."""

import urllib.request, json, math
from datetime import datetime

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

base = "https://fapi.binance.com"

# ── Data ──
ticker = fetch(f"{base}/fapi/v1/ticker/24hr?symbol=RAVEUSDT")
klines = fetch(f"{base}/fapi/v1/klines?symbol=RAVEUSDT&interval=1d&limit=200")
funding = fetch(f"{base}/fapi/v1/fundingRate?symbol=RAVEUSDT&limit=10")

closes = [float(k[4]) for k in klines]
highs = [float(k[2]) for k in klines]
lows = [float(k[3]) for k in klines]
vols = [float(k[5]) for k in klines]
opens = [float(k[1]) for k in klines]

price = closes[-1]
chg = float(ticker['priceChangePercent'])
n = len(closes)

# ── Indicators ──
def sma(d, p):
    return [sum(d[i-p+1:i+1])/p for i in range(p-1, len(d))]

def ema(d, p):
    if len(d) < p: return []
    k = 2/(p+1)
    r = [sum(d[:p])/p]
    for i in range(p, len(d)):
        r.append(d[i]*k + r[-1]*(1-k))
    return r

def rsi(d, p=14):
    if len(d) < p+1: return []
    g, l = [], []
    for i in range(1, len(d)):
        diff = d[i]-d[i-1]
        g.append(max(diff, 0))
        l.append(max(-diff, 0))
    ag, al = sum(g[:p])/p, sum(l[:p])/p
    rv = [100-100/(1+ag/max(al,1e-10))]
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p
        al = (al*(p-1)+l[i])/p
        rv.append(100-100/(1+ag/max(al,1e-10)))
    return rv

def bb(d, p=20, m=2):
    u, lo, mid = [], [], []
    for i in range(p-1, len(d)):
        w = d[i-p+1:i+1]
        mn = sum(w)/p
        std = (sum((x-mn)**2 for x in w)/p)**0.5
        mid.append(mn)
        u.append(mn+m*std)
        lo.append(mn-m*std)
    return mid, u, lo

sma7 = sma(closes, 7)
sma20 = sma(closes, 20)
sma50 = sma(closes, 50)
sma100 = sma(closes, 100) if n >= 100 else []
sma200 = sma(closes, 200) if n >= 200 else []

ema12 = ema(closes, 12)
ema26 = ema(closes, 26)
macd = [ema12[i]-ema26[i] for i in range(len(ema26))]
sig = ema(macd, 9)
hist = [macd[i+len(macd)-len(sig)]-sig[i] for i in range(len(sig))]

rsi_val = rsi(closes)
bbm, bbu, bbl = bb(closes)

trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, n)]
atr14 = sum(trs[-14:])/14

sup50 = min(lows[-50:])
res50 = max(highs[-50:])
sup100 = min(lows[-100:]) if n >= 100 else min(lows)
res100 = max(highs[-100:]) if n >= 100 else max(highs)

def fmt(v):
    return f"${v:.6f}"

def ab(val, ref):
    d = abs(val-ref)
    pct = d/price*100
    return f"{'above' if val>ref else 'below'} by {fmt(d)} ({pct:.1f}%)"

# ═══════════════════════════════════════════
# REPORT
# ═══════════════════════════════════════════
W = 65
eq = lambda: print("="*W)
dash = lambda: print("─"*W)

eq()
print("  RAVE/USDT FUTURES — TECHNICAL ANALYSIS & 3-WEEK FORECAST")
eq()

print(f"\n  Price:       {fmt(price)}")
print(f"  24h:         {chg:+.2f}%  |  H: {fmt(float(ticker['highPrice']))}  L: {fmt(float(ticker['lowPrice']))}")
print(f"  Volume:      {float(ticker['volume']):,.0f} RAVE  (${float(ticker['quoteVolume']):,.0f})")
print(f"  Candles:     {n}")
print(f"  All-time:    {fmt(max(highs))} / {fmt(min(lows))}")

# Funding
avg_fund = sum(float(f['fundingRate']) for f in funding[-8:]) / min(8, len(funding)) * 100 * 365
print(f"  Fund (ann):  {avg_fund:+.2f}%")

print(f"\n{'─'*W}")
print("  MOVING AVERAGES")
dash()
print(f"  SMA(7):    {fmt(sma7[-1]):>14s}   {ab(price, sma7[-1])}")
print(f"  SMA(20):   {fmt(sma20[-1]):>14s}   {ab(price, sma20[-1])}")
print(f"  SMA(50):   {fmt(sma50[-1]):>14s}   {ab(price, sma50[-1])}")
if sma100:
    print(f"  SMA(100):  {fmt(sma100[-1]):>14s}   {ab(price, sma100[-1])}")
if sma200:
    print(f"  SMA(200):  {fmt(sma200[-1]):>14s}   {ab(price, sma200[-1])}")
print(f"  EMA(12):   {fmt(ema12[-1]):>14s}")
print(f"  EMA(26):   {fmt(ema26[-1]):>14s}")

print(f"\n{'─'*W}")
print("  MOMENTUM")
dash()
print(f"  MACD:        {macd[-1]:+.6f}")
print(f"  MACD Signal: {sig[-1]:+.6f}")
print(f"  MACD Hist:   {hist[-1]:+.6f}")
r = rsi_val[-1]
zone = "OVERBOUGHT" if r>70 else "OVERSOLD" if r<30 else "bullish" if r>55 else "bearish" if r<45 else "neutral"
print(f"  RSI(14):     {r:.1f}  ({zone})")

bbr = bbu[-1]-bbl[-1]
bbp = (price-bbl[-1])/bbr*100 if bbr>0 else 50
print(f"\n{'─'*W}")
print("  BOLLINGER BANDS (20, 2)")
dash()
print(f"  Upper:    {fmt(bbu[-1]):>14s}")
print(f"  Middle:   {fmt(bbm[-1]):>14s}")
print(f"  Lower:    {fmt(bbl[-1]):>14s}")
print(f"  Width:    {fmt(bbr):>14s}  ({bbr/bbm[-1]*100:.1f}%)")
print(f"  Position: {bbp:.1f}%")
if bbp > 80: print(f"  Signal:   near UPPER — potential pullback")
elif bbp < 20: print(f"  Signal:   near LOWER — potential bounce")
else: print(f"  Signal:   middle zone")

print(f"\n{'─'*W}")
print("  VOLATILITY & LEVELS")
dash()
print(f"  ATR(14):       {fmt(atr14):>14s}  ({atr14/price*100:.2f}%)")
print(f"  Support (50):     {fmt(sup50):>14s}  ({(sup50-price)/price*100:+.1f}%)")
print(f"  Resistance (50):  {fmt(res50):>14s}  ({(res50-price)/price*100:+.1f}%)")
print(f"  Support (100):    {fmt(sup100):>14s}  ({(sup100-price)/price*100:+.1f}%)")
print(f"  Resistance (100): {fmt(res100):>14s}  ({(res100-price)/price*100:+.1f}%)")

# ── LAST 5 CANDLES ──
print(f"\n{'─'*W}")
print("  LAST 5 CANDLES")
dash()
for i in range(-5, 0):
    o, h, l, c = float(klines[i][1]), float(klines[i][2]), float(klines[i][3]), float(klines[i][4])
    body = c-o
    dire = "GREEN 🟢" if body > 0 else "RED 🔴"
    bpct = abs(body)/o*100
    print(f"  {dire}  O={fmt(o)} H={fmt(h)} L={fmt(l)} C={fmt(c)}  body={bpct:.1f}%")

# ── SCORING ──
print(f"\n{'─'*W}")
print("  SIGNAL SCORING")
dash()

score = 0.0; bull_c = 0; bear_c = 0

checks = [
    (price > sma7[-1], "RAVE > SMA7", 1),
    (price > sma20[-1], "RAVE > SMA20", 1),
    (price > sma50[-1], "RAVE > SMA50", 1),
    (sma20[-1] > sma50[-1], "SMA20 > SMA50", 1),
    (macd[-1] > sig[-1], "MACD > Signal", 1),
    (hist[-1] > 0, "MACD hist > 0", 0.5),
    (r > 50, f"RSI={r:.0f} bullish", 0.5),
    (bbp < 80, f"BB={bbp:.0f}% room", 0.5),
]
if sma100: checks.append((price > sma100[-1], "RAVE > SMA100", 1))
if sma200: checks.append((price > sma200[-1], "RAVE > SMA200", 1))

for cond, lbl, pts in checks:
    if cond:
        score += pts; bull_c += 1
        print(f"    [+] {lbl}  (+{pts})")
    else:
        score -= pts; bear_c += 1
        print(f"    [-] {lbl}  (-{pts})")

if r > 70: score -= 1.5; bear_c += 1; print(f"    [-] RSI={r:.0f} OVERBOUGHT  (-1.5)")
elif r < 30: score += 1.5; bull_c += 1; print(f"    [+] RSI={r:.0f} OVERSOLD  (+1.5)")

bb_pct = bbr/bbm[-1]*100
if bb_pct < 10: print(f"    [!] BB squeeze ({bb_pct:.1f}%) — breakout incoming")

va = sum(vols[-14:])/14
vr = sum(vols[-3:])/3
if va > 0:
    if vr/va > 2: score += 1; bull_c += 1; print(f"    [+] Volume SURGE ({vr/va:.1f}x)  (+1)")
    elif vr/va > 1.5: score += 0.5; bull_c += 1; print(f"    [+] Volume high ({vr/va:.1f}x)  (+0.5)")
    elif vr/va < 0.3: score -= 1; bear_c += 1; print(f"    [-] Volume VERY LOW ({vr/va:.1f}x)  (-1)")
    elif vr/va < 0.5: score -= 0.5; bear_c += 1; print(f"    [-] Volume low ({vr/va:.1f}x)  (-0.5)")

mx_score = sum(c[2] for c in checks) + 2.5
norm = max(-100, min(100, score/max(mx_score,1)*100))
print(f"\n  Score: {score:+.1f}  |  Bullish: {bull_c}  Bearish: {bear_c}")
print(f"  Normalized: {norm:+.0f}%")

# ── MOMENTUM ──
print(f"\n{'─'*W}")
print("  PRICE MOMENTUM")
dash()
for lbl, d in [("1W",7), ("2W",14), ("3W", 21), ("1M", 28)]:
    if n > d:
        ret = (closes[-1]/closes[-d]-1)*100
        print(f"  {lbl}: {ret:+.1f}%")
adr = sum(highs[-14-i]-lows[-14-i] for i in range(14))/14
print(f"\n  Avg Daily Range (14d): {fmt(adr)} ({adr/price*100:.1f}%)")

# ═══════════════════════════════════════════
# 3-WEEK FORECAST
# ═══════════════════════════════════════════
eq()
print("  3-WEEK FORECAST (21 trading days)")
eq()

# Trend
tn = min(21, n)
xm = (tn-1)/2
ym = sum(closes[-tn:])/tn
num = sum((i-xm)*(closes[-tn+i]-ym) for i in range(tn))
den = sum((i-xm)**2 for i in range(tn))
slope = num/den if den != 0 else 0
td = slope
t3w = slope*21

wv = atr14*math.sqrt(7)
w3v = atr14*math.sqrt(21)

print(f"\n  Current:        {fmt(price)}")
print(f"  Trend/day:      {fmt(abs(td))} ({td/price*100:+.2f}%)")
print(f"  3W trend proj:  {fmt(price+t3w)} ({t3w/price*100:+.1f}%)")
print(f"  Weekly vol:     {fmt(wv)} ({wv/price*100:.1f}%)")
print(f"  3-week vol:     {fmt(w3v)} ({w3v/price*100:.1f}%)")

# Fibonacci
sh = max(highs[-50:])
sl = min(lows[-50:])
fr = sh-sl
fibs = {"0%": sh, "23.6%": sh-fr*0.236, "38.2%": sh-fr*0.382,
        "50%": sh-fr*0.5, "61.8%": sh-fr*0.618, "78.6%": sh-fr*0.786, "100%": sl}
print(f"\n  Fibonacci (50d swing {fmt(sl)} — {fmt(sh)}):")
for lbl, lvl in fibs.items():
    near = " <-- PRICE" if abs(price-lvl)/price < 0.02 else ""
    print(f"    {lbl:>6s}  {fmt(lvl)}{near}")

# Scenarios
bull_t = price + t3w + w3v*0.5
base_t = price + t3w
bear_t = price - w3v*0.5

if norm > 50:
    pb = min(65, 40+norm*0.4); pa = max(15, 25-norm*0.15)
    pbb = 100-pb-pa
elif norm > 20:
    pb = 35+norm*0.3; pbb = max(20, 30-norm*0.2)
    pa = 100-pb-pbb
elif norm > -20:
    pb = 25+norm*0.3; pbb = 25-norm*0.3; pa = 100-pb-pbb
elif norm > -50:
    pbb = 35+abs(norm)*0.3; pb = max(20, 30-abs(norm)*0.2)
    pa = 100-pb-pbb
else:
    pbb = min(65, 40+abs(norm)*0.4); pb = max(15, 25-abs(norm)*0.15)
    pa = 100-pb-pbb

br = (bull_t/price-1)*100
bar = (base_t/price-1)*100
ber = (bear_t/price-1)*100

print(f"\n  ┌───────────────────────────────────────────────────────┐")
print(f"  │  SCENARIO       │  TARGET        │  RETURN │  PROB   │")
print(f"  ├───────────────────────────────────────────────────────┤")
print(f"  │  BULL 🟢        │  {fmt(bull_t):>12s}  │  {br:+5.1f}% │  {pb:>3.0f}%   │")
print(f"  │  BASE ⚪        │  {fmt(base_t):>12s}  │  {bar:+5.1f}% │  {pa:>3.0f}%   │")
print(f"  │  BEAR 🔴        │  {fmt(bear_t):>12s}  │  {ber:+5.1f}% │  {pbb:>3.0f}%   │")
print(f"  └───────────────────────────────────────────────────────┘")

ev = (bull_t*pb + base_t*pa + bear_t*pbb)/100
evr = (ev/price-1)*100
print(f"\n  Expected Value (21d): {fmt(ev)} ({evr:+.1f}%)")

print(f"\n  Weekly targets:")
for w in [1, 2, 3]:
    wt = price + slope*7*w
    print(f"    Week {w}: ~{fmt(wt)} ({(wt/price-1)*100:+.1f}%)")

# R:R
sll = max(sup50, bbl[-1])
tll = min(res50, bbu[-1])
rgl = (price-sll)/price*100
rtl = (tll-price)/price*100
rrl = rtl/rgl if rgl > 0 else 0

sls = min(res50, bbu[-1])
tls = max(sup50, bbl[-1])
rgs = (sls-price)/price*100
rts = (price-tls)/price*100
rrs = rts/rgs if rgs > 0 else 0

print(f"\n  Risk/Reward:")
print(f"    Long:  SL {fmt(sll)} (-{rgl:.1f}%) → TP {fmt(tll)} (+{rtl:.1f}%)  R:R = 1:{rrl:.1f}")
print(f"    Short: SL {fmt(sls)} (+{rgs:.1f}%) → TP {fmt(tls)} (-{rts:.1f}%)  R:R = 1:{rrs:.1f}")

# VERDICT
eq()
print("  VERDICT")
eq()

if norm > 40:
    v = "BULLISH 🟢🟢"; c = "HIGH" if norm > 60 else "MODERATE"
    s = "Strong bullish signals."
elif norm > 15:
    v = "BULLISH 🟢"; c = "MODERATE"; s = "Mildly bullish. Cautious longs."
elif norm > -15:
    v = "NEUTRAL ⚪"; c = "LOW"; s = "No clear direction. Wait."
elif norm > -40:
    v = "BEARISH 🔴"; c = "MODERATE"; s = "Mildly bearish. Stay flat or short."
else:
    v = "BEARISH 🔴🔴"; c = "HIGH" if norm < -60 else "MODERATE"
    s = "Strong bearish signals."

# Liquidity check
dv = float(ticker['quoteVolume'])
if dv < 2000000:
    lw = "⚠️  LOW LIQUIDITY — significant slippage on market orders!"
elif dv < 10000000:
    lw = "⚠️  Moderate liquidity — prefer limit orders."
else:
    lw = None

print(f"\n  Bias:       {v}")
print(f"  Confidence: {c}")
print(f"  Summary:    {s}")
if lw: print(f"\n  {lw}")
print(f"\n  3W Range:     {fmt(bear_t)} — {fmt(bull_t)}")
print(f"  Most likely: {fmt(base_t)} ({bar:+.1f}%)")
print()
