"""
engine_v2.py — Watchlist & Position Analysis Engine v2

Ключевые изменения:
1. Контекстный скоринг — учитывает фазу рынка (парабола, отскок, флэт)
2. Адаптивные пороги — для волатильных монет пороги шире
3. Паттерн-анализ — определяет развороты, продолжения, консолидации
4. Учёт стиля трейдера — раннее закрытие, не жадничаем
5. Risk/Reward вместо абсолютного скора — более практично
"""

import math
import httpx
from typing import Optional
from dataclasses import dataclass

BASE = "https://fapi.binance.com"

# ─── DATA FETCHING ─────────────────────────────────────────────

async def fetch_json(url: str, params: dict = None):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

async def get_ticker(symbol: str):
    return await fetch_json(f"{BASE}/fapi/v1/ticker/24hr", {"symbol": f"{symbol}USDT"})

async def get_klines(symbol: str, interval: str = "1d", limit: int = 100):
    return await fetch_json(f"{BASE}/fapi/v1/klines", {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit})

def parse_klines(klines: list):
    return {
        "open": [float(k[1]) for k in klines],
        "close": [float(k[4]) for k in klines],
        "high": [float(k[2]) for k in klines],
        "low": [float(k[3]) for k in klines],
        "volume": [float(k[5]) for k in klines],
    }

# ─── INDICATORS ────────────────────────────────────────────────

def sma(data, period):
    if len(data) < period: return data[-1]
    return sum(data[-period:]) / period

def ema(data, period):
    if len(data) < period: return [data[-1]]
    k = 2 / (period + 1)
    r = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        r.append(data[i] * k + r[-1] * (1 - k))
    return r

def calc_rsi(close, period=14):
    if len(close) < period + 1: return 50
    changes = [close[i] - close[i-1] for i in range(1, len(close))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period-1) + gains[i]) / period
        al = (al * (period-1) + losses[i]) / period
    if al < 1e-10: return 100
    return 100 - 100 / (1 + ag / al)

def calc_macd(close):
    e12 = ema(close, 12)
    e26 = ema(close, 26)
    offset = len(e12) - len(e26)
    macd_line = [e12[offset+i] - e26[i] for i in range(len(e26))]
    if len(macd_line) < 9: return macd_line[-1], macd_line[-1], 0
    sig = ema(macd_line, 9)
    return macd_line[-1], sig[-1], macd_line[-1] - sig[-1]

def calc_bb(close, period=20, std_mult=2.0):
    if len(close) < period: m = close[-1]; return m, m, m, 50
    w = close[-period:]
    mid = sum(w) / period
    std = math.sqrt(sum((x-mid)**2 for x in w) / period)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    rng = upper - lower
    pos = ((close[-1] - lower) / rng * 100) if rng > 0 else 50
    return upper, mid, lower, pos

def calc_atr(high, low, close, period=14):
    if len(high) < period + 1: return high[-1] - low[-1] if high else 0
    trs = [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])) for i in range(1, len(high))]
    if len(trs) < period: return sum(trs) / len(trs) if trs else 0
    return sum(trs[-period:]) / period

# ─── MARKET PHASE DETECTION ────────────────────────────────────

def detect_phase(close, high, low, volume):
    """
    Определяет фазу рынка:
    - PARABOLIC: параболический рост (>50% за 5 свечей)
    - BREAKOUT: пробой уровня с объёмом
    - REVERSAL_DOWN: разворот вниз (красные свечи после роста)
    - REVERSAL_UP: разворот вверх (зелёные после падения)
    - TREND_UP: устойчивый рост
    - TREND_DOWN: устойчивое падение
    - SIDEWAYS: флэт
    """
    if len(close) < 10: return "UNKNOWN"

    # Momentum
    mom_5d = (close[-1] / close[-6] - 1) * 100 if len(close) >= 6 else 0
    mom_10d = (close[-1] / close[-11] - 1) * 100 if len(close) >= 11 else 0

    # Candle pattern (last 3)
    last_3_green = sum(1 for i in range(-3, 0) if close[i] > close[i-1])
    last_3_red = 3 - last_3_green

    # Volume trend
    vol_recent = sum(volume[-3:]) / 3
    vol_prior = sum(volume[-10:-3]) / 7 if len(volume) >= 10 else vol_recent
    vol_surge = vol_recent / vol_prior if vol_prior > 0 else 1

    # Phase detection
    if mom_5d > 50:
        return "PARABOLIC"
    elif mom_5d > 20 and last_3_red >= 2:
        return "REVERSAL_DOWN"
    elif mom_5d < -20 and last_3_green >= 2:
        return "REVERSAL_UP"
    elif mom_10d > 15 and last_3_green >= 2:
        return "TREND_UP"
    elif mom_10d < -15 and last_3_red >= 2:
        return "TREND_DOWN"
    elif abs(mom_10d) < 10:
        return "SIDEWAYS"
    else:
        return "TRANSITION"

