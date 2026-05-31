"""
engine.py — Watchlist Analysis Engine v2
Полный анализ для LONG и SHORT направлений.

ВСЕ данные из публичного Binance Futures API.
Никаких API-ключей не нужны. Rate limit: 1200 req/min.
"""

import math
import httpx
from typing import Optional

BASE = "https://fapi.binance.com"

# ─── STEP 1: Получение данных ────────────────────────────────────────

async def fetch_json(url: str, params: dict = None) -> dict | list:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def get_ticker(symbol: str) -> dict:
    return await fetch_json(f"{BASE}/fapi/v1/ticker/24hr", {"symbol": f"{symbol}USDT"})


async def get_klines(symbol: str, interval: str = "1d", limit: int = 100) -> list:
    return await fetch_json(
        f"{BASE}/fapi/v1/klines",
        {"symbol": f"{symbol}USDT", "interval": interval, "limit": limit},
    )


def parse_klines(klines: list) -> dict:
    return {
        "close": [float(k[4]) for k in klines],
        "high": [float(k[2]) for k in klines],
        "low": [float(k[3]) for k in klines],
        "volume": [float(k[5]) for k in klines],
        "open_time": [k[0] for k in klines],
    }


# ─── STEP 2: Индикаторы ─────────────────────────────────────────────

def sma(data: list, period: int) -> float:
    if len(data) < period:
        return data[-1]
    return sum(data[-period:]) / period


def ema(data: list, period: int) -> list:
    if len(data) < period:
        return [data[-1]]
    multiplier = 2 / (period + 1)
    result = [sum(data[:period]) / period]
    for i in range(period, len(data)):
        result.append(data[i] * multiplier + result[-1] * (1 - multiplier))
    return result


def calc_macd(close: list) -> tuple:
    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    offset = len(ema12) - len(ema26)
    macd_line = [ema12[offset + i] - ema26[i] for i in range(len(ema26))]
    if len(macd_line) < 9:
        return macd_line[-1], macd_line[-1], 0.0
    signal_arr = ema(macd_line, 9)
    signal = signal_arr[-1]
    hist = macd_line[-1] - signal
    return macd_line[-1], signal, hist


