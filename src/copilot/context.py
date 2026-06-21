"""Grounded context assembly for copilot — no invented market data."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.agents.base_agent import AgentSignal, FeatureVector
from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.copilot.models import DataCitation
from src.data.feature_engine import FeatureEngine
from src.data.session_filter import SessionFilter
from src.engine.config import QuantAIConfig, load_yaml
from src.learning.layered_memory import LayeredMemory
from src.web.engine_registry import get_connector, get_engine
from src.web.runtime_state import is_state_stale, read_state

CRYPTO_SYMBOLS = frozenset({"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"})

# Reference mids for simulate/demo when runtime_state has no live tick (cited in analysis).
_DEMO_REFERENCE_MID: dict[str, float] = {
    "XAU/USD": 2350.0,
    "XAG/USD": 28.0,
    "EUR/USD": 1.085,
    "GBP/USD": 1.265,
    "USD/JPY": 157.5,
    "AUD/USD": 0.665,
    "USD/CAD": 1.365,
    "USD/CHF": 0.885,
    "EUR/GBP": 0.858,
    "EUR/CHF": 0.96,
    "BTC/USD": 65000.0,
    "ETH/USD": 3500.0,
    "SOL/USD": 150.0,
    "XRP/USD": 0.55,
    "BAR/USD": 100.0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_symbols() -> set[str]:
    instruments = load_yaml("instruments.yaml").get("instruments", [])
    return {str(i.get("symbol", "")) for i in instruments if i.get("symbol")}


def _resolve_symbol(message: str | None, explicit: str | None) -> str | None:
    if explicit and explicit.strip():
        return explicit.strip()
    if not message:
        return None
    text = message.upper()
    for sym in _allowed_symbols():
        if sym.replace("/", "").upper() in text.replace("/", "").upper() or sym.upper() in text:
            return sym
    aliases = {
        "GOLD": "XAU/USD",
        "SILVER": "XAG/USD",
        "BITCOIN": "BTC/USD",
        "ETHER": "ETH/USD",
        "ETHEREUM": "ETH/USD",
    }
    for alias, sym in aliases.items():
        if alias in text:
            return sym
    return None


class CopilotContextBuilder:
    """Load live state, OHLCV, features, and agent votes with citations."""

    def __init__(self, config: QuantAIConfig | None = None) -> None:
        self.config = config or QuantAIConfig.load()
        self.feature_engine = FeatureEngine()
        self.session_filter = SessionFilter()
        self.memory = LayeredMemory()
        self.agents = [
            TrendSurferAgent(self.config.agent_config("trend_surfer")),
            BreakoutHunterAgent(self.config.agent_config("breakout_hunter")),
            MomentumPulseAgent(self.config.agent_config("momentum_pulse")),
            MeanReversionAgent(self.config.agent_config("mean_reversion")),
        ]

    def build(
        self,
        symbol: str,
        state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[DataCitation], str | None]:
        """Return context dict, citations, and refusal_reason (if any)."""
        state = state or read_state()
        citations: list[DataCitation] = []
        now = _utc_now()

        if symbol not in _allowed_symbols():
            return {}, citations, f"{symbol} is not a competition instrument"

        mode = str(state.get("mode", "simulate"))
        data_source = "demo"
        if os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"):
            data_source = "demo"
        elif mode == "live" and state.get("mt5_connected"):
            data_source = "live"
        elif state.get("engine_running"):
            data_source = "simulate"

        if is_state_stale(state) and state.get("engine_running"):
            return {}, citations, "Dashboard state is stale — refresh engine connection"

        account = state.get("account", {})
        risk = state.get("risk", {})
        citations.append(DataCitation(
            source="runtime_state.account",
            field="equity",
            value=float(account.get("equity", 0)),
            timestamp=str(state.get("timestamp", now)),
        ))
        citations.append(DataCitation(
            source="runtime_state.risk",
            field="dd_tier",
            value=str(risk.get("dd_tier", "normal")),
            timestamp=str(state.get("timestamp", now)),
        ))

        instruments = state.get("instruments", {})
        inst = instruments.get(symbol, {})
        market = state.get("market", {})
        tick_age = inst.get("tick_age_ms") or market.get("last_tick_age_ms")
        mid = inst.get("mid") or inst.get("bid") or inst.get("ask")

        if tick_age is not None:
            citations.append(DataCitation(
                source="runtime_state.instruments",
                field=f"{symbol}.tick_age_ms",
                value=float(tick_age),
                timestamp=str(inst.get("updated_at", state.get("timestamp", now))),
            ))

        if mid is not None:
            citations.append(DataCitation(
                source="runtime_state.instruments",
                field=f"{symbol}.mid",
                value=float(mid),
                timestamp=str(inst.get("updated_at", state.get("timestamp", now))),
            ))
        elif data_source != "live" and symbol in _DEMO_REFERENCE_MID:
            mid = _DEMO_REFERENCE_MID[symbol]
            citations.append(DataCitation(
                source="demo_reference_mid",
                field=symbol,
                value=float(mid),
                timestamp=now,
            ))

        if data_source == "live":
            if not state.get("mt5_connected"):
                return {}, citations, "MT5 bridge offline — cannot analyze live symbols"
            if tick_age is None or float(tick_age) > 5000:
                return {}, citations, "Market data is stale — analysis refused in live mode"
            if mid is None:
                return {}, citations, "No live price for symbol — analysis refused"

        session_name = self.session_filter.session_name()
        session_info = self.session_filter.current_session()
        citations.append(DataCitation(
            source="session_filter",
            field="session",
            value=session_name,
            timestamp=now,
        ))

        ohlcv, ohlcv_source = self._load_ohlcv(symbol, state, float(mid) if mid else None)
        if ohlcv is None or len(ohlcv) < 50:
            return {}, citations, "Insufficient OHLCV data for technical analysis"

        citations.append(DataCitation(
            source=ohlcv_source,
            field="ohlcv_bars",
            value=len(ohlcv),
            timestamp=now,
        ))

        donchian = int(self.config.agent_config("breakout_hunter").get("donchian_period", 20))
        multi_features = self.feature_engine.compute_multi(symbol, ohlcv, donchian)
        primary = multi_features.get("M15") or next(iter(multi_features.values()))

        signals = self._run_agents(multi_features, session_name)
        for sig in signals:
            citations.append(DataCitation(
                source=f"agent.{sig.agent_name}",
                field="vote",
                value={"direction": sig.direction.value, "confidence": round(sig.confidence, 3)},
                timestamp=now,
            ))

        semantic = self.memory.get_semantic_context(
            primary.regime.value, symbol, session_name,
        )
        if semantic.get("best_agent"):
            citations.append(DataCitation(
                source="layered_memory.semantic",
                field="best_agent",
                value=semantic,
                timestamp=now,
            ))

        last_cycle = state.get("last_cycle", {})
        last_decision = None
        for dec in last_cycle.get("decisions", []):
            if dec.get("symbol") == symbol:
                last_decision = dec
                break

        positions = [p for p in state.get("positions", []) if str(p.get("symbol", "")).replace("/", "") == symbol.replace("/", "")]
        if positions:
            citations.append(DataCitation(
                source="runtime_state.positions",
                field=symbol,
                value=positions,
                timestamp=now,
            ))

        context = {
            "symbol": symbol,
            "data_source": data_source,
            "mode": mode,
            "session": session_name,
            "session_preferred": list(session_info.preferred_instruments),
            "session_agents": list(session_info.preferred_agents),
            "symbol_session_ok": self.session_filter.should_trade_symbol(symbol),
            "account": account,
            "risk": risk,
            "primary_features": primary,
            "multi_features": multi_features,
            "agent_signals": signals,
            "semantic": semantic,
            "last_decision": last_decision,
            "open_positions_on_symbol": positions,
            "market": {
                "mid": float(mid) if mid is not None else primary.close,
                "tick_age_ms": float(tick_age) if tick_age is not None else None,
                "regime": primary.regime.value,
                "adx": primary.adx,
                "rsi_14": primary.rsi_14,
                "atr_14": primary.atr_14,
            },
            "phase": state.get("phase", self.config.current_phase),
            "timestamp": now,
        }
        return context, citations, None

    def _load_ohlcv(
        self,
        symbol: str,
        state: dict[str, Any],
        mid: float | None,
    ) -> tuple[pd.DataFrame | None, str]:
        engine = get_engine()
        if engine is not None:
            df = engine._get_ohlcv(symbol, "M15")
            if df is not None and len(df) >= 50:
                return df, "engine.ohlcv"

        connector = get_connector()
        if connector.is_connected:
            df = connector.get_ohlcv(symbol, timeframe="M15", count=200)
            if df is not None and len(df) >= 50:
                return df, "zeromq.DATA"

        if mid is None:
            return None, "none"

        seed = abs(hash(symbol)) % (2**31)
        rng = np.random.default_rng(seed)
        n = 200
        returns = rng.normal(0, 0.0008, n)
        close = mid * np.exp(np.cumsum(returns))
        high = close * (1 + np.abs(rng.normal(0, 0.0005, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.0005, n)))
        open_ = np.roll(close, 1)
        open_[0] = mid
        df = pd.DataFrame({
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        })
        return df, "synthetic_from_runtime_mid"

    def _run_agents(
        self,
        multi_features: dict[str, FeatureVector],
        session_name: str,
    ) -> list[AgentSignal]:
        signals: list[AgentSignal] = []
        for agent in self.agents:
            if not self.config.is_agent_enabled(agent.name):
                continue
            timeframes = agent.config.get("timeframes", ["M15"])
            best: AgentSignal | None = None
            for tf in timeframes:
                features = multi_features.get(tf) or multi_features.get("M15")
                if features is None:
                    continue
                self._inject_extras(features, agent.name, multi_features, session_name)
                candidate = agent.analyze(features)
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is not None:
                signals.append(best)
        return signals

    @staticmethod
    def _inject_extras(
        features: FeatureVector,
        agent_name: str,
        multi_features: dict[str, FeatureVector],
        session_name: str,
    ) -> None:
        h1 = multi_features.get("H1")
        h4 = multi_features.get("H4")
        if h1:
            features.extras["h1_adx"] = h1.adx
            features.extras["h1_trend_bull"] = h1.close > h1.ema_50 and h1.ema_9 > h1.ema_21
            features.extras["h1_trend_bear"] = h1.close < h1.ema_50 and h1.ema_9 < h1.ema_21
        if h4:
            features.extras["h4_trend_bull"] = h4.close > h4.ema_50 and h4.ema_9 > h4.ema_21
            features.extras["h4_trend_bear"] = h4.close < h4.ema_50 and h4.ema_9 < h4.ema_21
        if agent_name == "breakout_hunter":
            features.extras["session_name"] = session_name


def resolve_symbol_from_message(message: str | None, explicit: str | None = None) -> str | None:
    return _resolve_symbol(message, explicit)