# ─── ADAPTIVE SCORING ──────────────────────────────────────────

def score_adaptive(price, rsi_val, bb_pos, macd_hist, atr_pct, mom_7d, mom_30d, vol_ratio, phase, direction):
    """
    Адаптивный скоринг с учётом фазы рынка.
    Возвращает (score, confidence, reasons)
    """
    score = 0
    max_score = 100
    reasons = []
    confidence = "MEDIUM"

    # ── PHASE-BASED ADJUSTMENTS ──

    if phase == "PARABOLIC":
        # Парабола: шорт выгоден, лонг опасен
        if direction == "SHORT":
            score += 25
            reasons.append(f"PARABOLIC phase — short favored (+25)")
            confidence = "HIGH"
        else:
            score -= 30
            reasons.append(f"PARABOLIC phase — long dangerous (-30)")
            confidence = "LOW"

    elif phase == "REVERSAL_DOWN":
        if direction == "SHORT":
            score += 20
            reasons.append(f"REVERSAL_DOWN — short confirmed (+20)")
            confidence = "HIGH"
        else:
            score -= 20
            reasons.append(f"REVERSAL_DOWN — long against trend (-20)")

    elif phase == "REVERSAL_UP":
        if direction == "LONG":
            score += 20
            reasons.append(f"REVERSAL_UP — long confirmed (+20)")
            confidence = "HIGH"
        else:
            score -= 20
            reasons.append(f"REVERSAL_UP — short against trend (-20)")

    elif phase == "TREND_UP":
        if direction == "LONG":
            score += 15
            reasons.append(f"TREND_UP — long with trend (+15)")
        else:
            score -= 15
            reasons.append(f"TREND_UP — short against trend (-15)")

    elif phase == "TREND_DOWN":
        if direction == "SHORT":
            score += 15
            reasons.append(f"TREND_DOWN — short with trend (+15)")
        else:
            score -= 15
            reasons.append(f"TREND_DOWN — long against trend (-15)")

    elif phase == "SIDEWAYS":
        # Флэт: работаем от границ BB
        if direction == "LONG" and bb_pos < 30:
            score += 15
            reasons.append(f"SIDEWAYS + BB low — long from bottom (+15)")
        elif direction == "SHORT" and bb_pos > 70:
            score += 15
            reasons.append(f"SIDEWAYS + BB high — short from top (+15)")
        else:
            score -= 10
            reasons.append(f"SIDEWAYS — no clear edge (-10)")

    # ── RSI (adaptive thresholds) ──

    if direction == "LONG":
        if rv < 25: score += 20; reasons.append(f"RSI deep OS ({rv:.0f}) +20")
        elif rv < 35: score += 15; reasons.append(f"RSI OS ({rv:.0f}) +15")
        elif rv < 45: score += 8; reasons.append(f"RSI low ({rv:.0f}) +8")
        elif rv > 70: score -= 15; reasons.append(f"RSI OB ({rv:.0f}) -15")
    else:  # SHORT
        if rv > 80: score += 20; reasons.append(f"RSI deep OB ({rv:.0f}) +20")
        elif rv > 70: score += 15; reasons.append(f"RSI OB ({rv:.0f}) +15")
        elif rv > 60: score += 8; reasons.append(f"RSI high ({rv:.0f}) +8")
        elif rv < 30: score -= 15; reasons.append(f"RSI OS ({rv:.0f}) -15")

    # ── BB (adaptive for volatility) ──

    if direction == "LONG":
        if bb_p < 15: score += 20; reasons.append(f"BB extreme low ({bb_p:.0f}%) +20")
        elif bb_p < 30: score += 12; reasons.append(f"BB low ({bb_p:.0f}%) +12")
        elif bb_p > 80: score -= 15; reasons.append(f"BB extreme high ({bb_p:.0f}%) -15")
    else:
        if bb_p > 90: score += 20; reasons.append(f"BB extreme high ({bb_p:.0f}%) +20")
        elif bb_p > 70: score += 12; reasons.append(f"BB high ({bb_p:.0f}%) +12")
        elif bb_p < 20: score -= 15; reasons.append(f"BB extreme low ({bb_p:.0f}%) -15")

    # ── MACD ──

    macd_norm = macd_hist / price * 100 if price > 0 else 0
    if direction == "LONG":
        if macd_norm > 2: score += 15; reasons.append(f"MACD strong bullish ({macd_norm:+.2f}%) +15")
        elif macd_norm > 0: score += 8; reasons.append(f"MACD bullish ({macd_norm:+.2f}%) +8")
        elif macd_norm < -1: score -= 10; reasons.append(f"MACD bearish ({macd_norm:+.2f}%) -10")
    else:
        if macd_norm < -2: score += 15; reasons.append(f"MACD strong bearish ({macd_norm:+.2f}%) +15")
        elif macd_norm < 0: score += 8; reasons.append(f"MACD bearish ({macd_norm:+.2f}%) +8")
        elif macd_norm > 1: score -= 10; reasons.append(f"MACD bullish ({macd_norm:+.2f}%) -10")

    # ── MOMENTUM (mean reversion vs trend following) ──

    if direction == "LONG":
        if mom_7d < -20: score += 15; reasons.append(f"Mean reversion ({P(mom_7d)}) +15")
        elif mom_7d < -10: score += 8; reasons.append(f"Dip ({P(mom_7d)}) +8")
        elif mom_7d > 30: score -= 20; reasons.append(f"Chasing pump ({P(mom_7d)}) -20")
        elif mom_7d > 15: score -= 10; reasons.append(f"Pumped ({P(mom_7d)}) -10")
    else:
        if mom_7d > 30: score += 15; reasons.append(f"Parabolic ({P(mom_7d)}) +15")
        elif mom_7d > 15: score += 8; reasons.append(f"Pumped ({P(mom_7d)}) +8")
        elif mom_7d < -20: score -= 15; reasons.append(f"Already dropped ({P(mom_7d)}) -15")

    # ── VOLUME ──

    if vol_ratio > 2: score += 10; reasons.append(f"Volume surge ({vol_ratio:.1f}x) +10")
    elif vol_ratio > 1.5: score += 5; reasons.append(f"Volume up ({vol_ratio:.1f}x) +5")
    elif vol_ratio < 0.3: score -= 10; reasons.append(f"Dead volume ({vol_ratio:.1f}x) -10")

    # ── VOLATILITY ADJUSTMENT ──

    if atr_pct > 15:
        # Высокая волатильность — нужен шире SL, меньший размер
        if direction == "SHORT":
            score += 5  # Шорт на волатильных — быстрые движения
            reasons.append(f"High vol ({atr_pct:.1f}%) — short favored +5")
        reasons.append(f"⚠️ High volatility — consider smaller size")

    # ── PENALTIES ──

    # Dead zone
    if 45 < rsi < 55 and 40 < bb_pos < 60 and abs(macd_norm) < 0.3:
        score -= 15
        reasons.append("Dead zone — no clear signal (-15)")

    # Already run (don't chase)
    if mom_30d > 100 and direction == "LONG":
        score -= 25
        reasons.append(f"Already ran {P(mom_30d)} — don't chase (-25)")

    if mom_30d < -50 and direction == "SHORT":
        score -= 20
        reasons.append(f"Already dropped {P(mom_30d)} — bounce risk (-20)")

    score = max(0, min(100, score))
    return score, confidence, reasons

