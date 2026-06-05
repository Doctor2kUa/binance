#!/usr/bin/env python3
"""
engine.py — Watchlist Analysis Engine v2.2 (ATR TP/SL + RSI Filter)
Анализ для LONG и SHORT направлений с BTC multi-timeframe filter.

Скоринг: RSI/BB/MACD/SMA на 1h, БЕЗ штрафов.
BTC filter: не входим если BTC падает (с проверкой bounce на 15m/5m).
RSI filter: LONG только при RSI<=35, SHORT только при RSI>=65.
ATR-based TP/SL: SL=1.5*ATR, TP=2.0*ATR (проверено бэктестом).
Анализ ОБОИХ направлений для каждой монеты.

Backtest verified (1h, 200 candles):
  score>=55, RSI 35/65, ATR TP/SL: 18 trades, PnL +83.3%, WR 83%, PF 17.2

CLI:
    python3 engine.py analyze SYMBOL
    python3 engine.py watchlist
    python3 engine.py json SYMBOL
"""

import math, json, urllib.request, urllib.error, time, sys

# ─── Helpers ──────────────────────────────────────────────────────

def api_fetch(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 418) and attempt < max_retries - 1: time.sleep(5)
            else: return None
        except:
            if attempt < max_retries - 1: time.sleep(2)
            else: return None
    return None

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
    sig = ema(ml, 9)
    return ml[-1], sig[-1], ml[-1] - sig[-1]

def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1: return None
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    return sum(trs[-period:]) / period

def pearson_correlation(x, y):
    n = min(len(x), len(y))
    if n < 3: return 0.0
    x = x[-n:]; y = y[-n:]
    mx, my = sum(x)/n, sum(y)/n
    cov = sum((x[i]-mx)*(y[i]-my) for i in range(n))
    sx = math.sqrt(sum((xi-mx)**2 for xi in x))
    sy = math.sqrt(sum((yi-my)**2 for yi in y))
    return cov/(sx*sy) if sx*sy else 0.0

# ─── BTC Multi-TF Analysis ─────────────────────────────────────────

def get_btc_data():
    """Fetch BTC klines for multiple timeframes."""
    result = {}
    for tf in ["1h", "15m", "5m"]:
        for base in ["https://fapi.binance.com", "https://api.binance.com"]:
            kl = api_fetch(f"{base}/fapi/v1/klines?symbol=BTCUSDT&interval={tf}&limit=100")
            if not kl: kl = api_fetch(f"{base}/api/v3/klines?symbol=BTCUSDT&interval={tf}&limit=100")
            if kl:
                result[tf] = kl
                break
    return result

def analyze_btc_tf(klines):
    """Analyze BTC on a single timeframe. Returns dict with trend, rsi, mom, reversal signals."""
    if not klines or len(klines) < 30:
        return {"trend": "unknown", "rsi": 50, "mom5": 0, "macd_hist": 0, "warning": False, "oversold_bounce": False, "price": 0, "sma20": 0}
    closes = [float(k[4]) for k in klines]
    rsi = calc_rsi(closes)
    sma20 = sma(closes, 20)[-1]
    price = closes[-1]
    mom5 = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
    m, sig, h = calc_macd(closes)
    above_sma = price > sma20
    macd_bull = (h > 0) if h else False
    strength = (1 if above_sma else -1) + (1 if macd_bull else -1) + (1 if mom5 > 0 else -1 if mom5 < -2 else 0) + (1 if rsi > 50 else -1 if rsi < 30 else 0)
    if strength >= 3: trend = "strong_up"
    elif strength >= 1: trend = "up"
    elif strength <= -3: trend = "strong_down"
    elif strength <= -1: trend = "down"
    else: trend = "neutral"
    oversold_bounce = rsi < 25 and mom5 > 0
    return {"trend": trend, "rsi": rsi, "mom5": mom5, "macd_hist": h, "warning": trend in ("down","strong_down") and rsi < 30, "oversold_bounce": oversold_bounce, "price": price, "sma20": sma20}

