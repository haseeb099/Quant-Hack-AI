"""Sentiment scoring — LLM with lexicon fallback."""

from __future__ import annotations

import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from src.intelligence.models import NewsItem, SentimentSnapshot

logger = logging.getLogger(__name__)

_BULLISH = {
    "surge", "rally", "gain", "bullish", "breakout", "strong", "rise", "higher",
    "support", "inflow", "optimism", "beat", "hawkish", "safe-haven", "demand",
}
_BEARISH = {
    "drop", "fall", "bearish", "decline", "weak", "selloff", "crash", "fear",
    "risk-off", "dovish", "miss", "pressure", "lower", "volatility", "uncertainty",
}


class SentimentScorer:
    """Scores headline batches into per-symbol sentiment snapshots."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sent_cfg = config.get("sentiment", {})
        self.min_headlines = int(sent_cfg.get("min_headlines", 3))
        self.llm_enabled = sent_cfg.get("llm_enabled", True)
        self.lexicon_fallback = sent_cfg.get("lexicon_fallback", True)

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _lexicon_score(self, headlines: list[NewsItem]) -> tuple[float, float, str]:
        if not headlines:
            return 0.0, 0.0, "No headlines available"

        now = datetime.now(timezone.utc)
        weighted_sum = 0.0
        weight_total = 0.0
        for item in headlines:
            words = set(re.findall(r"[a-zA-Z]+", item.title.lower()))
            bull = len(words & _BULLISH)
            bear = len(words & _BEARISH)
            raw = (bull - bear) / max(bull + bear, 1)
            try:
                age_h = max((now - self._parse_dt(item.published_at)).total_seconds() / 3600, 0.1)
            except ValueError:
                age_h = 1.0
            weight = math.exp(-0.693 * age_h / 1.0)  # half-life 1h
            weighted_sum += raw * weight
            weight_total += weight

        score = weighted_sum / max(weight_total, 1e-6)
        confidence = min(0.4 + 0.1 * len(headlines), 0.85)
        tone = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
        summary = f"Lexicon {tone} tone from {len(headlines)} headlines"
        return max(-1.0, min(1.0, score)), confidence, summary

    def _llm_score(self, symbol: str, headlines: list[NewsItem]) -> tuple[float, float, str] | None:
        if not self.llm_enabled:
            return None
        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("Groq_API_KEY")
        if not api_key:
            return None
        try:
            from pydantic import BaseModel, Field
            from pydantic_ai import Agent
        except ImportError:
            return None

        class SentimentResult(BaseModel):
            score: float = Field(ge=-1, le=1, description="Bearish -1 to bullish +1")
            confidence: float = Field(ge=0, le=1)
            summary: str = ""

        titles = "\n".join(f"- {h.title} ({h.source})" for h in headlines[:10])
        prompt = (
            f"Score market sentiment for {symbol} from these headlines:\n{titles}\n"
            "Return structured sentiment only."
        )
        model = "anthropic:claude-sonnet-4-20250514" if os.getenv("ANTHROPIC_API_KEY") else "openai:llama-3.3-70b-versatile"
        if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("GROQ_API_KEY"):
            os.environ.setdefault("OPENAI_API_KEY", os.getenv("GROQ_API_KEY", ""))
            os.environ.setdefault("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")

        try:
            agent = Agent(model, output_type=SentimentResult)
            result = agent.run_sync(prompt)
            out = result.output
            return out.score, out.confidence, out.summary
        except Exception:
            logger.warning("LLM sentiment failed for %s", symbol, exc_info=True)
            return None

    def score(
        self,
        symbol: str,
        headlines: list[NewsItem],
        macro_bias: str = "neutral",
    ) -> SentimentSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        if len(headlines) < self.min_headlines:
            return SentimentSnapshot(
                symbol=symbol,
                score=0.0,
                confidence=0.0,
                headline_count=len(headlines),
                summary=f"Insufficient headlines ({len(headlines)} < {self.min_headlines})",
                top_headlines=headlines[:5],
                macro_bias=macro_bias,
                fetched_at=now,
            )

        llm = self._llm_score(symbol, headlines)
        if llm:
            score, confidence, summary = llm
        elif self.lexicon_fallback:
            score, confidence, summary = self._lexicon_score(headlines)
        else:
            score, confidence, summary = 0.0, 0.0, "No sentiment method available"

        return SentimentSnapshot(
            symbol=symbol,
            score=score,
            confidence=confidence,
            headline_count=len(headlines),
            summary=summary,
            top_headlines=headlines[:5],
            macro_bias=macro_bias,
            fetched_at=now,
        )