# ─── RISK/REWARD CALCULATION ───────────────────────────────────

def calc_risk_reward(entry, sl, tp1, tp2, tp3, direction):
    """Рассчитывает R:R для каждого уровня"""
    if direction == "LONG":
        risk = abs(entry - sl) / entry * 100
        r1 = abs(tp1 - entry) / entry * 100
        r2 = abs(tp2 - entry) / entry * 100
        r3 = abs(tp3 - entry) / entry * 100
    else:
        risk = abs(sl - entry) / entry * 100
        r1 = abs(entry - tp1) / entry * 100
        r2 = abs(entry - tp2) / entry * 100
        r3 = abs(entry - tp3) / entry * 100

    return {
        "risk_pct": round(risk, 1),
        "tp1_rr": round(r1 / risk, 1) if risk > 0 else 0,
        "tp2_rr": round(r2 / risk, 1) if risk > 0 else 0,
        "tp3_rr": round(r3 / risk, 1) if risk > 0 else 0,
    }

# ─── POSITION ANALYSIS ─────────────────────────────────────────

async def analyze_position(symbol: str, side: str, entry: float, amount: float,
                           sl: float, tp1: float, tp2: float, tp3: float):
    """Анализ открытой позиции — держать или закрыть"""

    t = await get_ticker(symbol)
    name = symbol.replace("USDT", "")
    px = float(t['lastPrice'])
    ch = float(t['priceChangePercent'])

    klines = await get_klines(name, "1d", 100)
    d = parse_klines(klines)

    rv = calc_rsi(d["close"])
    macd_line, macd_sig, macd_hist = calc_macd(d["close"])
    bb_u, bb_m, bb_l, bb_pos = calc_bb(d["close"])
    atr = calc_atr(d["high"], d["low"], d["close"])
    atr_pct = atr / px * 100 if px > 0 else 0
    mom_7d = (d["close"][-1] / d["close"][-8] - 1) * 100
    mom_30d = (d["close"][-1] / d["close"][-31] - 1) * 100 if len(d["close"]) >= 31 else 0
    vol_ratio = d["volume"][-1] / (sum(d["volume"][-20:]) / 20) if sum(d["volume"][-20:]) > 0 else 1

    phase = detect_phase(d["close"], d["high"], d["low"], d["volume"])

    # PnL
    if side.upper() == "LONG":
        pnl = (px / entry - 1) * 100 * 2  # 2x leverage
        to_sl = (sl / px - 1) * 100
    else:
        pnl = (entry / px - 1) * 100 * 2
        to_sl = (sl / px - 1) * 100

    # Score for current direction
    score, confidence, reasons = score_adaptive(
        px, rv, bb_pos, macd_hist, atr_pct, mom_7d, mom_30d, vol_ratio, phase, side
    )

    # R:R
    rr = calc_risk_reward(entry, sl, tp1, tp2, tp3, side)

    # Close signals
    close_signals = []
    if abs(to_sl) < 5:
        close_signals.append(f"SL too close ({abs(to_sl):.1f}%)")
    if side.upper() == "LONG" and rv > 70 and bb_pos > 80:
        close_signals.append("Overbought — take profit")
    if side.upper() == "SHORT" and rv < 30 and bb_pos < 20:
        close_signals.append("Oversold — cover")
    if macd_hist < 0 and side.upper() == "LONG" and px < sma(d["close"], 20):
        close_signals.append("MACD bearish + below SMA20")
    if macd_hist > 0 and side.upper() == "SHORT" and px > sma(d["close"], 20):
        close_signals.append("MACD bullish + above SMA20")
    if phase == "REVERSAL_DOWN" and side.upper() == "LONG":
        close_signals.append("Reversal down — exit long")
    if phase == "REVERSAL_UP" and side.upper() == "SHORT":
        close_signals.append("Reversal up — cover short")

    # Verdict
    if score >= 70:
        verdict = "STRONG_HOLD"
    elif score >= 50:
        verdict = "HOLD"
    elif score >= 30:
        if close_signals:
            verdict = "CONSIDER_CLOSE"
        else:
            verdict = "HOLD_CAUTIOUS"
    else:
        verdict = "CLOSE"

    return {
        "symbol": f"{name}/USDT",
        "side": side,
        "entry": entry,
        "price": px,
        "pnl_pct": round(pnl, 1),
        "pnl_usd": round(amount * pnl / 100, 2),
        "to_sl_pct": round(to_sl, 1),
        "score": score,
        "confidence": confidence,
        "phase": phase,
        "indicators": {"rsi": round(rv, 1), "bb_pos": round(bb_pos, 1), "macd_hist": round(macd_hist, 6), "atr_pct": round(atr_pct, 1)},
        "rr": rr,
        "reasons": reasons,
        "close_signals": close_signals,
        "verdict": verdict,
    }

