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
    "risk-off", "dovish", "miss", "pressure", "lower",
}
_NEUTRAL = {
    "consolidates", "consolidation", "range-bound", "range", "steady", "tight",
    "session", "liquidity", "await", "catalyst", "thins", "neutral", "unchanged",
}


class SentimentScorer:
    """Scores headline batches into per-symbol sentiment snapshots."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sent_cfg = config.get("sentiment", {})
        self.min_headlines = int(sent_cfg.get("min_headlines", 3))
        self.min_headlines_with_macro = int(sent_cfg.get("min_headlines_with_macro", 1))
        from src.utils.llm_providers import sentiment_llm_enabled

        self.llm_enabled = sentiment_llm_enabled(sent_cfg.get("llm_enabled", True))
        self.lexicon_fallback = sent_cfg.get("lexicon_fallback", True)
        self.llm_budget_per_cycle_usd = float(config.get("llm_budget_per_cycle_usd", 0.10))

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _is_fixture_headline(item: NewsItem) -> bool:
        url = (item.url or "").lower()
        return "example.com/news/" in url

    @staticmethod
    def _headline_lexicon_raw(title: str) -> float:
        lower = title.lower()
        if "low-volatility" in lower or "low volatility" in lower:
            return 0.0
        words = set(re.findall(r"[a-zA-Z]+", lower))
        if words & _NEUTRAL and not (words & _BULLISH or words & _BEARISH):
            return 0.0
        bull = len(words & _BULLISH)
        bear = len(words & _BEARISH)
        if bull == 0 and bear == 0:
            return 0.0
        return (bull - bear) / max(bull + bear, 1)

    def _lexicon_score(self, headlines: list[NewsItem]) -> tuple[float, float, str]:
        if not headlines:
            return 0.0, 0.0, "No headlines available"

        if all(self._is_fixture_headline(item) for item in headlines):
            return 0.0, 0.35, f"Fixture headlines only ({len(headlines)}) — neutral"

        now = datetime.now(timezone.utc)
        weighted_sum = 0.0
        weight_total = 0.0
        for item in headlines:
            raw = self._headline_lexicon_raw(item.title)
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

    def _macro_fallback_score(
        self,
        symbol: str,
        macro_bias: str,
        *,
        usd_strength: str = "neutral",
    ) -> tuple[float, float, str]:
        """Derive a low-confidence sentiment from macro when headlines are unavailable."""
        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        is_metal = symbol in {"XAU/USD", "XAG/USD"}
        is_usd_base = symbol.startswith("USD/")

        score = 0.0
        if macro_bias == "risk_on":
            if is_crypto:
                score = 0.3
            elif is_metal:
                score = 0.15
        elif macro_bias == "risk_off":
            if is_crypto:
                score = -0.3
            elif is_metal:
                score = 0.2
            elif is_usd_base:
                score = 0.15
        elif usd_strength == "strong" and is_metal:
            score = 0.1
        elif usd_strength == "weak" and is_crypto:
            score = 0.1

        confidence = 0.35 if macro_bias != "neutral" else 0.25
        tone = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"
        summary = (
            f"Macro-only {tone} ({macro_bias}, USD {usd_strength}) — "
            "no matching headlines in lookback window"
        )
        return max(-1.0, min(1.0, score)), confidence, summary

    def _llm_score(
        self,
        symbol: str,
        headlines: list[NewsItem],
        *,
        macro_bias: str = "neutral",
    ) -> tuple[float, float, str] | None:
        if not self.llm_enabled:
            return None
        from src.utils.llm_providers import _available_providers, resolve_llm_model

        if not any(_available_providers().values()):
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
        fixture_note = ""
        if headlines and all(self._is_fixture_headline(h) for h in headlines):
            fixture_note = (
                "\nNote: headlines may be placeholder/simulated — score direction only if "
                "titles contain a clear catalyst; otherwise return score near 0 with low confidence.\n"
            )
        prompt = (
            f"You score tradable market sentiment for {symbol} (FX, crypto, or metals).\n"
            f"Macro backdrop: {macro_bias}.\n"
            f"Headlines:\n{titles}\n"
            f"{fixture_note}\n"
            "Rules:\n"
            "- Ignore generic 'consolidation' or 'await data' headlines — neutral score.\n"
            "- Only assign |score| > 0.4 when headlines show a clear directional catalyst.\n"
            "- confidence reflects headline quality and agreement (not macro alone).\n"
            "Return structured sentiment only."
        )

        try:
            model, provider = resolve_llm_model(role="sentiment")
        except RuntimeError:
            return None

        try:
            agent = Agent(model, output_type=SentimentResult)
            result = agent.run_sync(prompt)
            out = result.output
            summary = out.summary or f"{provider} sentiment for {symbol}"
            return out.score, out.confidence, summary
        except Exception:
            logger.warning("LLM sentiment failed for %s", symbol, exc_info=True)
            return None

    def _should_use_llm_first(self, headlines: list[NewsItem]) -> bool:
        from src.utils.llm_providers import sentiment_claude_preferred, sentiment_lexicon_first

        if not self.llm_enabled:
            return False
        if sentiment_claude_preferred():
            return True
        if all(self._is_fixture_headline(h) for h in headlines):
            return sentiment_claude_preferred() or not sentiment_lexicon_first()
        return not sentiment_lexicon_first()

    def score(
        self,
        symbol: str,
        headlines: list[NewsItem],
        macro_bias: str = "neutral",
        *,
        usd_strength: str = "neutral",
    ) -> SentimentSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        required = self.min_headlines
        if macro_bias != "neutral" and len(headlines) < self.min_headlines:
            required = min(self.min_headlines, self.min_headlines_with_macro)

        if len(headlines) < required:
            if len(headlines) == 0 and macro_bias != "neutral":
                score, confidence, summary = self._macro_fallback_score(
                    symbol, macro_bias, usd_strength=usd_strength,
                )
                return SentimentSnapshot(
                    symbol=symbol,
                    score=score,
                    confidence=confidence,
                    headline_count=0,
                    summary=summary,
                    top_headlines=[],
                    macro_bias=macro_bias,
                    fetched_at=now,
                )
            return SentimentSnapshot(
                symbol=symbol,
                score=0.0,
                confidence=0.0,
                headline_count=len(headlines),
                summary=f"Insufficient headlines ({len(headlines)} < {required})",
                top_headlines=headlines[:5],
                macro_bias=macro_bias,
                fetched_at=now,
            )

        llm = None
        use_llm_first = self._should_use_llm_first(headlines)

        if use_llm_first:
            llm = self._llm_score(symbol, headlines, macro_bias=macro_bias)
            if llm:
                score, confidence, summary = llm
            elif self.lexicon_fallback:
                score, confidence, summary = self._lexicon_score(headlines)
            else:
                score, confidence, summary = 0.0, 0.0, "No sentiment method available"
        elif self.lexicon_fallback:
            from src.utils.llm_providers import sentiment_lexicon_first

            lex_score, lex_conf, lex_summary = self._lexicon_score(headlines)
            if sentiment_lexicon_first() and lex_conf >= 0.55 and abs(lex_score) >= 0.15:
                score, confidence, summary = lex_score, lex_conf, lex_summary
            else:
                llm = self._llm_score(symbol, headlines, macro_bias=macro_bias)
                if llm:
                    score, confidence, summary = llm
                else:
                    score, confidence, summary = lex_score, lex_conf, lex_summary
        else:
            llm = self._llm_score(symbol, headlines, macro_bias=macro_bias)
            if llm:
                score, confidence, summary = llm
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