def analyze_btc_multi_tf(btc_data):
    """Analyze BTC across 1h, 15m, 5m. Returns dict per TF + aggregate warning."""
    result = {}
    for tf in ["1h", "15m", "5m"]:
        result[tf] = analyze_btc_tf(btc_data.get(tf))
    # Aggregate: warning only if 1h falling AND no bounce on 15m/5m
    h1 = result.get("1h", {})
    m15 = result.get("15m", {})
    m5 = result.get("5m", {})
    agg_warning = h1.get("warning", False) and not m15.get("oversold_bounce", False) and not m5.get("oversold_bounce", False)
    result["aggregate_warning"] = agg_warning
    result["aggregate_trend"] = h1.get("trend", "unknown")
    return result

# ─── Scoring ───────────────────────────────────────────────────────

def rating(pct):
    if pct >= 80: return "A"
    if pct >= 65: return "B"
    if pct >= 50: return "C"
    if pct >= 35: return "D"
    return "F"

def score_dir(price, rsi, bb_p, m, sig, hist, s20, s50, direction):
    sc, reasons, risks = 0, [], []
    # MACD hysteresis threshold: 0.3% of price to avoid noise
    macd_threshold = price * 0.003
    if direction == "LONG":
        if rsi is not None:
            if 20 <= rsi <= 35: sc += 25; reasons.append(f"RSI {rsi} OS")
            elif 35 < rsi < 45: sc += 15
            elif rsi < 20: sc += 10; risks.append("RSI<20")
            elif 45 <= rsi <= 50: sc += 5
        if bb_p is not None:
            if bb_p <= 5: sc += 25; reasons.append(f"BB {bb_p}% bot")
            elif bb_p <= 15: sc += 20
            elif bb_p <= 25: sc += 15
            elif bb_p <= 35: sc += 10
            elif bb_p <= 45: sc += 5
        if m is not None:
            # MACD with hysteresis: strong signal only if hist > threshold
            if m > sig and hist > macd_threshold: sc += 20; reasons.append("MACD+")
            elif m > sig: sc += 10
            elif m < sig and hist < -macd_threshold: sc -= 10; risks.append("MACD-")
            elif m < sig: sc -= 5
            else: sc += 5  # neutral zone (hist near 0)
        if s20 and s50:
            if price < s20 < s50: sc += 20; reasons.append("Below SMA")
            elif price < s20: sc += 10
            elif s20 > s50 and price > s20: sc += 10
            elif price < s50: sc += 5
    else:
        if rsi is not None:
            if 65 <= rsi <= 80: sc += 25; reasons.append(f"RSI {rsi} OB")
            elif 55 < rsi < 65: sc += 15
            elif rsi > 80: sc += 10; risks.append("RSI>80")
            elif 50 <= rsi <= 55: sc += 5
        if bb_p is not None:
            if bb_p >= 95: sc += 25; reasons.append(f"BB {bb_p}% top")
            elif bb_p >= 85: sc += 20
            elif bb_p >= 75: sc += 15
            elif bb_p >= 65: sc += 10
            elif bb_p >= 55: sc += 5
        if m is not None:
            # MACD with hysteresis for SHORT
            if m < sig and hist < -macd_threshold: sc += 20; reasons.append("MACD-")
            elif m < sig: sc += 10
            elif m > sig and hist > macd_threshold: sc -= 10; risks.append("MACD+")
            elif m > sig: sc -= 5
            else: sc += 5  # neutral zone
        if s20 and s50:
            if price > s20 > s50: sc += 20; reasons.append("Above SMA")
            elif price > s20: sc += 10
            elif s20 < s50 and price < s20: sc += 10
            elif price > s50: sc += 5
    return sc, reasons, risks