# ─── WATCHLIST ANALYSIS ────────────────────────────────────────

async def analyze_watchlist(symbol: str, direction: str = None):
    """Анализ монеты из вотчлиста"""
    name = symbol.upper().replace("USDT", "")

    t = await get_ticker(symbol)
    px = float(t['lastPrice'])
    ch = float(t['priceChangePercent'])

    klines = await get_klines(name, "1d", 100)
    d = parse_klines(klines)

    rv = calc_rsi(d["close"])
    macd_line, macd_sig, macd_hist = calc_macd(d["close"])
    bb_u, bb_m, bb_l, bb_pos = calc_bb(d["close"])
    atr = calc_atr(d["high"], d["low"], d["close"])
    atr_pct = atr / px * 100 if px > 0 else 0
    mom_7d = (d["close"][-1] / d["close"][-8] - 1) * 100
    mom_30d = (d["close"][-1] / d["close"][-31] - 1) * 100 if len(d["close"]) >= 31 else 0
    vol_ratio = d["volume"][-1] / (sum(d["volume"][-20:]) / 20) if sum(d["volume"][-20:]) > 0 else 1

    phase = detect_phase(d["close"], d["high"], d["low"], d["volume"])

    # Score both directions
    long_score, long_conf, long_reasons = score_adaptive(
        px, rv, bb_pos, macd_hist, atr_pct, mom_7d, mom_30d, vol_ratio, phase, "LONG"
    )
    short_score, short_conf, short_reasons = score_adaptive(
        px, rv, bb_pos, macd_hist, atr_pct, mom_7d, mom_30d, vol_ratio, phase, "SHORT"
    )

    # Pick best
    if long_score >= short_score:
        best_dir, best_score, best_conf, best_reasons = "LONG", long_score, long_conf, long_reasons
    else:
        best_dir, best_score, best_conf, best_reasons = "SHORT", short_score, short_conf, short_reasons

    # Override if direction specified
    if direction and direction.upper() != "SKIP":
        if direction.upper() == "LONG":
            best_dir, best_score, best_conf, best_reasons = "LONG", long_score, long_conf, long_reasons
        elif direction.upper() == "SHORT":
            best_dir, best_score, best_conf, best_reasons = "SHORT", short_score, short_conf, short_reasons

    # Grade
    if best_score >= 80: grade = "A"
    elif best_score >= 65: grade = "B"
    elif best_score >= 50: grade = "C"
    elif best_score >= 35: grade = "D"
    else: grade = "F"

    # Calculate entry params
    if best_dir == "LONG":
        sl = px - atr * 1.5
        if sl < px * 0.85: sl = px * 0.85
        if sl > px * 0.97: sl = px * 0.97
        tp1 = px + (px - sl) * 1.5
        tp2 = px + (px - sl) * 2.5
        tp3 = px + (px - sl) * 4.0
    elif best_dir == "SHORT":
        sl = px + atr * 1.5
        if sl > px * 1.15: sl = px * 1.15
        if sl < px * 1.03: sl = px * 1.03
        tp1 = px - (sl - px) * 1.5
        tp2 = px - (sl - px) * 2.5
        tp3 = px - (sl - px) * 4.0
    else:
        sl = tp1 = tp2 = tp3 = 0

    rr = calc_risk_reward(px, sl, tp1, tp2, tp3, best_dir) if best_dir != "SKIP" else {}

    return {
        "symbol": f"{name}/USDT",
        "price": px,
        "change_24h": ch,
        "phase": phase,
        "direction": best_dir,
        "score": best_score,
        "grade": grade,
        "confidence": best_conf,
        "long_score": long_score,
        "short_score": short_score,
        "indicators": {"rsi": round(rv, 1), "bb_pos": round(bb_pos, 1), "macd_hist": round(macd_hist, 6), "atr_pct": round(atr_pct, 1), "mom_7d": round(mom_7d, 1), "vol_ratio": round(vol_ratio, 2)},
        "entry_params": {"entry": round(px, 6), "sl": round(sl, 6), "tp1": round(tp1, 6), "tp2": round(tp2, 6), "tp3": round(tp3, 6)},
        "rr": rr,
        "reasons": best_reasons,
    }
