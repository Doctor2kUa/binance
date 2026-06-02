#!/usr/bin/env python3
"""
engine_v3.py — Multi-Timeframe Analysis Engine v3

Улучшения:
1. Адаптивные пороги индикаторов под каждый таймфрейм
2. Адаптивные пороги под тип актива (мемкоины vs альты)
3. Динамические веса (确认 vs фильтр)
4. Подтверждение 1d тренда вместо полного скоринга
"""

import json, math, urllib.request, urllib.error, time

BASE_URLS = ["https://fapi.binance.com", "https://api.binance.com"]

# ─── Helpers ──────────────────────────────────────────────────────

def api_fetch(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 418) and attempt < max_retries - 1:
                time.sleep(5)
            else:
                return None
        except:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return None
    return None

def get_klines(symbol, interval, limit):
    for base in BASE_URLS:
        for path in ["/fapi/v1/klines", "/api/v3/klines"]:
            url = f"{base}{path}?symbol={symbol}&interval={interval}&limit={limit}"
            data = api_fetch(url)
            if data and isinstance(data, list) and len(data) > 0:
                return data
    return None

def get_ticker(symbol):
    for base in BASE_URLS:
        for path in ["/fapi/v1/ticker/24hr", "/api/v3/ticker/24hr"]:
            tick = api_fetch(f"{base}{path}?symbol={symbol}")
            if tick:
                return tick
    return None

# ─── Indicators ───────────────────────────────────────────────────

def ema(data, period):
    k = 2 / (period + 1); r = [data[0]]
    for i in range(1, len(data)): r.append(data[i] * k + r[-1] * (1 - k))
    return r

def sma(data, period):
    r = []
    for i in range(len(data)):
        r.append(None if i < period - 1 else sum(data[i-period+1:i+1]) / period)
    return r

def calc_rsi(c, p=14):
    if len(c) < p + 1: return None
    g, l = [], []
    for i in range(1, len(c)):
        d = c[i] - c[i-1]; g.append(max(d, 0)); l.append(max(-d, 0))
    ag, al = sum(g[-p:]) / p, sum(l[-p:]) / p
    return 100 if al == 0 else 100 - (100 / (1 + ag / al))

def calc_bb(c, period=20, sd=2):
    if len(c) < period: return None, None, None, None
    w = c[-period:]; mid = sum(w) / period
    std = math.sqrt(sum((x-mid)**2 for x in w) / period)
    lo, hi = mid - sd * std, mid + sd * std
    return lo, mid, hi, (c[-1] - lo) / (hi - lo) * 100 if hi != lo else 50

def calc_macd(c):
    if len(c) < 26: return None, None, None
    ml = [ema(c,12)[i] - ema(c,26)[i] for i in range(len(c))]
    return ml[-1], ema(ml, 9)[-1], ml[-1] - ema(ml, 9)[-1]

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    return sum(trs[-period:]) / period

# ─── Adaptive Thresholds ──────────────────────────────────────────

MEME_KEYWORDS = ["DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "TRUMP", "TURBO", "BOME"]

def is_memecoin(symbol):
    s = symbol.upper()
    return any(kw in s for kw in MEME_KEYWORDS)

def get_thresholds(tf_name, symbol):
    """Adaptive thresholds per timeframe and asset type."""
    memecoin = is_memecoin(symbol)
    
    # Base thresholds (1h, normal alt)
    rsi_ob, rsi_os = 70, 30      # overbought, oversold
    bb_ob, bb_os = 90, 10        # BB position for overbought/oversold
    
    if memecoin:
        rsi_ob, rsi_os = 78, 25   # Memecoins: wider range
        bb_ob, bb_os = 95, 5
    
    if tf_name == "1d":
        rsi_ob, rsi_os = rsi_ob + 5, rsi_os - 5
        bb_ob, bb_os = bb_ob + 3, bb_os - 3
    elif tf_name == "4h":
        rsi_ob, rsi_os = rsi_ob + 2, rsi_os - 2
        bb_ob, bb_os = bb_ob + 1, bb_os - 1
    elif tf_name == "15m":
        rsi_ob, rsi_os = rsi_ob - 3, rsi_os + 3
        bb_ob, bb_os = bb_ob - 2, bb_os + 2
    
    return rsi_ob, rsi_os, bb_ob, bb_os

# ─── Trend Filter (1d) ────────────────────────────────────────────

def get_1d_trend_direction(klines_1d):
    """
    Returns True if 1d trend aligns with trade direction.
    This is a FILTER, not a score.
    """
    if not klines_1d or len(klines_1d) < 30:
        return True  # No data = no filter
    
    closes = [float(k[4]) for k in klines_1d]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-30:]) / 30 if len(closes) >= 30 else sma20
    price = closes[-1]
    
    # 1d trend up: price > sma20 > sma50
    trend_up = price > sma20 and sma20 > sma50
    trend_down = price < sma20 and sma20 < sma50
    
    return trend_up, trend_down

