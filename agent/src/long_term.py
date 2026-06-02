"""
long_term.py — Long-Term Position Analysis Engine

Для позиций от недели и дольше.

Отличия от engine.py (скальперский):
- Мультитаймфреймный анализ: 1d + 1w + 1M
- Широкие SL: 15-25%
- Фундаментальные фильтры: структура тренда, объём на проливках
- Больший вес тренда на больших ТФ
- Размер позиции: макс 20% депозита
- Меньше штрафов за моментум
- R:R начинается с 2:1 (не 1.5:1)

ВСЕ данные из публичного Binance Futures API.
"""

import math
import httpx
import json
from typing import Optional

BASE = "https://fapi.binance.com"

# ─── STEP 1: Получение данных ────────────────────────────────────────

async def fetch_json(url: str, params: dict = None) -> dict | list:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def get_klines(symbol: str, interval: str = "1d", limit: int = 100) -> list:
    """Получить свечи. interval: 1h, 4h, 1d, 1w, 1M"""
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


# ─── STEP 2: Индикаторы (те же что в engine.py + недельные/месячные) ──

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


def calc_momentum(close: list, period: int) -> float:
    """Momentum за period свечей в %."""
    if len(close) < period + 1:
        return 0.0
    return (close[-1] / close[-period] - 1) * 100


def calc_volume_analysis(volume: list, close: list, period: int = 20) -> tuple:
    """avg_vol в USDT, vol_ratio"""
    if len(volume) < period:
        return 0.0, 1.0
    vol_usdt = [volume[i] * close[i] for i in range(len(volume))]
    avg_vol = sum(vol_usdt[-period:]) / period
    return avg_vol, volume[-1] * close[-1] / avg_vol if avg_vol > 0 else 1.0


# ─── STEP 3: Мультитаймфреймный тренд ─────────────────────────────────

def analyze_trend_multi_tf(daily: dict, weekly: dict, monthly: dict) -> dict:
    """
    Анализ тренда на трёх ТФ.
    Возвращает: direction, strength (0-100), tf_alignment
    """
    d_close = daily["close"]
    w_close = weekly["close"]
    m_close = monthly["close"]

    trends = {}

    # Дневной ТФ
    if len(d_close) >= 50:
        d_sma20 = sma(d_close, 20)
        d_sma50 = sma(d_close, 50)
        d_price = d_close[-1]
        d_trend = "UP" if d_price > d_sma20 > d_sma50 else ("DOWN" if d_price < d_sma20 < d_sma50 else "SIDE")
        d_strength = min(100, abs(d_price - d_sma50) / d_sma50 * 100 * 2)
    else:
        d_trend = "SIDE"
        d_strength = 0

    # Недельный ТФ
    if len(w_close) >= 50:
        w_sma20 = sma(w_close, 20)
        w_sma50 = sma(w_close, 50)
        w_price = w_close[-1]
        w_trend = "UP" if w_price > w_sma20 > w_sma50 else ("DOWN" if w_price < w_sma20 < w_sma50 else "SIDE")
        w_strength = min(100, abs(w_price - w_sma50) / w_sma50 * 100 * 2)
    else:
        w_trend = "SIDE"
        w_strength = 0

    # Месячный ТФ
    if len(m_close) >= 12:
        m_sma6 = sma(m_close, 6)
        m_sma12 = sma(m_close, 12)
        m_price = m_close[-1]
        m_trend = "UP" if m_price > m_sma6 > m_sma12 else ("DOWN" if m_price < m_sma6 < m_sma12 else "SIDE")
        m_strength = min(100, abs(m_price - m_sma12) / m_sma12 * 100 * 2)
    else:
        m_trend = "SIDE"
        m_strength = 0

    # Выравнивание ТФ (все 3 в одном направлении = сильнейший сигнал)
    if d_trend == w_trend == m_trend and d_trend != "SIDE":
        alignment = 100
        direction = d_trend
    elif d_trend == w_trend and d_trend != "SIDE":
        alignment = 70
        direction = d_trend
    elif d_trend == m_trend and d_trend != "SIDE":
        alignment = 60
        direction = d_trend
    elif w_trend == m_trend and w_trend != "SIDE":
        alignment = 50
        direction = w_trend
    else:
        alignment = 20
        direction = d_trend if d_trend != "SIDE" else "SIDE"

    return {
        "daily": {"trend": d_trend, "strength": round(d_strength, 1)},
        "weekly": {"trend": w_trend, "strength": round(w_strength, 1)},
        "monthly": {"trend": m_trend, "strength": round(m_strength, 1)},
        "alignment": alignment,
        "direction": direction,
        "combined_strength": round((d_strength + w_strength + m_strength) / 3, 1),
    }


