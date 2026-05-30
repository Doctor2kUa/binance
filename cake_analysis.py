#!/usr/bin/env python3
"""CAKE/USDT full technical analysis with 3-week forecast."""

import urllib.request
import json
import math

def fetch_klines(symbol, interval, limit):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def fetch_ticker(symbol):
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def sma(data, period):
    result = []
    for i in range(period - 1, len(data)):
        result.append(sum(data[i - period + 1:i + 1]) / period)
    return result

def ema(data, period):
    if len(data) < period: return []
    k = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result

def calc_rsi(data, period=14):
    if len(data) < period + 1: return []
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = [100 - (100 / (1 + avg_gain / max(avg_loss, 1e-10)))]
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi_values.append(100 - (100 / (1 + avg_gain / max(avg_loss, 1e-10))))
    return rsi_values

def bollinger(data, period=20, std_mult=2):
    upper, lower, middle = [], [], []
    for i in range(period - 1, len(data)):
        window = data[i - period + 1:i + 1]
        mean = sum(window) / period
        std = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
        middle.append(mean)
        upper.append(mean + std_mult * std)
        lower.append(mean - std_mult * std)
    return middle, upper, lower

# ── Fetch data ──
klines = fetch_klines("CAKEUSDT", "1d", 200)
ticker = fetch_ticker("CAKEUSDT")

closes = [float(k[4]) for k in klines]
highs = [float(k[2]) for k in klines]
lows = [float(k[3]) for k in klines]
volumes = [float(k[5]) for k in klines]

price = closes[-1]
chg = float(ticker['priceChangePercent'])

print("=" * 65)
print("  CAKE/USDT — TECHNICAL ANALYSIS & 3-WEEK FORECAST")
print("=" * 65)
print(f"\n  Price:       ${price:.4f}")
print(f"  24h:         {chg:+.2f}%  |  H: ${float(ticker['highPrice']):.4f}  L: ${float(ticker['lowPrice']):.4f}")
print(f"  Volume:      {float(ticker['volume']):,.0f} CAKE  (${float(ticker['quoteVolume']):,.0f})")

# ── Indicators ──
sma7 = sma(closes, 7)
sma20 = sma(closes, 20)
sma50 = sma(closes, 50)
sma100 = sma(closes, 100)
sma200 = sma(closes, 200) if len(closes) >= 200 else []

ema12 = ema(closes, 12)
ema26 = ema(closes, 26)
macd_line = [ema12[i] - ema26[i] for i in range(len(ema26))]
signal_line = ema(macd_line, 9)
macd_hist = [macd_line[i + len(macd_line) - len(signal_line)] - signal_line[i] for i in range(len(signal_line))]

rsi = calc_rsi(closes)
bb_mid, bb_upper, bb_lower = bollinger(closes)

trs = []
for i in range(1, len(closes)):
    tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    trs.append(tr)
atr14 = sum(trs[-14:]) / 14

support_50 = min(lows[-50:])
resistance_50 = max(highs[-50:])
support_100 = min(lows[-100:])
resistance_100 = max(highs[-100:])

def above_below(val, ref):
    diff = abs(val - ref)
    pct = diff / price * 100
    direction = "above" if val > ref else "below"
    return f"{direction} by ${diff:.4f} ({pct:.1f}%)"

print(f"\n{'─'*65}")
print("  MOVING AVERAGES")
print(f"{'─'*65}")
print(f"  SMA(7):    ${sma7[-1]:.4f}   {above_below(price, sma7[-1])}")
print(f"  SMA(20):   ${sma20[-1]:.4f}   {above_below(price, sma20[-1])}")
print(f"  SMA(50):   ${sma50[-1]:.4f}   {above_below(price, sma50[-1])}")
print(f"  SMA(100):  ${sma100[-1]:.4f}   {above_below(price, sma100[-1])}")
if sma200:
    print(f"  SMA(200):  ${sma200[-1]:.4f}   {above_below(price, sma200[-1])}")

print(f"\n{'─'*65}")
print("  MOMENTUM")
print(f"{'─'*65}")
print(f"  MACD:        {macd_line[-1]:+.4f}")
print(f"  MACD Signal: {signal_line[-1]:+.4f}")
print(f"  MACD Hist:   {macd_hist[-1]:+.4f}")
print(f"  RSI(14):     {rsi[-1]:.1f}")

bb_range = bb_upper[-1] - bb_lower[-1]
bb_pos = (price - bb_lower[-1]) / bb_range * 100
print(f"\n{'─'*65}")
print("  BOLLINGER BANDS (20, 2)")
print(f"{'─'*65}")
print(f"  Upper:    ${bb_upper[-1]:.4f}")
print(f"  Middle:   ${bb_mid[-1]:.4f}")
print(f"  Lower:    ${bb_lower[-1]:.4f}")
print(f"  Width:    ${bb_range:.4f} ({bb_range/bb_mid[-1]*100:.1f}%)")
print(f"  Position: {bb_pos:.1f}%")