# ─── Adaptive Scoring per Timeframe ───────────────────────────────

def score_tf(price, rsi, bb_p, bb_m, m, sig, hist, s20, s200, direction, tf_name, symbol):
    """Score single timeframe with adaptive thresholds."""
    rsi_ob, rsi_os, bb_ob, bb_os = get_thresholds(tf_name, symbol)
    
    sc, reasons, risks = 0, [], []
    
    if direction == "LONG":
        # RSI
        if rsi is not None:
            if rsi <= rsi_os: sc += 25; reasons.append(f"[{tf_name}] RSI {rsi:.0f} OS")
            elif rsi < rsi_os + 10: sc += 15
            elif rsi < 50: sc += 5
            elif rsi >= rsi_ob: risks.append(f"[{tf_name}] RSI {rsi:.0f} OB")
        
        # BB
        if bb_p is not None:
            if bb_p <= bb_os: sc += 25; reasons.append(f"[{tf_name}] BB {bb_p:.0f}% bot")
            elif bb_p <= bb_os + 15: sc += 20
            elif bb_p <= bb_os + 25: sc += 15
            elif bb_p <= 45: sc += 10
        
        # MACD
        if m is not None:
            if m > sig and hist > 0: sc += 20; reasons.append(f"[{tf_name}] MACD+rising")
            elif m > sig: sc += 10
            elif m < sig and hist < 0: sc -= 5; risks.append(f"[{tf_name}] MACD-")
            else: sc += 5
        
        # SMA trend
        if s20 and s200:
            if price < s20 < s200: sc += 20; reasons.append(f"[{tf_name}] Deep value")
            elif price < s20: sc += 10
            elif s20 > s200 and price > s20: sc += 5
            elif s20 < s200 and price < s20: sc += 5
            elif s20 > s200 and price < s200: sc += 5
    else:
        if rsi is not None:
            if rsi >= rsi_ob: sc += 25; reasons.append(f"[{tf_name}] RSI {rsi:.0f} OB")
            elif rsi > rsi_ob - 10: sc += 15
            elif rsi > 50: sc += 5
            elif rsi <= rsi_os: risks.append(f"[{tf_name}] RSI {rsi:.0f} OS")
        
        if bb_p is not None:
            if bb_p >= bb_ob: sc += 25; reasons.append(f"[{tf_name}] BB {bb_p:.0f}% top")
            elif bb_p >= bb_ob - 15: sc += 20
            elif bb_p >= bb_ob - 25: sc += 15
            elif bb_p >= 55: sc += 10
        
        if m is not None:
            if m < sig and hist < 0: sc += 20; reasons.append(f"[{tf_name}] MACD-falling")
            elif m < sig: sc += 10
            elif m > sig and hist > 0: sc -= 5; risks.append(f"[{tf_name}] MACD+")
            else: sc += 5
        
        if s20 and s200:
            if price > s20 > s200: sc += 20; reasons.append(f"[{tf_name}] Overextended")
            elif price > s20: sc += 10
            elif s20 < s200 and price < s20: sc += 5
            elif s20 > s200 and price < s200: sc += 5
    
    return sc, reasons, risks

# ─── Main Analysis ────────────────────────────────────────────────