def calc_rsi(close: list, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    changes = [close[i] - close[i - 1] for i in range(1, len(close))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calc_bb(close: list, period: int = 20, std_mult: float = 2.0) -> tuple:
    if len(close) < period:
        m = close[-1]
        return m, m, m, 50.0
    window = close[-period:]
    middle = sum(window) / period
    std = math.sqrt(sum((x - middle) ** 2 for x in window) / period)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    rng = upper - lower
    bb_pos = ((close[-1] - lower) / rng * 100) if rng > 0 else 50.0
    return upper, middle, lower, bb_pos


def calc_atr(high: list, low: list, close: list, period: int = 14) -> float:
    if len(high) < period + 1:
        return (high[-1] - low[-1]) if high else 0.0
    trs = []
    for i in range(1, len(high)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def calc_momentum(close: list) -> tuple:
    mom_7d = (close[-1] / close[-8] - 1) * 100 if len(close) >= 8 else 0.0
    mom_30d = (close[-1] / close[-31] - 1) * 100 if len(close) >= 31 else 0.0
    return mom_7d, mom_30d


def calc_volume_analysis(volume: list, close: list, period: int = 20) -> tuple:
    if len(volume) < period:
        return 0.0, 1.0
    vol_usdt = [volume[i] * close[i] for i in range(len(volume))]
    avg_vol = sum(vol_usdt[-period:]) / period
    return avg_vol, volume[-1] * close[-1] / avg_vol if avg_vol > 0 else 1.0


def pearson_correlation(x: list, y: list) -> float:
    n = min(len(x), len(y))
    if n < 3:
        return 0.0
    x = x[-n:]
    y = y[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx * sy == 0:
        return 0.0
    return cov / (sx * sy)


# ─── MEMECOIN LIST ───────────────────────────────────────────────────

MEMECOINS = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "SATS",
    "BOME", "MEME", "TURBO", "LADYS", "VRA", "TRUMP", "MAGA",
}


def is_memecoin(symbol: str) -> bool:
    s = symbol.upper().replace("USDT", "")
    return s in MEMECOINS


# ─── STEP 3: Направление ─────────────────────────────────────────────

def count_signals(price, rsi_val, bb_pos, macd_hist, sma_vals, mom_7d, vol_ratio) -> int:
    """Суммирует бычьи (+1) и медвежьи (-1) сигналы. Макс +6 / мин -6."""
    score = 0
    # Бычье
    if rsi_val < 35: score += 1
    if bb_pos < 30: score += 1
    if macd_hist > 0: score += 1
    if price > sma_vals[2]: score += 1
    if mom_7d < -5: score += 1
    if vol_ratio > 1.2: score += 1
    # Медвежье
    if rsi_val > 65: score -= 1
    if bb_pos > 70: score -= 1
    if macd_hist < 0: score -= 1
    if price < sma_vals[2]: score -= 1
    if mom_7d > 10: score -= 1
    if vol_ratio < 0.5: score -= 1
    return score


def get_direction(signals_sum: int) -> str:
    """Возвращает LONG, SHORT или SKIP."""
    if signals_sum >= 3:
        return "LONG"
    elif signals_sum <= -3:
        return "SHORT"
    else:
        return "SKIP"


# ─── STEP 4: Entry Quality Score (с поддержкой direction) ────────────

def score_rsi(rsi_val: float, direction: str = "LONG") -> int:
    if direction == "LONG":
        if rsi_val < 20: return 20
        elif rsi_val < 30: return 18
        elif rsi_val < 40: return 14
        elif rsi_val < 45: return 10
        elif rsi_val < 55: return 5
        else: return 0
    else:  # SHORT
        if rsi_val > 80: return 20
        elif rsi_val > 70: return 18
        elif rsi_val > 60: return 14
        elif rsi_val > 55: return 10
        elif rsi_val > 45: return 5
        else: return 0


def score_bb(bb_pos: float, direction: str = "LONG") -> int:
    if direction == "LONG":
        if bb_pos < 10: return 20
        elif bb_pos < 20: return 18
        elif bb_pos < 30: return 14
        elif bb_pos < 40: return 8
        elif bb_pos < 50: return 4
        else: return 0
    else:  # SHORT
        if bb_pos > 90: return 20
        elif bb_pos > 80: return 18
        elif bb_pos > 70: return 14
        elif bb_pos > 60: return 8
        elif bb_pos > 50: return 4
        else: return 0


def score_macd(macd_norm: float, price: float, direction: str = "LONG") -> int:
    if direction == "LONG":
        if price > 10:
            thresholds = [(3.0, 20), (2.0, 16), (1.0, 12), (0.5, 8), (0.0, 4)]
        elif price > 1:
            thresholds = [(6.0, 20), (4.0, 16), (2.0, 12), (1.0, 8), (0.0, 4)]
        else:
            thresholds = [(15.0, 20), (10.0, 16), (5.0, 12), (2.0, 8), (0.0, 4)]
        for t, s in thresholds:
            if macd_norm > t:
                return s
        return 0
    else:  # SHORT — инвертировать
        if price > 10:
            thresholds = [(-3.0, 20), (-2.0, 16), (-1.0, 12), (-0.5, 8), (0.0, 4)]
        elif price > 1:
            thresholds = [(-6.0, 20), (-4.0, 16), (-2.0, 12), (-1.0, 8), (0.0, 4)]
        else:
            thresholds = [(-15.0, 20), (-10.0, 16), (-5.0, 12), (-2.0, 8), (0.0, 4)]
        for t, s in thresholds:
            if macd_norm < t:
                return s
        return 0


def score_volume(vol_ratio: float) -> int:
    if vol_ratio > 2.0: return 15
    elif vol_ratio > 1.5: return 13
    elif vol_ratio > 1.2: return 10
    elif vol_ratio > 0.8: return 7
    elif vol_ratio > 0.5: return 3
    else: return 0


def score_sma_trend(price: float, sma_vals: list, direction: str = "LONG") -> int:
    if direction == "LONG":
        above = sum(1 for s in sma_vals if price > s)
        if above == 3: return 15
        elif above == 2: return 11
        elif above == 1: return 5
        else: return 0
    else:  # SHORT
        below = sum(1 for s in sma_vals if price < s)
        if below == 3: return 15
        elif below == 2: return 11
        elif below == 1: return 5
        else: return 0


def score_momentum(mom_7d: float, direction: str = "LONG") -> int:
    if direction == "LONG":
        if mom_7d < -20: return 10
        elif mom_7d < -15: return 8
        elif mom_7d < -10: return 6
        elif mom_7d < -5: return 3
        elif mom_7d < 0: return 1
        else: return 0
    else:  # SHORT
        if mom_7d > 20: return 10
        elif mom_7d > 15: return 8
        elif mom_7d > 10: return 6
        elif mom_7d > 5: return 3
        elif mom_7d > 0: return 1
        else: return 0


# ─── STEP 5: Штрафы ──────────────────────────────────────────────────

def calc_penalties(price, rsi_val, bb_pos, macd_hist, mom_7d,
                   vol_ratio, avg_vol_usdt, atr, atr_pct, symbol: str) -> list:
    p = []
    # Memecoin — штраф, не блокировка
    if is_memecoin(symbol):
        p.append(("Memecoin Penalty", -20))
    # Low liquidity
    if avg_vol_usdt < 100_000:
        p.append(("Low Liquidity", -15))
    # Extreme ATR
    if atr_pct > 15:
        p.append(("Extreme ATR", -10))
    # Already run — только штраф, не блокировка
    if mom_7d > 25:
        p.append(("Already Run", -15))
    # Dead zone
    if 40 < rsi_val < 55 and 40 < bb_pos < 60 and abs(macd_hist) < 0.001 * price:
        p.append(("Dead Zone", -10))
    # Momentum run — штраф для лонга
    if mom_7d > 15:
        p.append(("Momentum Run", -5))
    return p


# ─── STEP 6: Рейтинг ─────────────────────────────────────────────────

def score_to_rating(score: int) -> str:
    if score >= 80: return "A"
    elif score >= 65: return "B"
    elif score >= 50: return "C"
    elif score >= 35: return "D"
    else: return "F"


# ─── STEP 7: Параметры входа (LONG + SHORT) ──────────────────────────

def calc_entry_params(price, atr, direction: str = "LONG",
                      deposit: float = 1000.0, amount: float = 10.0) -> dict:
    risk = deposit * 0.02

    if direction == "LONG":
        sl = price - atr * 1.5
        sl_pct = abs(price - sl) / price * 100
        if sl_pct < 3: sl = price * 0.97
        elif sl_pct > 15: sl = price * 0.85
        sl_dist = price - sl
        tp1 = price + sl_dist * 1.5
        tp2 = price + sl_dist * 2.5
        tp3 = price + sl_dist * 4.0
    else:  # SHORT
        sl = price + atr * 1.5
        sl_pct = abs(sl - price) / price * 100
        if sl_pct < 3: sl = price * 1.03
        elif sl_pct > 15: sl = price * 1.15
        sl_dist = sl - price
        tp1 = price - sl_dist * 1.5
        tp2 = price - sl_dist * 2.5
        tp3 = price - sl_dist * 4.0

    pos_value = risk / (sl_dist / price) if sl_dist > 0 else 0
    if pos_value < 10: pos_value = 10
    if pos_value > deposit * 0.5: pos_value = deposit * 0.5
    leverage = max(1, min(5, round(pos_value / amount)))

    return {
        "entry": round(price, 6),
        "sl": round(sl, 6),
        "sl_pct": round(sl_pct, 1),
        "tp1": round(tp1, 6),
        "tp1_pct": round((tp1 / price - 1) * 100, 1),
        "tp2": round(tp2, 6),
        "tp2_pct": round((tp2 / price - 1) * 100, 1),
        "tp3": round(tp3, 6),
        "tp3_pct": round((tp3 / price - 1) * 100, 1),
        "size_usdt": round(pos_value, 2),
        "leverage": leverage,
        "rr_tp1": "1.5:1",
        "rr_tp3": "4:1",
    }


# ─── STEP 8: Danger Score (LONG + SHORT) ─────────────────────────────

def calc_danger_score(price, rsi_val, bb_pos, macd_hist, mom_7d, vol_ratio,
                      sma7, sma20, sma50, direction: str = "LONG") -> int:
    d = 0
    if rsi_val > 60: d += 25
    if rsi_val < 20: d += 20
    if bb_pos > 90: d += 20
    if bb_pos < 10: d += 20
    if macd_hist < 0 and direction == "LONG": d += 15
    if macd_hist > 0 and direction == "SHORT": d += 15
    if price < sma20 and direction == "LONG": d += 10
    if price > sma20 and direction == "SHORT": d += 10
    if price < sma50 and direction == "LONG": d += 10
    if price > sma50 and direction == "SHORT": d += 10
    if mom_7d > 20: d += 10
    if mom_7d < -20: d += 15
    if vol_ratio < 0.5: d += 5
    return min(d, 100)


def danger_level(score: int) -> str:
    if score < 30: return "LOW"
    elif score < 60: return "MEDIUM"
    else: return "HIGH"


# ─── ОСНОВНОЙ PIPELINE ───────────────────────────────────────────────

async def analyze_coin(
    symbol: str,
    deposit: float = 1000.0,
    amount: float = 10.0,
    btc_correlation: bool = True,
) -> dict:
    """
    Полный анализ одной монеты. Считает score для LONG и SHORT,
    выбирает лучшее направление.
    """
    sym = symbol.upper().replace("USDT", "")

    # BTC momentum check
    btc_data = None
    if btc_correlation:
        try:
            btc_klines = await get_klines("BTC", "1d", 100)
            btc_data = parse_klines(btc_klines)
            btc_mom7 = (btc_data["close"][-1] / btc_data["close"][-8] - 1) * 100
            if btc_mom7 < -10:
                return {
                    "symbol": f"{sym}/USDT",
                    "skip": True,
                    "skip_reason": f"BTC falling (MOM_7d={btc_mom7:.1f}%), market risk",
                    "direction": "SKIP",
                    "rating": "F",
                    "score": 0,
                }
        except Exception:
            pass

    # Fetch data
    klines = await get_klines(sym, "1d", 100)
    data = parse_klines(klines)
    price = data["close"][-1]

    # Indicators
    sma7 = sma(data["close"], 7)
    sma20 = sma(data["close"], 20)
    sma50 = sma(data["close"], 50)
    rsi = calc_rsi(data["close"])
    macd_line, macd_signal, macd_hist = calc_macd(data["close"])
    bb_upper, bb_middle, bb_lower, bb_pos = calc_bb(data["close"])
    atr = calc_atr(data["high"], data["low"], data["close"])
    atr_pct = atr / price * 100 if price > 0 else 0
    mom_7d, mom_30d = calc_momentum(data["close"])
    avg_vol, vol_ratio = calc_volume_analysis(data["volume"], data["close"])
    ath, atl, drop_ath = calc_ath_atl(data["high"], data["low"], price)

    # BTC correlation
    btc_corr = None
    if btc_data:
        btc_corr = pearson_correlation(data["close"][-30:], btc_data["close"][-30:])

    # Signals count
    signals_sum = count_signals(price, rsi, bb_pos, macd_hist, [sma7, sma20, sma50], mom_7d, vol_ratio)

    # ─── Score для обоих направлений ───
    macd_norm = macd_hist / price * 100 if price > 0 else 0

    long_score = (
        score_rsi(rsi, "LONG") +
        score_bb(bb_pos, "LONG") +
        score_macd(macd_norm, price, "LONG") +
        score_volume(vol_ratio) +
        score_sma_trend(price, [sma7, sma20, sma50], "LONG") +
        score_momentum(mom_7d, "LONG")
    )

    short_score = (
        score_rsi(rsi, "SHORT") +
        score_bb(bb_pos, "SHORT") +
        score_macd(macd_norm, price, "SHORT") +
        score_volume(vol_ratio) +
        score_sma_trend(price, [sma7, sma20, sma50], "SHORT") +
        score_momentum(mom_7d, "SHORT")
    )

    # Penalties (одинаковые для обоих)
    penalties = calc_penalties(
        price, rsi, bb_pos, macd_hist, mom_7d,
        vol_ratio, avg_vol, atr, atr_pct, sym,
    )
    total_penalty = sum(p[1] for p in penalties)

    long_final = max(0, min(100, long_score + total_penalty))
    short_final = max(0, min(100, short_score + total_penalty))

    # Блокировка: недостаточно сигналов
    if signals_sum < 3:
        long_final = min(long_final, 49)  # Force SKIP для лонга
    if signals_sum > -3:
        short_final = min(short_final, 49)  # Force SKIP для шорта

    # Выбираем лучшее направление
    if long_final >= short_final:
        final_score = long_final
        direction = "LONG"
    else:
        final_score = short_final
        direction = "SHORT"

    rating = score_to_rating(final_score)

    # Danger score для выбранного направления
    danger = calc_danger_score(
        price, rsi, bb_pos, macd_hist, mom_7d, vol_ratio,
        sma7, sma20, sma50, direction
    )
    dl = danger_level(danger)

    # Формируем результат
    result = {
        "symbol": f"{sym}/USDT",
        "price": price,
        "direction": direction,
        "rating": rating,
        "score": final_score,
        "danger": dl,
        "danger_score": danger,
        "indicators": {
            "rsi": round(rsi, 1),
            "bb_pos": round(bb_pos, 1),
            "macd_hist": round(macd_hist, 6),
            "mom_7d": round(mom_7d, 1),
            "mom_30d": round(mom_30d, 1),
            "vol_ratio": round(vol_ratio, 2),
            "sma7": round(sma7, 4),
            "sma20": round(sma20, 4),
            "sma50": round(sma50, 4),
            "atr": round(atr, 4),
            "atr_pct": round(atr_pct, 1),
            "btc_correlation": round(btc_corr, 3) if btc_corr else None,
        },
        "score_breakdown": {
            "long": {
                "rsi": score_rsi(rsi, "LONG"),
                "bb": score_bb(bb_pos, "LONG"),
                "macd": score_macd(macd_norm, price, "LONG"),
                "volume": score_volume(vol_ratio),
                "sma_trend": score_sma_trend(price, [sma7, sma20, sma50], "LONG"),
                "momentum": score_momentum(mom_7d, "LONG"),
                "raw": long_score,
                "final": long_final,
            },
            "short": {
                "rsi": score_rsi(rsi, "SHORT"),
                "bb": score_bb(bb_pos, "SHORT"),
                "macd": score_macd(macd_norm, price, "SHORT"),
                "volume": score_volume(vol_ratio),
                "sma_trend": score_sma_trend(price, [sma7, sma20, sma50], "SHORT"),
                "momentum": score_momentum(mom_7d, "SHORT"),
                "raw": short_score,
                "final": short_final,
            },
            "penalties": {p[0]: p[1] for p in penalties},
            "total_penalty": total_penalty,
        },
    }

    # SKIP если рейтинг ниже B
    if rating in ("C", "D", "F"):
        result["skip"] = True
        result["skip_reason"] = f"Score {final_score}/100 below B threshold (65)"
        return result

    # Rating A или B — считаем entry params
    result["skip"] = False
    result["entry_params"] = calc_entry_params(price, atr, direction, deposit, amount)

    return result