print(f"\n{'─'*65}")
print("  VOLATILITY & LEVELS")
print(f"{'─'*65}")
print(f"  ATR(14):       ${atr14:.4f} ({atr14/price*100:.2f}%)")
print(f"  Support (50):     ${support_50:.4f} ({(support_50-price)/price*100:+.1f}%)")
print(f"  Resistance (50):  ${resistance_50:.4f} ({(resistance_50-price)/price*100:+.1f}%)")
print(f"  Support (100):    ${support_100:.4f} ({(support_100-price)/price*100:+.1f}%)")
print(f"  Resistance (100): ${resistance_100:.4f} ({(resistance_100-price)/price*100:+.1f}%)")

# ── SCORING ──
print(f"\n{'─'*65}")
print("  SIGNAL SCORING")
print(f"{'─'*65}")

score = 0.0
bullish_count = 0
bearish_count = 0

checks = [
    (price > sma7[-1], "CAKE > SMA7", 1),
    (price > sma20[-1], "CAKE > SMA20", 1),
    (price > sma50[-1], "CAKE > SMA50", 1),
    (price > sma100[-1], "CAKE > SMA100", 1),
    (sma20[-1] > sma50[-1], "SMA20 > SMA50", 1),
    (macd_line[-1] > signal_line[-1], "MACD > Signal", 1),
    (macd_hist[-1] > 0, "MACD histogram > 0", 0.5),
    (30 < rsi[-1] < 70 and rsi[-1] > 50, f"RSI={rsi[-1]:.0f} bullish zone", 0.5),
    (bb_pos < 80, f"BB position={bb_pos:.0f}% not overbought", 0.5),
]

if sma200:
    checks.append((price > sma200[-1], "CAKE > SMA200", 1))

for condition, label, points in checks:
    if condition:
        score += points
        bullish_count += 1
        print(f"    [+] {label}  (+{points})")
    else:
        score -= points
        bearish_count += 1
        print(f"    [-] {label}  (-{points})")

# RSI extremes
if rsi[-1] > 70:
    score -= 1; bearish_count += 1
    print(f"    [-] RSI={rsi[-1]:.0f} OVERBOUGHT  (-1)")
elif rsi[-1] < 30:
    score += 1; bullish_count += 1
    print(f"    [+] RSI={rsi[-1]:.0f} OVERSOLD  (+1)")

# Volume
vol_avg = sum(volumes[-14:]) / 14
vol_recent = sum(volumes[-3:]) / 3
if vol_recent > vol_avg * 1.5:
    score += 0.5; bullish_count += 1
    print(f"    [+] Volume surge ({vol_recent/vol_avg:.1f}x avg)  (+0.5)")
elif vol_recent < vol_avg * 0.5:
    score -= 0.5; bearish_count += 1
    print(f"    [-] Volume low ({vol_recent/vol_avg:.1f}x avg)  (-0.5)")

max_score = sum(c[2] for c in checks) + 1.5  # approximate max
normalized = max(-100, min(100, score / max_score * 100))

print(f"\n  Score: {score:+.1f}  |  Bullish: {bullish_count}  Bearish: {bearish_count}")
print(f"  Normalized: {normalized:+.0f}%")

# ── MOMENTUM ──
print(f"\n{'─'*65}")
print("  PRICE MOMENTUM")
print(f"{'─'*65}")
for label, days in [("1W", 7), ("2W", 14), ("3W", 21), ("4W", 28)]:
    if len(closes) > days:
        ret = (closes[-1] / closes[-days] - 1) * 100
        print(f"  {label}: {ret:+.1f}%")

avg_daily_range = sum(highs[-14-i] - lows[-14-i] for i in range(14)) / 14
print(f"\n  Avg Daily Range (14d): ${avg_daily_range:.4f} ({avg_daily_range/price*100:.1f}%)")

# ═══════════════════════════════════════════
# 3-WEEK FORECAST
# ═══════════════════════════════════════════
print(f"\n{'='*65}")
print("  3-WEEK FORECAST (21 trading days)")
print(f"{'='*65}")

# Scenario modeling
weekly_vol = atr14 * math.sqrt(7)  # weekly volatility estimate
three_week_vol = atr14 * math.sqrt(21)

# Trend bias from momentum
momentum_1w = (closes[-1] / closes[-7] - 1) * 100
momentum_2w = (closes[-1] / closes[-14] - 1) * 100 if len(closes) >= 14 else 0

# Linear regression on last 21 days for trend
n = 21
x_mean = (n - 1) / 2
y_mean = sum(closes[-n:]) / n
numerator = sum((i - x_mean) * (closes[-n+i] - y_mean) for i in range(n))
denominator = sum((i - x_mean) ** 2 for i in range(n))
slope = numerator / denominator if denominator != 0 else 0
trend_per_day = slope
trend_3week = slope * 21

