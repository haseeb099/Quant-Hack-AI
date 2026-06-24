"""Competition strategy — audit-driven symbol/agent routing for top-20 scoring."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_PATH = Path("data/agent_audit.json")

# Symbols with strong live audit + leaderboard-style return potential
TIER_A_SYMBOLS = frozenset({
    "XAG/USD",
    "USD/CAD",
    "AUD/USD",
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
})

TIER_B_SYMBOLS = frozenset({
    "XAU/USD",
    "EUR/USD",
    "GBP/USD",
})


@lru_cache(maxsize=1)
def _load_audit() -> dict[str, Any]:
    if not AUDIT_PATH.exists():
        return {}
    try:
        with open(AUDIT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load agent audit: %s", exc)
        return {}


def refresh_audit_cache() -> None:
    _load_audit.cache_clear()


class CompetitionStrategy:
    """Uses agent audit to boost winners and block repeat losers."""

    def __init__(
        self,
        min_samples_block: int = 2,
        block_win_rate: float = 0.34,
        min_samples_boost: int = 3,
        boost_win_rate: float = 0.55,
    ) -> None:
        self.min_samples_block = min_samples_block
        self.block_win_rate = block_win_rate
        self.min_samples_boost = min_samples_boost
        self.boost_win_rate = boost_win_rate

    def _agent_symbol_stats(self, symbol: str, agent: str) -> dict[str, Any] | None:
        audit = _load_audit()
        agents = audit.get("agents") or {}
        agent_data = agents.get(agent)
        if not agent_data:
            return None
        by_symbol = agent_data.get("by_symbol") or {}
        stats = by_symbol.get(symbol)
        return stats if isinstance(stats, dict) else None

    def symbol_agent_win_rate(self, symbol: str, agent: str) -> float | None:
        stats = self._agent_symbol_stats(symbol, agent)
        if not stats:
            return None
        sample = int(stats.get("sample_size") or 0)
        if sample < 1:
            return None
        wr = stats.get("win_rate")
        return float(wr) if wr is not None else None

    def block_agent(self, symbol: str, agent: str) -> bool:
        stats = self._agent_symbol_stats(symbol, agent)
        if not stats:
            return False
        sample = int(stats.get("sample_size") or 0)
        wr = stats.get("win_rate")
        if sample >= self.min_samples_block and wr is not None and float(wr) <= self.block_win_rate:
            return True
        avg_r = stats.get("avg_r")
        if sample >= self.min_samples_block and avg_r is not None and float(avg_r) < -0.45:
            return True
        return False

    def strength_multiplier(self, symbol: str, agent: str) -> float:
        stats = self._agent_symbol_stats(symbol, agent)
        if not stats:
            return 1.0
        sample = int(stats.get("sample_size") or 0)
        wr = stats.get("win_rate")
        if sample < self.min_samples_boost or wr is None:
            return 1.0
        win_rate = float(wr)
        if win_rate >= 0.65:
            return 1.35
        if win_rate >= self.boost_win_rate:
            return 1.18
        if win_rate <= self.block_win_rate:
            return 0.25
        if win_rate < 0.45:
            return 0.55
        return 0.85

    def symbol_rates(self, symbol: str) -> dict[str, float]:
        rates: dict[str, float] = {}
        audit = _load_audit()
        for agent, data in (audit.get("agents") or {}).items():
            by_symbol = (data or {}).get("by_symbol") or {}
            stats = by_symbol.get(symbol)
            if not stats:
                continue
            wr = stats.get("win_rate")
            if wr is not None and int(stats.get("sample_size") or 0) >= 1:
                rates[str(agent)] = float(wr)
        return rates

    def symbol_tier(self, symbol: str) -> str:
        if symbol in TIER_A_SYMBOLS:
            return "A"
        if symbol in TIER_B_SYMBOLS:
            return "B"
        return "C"

    def _confluence_size_boost(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        signals: list[Any],
        cfg: dict[str, Any],
        *,
        counts_as_technical: Callable[[Any], bool],
        default_symbols: frozenset[str],
    ) -> dict[str, float] | None:
        if direction == "HOLD" or not cfg.get("enabled"):
            return None

        allowed = set(cfg.get("symbols") or default_symbols)
        if symbol not in allowed:
            return None

        min_conf = float(cfg.get("min_confidence", 0.85))
        min_consensus = int(cfg.get("min_consensus_agents", 3))
        min_technical = int(cfg.get("require_technical_agents", 2))
        if confidence < min_conf:
            return None

        agreeing = [
            s for s in signals
            if getattr(s, "is_actionable", False)
            and getattr(getattr(s, "direction", None), "value", None) == direction
        ]
        if len(agreeing) < min_consensus:
            return None

        technical_agreeing = sum(1 for s in agreeing if counts_as_technical(s))
        if technical_agreeing < min_technical:
            return None

        if cfg.get("require_trend_surfer_or_ml", True):
            has_anchor = any(
                getattr(s, "agent_name", "") in ("trend_surfer", "ml_signal")
                for s in agreeing
            )
            if not has_anchor:
                return None

        src_max_fx = cfg.get("max_fx_lots")
        src_max_crypto = cfg.get("max_crypto_lots")
        src_max_metal = cfg.get("max_metal_lots")
        return {
            "boost_tier": str(cfg.get("boost_tier", "confluence")),
            "orchestrator_scale_mult": float(cfg.get("orchestrator_scale_mult", 1.42)),
            "max_risk_pct_mult": float(cfg.get("max_risk_pct_mult", 1.38)),
            "max_risk_pct_ceiling": float(cfg.get("max_risk_pct_ceiling", 0.021)),
            "max_fx_lots": float(src_max_fx) if src_max_fx is not None else None,
            "max_crypto_lots": float(src_max_crypto) if src_max_crypto is not None else None,
            "max_metal_lots": float(src_max_metal) if src_max_metal is not None else None,
            "fx_min_lot_bump_risk_pct": float(cfg.get("fx_min_lot_bump_risk_pct", 0.0075)),
            "crypto_min_lot_bump_risk_pct": float(cfg.get("crypto_min_lot_bump_risk_pct", 0.0085)),
            "metal_min_lot_bump_risk_pct": float(cfg.get("metal_min_lot_bump_risk_pct", 0.0065)),
        }

    def tier_a_plus_size_boost(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        signals: list[Any],
        live_filters: dict[str, Any],
        *,
        counts_as_technical: Callable[[Any], bool],
    ) -> dict[str, float] | None:
        """Return sizing multipliers when tier-A symbol hits elite A+ confluence."""
        cfg = dict(live_filters.get("tier_a_plus_size_boost") or {})
        cfg.setdefault("boost_tier", "tier_a_plus")
        return self._confluence_size_boost(
            symbol,
            direction,
            confidence,
            signals,
            cfg,
            counts_as_technical=counts_as_technical,
            default_symbols=TIER_A_SYMBOLS,
        )

    def audit_winner_size_boost(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        signals: list[Any],
        live_filters: dict[str, Any],
        *,
        counts_as_technical: Callable[[Any], bool],
    ) -> dict[str, float] | None:
        """Moderate size boost on proven audit-winner pairs with 2-agent confluence."""
        cfg = dict(live_filters.get("audit_winner_size_boost") or {})
        cfg.setdefault("boost_tier", "audit_winner")
        winners = frozenset(live_filters.get("audit_winner_symbols") or [])
        return self._confluence_size_boost(
            symbol,
            direction,
            confidence,
            signals,
            cfg,
            counts_as_technical=counts_as_technical,
            default_symbols=winners,
        )

    def resolve_size_boost(
        self,
        symbol: str,
        direction: str,
        confidence: float,
        signals: list[Any],
        live_filters: dict[str, Any],
        *,
        counts_as_technical: Callable[[Any], bool],
    ) -> dict[str, float] | None:
        """Prefer elite tier-A A+ boost, else audit-winner boost."""
        elite = self.tier_a_plus_size_boost(
            symbol,
            direction,
            confidence,
            signals,
            live_filters,
            counts_as_technical=counts_as_technical,
        )
        if elite is not None:
            return elite
        return self.audit_winner_size_boost(
            symbol,
            direction,
            confidence,
            signals,
            live_filters,
            counts_as_technical=counts_as_technical,
        )

    def min_consensus_for_symbol(
        self,
        symbol: str,
        base: int,
        *,
        tier_a_consensus: int = 1,
        tier_b_consensus: int = 2,
        tier_c_consensus: int = 2,
    ) -> int:
        tier = self.symbol_tier(symbol)
        if tier == "A":
            return tier_a_consensus
        if tier == "B":
            return max(base, tier_b_consensus)
        return max(base, tier_c_consensus)

    def global_agent_win_rates(self) -> dict[str, float]:
        audit = _load_audit()
        rates: dict[str, float] = {}
        for agent, data in (audit.get("agents") or {}).items():
            wr = (data or {}).get("win_rate")
            sample = int((data or {}).get("sample_size") or 0)
            if wr is not None and sample >= 3:
                rates[str(agent)] = float(wr)
        return rates