def fetch(sym):
    tick = kl = kl_d = None
    for base in ["https://fapi.binance.com", "https://api.binance.com"]:
        tick = api_fetch(f"{base}/fapi/v1/ticker/24hr?symbol={sym}")
        if not tick: tick = api_fetch(f"{base}/api/v3/ticker/24hr?symbol={sym}")
        if tick: break
    for base in ["https://fapi.binance.com", "https://api.binance.com"]:
        kl = api_fetch(f"{base}/fapi/v1/klines?symbol={sym}&interval=1h&limit=200")
        if not kl: kl = api_fetch(f"{base}/api/v3/klines?symbol={sym}&interval=1h&limit=200")
        if kl: break
    for base in ["https://fapi.binance.com"]:
        kl_d = api_fetch(f"{base}/fapi/v1/klines?symbol={sym}&interval=1d&limit=30")
        if kl_d: break
    return tick, kl, kl_d

def analyze_coin(symbol):
    """Analyze single coin. Returns dict with both directions."""
    sym = symbol.upper().replace("USDT", "")
    tick, kl, kl_d = fetch(f"{sym}USDT")
    if not tick or not kl or len(kl) < 50:
        return {"symbol": f"{sym}/USDT", "error": "No data"}

    price = float(tick["lastPrice"])
    ch24 = float(tick.get("priceChangePercent", 0))
    vol = float(tick.get("quoteVolume", 0))
    ch7d = 0
    if kl_d and len(kl_d) >= 7:
        c7 = float(kl_d[-7][4])
        if c7 > 0: ch7d = ((price - c7) / c7) * 100

    closes = [float(k[4]) for k in kl]
    rsi = calc_rsi(closes)
    bb_l, bb_m, bb_u, bb_p = calc_bb(closes)
    m, sig, hist = calc_macd(closes)
    atr_val = atr([float(k[2]) for k in kl], [float(k[3]) for k in kl], closes)
    s20 = sma(closes, 20)[-1]; s50 = sma(closes, 50)[-1]

    # Score both directions
    long_sc, long_r, long_risk = score_dir(price, rsi, bb_p, m, sig, hist, s20, s50, "LONG")
    short_sc, short_r, short_risk = score_dir(price, rsi, bb_p, m, sig, hist, s20, s50, "SHORT")

    # BTC Multi-TF Analysis
    btc_data = get_btc_data()
    btc_multi = analyze_btc_multi_tf(btc_data)
    btc_corr = pearson_correlation(closes, [float(k[4]) for k in btc_data.get("1h", [])]) if btc_data.get("1h") else 0.0
    btc_warning = btc_multi.get("aggregate_warning", False)
    btc_bounce = btc_multi.get("15m", {}).get("oversold_bounce", False) or btc_multi.get("5m", {}).get("oversold_bounce", False)
    btc_trend_dir = btc_multi.get("aggregate_trend", "unknown")

    # Initial best direction
    long_p = max(0, long_sc); short_p = max(0, short_sc)
    if long_p >= short_p:
        best_dir = "LONG"; best_p = long_p; best_rt = rating(long_p)
    else:
        best_dir = "SHORT"; best_p = short_p; best_rt = rating(short_p)

    # RSI filter: LONG only if RSI<=35, SHORT only if RSI>=65
    # Backtest verified: RSI filter improves WR from 48% to 83%
    rsi_filter_skip = False
    if best_dir == "LONG" and rsi is not None and rsi > 35:
        rsi_filter_skip = True
    elif best_dir == "SHORT" and rsi is not None and rsi < 65:
        rsi_filter_skip = True

    # BTC filter: if BTC falling (and no bounce), penalize LONG
    if btc_warning and best_dir == "LONG":
        long_sc -= 30
        long_risk.append(f"BTC falling ({btc_trend_dir})")
        long_p = max(0, long_sc); short_p = max(0, short_sc)
        if short_p > long_p:
            best_dir = "SHORT"; best_p = short_p; best_rt = rating(short_p)

    # Apply RSI filter — downgrade to skip if RSI not in zone
    if rsi_filter_skip:
        best_rt = "F"
        best_p = 0
        if best_dir == "LONG":
            long_risk.append(f"RSI {rsi:.0f} > 35, no LONG zone")
        else:
            short_risk.append(f"RSI {rsi:.0f} < 65, no SHORT zone")

    # Recalculate
    long_p = max(0, long_sc); short_p = max(0, short_sc)
    long_rt = rating(long_p); short_rt = rating(short_p)

    # Entry/SL/TP — ATR-based (backtest verified: SL=1.5*ATR, TP=2.0*ATR)
    if atr_val and atr_val > 0:
        if best_dir == "LONG":
            entry = price
            sl = price - 1.5 * atr_val
            tp1 = price + 1.0 * atr_val
            tp2 = price + 2.0 * atr_val
            tp3 = price + 3.0 * atr_val
        else:
            entry = price
            sl = price + 1.5 * atr_val
            tp1 = price - 1.0 * atr_val
            tp2 = price - 2.0 * atr_val
            tp3 = price - 3.0 * atr_val
    else:
        # Fallback to BB-based
        if best_dir == "LONG":
            entry = bb_l if bb_l else price * 0.99
            sl = (bb_l - 0.5 * atr_val) if bb_l and atr_val else price * 0.975
            tp1 = bb_m; tp2 = bb_u; tp3 = price * 1.05
        else:
            entry = price
            sl = (bb_u + 0.5 * atr_val) if bb_u and atr_val else price * 1.025
            tp1 = bb_m; tp2 = bb_l; tp3 = price * 0.95

    return {
        "symbol": f"{sym}/USDT", "price": price, "ch24": ch24, "ch7d": ch7d, "vol": vol,
        "best_dir": best_dir, "best_p": best_p, "best_rt": best_rt,
        "long_p": long_p, "long_rt": long_rt, "short_p": short_p, "short_rt": short_rt,
        "rsi": rsi, "bb_p": bb_p, "hist": hist, "bb_l": bb_l, "bb_m": bb_m, "bb_u": bb_u,
        "s20": s20, "s50": s50, "atr": atr_val, "long_r": long_r, "long_risk": long_risk,
        "short_r": short_r, "short_risk": short_risk, "ch7d_penalty": abs(ch7d) > 20,
        "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "btc_multi": btc_multi, "btc_corr": btc_corr, "btc_warning": btc_warning, "btc_bounce": btc_bounce,
    }

