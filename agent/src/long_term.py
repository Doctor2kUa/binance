#!/usr/bin/env python3
"""
long_term.py — Long-Term Position Analysis Engine v2

Для позиций от недели и дольше. Всегда анализирует ОБА направления.

Использование:
  python3 long_term.py SYMBOL [DEPOSIT]     — анализ одной монеты
  python3 long_term.py --batch SYM1,SYM2    — анализ нескольких монет
  python3 long_term.py --watchlist          — анализ watchlist из K8s
  python3 long_term.py --json SYMBOL        — вывод в JSON

Примеры:
  python3 long_term.py BTC
  python3 long_term.py STG 5000
  python3 long_term.py --batch BTC,ETH,SOL
  python3 long_term.py --watchlist
"""

import math
import httpx
import json
import sys
import asyncio
import argparse

BASE = "https://fapi.binance.com"

# ─── Данные ──────────────────────────────────────────────────────────

async def fetch_json(url, params=None):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

async def get_klines(symbol, interval="1d", limit=100):
    return await fetch_json(f"{BASE}/fapi/v1/klines",
                            {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit})

def parse_klines(klines):
    return {
        "close": [float(k[4]) for k in klines],
        "high": [float(k[2]) for k in klines],
        "low": [float(k[3]) for k in klines],
        "volume": [float(k[5]) for k in klines],
    }

# ─── Индикаторы ──────────────────────────────────────────────────────

def sma(data, period):
    return sum(data[-period:]) / period if len(data) >= period else data[-1]

def ema(data, period):
    if len(data) < period: return [data[-1]]
    m = 2 / (period + 1)
    r = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        r.append(data[i] * m + r[-1] * (1 - m))
    return r

def calc_macd(close):
    e12, e26 = ema(close, 12), ema(close, 26)
    off = len(e12) - len(e26)
    ml = [e12[off+i] - e26[i] for i in range(len(e26))]
    if len(ml) < 9: return ml[-1], ml[-1], 0.0
    sig = ema(ml, 9)
    return ml[-1], sig[-1], ml[-1] - sig[-1]

def calc_rsi(close, p=14):
    if len(close) < p+1: return 50.0
    ch = [close[i]-close[i-1] for i in range(1, len(close))]
    g, l = [max(c,0) for c in ch], [max(-c,0) for c in ch]
    ag, al = sum(g[:p])/p, sum(l[:p])/p
    for i in range(p, len(g)):
        ag = (ag*(p-1)+g[i])/p
        al = (al*(p-1)+l[i])/p
    if al < 1e-10: return 100.0
    return 100 - 100/(1+ag/al)

def calc_bb(close, p=20, std_m=2.0):
    if len(close) < p: return close[-1], close[-1], close[-1], 50.0
    w = close[-p:]
    mid = sum(w)/p
    std = math.sqrt(sum((x-mid)**2 for x in w)/p)
    upper, lower = mid+std_m*std, mid-std_m*std
    rng = upper-lower
    return upper, mid, lower, ((close[-1]-lower)/rng*100) if rng > 0 else 50.0

def calc_atr(h, l, c, p=14):
    if len(h) < p+1: return (h[-1]-l[-1]) if h else 0.0
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1,len(h))]
    return sum(trs[-p:])/p if len(trs)>=p else (sum(trs)/len(trs) if trs else 0.0)

def calc_mom(close, period):
    return (close[-1]/close[-period]-1)*100 if len(close)>=period else 0.0

def vol_analysis(vol, close, p=20):
    if len(vol)<p: return 0.0, 1.0
    vu = [vol[i]*close[i] for i in range(len(vol))]
    avg = sum(vu[-p:])/p
    return avg, vol[-1]*close[-1]/avg if avg>0 else 1.0

# ─── Мультитаймфреймный тренд ────────────────────────────────────────

def analyze_trend(daily, weekly, monthly):
    d_close, w_close, m_close = daily["close"], weekly["close"], monthly["close"]
    trends = {}

    for name, data, sma_s, sma_l in [("daily", d_close, 20, 50), ("weekly", w_close, 20, 50), ("monthly", m_close, 6, 12)]:
        if len(data) >= sma_l:
            s_s, s_l = sma(data, sma_s), sma(data, sma_l)
            p = data[-1]
            t = "UP" if p > s_s > s_l else ("DOWN" if p < s_s < s_l else "SIDE")
            st = min(100, abs(p-s_l)/s_l*100*2)
        else:
            t, st = "SIDE", 0
        trends[name] = {"trend": t, "strength": round(st, 1)}

    d, w, m = trends["daily"]["trend"], trends["weekly"]["trend"], trends["monthly"]["trend"]
    if d == w == m and d != "SIDE":
        align, direction = 100, d
    elif d == w and d != "SIDE":
        align, direction = 70, d
    elif d == m and d != "SIDE":
        align, direction = 60, d
    elif w == m and w != "SIDE":
        align, direction = 50, w
    else:
        align, direction = 20, d if d != "SIDE" else "SIDE"

    return {**trends, "alignment": align, "direction": direction,
            "combined_strength": round((trends["daily"]["strength"]+trends["weekly"]["strength"]+trends["monthly"]["strength"])/3, 1)}