# ─── STEP 4: Скоринг для долгосрочных позиций ─────────────────────────

def score_trend(trend_data: dict, direction: str) -> int:
    """Оценка тренда (макс 30 баллов для долгосрочных)."""
    score = 0

    # Alignment — главный фактор для лонг-терма
    alignment = trend_data["alignment"]
    if alignment >= 80:
        score += 15  # Все ТФ выровнены
    elif alignment >= 60:
        score += 10
    elif alignment >= 40:
        score += 5
    else:
        score -= 5  # ТФ расходятся — слабый сигнал

    # Direction match
    trend_dir = trend_data["direction"]
    if trend_dir == direction:
        score += 10
    elif trend_dir == "SIDE":
        score += 2
    else:
        score -= 10  # Тренд против

    # Combined strength
    strength = trend_data["combined_strength"]
    if strength > 20:
        score += 5

    return max(-15, min(30, score))


def score_rsi_long_term(rsi_val: float, direction: str) -> int:
    """
    RSI для долгосрочных — мягче пороги.
    Не требуем экстремальных значений, ищем зоны.
    """
    if direction == "LONG":
        if rsi_val < 25: return 20  # Глубокая перепроданность
        elif rsi_val < 35: return 18
        elif rsi_val < 45: return 14
        elif rsi_val < 55: return 10  # Нейтральная зона тоже ок для долгосрочных
        elif rsi_val < 65: return 5
        elif rsi_val < 75: return 2
        else: return 0  # Перекуплен для долгосрочного лонга
    else:  # SHORT
        if rsi_val > 75: return 20
        elif rsi_val > 65: return 18
        elif rsi_val > 55: return 14
        elif rsi_val > 45: return 10
        elif rsi_val < 25: return 0
        else: return 2


def score_bb_long_term(bb_pos: float, direction: str) -> int:
    """BB для долгосрочных — мягче."""
    if direction == "LONG":
        if bb_pos < 15: return 20
        elif bb_pos < 30: return 16
        elif bb_pos < 40: return 12
        elif bb_pos < 50: return 8
        elif bb_pos < 60: return 4
        else: return 0
    else:  # SHORT
        if bb_pos > 85: return 20
        elif bb_pos > 70: return 16
        elif bb_pos > 60: return 12
        elif bb_pos > 50: return 8
        elif bb_pos < 40: return 4
        else: return 0


def score_macd_long_term(macd_hist: float, price: float, direction: str) -> int:
    """MACD для долосрочных — смотрим на разворот."""
    macd_norm = macd_hist / price * 100 if price > 0 else 0

    if direction == "LONG":
        if macd_norm > 2.0: return 20
        elif macd_norm > 1.0: return 16
        elif macd_norm > 0.3: return 12
        elif macd_norm > 0: return 8
        elif macd_norm > -0.5: return 4  # Лёгкий минус — ещё ок
        else: return 0
    else:  # SHORT
        if macd_norm < -2.0: return 20
        elif macd_norm < -1.0: return 16
        elif macd_norm < -0.3: return 12
        elif macd_norm < 0: return 8
        elif macd_norm < 0.5: return 4
        else: return 0