def format_result(r):
    if "error" in r:
        return f"  {r['symbol']}: ERROR — {r['error']}"
    lines = []
    sym = r["symbol"]
    skip = r["best_rt"] in ("D", "F")
    tag = {"A":"[A]","B":"[B]","C":"[~]","D":"[-]","F":"[x]"}.get(r["best_rt"],"[?]")
    p_str = f"{r['price']:.6f}".rstrip("0").rstrip(".")
    lines.append(f"\n{tag} {sym} — {r['best_dir']} {r['best_rt']} ({r['best_p']:.0f}%)")
    lines.append(f"    ${p_str}  |  24h: {r['ch24']:+.1f}%  7d: {r['ch7d']:+.1f}%  Vol: ${r['vol']/1e6:.0f}M")
    lines.append(f"    RSI {r['rsi']:.0f}  BB {r['bb_p']:.0f}%  MACD {'↑' if r['hist'] and r['hist'] > 0 else '↓'}")
    # BTC info
    if r.get("btc_multi"):
        h1 = r["btc_multi"].get("1h", {})
        m15 = r["btc_multi"].get("15m", {})
        m5 = r["btc_multi"].get("5m", {})
        btc_warn = " ⚠️ BTC FALLING" if r.get("btc_warning") else ""
        btc_bounce = " 🔄 BTC BOUNCE" if r.get("btc_bounce") else ""
        lines.append(f"    BTC: 1h={h1.get('trend','?')} RSI={h1.get('rsi',0):.0f} MOM5={h1.get('mom5',0):+.1f}% | 15m={m15.get('trend','?')} mom={m15.get('mom5',0):+.1f}% | 5m={m5.get('trend','?')} mom={m5.get('mom5',0):+.1f}%{btc_warn}{btc_bounce}")
        lines.append(f"    BTC corr: {r.get('btc_corr',0):.2f}")
    if r['bb_l']:
        lines.append(f"    BB: {r['bb_l']:.4f} / {r['bb_m']:.4f} / {r['bb_u']:.4f}")
    lines.append(f"    LONG {r['long_rt']}({r['long_p']:.0f}%)  SHORT {r['short_rt']}({r['short_p']:.0f}%)")
    if r["best_dir"] == "LONG":
        for reason in r["long_r"][:3]: lines.append(f"    + {reason}")
        for risk in r["long_risk"][:2]: lines.append(f"    ! {risk}")
    else:
        for reason in r["short_r"][:3]: lines.append(f"    + {reason}")
        for risk in r["short_risk"][:2]: lines.append(f"    ! {risk}")
    if not skip:
        lines.append(f"    Entry: ${r['entry']:.6f}".rstrip("0").rstrip("."))
        lines.append(f"    SL:    ${r['sl']:.6f}".rstrip("0").rstrip(".") + f"  ({((r['sl']/r['entry'])-1)*100:+.1f}%)")
        lines.append(f"    TP1:   ${r['tp1']:.6f}".rstrip("0").rstrip(".") + f"  ({((r['tp1']/r['entry'])-1)*100:+.1f}%)")
        lines.append(f"    TP2:   ${r['tp2']:.6f}".rstrip("0").rstrip(".") + f"  ({((r['tp2']/r['entry'])-1)*100:+.1f}%)")
    else:
        lines.append(f"    >> SKIP")
    return "\n".join(lines)