# ─── Скоринг ─────────────────────────────────────────────────────────

def score_trend(trend, direction):
    s = 0
    a = trend["alignment"]
    if a >= 80: s += 15
    elif a >= 60: s += 10
    elif a >= 40: s += 5
    else: s -= 5

    if trend["direction"] == direction: s += 10
    elif trend["direction"] == "SIDE": s += 2
    else: s -= 10

    if trend["combined_strength"] > 20: s += 5
    return max(-15, min(30, s))

def score_rsi(v, d):
    if d == "LONG":
        if v<25: return 20
        elif v<35: return 18
        elif v<45: return 14
        elif v<55: return 10
        elif v<65: return 5
        elif v<75: return 2
        else: return 0
    else:
        if v>75: return 20
        elif v>65: return 18
        elif v>55: return 14
        elif v>45: return 10
        elif v<25: return 0
        else: return 2

def score_bb(v, d):
    if d == "LONG":
        if v<15: return 20
        elif v<30: return 16
        elif v<40: return 12
        elif v<50: return 8
        elif v<60: return 4
        else: return 0
    else:
        if v>85: return 20
        elif v>70: return 16
        elif v>60: return 12
        elif v>50: return 8
        elif v<40: return 4
        else: return 0

def score_macd(mn, price, d):
    if d == "LONG":
        if price>10: ths=[(2.0,20),(1.0,16),(0.3,12),(0,8),(-0.5,4)]
        elif price>1: ths=[(4.0,20),(2.0,16),(0.5,12),(0,8),(-0.2,4)]
        else: ths=[(10.0,20),(5.0,16),(1.0,12),(0,8),(-0.5,4)]
        for t,s in ths:
            if mn>t: return s
        return 0
    else:
        if price>10: ths=[(-2.0,20),(-1.0,16),(-0.3,12),(0,8),(0.5,4)]
        elif price>1: ths=[(-4.0,20),(-2.0,16),(-0.5,12),(0,8),(0.2,4)]
        else: ths=[(-10.0,20),(-5.0,16),(-1.0,12),(0,8),(0.5,4)]
        for t,s in ths:
            if mn<t: return s
        return 0

def score_vol(avg_vol, vr):
    s = 0
    if avg_vol>10_000_000: s += 10
    elif avg_vol>5_000_000: s += 8
    elif avg_vol>1_000_000: s += 5
    elif avg_vol>500_000: s += 2
    else: s -= 10
    if vr>1.5: s += 5
    elif vr>1.0: s += 3
    elif vr<0.5: s -= 3
    return s

def score_mom(m7, m30, d):
    s = 0
    if d == "LONG":
        if 10<m30<50: s += 10
        elif 5<m30<70: s += 6
        elif m30>70: s -= 5
        elif m30>0: s += 3
        else: s += m30/10
        if m7>0: s += 3
        elif m7>-10: s += 1
        else: s -= 2
    else:
        if m30>100: s += 10
        elif m30>50: s += 8
        elif m30>20: s += 5
        elif m30>0: s += 2
        else: s -= 5
        if m7<-10: s += 5
        elif m7<0: s += 3
    return max(-10, min(15, s))

def calc_penalties(sym, avg_vol, atr_pct, m30, rsi):
    p = []
    if avg_vol<500_000: p.append(("Very Low Liquidity",-20))
    if atr_pct>20: p.append(("Extreme Volatility",-10))
    if m30>200: p.append(("Bubble Risk",-10))
    if rsi>85 or rsi<15: p.append(("Extreme RSI",-5))
    return p

def to_rating(s):
    if s>=80: return "A"
    elif s>=65: return "B"
    elif s>=50: return "C"
    elif s>=35: return "D"
    return "F"