def score_volume_long_term(avg_vol_usdt: float, vol_ratio: float, direction: str) -> int:
    """
    Volume для долгосрочных — важна ликвидность.
    Низкий объём = шортить/лонгить опасно из-за манипуляций.
    """
    score = 0

    # Минимальная ликвидность
    if avg_vol_usdt > 10_000_000: score += 10
    elif avg_vol_usdt > 5_000_000: score += 8
    elif avg_vol_usdt > 1_000_000: score += 5
    elif avg_vol_usdt > 500_000: score += 2
    else: score -= 10  # Опасно — низкая ликвидность

    # Volume confirmation
    if vol_ratio > 1.5: score += 5  # Рост объёма подтверждает движение
    elif vol_ratio > 1.0: score += 3
    elif vol_ratio > 0.5: score += 0
    else: score -= 3  # Нет объёма

    return score


def score_momentum_long_term(mom_7d, mom_30d, direction):
    """Momentum для долгосрочных — умеренный рост лучше параболы."""
    score = 0

    if direction == "LONG":
        # Для долгосрочного лонга: умеренный рост 30d лучше параболы 7d
        if 10 < mom_30d < 50: score += 10  # Здоровый рост
        elif 5 < mom_30d < 70: score += 6
        elif mom_30d > 70: score -= 5  # Слишком перегрет
        elif mom_30d > 0: score += 3
        else: score += mom_30d / 10  # Штраф за падение

        # 7d momentum — не штрафуем за перегрев
        if mom_7d > 0: score += 3
        elif mom_7d > -10: score += 1
        else: score -= 2  # Коррекция 7d — штраф

    else:  # SHORT
        # Для долгосрочного шорта: параболический рост 30d — сигнал
        if mom_30d > 100: score += 10  # Пузырь
        elif mom_30d > 50: score += 8
        elif mom_30d > 20: score += 5
        elif mom_30d > 0: score += 2
        else: score -= 5  # Падающий актив — шорт опасен

        # 7d коррекция — бонус для шорта
        if mom_7d < -10: score += 5
        elif mom_7d < 0: score += 3

    return max(-10, min(15, score))


# ─── STEP 5: Штрафы для долгосрочных ──────────────────────────────────

def calc_penalties_long_term(symbol: str, avg_vol_usdt: float, atr_pct: float,
                              mom_30d: float, rsi: float) -> list:
    """Штрафы для долгосрочных — мягче чем для скальпинга."""
    p = []

    # Очень низкая ликвидность — критично для долгосрочных
    if avg_vol_usdt < 500_000:
        p.append(("Very Low Liquidity", -20))

    # Extreme ATR — риск манипуляций
    if atr_pct > 20:
        p.append(("Extreme Volatility", -10))

    # Параболический рост — пузырь
    if mom_30d > 200:
        p.append(("Bubble Risk", -10))

    # RSI экстрем — но не блокируем
    if rsi > 85 or rsi < 15:
        p.append(("Extreme RSI", -5))

    return p


# ─── STEP 6: Рейтинг ─────────────────────────────────────────────────

def score_to_rating(score: int) -> str:
    if score >= 80: return "A"
    elif score >= 65: return "B"
    elif score >= 50: return "C"
    elif score >= 35: return "D"
    else: return "F"


# ─── STEP 7: Entry params для долгосрочных ────────────────────────────

