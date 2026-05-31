"""
main.py — Watchlist Analysis Agent API

Endpoints:
  GET  /health     — health check
  POST /analyze    — analyze single coin (raw indicators + score)
  POST /batch      — analyze watchlist (batch)
  POST /hermes     — full analysis with LLM verdict via OpenRouter
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

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
HERMES_MODEL = os.getenv("HERMES_MODEL", "openrouter/owl-alpha")

API_KEY = os.getenv("API_KEY", "")


# ─── API Key Auth ─────────────────────────────────────────────────────

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


async def verify_api_key(key: str = Depends(api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )
    return key


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
    """Full analysis with LLM verdict"""
    prompt: str = "Проанализируй монету и дай вердикт"
    symbol: Optional[str] = None
    analysis_data: Optional[dict] = None
    deposit: float = 1000.0
    amount: float = 10.0
    send_telegram: bool = False


# ─── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/analyze", dependencies=[Depends(verify_api_key)])
async def analyze(req: AnalyzeRequest):
    """Анализ одной монеты — сырые данные + скоринг"""
    try:
        result = await analyze_coin(req.symbol, req.deposit, req.amount)
        return result
    except Exception as e:
        log.error(f"Error analyzing {req.symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/batch", dependencies=[Depends(verify_api_key)])
async def batch_analyze(req: BatchRequest):
    """Анализ нескольких монет (watchlist)"""
    import httpx

    results = []
    for sym in req.symbols:
        try:
            r = await analyze_coin(sym, req.deposit, req.amount)
            results.append(r)
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return {"results": results, "count": len(results)}


@app.post("/hermes", dependencies=[Depends(verify_api_key)])
async def hermes_analyze(req: HermesRequest):
    """
    Полный анализ с LLM-вердиктом:
    1. Считаем индикаторы (engine.py)
    2. Формируем промпт
    3. Дергаем OpenRouter API
    4. Опционально отправляем в Telegram
    """
    import httpx

    analysis_data = req.analysis_data

    # Если symbol передан — считаем сами
    if req.symbol and not analysis_data:
        analysis_data = await analyze_coin(req.symbol, req.deposit, req.amount)

    if not analysis_data:
        raise HTTPException(400, "symbol or analysis_data required")

    # Формируем промпт
    prompt = build_hermes_prompt(req.prompt, analysis_data, req.deposit)

    # Вызываем OpenRouter
    llm_response = None
    if OPENROUTER_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": HERMES_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Ты — критичный трейдер-аналитик. Даёшь честные рекомендации. Никаких 'может взлететь'. SL всегда. Ниже B = SKIP.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 1000,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                llm_response = data["choices"][0]["message"]["content"]
        except Exception as e:
            log.error(f"OpenRouter error: {e}")
            llm_response = f"LLM error: {e}"
    else:
        llm_response = "OPENROUTER_API_KEY not set — skipping LLM call"

    return {
        "agent": "binance-watchlist-v1",
        "analysis": analysis_data,
        "llm_verdict": llm_response,
    }


def build_hermes_prompt(user_prompt: str, analysis: dict, deposit: float) -> str:
    """Формирует структурированный промпт для LLM"""
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
{sym} | ${price}
Direction: SKIP
Rating: {rating} ({score}/100)
Reason: {skip_reason}"""
    else:
        verdict_section = f"""
ENTRY VERDICT
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

    return f"""Данные анализа по WATCHLIST_INSTRUCTION.md:

{verdict_section}

Indicators:
{ind_str}

Score Breakdown:
{br_str}

Deposit: ${deposit}
Запрос: {user_prompt}

Дай:
1. Краткий вердикт (1-2 предложения)
2. Key risks (2-3 пункта)
3. Рекомендацию: входить или нет
Будь критичен. Никакого "может взлететь". SL всегда. Ниже B = SKIP.
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")
