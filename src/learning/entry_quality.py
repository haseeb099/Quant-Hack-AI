"""Audit-driven entry quality scoring — gates low-probability setups before execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Symbols with historically strong audit performance when confluence is present
AUDIT_WINNER_SYMBOLS = frozenset({"USD/CAD", "XAG/USD"})
ANCHOR_AGENTS = frozenset({"trend_surfer", "ml_signal"})


@dataclass(frozen=True)
class EntryQualityResult:
    score: float
    passed: bool
    reasons: tuple[str, ...]
    tier: str  # reject | bronze | silver | gold


def _agent_win_rate(
    agent: str,
    symbol: str,
    symbol_rates: dict[str, float],
    audit_rates: dict[str, float],
) -> float | None:
    if agent in symbol_rates:
        return symbol_rates[agent]
    return audit_rates.get(agent)


def score_entry(
    *,
    symbol: str,
    direction: str,
    regime: str,
    adx: float,
    rsi: float,
    confidence: float,
    agreeing_agents: list[str],
    symbol_rates: dict[str, float],
    audit_rates: dict[str, float],
    debate_confirms: bool,
    solo_metal_sell_ok: bool = False,
    audit_solo_trend_surfer_ok: bool = False,
    audit_winner_symbols: frozenset[str] | None = None,
) -> EntryQualityResult:
    """Score 0–1 from audit patterns; higher = better expected edge."""
    if direction == "HOLD":
        return EntryQualityResult(0.0, False, ("HOLD",), "reject")

    winners = audit_winner_symbols or AUDIT_WINNER_SYMBOLS
    reasons: list[str] = []
    score = 0.0
    agents = set(agreeing_agents)
    n_agree = len(agents)

    if solo_metal_sell_ok:
        score += 0.55
        reasons.append("proven solo ml metal SELL in trend")
    elif audit_solo_trend_surfer_ok:
        score += 0.48
        reasons.append("audit-winner solo trend_surfer in trend")
    elif n_agree >= 2:
        score += 0.32
        reasons.append(f"{n_agree}-agent consensus")
    elif n_agree == 1:
        score -= 0.22
        reasons.append("solo agent — penalty")

    if ANCHOR_AGENTS.issubset(agents):
        score += 0.22
        reasons.append("trend_surfer + ml_signal anchor")

    wrs = [
        wr
        for a in agents
        if (wr := _agent_win_rate(a, symbol, symbol_rates, audit_rates)) is not None
    ]
    if wrs:
        avg_wr = sum(wrs) / len(wrs)
        if avg_wr >= 0.60:
            score += 0.18
            reasons.append(f"audit WR {avg_wr:.0%}")
        elif avg_wr >= 0.50:
            score += 0.10
            reasons.append(f"audit WR {avg_wr:.0%}")
        elif avg_wr < 0.40:
            score -= 0.15
            reasons.append(f"weak audit WR {avg_wr:.0%}")

    if regime in ("trending", "volatile"):
        if adx >= 30:
            score += 0.14
            reasons.append(f"strong ADX {adx:.0f}")
        elif adx >= 24:
            score += 0.08
            reasons.append(f"ADX {adx:.0f}")
        else:
            score -= 0.12
            reasons.append(f"weak ADX {adx:.0f} in {regime}")

    if debate_confirms:
        score += 0.10
        reasons.append("debate confirms")

    if symbol in winners:
        score += 0.08
        reasons.append("audit-winner symbol")

    if confidence >= 0.80:
        score += 0.06
    elif confidence >= 0.74:
        score += 0.03

    is_fx = "/" in symbol and symbol.count("/") == 1 and "XAU" not in symbol and "XAG" not in symbol
    is_metal = symbol in ("XAU/USD", "XAG/USD")

    if is_fx and direction == "SELL" and regime in ("ranging", "calm"):
        score -= 0.40
        reasons.append("FX short in chop — blocked pattern")

    if is_metal and direction == "BUY" and regime in ("calm", "ranging"):
        score -= 0.35
        reasons.append("metal long in calm/range — blocked pattern")

    if agents == {"ml_signal"} and regime == "trending" and not solo_metal_sell_ok:
        score -= 0.20
        reasons.append("solo ml in trending — low historical WR")

    if agents == {"trend_surfer"} and regime in ("ranging", "calm") and not audit_solo_trend_surfer_ok:
        score -= 0.30
        reasons.append("solo trend_surfer in chop")

    score = max(0.0, min(1.0, score))

    if score >= 0.85:
        tier = "gold"
    elif score >= 0.72:
        tier = "silver"
    elif score >= 0.58:
        tier = "bronze"
    else:
        tier = "reject"

    return EntryQualityResult(score, score >= 0.72, tuple(reasons), tier)


def passes_quality_gate(
    result: EntryQualityResult,
    *,
    min_score: float = 0.72,
    allow_solo_metal_sell: bool = False,
    allow_audit_solo_trend_surfer: bool = False,
) -> bool:
    if allow_solo_metal_sell and "proven solo ml metal SELL" in result.reasons:
        return result.score >= max(0.68, min_score - 0.06)
    if allow_audit_solo_trend_surfer and "audit-winner solo trend_surfer" in result.reasons:
        return result.score >= max(0.68, min_score - 0.06)
    return result.score >= min_score