def calc_entry_params_long_term(price, atr, direction: str = "LONG",
                                 deposit: float = 1000.0, amount: float = 10.0) -> dict:
    """
    Entry params для долгосрочных:
    - SL: ATR × 3-4 (шире)
    - TP: R:R 2:1 / 3:1 / 5:1 (дальше)
    - Size: макс 20% депозита
    - Leverage: 1-3x (меньше)
    """
    risk = deposit * 0.02  # 2% риск

    if direction == "LONG":
        sl = price - atr * 3.0  # Шире SL
        sl_pct = abs(price - sl) / price * 100
        if sl_pct < 10: sl = price * 0.90  # Мин 10% для долгосрочных
        elif sl_pct > 25: sl = price * 0.75  # Макс 25%
        sl_dist = price - sl
        tp1 = price + sl_dist * 2.0  # R:R 2:1
        tp2 = price + sl_dist * 3.0  # R:R 3:1
        tp3 = price + sl_dist * 5.0  # R:R 5:1
    else:  # SHORT
        sl = price + atr * 3.0
        sl_pct = abs(sl - price) / price * 100
        if sl_pct < 10: sl = price * 1.10
        elif sl_pct > 25: sl = price * 1.25
        sl_dist = sl - price
        tp1 = price - sl_dist * 2.0
        tp2 = price - sl_dist * 3.0
        tp3 = price - sl_dist * 5.0

    pos_value = risk / (sl_dist / price) if sl_dist > 0 else 0
    if pos_value < 10: pos_value = 10
    if pos_value > deposit * 0.20: pos_value = deposit * 0.20  # Макс 20% депозита

    leverage = max(1, min(3, round(pos_value / amount)))  # Макс 3x

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
        "rr_tp1": "2:1",
        "rr_tp2": "3:1",
        "rr_tp3": "5:1",
    }


# ─── STEP 8: Danger Score для долгосрочных ────────────────────────────

def calc_danger_score_long_term(price, rsi, bb_pos, macd_hist, mom_7d, mom_30d,
                                 vol_ratio, trend_data, direction) -> int:
    """Danger score для долгосрочных — фокус на структуру."""
    d = 0

    # Расхождение ТФ — главный риск для долгосрочных
    if trend_data["alignment"] < 40:
        d += 30  # ТФ расходятся — опасно
    elif trend_data["alignment"] < 60:
        d += 15

    # Тренд против
    if trend_data["direction"] != direction and trend_data["direction"] != "SIDE":
        d += 20

    # RSI экстрем
    if rsi > 80: d += 15
    elif rsi < 20: d += 15

    # BB экстрем
    if bb_pos > 95 or bb_pos < 5: d += 10

    # Парабола
    if mom_30d > 100: d += 15
    elif mom_30d > 50: d += 8

    # Низкий объём
    if vol_ratio < 0.3: d += 10

    return min(d, 100)


# ─── ОСНОВНОЙ PIPELINE ───────────────────────────────────────────────