def entry_params(price, atr, d, deposit=1000.0, amount=10.0):
    risk = deposit*0.02
    if d == "LONG":
        sl = price-atr*3.0
        sl_pct = abs(price-sl)/price*100
        if sl_pct<10: sl=price*0.90
        elif sl_pct>25: sl=price*0.75
        dist = price-sl
        tp1, tp2, tp3 = price+dist*2.0, price+dist*3.0, price+dist*5.0
    else:
        sl = price+atr*3.0
        sl_pct = abs(sl-price)/price*100
        if sl_pct<10: sl=price*1.10
        elif sl_pct>25: sl=price*1.25
        dist = sl-price
        tp1, tp2, tp3 = price-dist*2.0, price-dist*3.0, price-dist*5.0
    pv = risk/(dist/price) if dist>0 else 0
    if pv<10: pv=10
    if pv>deposit*0.20: pv=deposit*0.20
    lev = max(1,min(3,round(pv/amount)))
    return {
        "entry":round(price,6),"sl":round(sl,6),"sl_pct":round(sl_pct,1),
        "tp1":round(tp1,6),"tp1_pct":round((tp1/price-1)*100,1),
        "tp2":round(tp2,6),"tp2_pct":round((tp2/price-1)*100,1),
        "tp3":round(tp3,6),"tp3_pct":round((tp3/price-1)*100,1),
        "size_usdt":round(pv,2),"leverage":lev,
    }

def danger_score(price, rsi, bb, macd, m7, m30, vr, trend, d):
    dg=0
    if trend["alignment"]<40: dg+=30
    elif trend["alignment"]<60: dg+=15
    if trend["direction"]!=d and trend["direction"]!="SIDE": dg+=20
    if rsi>80 or rsi<20: dg+=15
    if bb>95 or bb<5: dg+=10
    if m30>100: dg+=15
    elif m30>50: dg+=8
    if vr<0.3: dg+=10
    return min(dg,100)

# ─── Основной анализ ─────────────────────────────────────────────────

async def analyze(symbol, deposit=1000.0, amount=10.0):
    """Полный анализ монеты. Всегда считает ОБА направления."""
    sym = symbol.upper().replace("USDT", "")

    # Fetch all timeframes
    daily = parse_klines(await get_klines(sym, "1d", 100))
    weekly = parse_klines(await get_klines(sym, "1w", 100))
    monthly = parse_klines(await get_klines(sym, "1M", 50))

    price = daily["close"][-1]

    # Trend
    trend = analyze_trend(daily, weekly, monthly)

    # Daily indicators
    s7=sma(daily["close"],7); s20=sma(daily["close"],20); s50=sma(daily["close"],50)
    rsi=calc_rsi(daily["close"])
    ml, sig, mh = calc_macd(daily["close"])
    bu, bm, bl, bb = calc_bb(daily["close"])
    atr=calc_atr(daily["high"],daily["low"],daily["close"])
    atr_pct=atr/price*100 if price>0 else 0
    m7=calc_mom(daily["close"],7); m30=calc_mom(daily["close"],30)
    avg_vol, vr = vol_analysis(daily["volume"], daily["close"])
    mn = mh/price*100 if price>0 else 0

    # Score for BOTH directions
    results = {}
    for direction in ["LONG", "SHORT"]:
        raw = (
            score_trend(trend, direction) +
            score_rsi(rsi, direction) +
            score_bb(bb, direction) +
            score_macd(mn, price, direction) +
            score_vol(avg_vol, vr) +
            score_mom(m7, m30, direction)
        )
        penalties = calc_penalties(sym, avg_vol, atr_pct, m30, rsi)
        total_penalty = sum(p[1] for p in penalties)
        final = max(0, min(100, raw + total_penalty))
        rating = to_rating(final)
        d_score = danger_score(price, rsi, bb, mh, m7, m30, vr, trend, direction)
        dl = "LOW" if d_score<30 else ("MEDIUM" if d_score<60 else "HIGH")

        results[direction] = {
            "score": final,
            "rating": rating,
            "danger": d_score,
            "danger_level": dl,
            "raw": raw,
            "penalties": {p[0]: p[1] for p in penalties},
            "total_penalty": total_penalty,
            "skip": rating in ("C", "D", "F"),
        }

        # Entry params только для A/B
        if rating in ("A", "B"):
            results[direction]["entry"] = entry_params(price, atr, direction, deposit, amount)

    return {
        "symbol": f"{sym}/USDT",
        "price": price,
        "trend": trend,
        "indicators": {
            "rsi": round(rsi,1), "bb": round(bb,1), "macd": round(mh,6),
            "m7": round(m7,1), "m30": round(m30,1), "vr": round(vr,2),
            "avg_vol": round(avg_vol,0), "atr": round(atr,6), "atr_pct": round(atr_pct,1),
            "sma7": round(s7,6), "sma20": round(s20,6), "sma50": round(s50,6),
        },
        "long": results["LONG"],
        "short": results["SHORT"],
    }

# ─── Форматирование вывода ───────────────────────────────────────────

