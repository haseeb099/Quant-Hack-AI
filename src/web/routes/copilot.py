"""Read-only copilot API — analyze symbols and chat (SSE)."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.copilot.analyzer import CopilotAnalyzer
from src.copilot.models import ChatRequest, SymbolAnalysisResponse
from src.web.runtime_state import read_state

router = APIRouter(tags=["copilot"])

_analyzer = CopilotAnalyzer()
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW_SEC = 60.0


def _check_rate_limit(client_id: str) -> None:
    now = time.time()
    bucket = _rate_buckets[client_id]
    _rate_buckets[client_id] = [t for t in bucket if now - t < _RATE_WINDOW_SEC]
    if len(_rate_buckets[client_id]) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Copilot rate limit — max 10 messages per minute")
    _rate_buckets[client_id].append(now)


@router.post("/api/copilot/analyze-symbol", response_model=SymbolAnalysisResponse)
def analyze_symbol(
    request: Request,
    symbol: str = Query(..., min_length=3),
    direction: str = Query("BUY", pattern="^(BUY|SELL|buy|sell)$"),
    volume: float = Query(0.01, gt=0, le=100),
    use_llm: bool = Query(True),
) -> SymbolAnalysisResponse:
    _check_rate_limit(request.client.host if request.client else "local")
    return _analyzer.analyze_symbol(
        symbol=symbol.strip(),
        volume=volume,
        direction=direction.upper(),
        state=read_state(),
        use_llm=use_llm,
    )


@router.post("/api/copilot/chat")
async def copilot_chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """SSE stream: citations → analysis chunks → done. Read-only — no trade execution."""
    _check_rate_limit(request.client.host if request.client else "local")

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start", "message": "Analyzing…"})

        result_reply, analysis = _analyzer.chat(body.message, symbol=body.symbol, state=read_state(), use_llm=True)

        if analysis is None:
            yield _sse({"type": "text", "content": result_reply})
            yield _sse({"type": "done", "analysis": None})
            return

        yield _sse({
            "type": "citations",
            "data_citations": [c.model_dump() for c in analysis.data_citations],
        })

        if analysis.refused:
            yield _sse({"type": "refusal", "reason": analysis.refusal_reason, "summary": analysis.summary})
            yield _sse({"type": "done", "analysis": analysis.model_dump()})
            return

        # Stream summary in sentence chunks for UX
        for sentence in _chunk_sentences(analysis.summary):
            yield _sse({"type": "text", "content": sentence + " "})
            await _async_sleep(0.02)

        yield _sse({
            "type": "analysis",
            "verdict": analysis.verdict,
            "confidence": analysis.confidence,
            "risks": analysis.risks,
            "trade_check": analysis.trade_check,
            "provider": analysis.provider,
        })
        yield _sse({"type": "done", "analysis": analysis.model_dump()})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def _chunk_sentences(text: str) -> list[str]:
    parts = []
    for segment in text.replace("! ", "!|").replace("? ", "?|").replace(". ", ".|").split("|"):
        segment = segment.strip()
        if segment:
            parts.append(segment)
    return parts or [text]


async def _async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
