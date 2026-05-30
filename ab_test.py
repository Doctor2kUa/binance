#!/usr/bin/env python3
"""A/B test: backtest signal quality on historical data for RAVE/USDT."""

import urllib.request, json, math
from datetime import datetime
from pathlib import Path

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

base = "https://fapi.binance.com"

# ── Fetch max available daily data for RAVEUSDT ──
# klines endpoint allows up to 1000 candles
klines = fetch(f"{base}/fapi/v1/klines?symbol=RAVEUSDT&interval=1d&limit=1000")

# Also 4h data for more granular signals
klines_4h = fetch(f"{base}/fapi/v1/klines?symbol=RAVEUSDT&interval=4h&limit=1000")

print(f"RAVE/USDT daily candles: {len(klines)}")
print(f"RAVE/USDT 4h candles: {len(klines_4h)}")

closes = [float(k[4]) for k in klines]
highs = [float(k[2]) for k in klines]
lows = [float(k[3]) for k in klines]
opens = [float(k[1]) for k in klines]
vols = [float(k[5]) for k in klines]
dates = [datetime.utcfromtimestamp(k[0]/1000).strftime('%Y-%m-%d') for k in klines]

print(f"Date range: {dates[0]} → {dates[-1]}")
print(f"Price range: ${min(lows):.4f} — ${max(highs):.4f}")
print(f"Current: ${closes[-1]:.4f}")

# ── Indicators ──
def sma(d, p):
    return [sum(d[i-p+1:i+1])/p for i in range(p-1, len(d))]

def ema(d, p):
    if len(d) < p: return []
    k = 2/(p+1); r = [sum(d[:p])/p]
    for i in range(p, len(d)):
        r.append(d[i]*k + r[-1]*(1-k))
    return r

def calc_rsi(d, p=14):
    if len(d) < p+1: return [50]*len(d)
    rv = [50]*p
    g, l = [], []
    for i in range(1, len(d)):
        df = d[i]-d[i-1]; g.append(max(df, 0)); l.append(max(-df, 0))
    ag, al = sum(g[:p])/p, sum(l[:p])/p
    rv.append(100-100/(1+ag/max(al,1e-10)))
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p; al = (al*(p-1)+l[i])/p
        rv.append(100-100/(1+ag/max(al,1e-10)))
    return rv

def bb(d, p=20, m=2):
    u, lo, mid = [], [], []
    for i in range(p-1, len(d)):
        w = d[i-p+1:i+1]; mn = sum(w)/p
        std = (sum((x-mn)**2 for x in w)/p)**0.5
        mid.append(mn); u.append(mn+m*std); lo.append(mn-m*std)
    return mid, u, lo