print(f"\n  Current:        ${price:.4f}")
print(f"  Trend/day:      ${trend_per_day:+.4f} ({trend_per_day/price*100:+.2f}%)")
print(f"  3W trend proj:  ${price + trend_3week:.4f} ({(trend_3week)/price*100:+.1f}%)")
print(f"  Weekly vol:     ${weekly_vol:.4f} ({weekly_vol/price*100:.1f}%)")
print(f"  3-week vol:     ${three_week_vol:.4f} ({three_week_vol/price*100:.1f}%)")

# Scenarios
bull_target = price + trend_3week + three_week_vol * 0.5
base_target = price + trend_3week
bear_target = price + trend_3week - three_week_vol * 0.5

# Probability estimation based on score
if normalized > 50:
    p_bull = min(70, 50 + normalized * 0.3)
    p_base = 100 - p_bull - 15
    p_bear = 15
elif normalized > 20:
    p_bull = 40 + normalized * 0.3
    p_base = 100 - p_bull - 20
    p_bear = 20
elif normalized > -20:
    p_bull = 30 + normalized * 0.3
    p_base = 40
    p_bear = 100 - p_bull - p_base
elif normalized > -50:
    p_bear = 40 + abs(normalized) * 0.3
    p_base = 100 - p_bear - 20
    p_bull = 20
else:
    p_bear = min(70, 50 + abs(normalized) * 0.3)
    p_base = 100 - p_bear - 15
    p_bull = 15

# Normalize to 100
total = p_bull + p_base + p_bear
p_bull = p_bull / total * 100
p_base = p_base / total * 100
p_bear = p_bear / total * 100

print(f"\n  ┌─────────────────────────────────────────────────────┐")
print(f"  │  SCENARIO        │  TARGET        │  PROBABILITY   │")
print(f"  ├─────────────────────────────────────────────────────┤")
print(f"  │  BULL 🟢         │  ${bull_target:.4f}     │  {p_bull:.0f}%           │")
print(f"  │  BASE ⚪         │  ${base_target:.4f}     │  {p_base:.0f}%           │")
print(f"  │  BEAR 🔴         │  ${bear_target:.4f}     │  {p_bear:.0f}%           │")
print(f"  └─────────────────────────────────────────────────────┘")

# Key levels for the forecast period
print(f"\n  Key levels to watch:")
print(f"    Strong Resistance: ${resistance_50:.4f} → ${resistance_100:.4f}")
print(f"    Current:           ${price:.4f}")
print(f"    Strong Support:    ${support_50:.4f} → ${support_100:.4f}")

# Expected value
ev = (bull_target * p_bull + base_target * p_base + bear_target * p_bear) / 100
ev_return = (ev / price - 1) * 100
print(f"\n  Expected Value (21d): ${ev:.4f} ({ev_return:+.1f}%)")

# Risk/Reward
risk_long = (price - support_50) / price * 100
reward_long = (resistance_50 - price) / price * 100
rr_long = reward_long / risk_long if risk_long > 0 else 0

risk_short = (resistance_50 - price) / price * 100
reward_short = (price - support_50) / price * 100
rr_short = reward_short / risk_short if risk_short > 0 else 0

print(f"\n  Risk/Reward:")
print(f"    Long:  SL ${support_50:.4f} (-{risk_long:.1f}%) → TP ${resistance_50:.4f} (+{reward_long:.1f}%)  R:R = 1:{rr_long:.1f}")
print(f"    Short: SL ${resistance_50:.4f} (+{risk_short:.1f}%) → TP ${support_50:.4f} (-{reward_short:.1f}%)  R:R = 1:{rr_short:.1f}")

# ── VERDICT ──
print(f"\n{'='*65}")
print("  VERDICT")
print(f"{'='*65}")

if normalized > 40:
    verdict = "BULLISH 🟢🟢"
    confidence = "HIGH" if normalized > 60 else "MODERATE"
    summary = "Strong bullish signals. Uptrend likely to continue."
elif normalized > 15:
    verdict = "BULLISH 🟢"
    confidence = "MODERATE"
    summary = "Mildly bullish. Cautious longs with tight stops."
elif normalized > -15:
    verdict = "NEUTRAL ⚪"
    confidence = "LOW"
    summary = "No clear direction. Wait for breakout or breakdown."
elif normalized > -40:
    verdict = "BEARISH 🔴"
    confidence = "MODERATE"
    summary = "Mildly bearish. Consider shorts or stay flat."
else:
    verdict = "BEARISH 🔴🔴"
    confidence = "HIGH" if normalized < -60 else "MODERATE"
    summary = "Strong bearish signals. Downtrend likely to continue."

print(f"\n  Bias:       {verdict}")
print(f"  Confidence: {confidence}")
print(f"  Summary:    {summary}")
print(f"\n  3W Range Estimate: ${bear_target:.4f} — ${bull_target:.4f}")
print(f"  Most likely:       ${base_target:.4f} ({(base_target/price-1)*100:+.1f}%)")
print()