async def analyze_long_term(
    symbol: str,
    deposit: float = 1000.0,
    amount: float = 10.0,
) -> dict:
    """
    Полный анализ для долгосрочной позиции.
    Мультитаймфреймный: 1d + 1w + 1M.
    """
    sym = symbol.upper().replace("USDT", "")

    # Fetch all timeframes
    daily_klines = await get_klines(sym, "1d", 100)
    weekly_klines = await get_klines(sym, "1w", 100)
    monthly_klines = await get_klines(sym, "1M", 50)

    daily = parse_klines(daily_klines)
    weekly = parse_klines(weekly_klines)
    monthly = parse_klines(monthly_klines)

    price = daily["close"][-1]

    # ─── Multi-TF Trend Analysis ───
    trend = analyze_trend_multi_tf(daily, weekly, monthly)

    # ─── Daily Indicators ───
    sma7 = sma(daily["close"], 7)
    sma20 = sma(daily["close"], 20)
    sma50 = sma(daily["close"], 50)
    rsi = calc_rsi(daily["close"])
    macd_line, macd_signal, macd_hist = calc_macd(daily["close"])
    bb_upper, bb_middle, bb_lower, bb_pos = calc_bb(daily["close"])
    atr = calc_atr(daily["high"], daily["low"], daily["close"])
    atr_pct = atr / price * 100 if price > 0 else 0
    mom_7d = calc_momentum(daily["close"], 7)
    mom_30d = calc_momentum(daily["close"], 30)
    avg_vol, vol_ratio = calc_volume_analysis(daily["volume"], daily["close"])

    # ─── Score для обоих направлений ───
    long_score = (
        score_trend(trend, "LONG") +
        score_rsi_long_term(rsi, "LONG") +
        score_bb_long_term(bb_pos, "LONG") +
        score_macd_long_term(macd_hist, price, "LONG") +
        score_volume_long_term(avg_vol, vol_ratio, "LONG") +
        score_momentum_long_term(mom_7d, mom_30d, "LONG")
    )

    short_score = (
        score_trend(trend, "SHORT") +
        score_rsi_long_term(rsi, "SHORT") +
        score_bb_long_term(bb_pos, "SHORT") +
        score_macd_long_term(macd_hist, price, "SHORT") +
        score_volume_long_term(avg_vol, vol_ratio, "SHORT") +
        score_momentum_long_term(mom_7d, mom_30d, "SHORT")
    )

    # Penalties
    penalties = calc_penalties_long_term(sym, avg_vol, atr_pct, mom_30d, rsi)
    total_penalty = sum(p[1] for p in penalties)

    long_final = max(0, min(100, long_score + total_penalty))
    short_final = max(0, min(100, short_score + total_penalty))

    # Выбираем лучшее
    if long_final >= short_final:
        direction, final_score = "LONG", long_final
    else:
        direction, final_score = "SHORT", short_final

    rating = score_to_rating(final_score)

    # Danger
    danger = calc_danger_score_long_term(
        price, rsi, bb_pos, macd_hist, mom_7d, mom_30d, vol_ratio, trend, direction
    )
    dl = "LOW" if danger < 30 else ("MEDIUM" if danger < 60 else "HIGH")

    result = {
        "symbol": f"{sym}/USDT",
        "price": price,
        "direction": direction,
        "rating": rating,
        "score": final_score,
        "danger": danger,
        "danger_level": dl,
        "trend": trend,
        "indicators": {
            "rsi": round(rsi, 1),
            "bb_pos": round(bb_pos, 1),
            "macd_hist": round(macd_hist, 6),
            "mom_7d": round(mom_7d, 1),
            "mom_30d": round(mom_30d, 1),
            "vol_ratio": round(vol_ratio, 2),
            "avg_vol_usdt": round(avg_vol, 0),
            "atr": round(atr, 6),
            "atr_pct": round(atr_pct, 1),
            "sma7": round(sma7, 6),
            "sma20": round(sma20, 6),
            "sma50": round(sma50, 6),
        },
        "score_breakdown": {
            "long": {
                "trend": score_trend(trend, "LONG"),
                "rsi": score_rsi_long_term(rsi, "LONG"),
                "bb": score_bb_long_term(bb_pos, "LONG"),
                "macd": score_macd_long_term(macd_hist, price, "LONG"),
                "volume": score_volume_long_term(avg_vol, vol_ratio, "LONG"),
                "momentum": score_momentum_long_term(mom_7d, mom_30d, "LONG"),
                "raw": long_score,
                "final": long_final,
            },
            "short": {
                "trend": score_trend(trend, "SHORT"),
                "rsi": score_rsi_long_term(rsi, "SHORT"),
                "bb": score_bb_long_term(bb_pos, "SHORT"),
                "macd": score_macd_long_term(macd_hist, price, "SHORT"),
                "volume": score_volume_long_term(avg_vol, vol_ratio, "SHORT"),
                "momentum": score_momentum_long_term(mom_7d, mom_30d, "SHORT"),
                "raw": short_score,
                "final": short_final,
            },
            "penalties": {p[0]: p[1] for p in penalties},
            "total_penalty": total_penalty,
        },
    }

    # Entry params для A/B рейтингов
    if rating in ("A", "B"):
        result["skip"] = False
        result["entry_params"] = calc_entry_params_long_term(price, atr, direction, deposit, amount)
    else:
        result["skip"] = True
        result["skip_reason"] = f"Score {final_score}/100 below B threshold (65)"

    return result


# ─── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    deposit = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0

    async def main():
        result = await analyze_long_term(symbol, deposit)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(main())