def atr_14(h, l, c):
    trs = []
    for i in range(1, len(c)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        trs.append(tr)
    if len(trs) >= 14:
        return sum(trs[-14:])/14
    return 0

# Compute all indicators
rsi_all = calc_rsi(closes)
sma7_all  = [0]*6  + sma(closes, 7)
sma20_all = [0]*19 + sma(closes, 20)
sma50_all = [0]*49 + sma(closes, 50)

ema12_all = ema(closes, 12)
ema26_all = ema(closes, 26)
macd_all  = [ema12_all[i]-ema26_all[i] for i in range(len(ema26_all))]
sig_all   = ema(macd_all, 9)
hist_all  = [macd_all[i+len(macd_all)-len(sig_all)]-sig_all[i] for i in range(len(sig_all))]
# pad hist to match closes length
hist_all  = [0]*(len(closes)-len(hist_all)) + hist_all

bbm_all, bbu_all, bbl_all = bb(closes)
bbm_all = [0]*19 + bbm_all
bbu_all = [0]*19 + bbu_all
bbl_all = [0]*19 + bbl_all

# ═══ A/B TEST: Score each day and measure forward returns ═══
# We simulate: if on day N we get a signal, what happens in +3d, +7d, +14d, +21d?

results = {
    "LONG":  {"score_ge3": [], "score_1_3": [], "score_neg": []},
    "SHORT": {"score_ge3": [], "score_1_3": [], "score_neg": []},
}

for i in range(50, len(closes)-21):  # need 50 days for indicators, 21 days forward
    px = closes[i]
    r  = rsi_all[i]
    s7 = sma7_all[i]; s20 = sma20_all[i]; s50 = sma50_all[i]
    macd_v = macd_all[i] if i < len(macd_all) else 0
    sig_v  = sig_all[i] if i < len(sig_all) else 0
    hist_v = hist_all[i]

    # ── Score (same logic as send_report.py) ──
    score = 0
    checks = []

    # Price vs MAs for LONG signal
    if px > s7:   score += 1; checks.append("above SMA7")
    else:         score -= 1
    if px > s20:  score += 1; checks.append("above SMA20")
    else:         score -= 2
    if px > s50:  score += 1; checks.append("above SMA50")
    else:         score -= 2
    if s7 > s20 > s50: score += 2
    elif s7 < s20 < s50: score -= 2

    # MACD
    if macd_v > sig_v:  score += 1
    else:               score -= 1
    if hist_v > 0:      score += 0.5
    else:               score -= 0.5

    # RSI
    if 40 < r < 70:
        if r > 50: score += 0.5
        else:      score -= 0.5
    elif r >= 75:  score -= 2
    elif r >= 70:  score -= 1
    elif r <= 30:  score += 2

    # Determine signal direction & bucket
    if score >= 3:
        signal = "LONG"; bucket = "score_ge3"
    elif score >= 1:
        signal = "LONG"; bucket = "score_1_3"
    elif score <= -2:
        signal = "SHORT"; bucket = "score_ge3"
    elif score <= -1:
        signal = "SHORT"; bucket = "score_1_3"
    else:
        continue  # skip neutral

    # ── Forward returns ──
    entry = px
    for horizon, label in [(3, "3d"), (7, "7d"), (14, "14d"), (21, "21d")]:
        if i + horizon < len(closes):
            fwd = closes[i + horizon]
            if signal == "LONG":
                fwd_ret = (fwd / entry - 1) * 100
            else:
                fwd_ret = (entry - fwd) / entry * 100

            # Max adverse excursion (drawdown from entry)
            if signal == "LONG":
                prices_ahead = closes[i:i+horizon+1]
                min_price = min(prices_ahead)
                max_adverse = (min_price / entry - 1) * 100
                max_favorable = (max(prices_ahead) / entry - 1) * 100
            else:
                prices_ahead = closes[i:i+horizon+1]
                max_price = max(prices_ahead)
                max_adverse = (entry - max_price) / entry * 100
                max_favorable = (entry - min(prices_ahead)) / entry * 100

            results[signal][bucket].append({
                "date": dates[i],
                "entry": entry,
                f"fwd_ret_{label}": fwd_ret,
                f"max_adverse_{label}": max_adverse,
                f"max_favorable_{label}": max_favorable,
                "score": score,
                "rsi": r,
            })

# ═══ STATS ═══
W = 72
print("\n" + "="*W)
print("  A/B TEST RESULTS — RAVE/USDT")
print("="*W)

for signal in ["LONG", "SHORT"]:
    for bucket in ["score_ge3", "score_1_3", "score_neg"]:
        data = results[signal][bucket]
        if not data:
            continue

        label_map = {"score_ge3": "STRONG (score>=3)", "score_1_3": "WEAK (score 1-3)", "score_neg": "NEGATIVE"}
        print(f"\n{'─'*W}")
        print(f"  {signal} — {label_map[bucket]}  ({len(data)} signals)")
        print(f"{'─'*W}")

        for horizon in ["3d", "7d", "14d", "21d"]:
            rets    = [d[f"fwd_ret_{horizon}"]    for d in data if f"fwd_ret_{horizon}" in d]
            adverse = [d[f"max_adverse_{horizon}"] for d in data if f"max_adverse_{horizon}" in d]
            favor   = [d[f"max_favorable_{horizon}"] for d in data if f"max_favorable_{horizon}" in d]

            if not rets:
                continue

            avg_ret     = sum(rets)/len(rets)
            median_ret  = sorted(rets)[len(rets)//2]
            win_rate    = sum(1 for r in rets if r > 0) / len(rets) * 100
            avg_adverse = sum(adverse)/len(adverse)
            avg_favor   = sum(favor)/len(favor)
            best        = max(rets)
            worst       = min(rets)

            print(f"\n  {horizon} forward ({len(rets)} samples):")
            print(f"    Avg return:    {avg_ret:+.2f}%  (median: {median_ret:+.2f}%)")
            print(f"    Win rate:      {win_rate:.0f}%")
            print(f"    Best:          {best:+.2f}%  |  Worst: {worst:+.2f}%")
            print(f"    Avg adverse:   {avg_adverse:.2f}%  |  Avg favorable: {avg_favor:+.2f}%")

# ═══ CURRENT SIGNAL QUALITY ═══
print(f"\n{'='*W}")
print("  CURRENT POSITION QUALITY CHECK")
print(f"{'='*W}")

# What does history say about entering RAVE SHORT at current price level?
current_score = 0
i = len(closes) - 1
px = closes[i]; r = rsi_all[i]; s7 = sma7_all[i]; s20 = sma20_all[i]; s50 = sma50_all[i]
macd_v = macd_all[i] if i < len(macd_all) else 0
sig_v  = sig_all[i] if i < len(sig_all) else 0
hist_v = hist_all[i]

print(f"\n  Price: ${px:.4f}")
print(f"  RSI: {r:.1f} | SMA7: {s7:.4f} | SMA20: {s20:.4f} | SMA50: {s50:.4f}")
print(f"  MACD: {macd_v:+.4f} | Signal: {sig_v:+.4f} | Hist: {hist_v:+.4f}")

# Find similar historical setups (score <= -2 at similar price zone)
similar = []
for entry in results["SHORT"]["score_ge3"]:
    similarity = abs(entry["entry"] - px) / px  # within 20% price zone
    if similarity < 0.2:
        similar.append(entry)

if similar:
    print(f"\n  Found {len(similar)} similar STRONG SHORT setups (±20% price zone):")
    for d in similar[-5:]:  # last 5
        print(f"    {d['date']}: entry={d['entry']:.4f}, score={d['score']}, RSI={d['rsi']:.0f}")
        for h in ["3d","7d","14d","21d"]:
            key = f"fwd_ret_{h}"
            if key in d:
                wr = "✓" if d[key] > 0 else "✗"
                print(f"      {h}: {d[key]:+.1f}% {wr}  (max adverse: {d[f'max_adverse_{h}']:.1f}%)")
else:
    print(f"\n  No similar historical setups found in this price zone.")

# ═══ RECOMMENDATION ═══
print(f"\n{'='*W}")
print("  RECOMMENDATION BASED ON BACKTEST")
print(f"{'='*W}")

short_strong = results["SHORT"]["score_ge3"]
if short_strong:
    wins_7d  = sum(1 for d in short_strong if d.get("fwd_ret_7d", 0) > 0)
    win_7d   = wins_7d / len(short_strong) * 100
    avg_7d   = sum(d.get("fwd_ret_7d", 0) for d in short_strong) / len(short_strong)
    avg_adv  = sum(d.get("max_adverse_7d", 0) for d in short_strong) / len(short_strong)

    print(f"\n  STRONG SHORT signals historical win rate (7d): {win_7d:.0f}%")
    print(f"  Avg 7d return: {avg_7d:+.2f}%")
    print(f"  Avg max adverse: {avg_adv:.2f}%")

    if win_7d > 60 and avg_7d > 3:
        print(f"\n  ✅ KEEP SHORT — historical win rate {win_7d:.0f}% with avg {avg_7d:+.1f}% gain")
    elif win_7d > 50:
        print(f"\n  ⚠️ HOLD SHORT — historical win rate {win_7d:.0f}%, but not strong")
    else:
        print(f"\n  🔴 CLOSE SHORT — historical win rate only {win_7d:.0f}%")

print()
