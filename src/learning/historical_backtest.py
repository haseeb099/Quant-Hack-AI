"""Replay rule agents on historical M15 bars and store trades in layered memory."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agents.base_agent import AgentSignal, Direction
from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.ml_signal_agent import MLSignalAgent
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.data.feature_engine import FeatureEngine
from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory, TradeRecord, build_trade_attribution

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.65
WINDOW_BARS = 200
TIME_STOP_BARS = 48  # 12 hours on M15


@dataclass
class OpenPosition:
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    entry_bar: int
    sl: float | None
    tp: float | None
    agent: str
    regime: str
    features_snapshot: dict[str, Any]
    agent_votes: list[dict[str, Any]]


class HistoricalBacktester:
    """Simulate agent consensus entries with SL/TP/time-stop exits."""

    def __init__(
        self,
        memory: LayeredMemory | None = None,
        min_confidence: float = MIN_CONFIDENCE,
        window_bars: int = WINDOW_BARS,
        time_stop_bars: int = TIME_STOP_BARS,
        config: QuantAIConfig | None = None,
    ) -> None:
        self.memory = memory or LayeredMemory()
        self.min_confidence = min_confidence
        self.window_bars = window_bars
        self.time_stop_bars = time_stop_bars
        self.config = config or QuantAIConfig.load()
        self.feature_engine = FeatureEngine()
        agent_cfg = self.config.agents
        self.agents = [
            TrendSurferAgent(agent_cfg.get("trend_surfer", {})),
            BreakoutHunterAgent(agent_cfg.get("breakout_hunter", {"donchian_period": 20})),
            MomentumPulseAgent(agent_cfg.get("momentum_pulse", {})),
            MeanReversionAgent(agent_cfg.get("mean_reversion", {})),
            SentimentAgent(agent_cfg.get("sentiment_agent", {})),
            MLSignalAgent(agent_cfg.get("ml_signal", {})),
        ]

    def _inject_mtf_extras(self, features, multi_features: dict) -> None:
        h1 = multi_features.get("H1")
        h4 = multi_features.get("H4")
        if h1:
            features.extras["h1_adx"] = h1.adx
            features.extras["h1_trend_bull"] = h1.close > h1.ema_50 and h1.ema_9 > h1.ema_21
            features.extras["h1_trend_bear"] = h1.close < h1.ema_50 and h1.ema_9 < h1.ema_21
        if h4:
            features.extras["h4_trend_bull"] = h4.close > h4.ema_50 and h4.ema_9 > h4.ema_21
            features.extras["h4_trend_bear"] = h4.close < h4.ema_50 and h4.ema_9 < h4.ema_21

    def _collect_signals(self, symbol: str, m15_df: Any) -> tuple[list[AgentSignal], Any]:
        multi = self.feature_engine.compute_multi(symbol, m15_df, donchian_period=20)
        if not multi:
            return [], None
        primary = multi.get("M15") or next(iter(multi.values()))
        signals: list[AgentSignal] = []
        for agent in self.agents:
            agent_cfg = agent.config
            timeframes = agent_cfg.get("timeframes", ["M15"])
            best: AgentSignal | None = None
            for tf in timeframes:
                features = multi.get(tf) or (multi.get("M15") if tf != "M15" else None)
                if features is None:
                    continue
                self._inject_mtf_extras(features, multi)
                if agent.name == "sentiment_agent":
                    features.extras["sentiment_snapshot"] = {
                        "score": 0.35,
                        "confidence": 0.65,
                        "headline_count": 4,
                        "summary": "Backtest neutral sentiment fixture",
                        "macro_bias": "neutral",
                    }
                    features.extras["event_gate"] = {"allowed": True}
                candidate = agent.analyze(features)
                if best is None or candidate.confidence > best.confidence:
                    best = candidate
            if best is not None:
                signals.append(best)
        return signals, primary

    def _consensus_direction(self, signals: list[AgentSignal]) -> tuple[Direction, float, AgentSignal | None]:
        buys = [s for s in signals if s.direction == Direction.BUY and s.confidence >= self.min_confidence]
        sells = [s for s in signals if s.direction == Direction.SELL and s.confidence >= self.min_confidence]
        if len(buys) >= 2 and len(buys) > len(sells):
            best = max(buys, key=lambda s: s.confidence)
            conf = min(sum(s.confidence for s in buys) / len(buys), 1.0)
            return Direction.BUY, conf, best
        if len(sells) >= 2 and len(sells) > len(buys):
            best = max(sells, key=lambda s: s.confidence)
            conf = min(sum(s.confidence for s in sells) / len(sells), 1.0)
            return Direction.SELL, conf, best
        return Direction.HOLD, 0.0, None

    def _check_exit(self, pos: OpenPosition, bar_high: float, bar_low: float, bar_idx: int) -> tuple[bool, float | None, str]:
        if pos.direction == "BUY":
            if pos.sl is not None and bar_low <= pos.sl:
                return True, pos.sl, "sl"
            if pos.tp is not None and bar_high >= pos.tp:
                return True, pos.tp, "tp"
        else:
            if pos.sl is not None and bar_high >= pos.sl:
                return True, pos.sl, "sl"
            if pos.tp is not None and bar_low <= pos.tp:
                return True, pos.tp, "tp"
        if bar_idx - pos.entry_bar >= self.time_stop_bars:
            return True, None, "time_stop"
        return False, None, ""

    def _finalize(
        self,
        pos: OpenPosition,
        exit_price: float,
        exit_reason: str,
        round_id: str,
    ) -> TradeRecord:
        entry = pos.entry_price
        sl_dist = abs(entry - pos.sl) if pos.sl is not None else entry * 0.001
        if pos.direction == "BUY":
            price_move = exit_price - entry
        else:
            price_move = entry - exit_price
        r_multiple = price_move / max(sl_dist, 1e-9)
        now = datetime.now(timezone.utc).isoformat()
        record = TradeRecord(
            trade_id=pos.trade_id,
            symbol=pos.symbol,
            session="backtest",
            regime=pos.regime,
            agent=pos.agent,
            direction=pos.direction,
            entry_price=entry,
            exit_price=exit_price,
            r_multiple=r_multiple,
            pnl=price_move,
            features_snapshot=pos.features_snapshot,
            agent_votes=pos.agent_votes,
            attribution_json=build_trade_attribution(
                signals=pos.agent_votes,
                decision_direction=pos.direction,
                primary_agent=pos.agent,
                orchestrator_used_ai=False,
            ),
            orchestrator_reasoning=f"backtest exit: {exit_reason}",
            entry_time=now,
            exit_time=now,
            round_id=round_id,
        )
        self.memory.store_trade(record)
        return record

    def run_symbol(self, symbol: str, ohlcv_df: Any, round_id: str = "pricer_backtest") -> int:
        import pandas as pd

        df = ohlcv_df.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)

        if len(df) < self.window_bars + 10:
            logger.warning("Insufficient bars for %s (%d)", symbol, len(df))
            return 0

        open_pos: OpenPosition | None = None
        trades = 0

        for i in range(self.window_bars, len(df)):
            row = df.iloc[i]
            bar_high = float(row["high"])
            bar_low = float(row["low"])
            bar_close = float(row["close"])

            if open_pos is not None:
                exited, exit_px, reason = self._check_exit(open_pos, bar_high, bar_low, i)
                if exited:
                    final_px = exit_px if exit_px is not None else bar_close
                    self._finalize(open_pos, final_px, reason, round_id)
                    trades += 1
                    open_pos = None
                continue

            chunk = df.iloc[i - self.window_bars : i + 1].copy()
            signals, primary = self._collect_signals(symbol, chunk)
            if primary is None:
                continue

            direction, confidence, lead = self._consensus_direction(signals)
            if direction == Direction.HOLD or lead is None or confidence < self.min_confidence:
                continue

            open_pos = OpenPosition(
                trade_id=str(uuid.uuid4()),
                symbol=symbol,
                direction=direction.value,
                entry_price=bar_close,
                entry_bar=i,
                sl=lead.stop_loss,
                tp=lead.take_profit,
                agent=lead.agent_name,
                regime=primary.regime.value,
                features_snapshot={
                    "adx": primary.adx,
                    "rsi_14": primary.rsi_14,
                    "atr_14": primary.atr_14,
                },
                agent_votes=[
                    {"agent": s.agent_name, "direction": s.direction.value, "confidence": s.confidence}
                    for s in signals
                ],
            )

        if open_pos is not None:
            final_close = float(df.iloc[-1]["close"])
            self._finalize(open_pos, final_close, "end_of_data", round_id)
            trades += 1

        logger.info("Backtest %s: %d trades", symbol, trades)
        return trades

    def run_directory(
        self,
        data_dir: str | Path,
        round_id: str = "pricer_backtest",
    ) -> dict[str, int]:
        path = Path(data_dir)
        results: dict[str, int] = {}
        files = sorted(path.glob("*.parquet")) + sorted(path.glob("*.csv"))
        for fpath in files:
            import pandas as pd

            if fpath.suffix == ".parquet":
                df = pd.read_parquet(fpath)
            else:
                df = pd.read_csv(fpath)
            symbol = fpath.stem.replace("_", "/")
            results[symbol] = self.run_symbol(symbol, df, round_id=round_id)
        return results