def format_result(r, deposit=1000.0):
    """Форматирует результат анализа в читаемый вид."""
    lines = []
    sym = r["symbol"]
    price = r["price"]
    trend = r["trend"]
    ind = r["indicators"]

    lines.append(f"\n{'='*70}")
    lines.append(f"  {sym} @ ${price}")
    lines.append(f"{'='*70}")

    # Trend
    lines.append(f"\n  📊 TREND (alignment: {trend['alignment']}%)")
    for tf in ["daily", "weekly", "monthly"]:
        t = trend[tf]
        emoji = "🟢" if t["trend"]=="UP" else ("🔴" if t["trend"]=="DOWN" else "⚪")
        lines.append(f"    {tf:8} {emoji} {t['trend']:5} (strength: {t['strength']})")

    # Indicators
    lines.append(f"\n  📈 INDICATORS")
    lines.append(f"    RSI: {ind['rsi']} | BB: {ind['bb']}% | MACD: {ind['macd']}")
    lines.append(f"    MOM 7d: {ind['m7']}% | MOM 30d: {ind['m30']}%")
    lines.append(f"    Vol: {ind['vr']}x | Avg: ${ind['avg_vol']:,.0f} | ATR: {ind['atr_pct']}%")

    # Both directions
    for direction in ["LONG", "SHORT"]:
        d = r[direction.lower()]
        emoji = "🟢" if direction=="LONG" else "🔴"
        skip_emoji = "✅" if not d["skip"] else "❌"

        lines.append(f"\n  {emoji} {direction} — {d['rating']} ({d['score']}%) | Danger: {d['danger_level']} {skip_emoji}")

        if d["penalties"]:
            for name, val in d["penalties"].items():
                lines.append(f"    ⚠ {name}: {val}")
            lines.append(f"    Total penalty: {d['total_penalty']}")

        if "entry" in d:
            ep = d["entry"]
            lines.append(f"    Entry: ${ep['entry']}")
            lines.append(f"    SL: ${ep['sl']} ({ep['sl_pct']}%)")
            lines.append(f"    TP1: ${ep['tp1']} ({ep['tp1_pct']}%) — 30%")
            lines.append(f"    TP2: ${ep['tp2']} ({ep['tp2_pct']}%) — 35%")
            lines.append(f"    TP3: ${ep['tp3']} ({ep['tp3_pct']}%) — 35%")
            lines.append(f"    Size: ${ep['size_usdt']} | Lev: {ep['leverage']}x | R:R 2:1/3:1/5:1")
        else:
            lines.append(f"    SKIP — score {d['score']}% below B threshold (65%)")

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Long-Term Position Analysis")
    parser.add_argument("symbol", nargs="?", help="Symbol to analyze (e.g. BTC)")
    parser.add_argument("deposit", nargs="?", type=float, default=1000.0, help="Deposit in USDT")
    parser.add_argument("--batch", help="Comma-separated symbols (e.g. BTC,ETH,SOL)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--watchlist", action="store_true", help="Analyze K8s watchlist")
    args = parser.parse_args()

    symbols = []

    if args.watchlist:
        # Read from K8s
        import subprocess
        try:
            result = subprocess.run(
                ["kubectl", "get", "configmap", "binance-config", "-n", "function",
                 "-o", "jsonpath={.data.positions\\.json}"],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(result.stdout)
            for w in data.get("watchlist", []):
                sym = w["symbol"].replace("USDT", "")
                if w.get("direction") != "SKIP":
                    symbols.append(sym)
        except Exception as e:
            print(f"Error reading watchlist: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.batch:
        symbols = [s.strip().upper() for s in args.batch.split(",")]
    elif args.symbol:
        symbols = [args.symbol.upper()]
    else:
        parser.print_help()
        sys.exit(1)

    deposit = args.deposit or 1000.0

    all_results = []
    for sym in symbols:
        try:
            r = await analyze(sym, deposit)
            all_results.append(r)
            if not args.json:
                print(format_result(r, deposit))
        except Exception as e:
            print(f"\n❌ {sym}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))

    # Summary
    if not args.json and len(all_results) > 1:
        print(f"\n{'='*70}")
        print("  SUMMARY")
        print(f"{'='*70}")
        recommended = []
        for r in all_results:
            for d in ["long", "short"]:
                if not r[d]["skip"]:
                    recommended.append((r["symbol"], d.upper(), r[d]["score"], r[d]["rating"]))

        if recommended:
            recommended.sort(key=lambda x: -x[2])
            print(f"\n  ✅ RECOMMENDED ({len(recommended)}):")
            for sym, direction, score, rating in recommended:
                print(f"    {sym:12} {direction:5} {rating} ({score}%)")
        else:
            print(f"\n  ❌ No recommended positions (all below B threshold)")

        print(f"\n  ❌ SKIP ({len(all_results) - len(recommended)}):")
        for r in all_results:
            for d in ["long", "short"]:
                if r[d]["skip"]:
                    print(f"    {r['symbol']:12} {d.upper():5} {r[d]['rating']} ({r[d]['score']}%)")

if __name__ == "__main__":
    asyncio.run(main())