def analyze(symbol, direction):
    result = {
        "symbol": symbol, "direction": direction,
        "tf_scores": {}, "reasons": [], "risks": [],
        "momentum_penalty": False,
        "mc_penalty": False,
    }
    
    # Fetch timeframes
    kl_1d = get_klines(symbol, "1d", 60)
    kl_4h = get_klines(symbol, "4h", 200)
    kl_1h = get_klines(symbol, "1h", 200)
    tick = get_ticker(symbol)
    
    price = float(tick["lastPrice"]) if tick else float(kl_1h[-1][4])
    vol = float(tick.get("quoteVolume", 0)) if tick else 0
    
    # 7d momentum check
    if kl_1d and len(kl_1d) >= 7:
        c7 = float(kl_1d[-7][4])
        ch7d = ((price - c7) / c7) * 100 if c7 > 0 else 0
        result["ch7d"] = ch7d
        if abs(ch7d) > 30:
            result["momentum_penalty"] = True
    
    # ─── 1d: Trend Filter (not score) ────────────────────────────
    trend_aligns = True
    if kl_1d and len(kl_1d) >= 30:
        closes_1d = [float(k[4]) for k in kl_1d]
        s20_1d = sum(closes_1d[-20:]) / 20
        s50_1d = sum(closes_1d[-30:]) / 30 if len(closes_1d) >= 30 else s20_1d
        
        trend_up = price > s20_1d and s20_1d > s50_1d
        trend_down = price < s20_1d and s20_1d < s50_1d
        
        if direction == "LONG" and trend_down:
            trend_aligns = False
            result["risks"].append("[1d] AGAINST trend (downtrend)")
        elif direction == "SHORT" and trend_up:
            trend_aligns = False
            result["risks"].append("[1d] AGAINST trend (uptrend)")
        elif direction == "LONG" and trend_up:
            result["reasons"].append("[1d] With trend (uptrend)")
        elif direction == "SHORT" and trend_down:
            result["reasons"].append("[1d] With trend (downtrend)")
        
        result["tf_scores"]["1d"] = {"aligns": trend_aligns, "trend": "up" if trend_up else "down" if trend_down else "flat"}
    
    # ─── Score each TF ───────────────────────────────────────────
    tf_data = {"1d": kl_1d, "4h": kl_4h, "1h": kl_1h}
    weights_tf = {"1d": 0.15, "4h": 0.35, "1h": 0.50}  # 1d = filter, 1h = main
    
    weighted_score = 0
    total_weight = 0
    
    for tf_name, kl in tf_data.items():
        if not kl or len(kl) < 50:
            continue
        
        closes = [float(k[4]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        p = closes[-1]
        
        rsi = calc_rsi(closes)
        bb_l, bb_m, bb_u, bb_p = calc_bb(closes)
        m, sig, hist = calc_macd(closes)
        
        s20_p = {"1d": 10, "4h": 20, "1h": 20}.get(tf_name, 20)
        s200_p = {"1d": 30, "4h": 100, "1h": 200}.get(tf_name, 200)
        
        s20 = sma(closes, s20_p)[-1] if len(closes) >= s20_p else None
        s200 = sma(closes, s200_p)[-1] if len(closes) >= s200_p else None
        
        sc, reasons, risks = score_tf(p, rsi, bb_p, bb_m, m, sig, hist, s20, s200, direction, tf_name, symbol)
        pct = max(0, sc)
        
        w = weights_tf.get(tf_name, 0.25)
        
        # Don't penalize score for 1d trend misalignment — just flag it
        if tf_name == "1d":
            weighted_score += pct * w * 0.5  # 1d contributes less to score
        else:
            weighted_score += pct * w
        total_weight += w
        
        result["tf_scores"][tf_name] = {"pct": pct, "rating": _rating(pct), "rsi": rsi, "bb_p": bb_p}
        result["reasons"].extend(reasons)
        result["risks"].extend(risks)
        
        if tf_name == "1h":
            result["ind_1h"] = {"rsi": rsi, "bb_p": bb_p, "macd_hist": hist, "s20": s20, "s200": s200, "bb_l": bb_l, "bb_m": bb_m, "bb_u": bb_u}
    
    # ─── Memecoin penalty ────────────────────────────────────────
    if is_memecoin(symbol):
        weighted_score *= 0.85  # 15% penalty for memecoins
        result["mc_penalty"] = True
        result["risks"].append("Memecoin: 15% score penalty")
    
    # ─── Momentum penalty ────────────────────────────────────────
    if result.get("momentum_penalty"):
        weighted_score *= 0.85  # 15% penalty for >30% 7d move
        result["risks"].append(f"Impulse {result.get('ch7d', 0):+.1f}% /7d")
    
    result["score_pct"] = weighted_score / total_weight if total_weight > 0 else 0
    result["rating"] = _rating(result["score_pct"])
    result["trend_aligns"] = trend_aligns
    
    # ─── Entry/SL/TP from 1h ─────────────────────────────────────
    if kl_1h and len(kl_1h) >= 50:
        closes_h = [float(k[4]) for k in kl_1h]
        highs_h = [float(k[2]) for k in kl_1h]
        lows_h = [float(k[3]) for k in kl_1h]
        p = closes_h[-1]
        
        bb_l, bb_m, bb_u, _ = calc_bb(closes_h)
        atr_v = atr(highs_h, lows_h, closes_h)
        
        if direction == "LONG":
            result["entry"] = bb_l if bb_l else p * 0.99
            result["sl"] = (bb_l - 0.5 * atr_v) if bb_l and atr_v else p * 0.975
            result["tp1"] = bb_m
            result["tp2"] = bb_u
            result["tp3"] = p + 2 * atr_v if atr_v else p * 1.03
        else:
            result["entry"] = p
            result["sl"] = (bb_u + 0.5 * atr_v) if bb_u and atr_v else p * 1.025
            result["tp1"] = bb_m
            result["tp2"] = bb_l
            result["tp3"] = p - 2 * atr_v if atr_v else p * 0.97
    
    return result

def _rating(pct):
    if pct >= 80: return "A"
    if pct >= 65: return "B"
    if pct >= 50: return "C"
    if pct >= 35: return "D"
    return "F"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 engine_v3.py SYMBOL DIRECTION")
        sys.exit(1)
    
    sym = sys.argv[1].upper()
    direction = sys.argv[2].upper()
    
    print(f"\n{'='*60}\n  {sym} {direction} — v3 Adaptive Multi-TF\n{'='*60}\n")
    
    r = analyze(sym, direction)
    
    trend_str = "✓" if r.get("trend_aligns") else "✗ AGAINST"
    penalties = []
    if r.get("mc_penalty"): penalties.append("MC-15%")
    if r.get("momentum_penalty"): penalties.append("IMP-15%")
    pen_str = f"  [{', '.join(penalties)}]" if penalties else ""
    
    print(f"  Score: {r['score_pct']:.0f}%  |  Rating: {r['rating']}  |  1d Trend: {trend_str}{pen_str}\n")
    
    print(f"  TF Scores:")
    for tf in ["1d", "4h", "1h"]:
        if tf in r["tf_scores"]:
            d = r["tf_scores"][tf]
            if tf == "1d" and "trend" in d:
                print(f"    {tf}: {d['rating']} ({d['pct']:.0f}%) trend={d.get('trend','?')} aligns={d.get('aligns',True)}")
            else:
                print(f"    {tf}: {d['rating']} ({d['pct']:.0f}%) RSI={d.get('rsi',0):.0f} BB={d.get('bb_p',0):.0f}")
    print()
    
    if "entry" in r:
        print(f"  Entry: ${r['entry']:.6f}")
        print(f"  SL:    ${r['sl']:.6f}  ({((r['sl']/r['entry'])-1)*100:+.1f}%)")
        print(f"  TP1:   ${r['tp1']:.6f}  ({((r['tp1']/r['entry'])-1)*100:+.1f}%)")
        print(f"  TP2:   ${r['tp2']:.6f}  ({((r['tp2']/r['entry'])-1)*100:+.1f}%)")
        print(f"  TP3:   ${r['tp3']:.6f}  ({((r['tp3']/r['entry'])-1)*100:+.1f}%)")
        print()
    
    if r["reasons"]:
        print(f"  Reasons:")
        for reason in r["reasons"][:6]:
            print(f"    + {reason}")
        print()
    
    if r["risks"]:
        print(f"  Risks:")
        for risk in r["risks"][:4]:
            print(f"    ! {risk}")
        print()
