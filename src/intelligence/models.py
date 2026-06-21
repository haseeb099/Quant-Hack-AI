"""Data models for market intelligence layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published_at: str
    symbol: str = ""
    category: str = ""


@dataclass
class CalendarEvent:
    name: str
    currency: str
    impact: str  # tier_1 | tier_2 | tier_3
    scheduled_at: str  # ISO UTC
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None

    @property
    def tier(self) -> int:
        mapping = {"tier_1": 1, "tier_2": 2, "tier_3": 3}
        return mapping.get(self.impact, 3)


@dataclass
class SentimentSnapshot:
    symbol: str
    score: float  # -1 bearish .. +1 bullish
    confidence: float
    headline_count: int
    summary: str
    top_headlines: list[NewsItem] = field(default_factory=list)
    macro_bias: str = "neutral"
    fetched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "confidence": self.confidence,
            "headline_count": self.headline_count,
            "summary": self.summary,
            "macro_bias": self.macro_bias,
            "fetched_at": self.fetched_at,
            "top_headlines": [
                {
                    "title": h.title,
                    "source": h.source,
                    "url": h.url,
                    "published_at": h.published_at,
                }
                for h in self.top_headlines
            ],
        }


@dataclass
class MacroRegime:
    bias: str  # risk_on | risk_off | neutral
    usd_strength: str  # weak | neutral | strong
    fear_greed: int | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "usd_strength": self.usd_strength,
            "fear_greed": self.fear_greed,
            "notes": self.notes,
        }


@dataclass
class EventGateResult:
    allowed: bool
    size_multiplier: float = 1.0
    min_confidence_override: float | None = None
    reason: str = ""
    blocking_event: CalendarEvent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "size_multiplier": self.size_multiplier,
            "min_confidence_override": self.min_confidence_override,
            "reason": self.reason,
            "blocking_event": (
                {
                    "name": self.blocking_event.name,
                    "currency": self.blocking_event.currency,
                    "impact": self.blocking_event.impact,
                    "scheduled_at": self.blocking_event.scheduled_at,
                }
                if self.blocking_event
                else None
            ),
        }