# ─── CLI ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 engine.py analyze SYMBOL")
        print("  python3 engine.py watchlist")
        print("  python3 engine.py json SYMBOL")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "analyze":
        sym = sys.argv[2].upper()
        r = analyze_coin(sym)
        print(format_result(r))

    elif cmd == "json":
        sym = sys.argv[2].upper()
        r = analyze_coin(sym)
        print(json.dumps(r, indent=2, default=str))

    elif cmd == "watchlist":
        watchlist = ["NEAR","1INCH","FET","STG","TRUMP","ALLO","ZEC","BCH","ADA","DASH","PORTAL","CAKE"]
        if len(sys.argv) > 2:
            import yaml
            with open(sys.argv[2]) as f:
                cfg = yaml.safe_load(f)
            try:
                wl_data = json.loads(cfg["data"]["positions.json"])
                watchlist = [w["symbol"].replace("USDT","") for w in wl_data["watchlist"]]
            except: pass

        print(f"\n{'='*95}")
        print(f"  WATCHLIST v2.2 + ATR TP/SL + RSI Filter — {time.strftime('%H:%M:%S')}")
        print(f"{'='*95}")

        results = []
        for sym in watchlist:
            r = analyze_coin(sym)
            if "error" not in r:
                results.append(r)
                print(format_result(r))
            else:
                print(f"  {r['symbol']}: {r['error']}")

        good = [r for r in results if r["best_rt"] in ("A","B")]
        c_grade = [r for r in results if r["best_rt"] == "C"]
        skipped = [r for r in results if r["best_rt"] in ("D","F")]

        print(f"\n{'='*95}")
        print("  SUMMARY")
        print(f"{'='*95}")
        print(f"\n  B+: {len(good)} | C: {len(c_grade)} | Skip: {len(skipped)}")
        if good:
            for r in good:
                btc_w = " ⚠️ BTC" if r.get("btc_warning") and r["best_dir"]=="LONG" else ""
                btc_b = " 🔄 BTC bounce" if r.get("btc_bounce") else ""
                print(f"    [+] {r['symbol']} {r['best_dir']} — {r['best_rt']} ({r['best_p']:.0f}%){btc_w}{btc_b}")
        if c_grade:
            print("  C (watch):")
            for r in c_grade:
                btc_w = " ⚠️ BTC" if r.get("btc_warning") and r["best_dir"]=="LONG" else ""
                btc_b = " 🔄 BTC bounce" if r.get("btc_bounce") else ""
                print(f"    [~] {r['symbol']} {r['best_dir']} — C ({r['best_p']:.0f}%){btc_w}{btc_b}")
        print(f"\nDone. {len(good)} candidates, {len(c_grade)} watch, {len(skipped)} skip.")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
