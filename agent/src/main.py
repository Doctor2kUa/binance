"""
main.py — Watchlist Analysis Agent API

Endpoints:
  GET  /health     — health check
  POST /analyze    — analyze single coin
  POST /batch      — analyze watchlist (batch)
  POST /hermes     — полноценный запрос через Hermes Agent
"""

import os
import json
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from engine import analyze_coin

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent")

app = FastAPI(title="Binance Watchlist Agent", version="1.0.0")


# ─── Models ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    symbol: str
    deposit: float = 1000.0
    amount: float = 10.0


class BatchRequest(BaseModel):
    symbols: list[str]
    deposit: float = 1000.0
    amount: float = 10.0


class HermesRequest(BaseModel):
    """Полноценный запрос к Hermes Agent — prompt + context"""
    prompt: str
    symbol: Optional[str] = None
    analysis_data: Optional[dict] = None  # pre-computed analysis
    deposit: float = 1000.0
    amount: float = 10.0


# ─── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Анализ одной монеты"""
    try:
        result = await analyze_coin(req.symbol, req.deposit, req.amount)
        return result
    except Exception as e:
        log.error(f"Error analyzing {req.symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch")
async def batch_analyze(req: BatchRequest):
    """Анализ нескольких монет (watchlist)"""
    results = []
    for sym in req.symbols:
        try:
            r = await analyze_coin(sym, req.deposit, req.amount)
            results.append(r)
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
    # Sort: recommended first (A/B), then by score
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return {"results": results, "count": len(results)}


@app.post("/hermes")
async def hermes_analyze(req: HermesRequest):
    """
    Полноценный запрос Hermes Agent:
    1. Сначала делаем расчёт индикаторов (engine.py)
    2. Формируем prompt для LLM с данными анализа
    3. Возвращаем структурированный answer

    В режиме без Hermes CLI (в контейнере) —
    возвращаем данные для LLM в формате, готовом к отправке.
    """
    analysis_data = req.analysis_data

    # Если symbol передан — считаем сами
    if req.symbol and not analysis_data:
        symbol = req.symbol.upper().replace("USDT", "")
        analysis_data = await analyze_coin(symbol, req.deposit, req.amount)

    # Формируем LLM-ready prompt
    prompt = build_hermes_prompt(req.prompt, analysis_data, req.deposit)

    return {
        "agent": "binance-watchlist-v1",
        "analysis": analysis_data,
        "llm_prompt": prompt,
        "usage": "Отправить prompt на OpenRouter API с моделью Hermes",
    }


def build_hermes_prompt(user_prompt: str, analysis: dict, deposit: float) -> str:
    """Формирует структурированный промпт для Hermes/LLM агента"""
    if not analysis:
        return user_prompt

    sym = analysis.get("symbol", "?")
    price = analysis.get("price", "?")
    rating = analysis.get("rating", "?")
    score = analysis.get("score", "?")
    danger = analysis.get("danger", "?")

    indicators = analysis.get("indicators", {})
    breakdown = analysis.get("score_breakdown", {})

    skip_reason = analysis.get("skip_reason", "")
    entry = analysis.get("entry_params", {})

    ind_str = "\n".join(f"  {k}: {v}" for k, v in indicators.items())
    br_str = json.dumps(breakdown, ensure_ascii=False, indent=2)

    if analysis.get("skip"):
        verdict_section = f"""
ENTRY VERDICT
═════════════
{sym} | ${price}
Direction: SKIP
Rating: {rating} ({score}/100)
Reason: {skip_reason}"""
    else:
        verdict_section = f"""
ENTRY VERDICT
═════════════
{sym} | ${price}
Direction: {analysis.get('direction', 'LONG')}
Rating: {rating} ({score}/100)
Risk: {danger}

Entry: ${entry.get('entry', '?')}
SL: ${entry.get('sl', '?')} ({entry.get('sl_pct', '?')}%)
TP1: ${entry.get('tp1', '?')} ({entry.get('tp1_pct', '?')}%) — close 30%
TP2: ${entry.get('tp2', '?')} ({entry.get('tp2_pct', '?')}%) — close 35%
TP3: ${entry.get('tp3', '?')} ({entry.get('tp3_pct', '?')}%) — close 35%
Size: ${entry.get('size_usdt', '?')} | Lev: {entry.get('leverage', '?')}x
R:R TP1: 1.5:1 | R:R TP3: 4:1"""

    return f"""Ты — критичный трейдер-аналитик. Твоя задача: проанализировать данные и дать честный вердикт.

Шаблон отчёта по WATCHLIST_INSTRUCTION.md.

{verdict_section}

Indicators:
{ind_str}

Score Breakdown:
{br_str}

Deposit: ${deposit}
Пользовательский запрос: {user_prompt}

Дай:
1. Краткий вердикт (1-2 предложения)
2. Key risks (2-3 пункта)
3. Рекомендацию: входить или нет, и почему
Будь критичен. Никакого "может взлететь". SL всегда.
"""
