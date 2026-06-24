"""Walk-forward validation for parameter promotion."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    run_id: str
    dataset_window: str
    params_changed: str
    oos_return: float
    oos_sharpe: float
    oos_max_dd: float
    baseline_sharpe: float
    promoted: bool
    symbol_count: int = 0


class WalkForwardValidator:
    """Validates weight changes via agent-signal replay on historical bars."""

    OOS_SHARPE_DELTA_GATE = 0.02
    OOS_MAX_DD_GATE = 0.12
    BARS_PER_DAY = 96
    SHORT_DATA_DAYS = 60

    def __init__(self, train_window_days: int = 60, test_window_days: int = 14) -> None:
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days

    def adjust_windows_for_data(self, total_bars: int) -> tuple[int, int]:
        """Shrink train/test windows when dataset spans fewer than 60 days."""
        days = total_bars / self.BARS_PER_DAY
        if days < self.SHORT_DATA_DAYS:
            return 14, 7
        return self.train_window_days, self.test_window_days

    @staticmethod
    def _non_annualized_sharpe(returns: np.ndarray) -> float:
        if len(returns) < 2:
            return 0.0
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns))
        if std_r < 1e-9:
            return 0.0
        return mean_r / std_r

    def _replay_weighted_returns(
        self,
        test_df: Any,
        weights: dict[str, float],
    ) -> np.ndarray:
        """Replay agent signals with minimal SL/TP exit simulation."""
        from src.agents.breakout_hunter import BreakoutHunterAgent
        from src.agents.mean_reversion import MeanReversionAgent
        from src.agents.momentum_pulse import MomentumPulseAgent
        from src.agents.sentiment_agent import SentimentAgent
        from src.agents.trend_surfer import TrendSurferAgent
        from src.agents.base_agent import Direction
        from src.data.feature_engine import FeatureEngine

        agents = {
            "trend_surfer": TrendSurferAgent({}),
            "breakout_hunter": BreakoutHunterAgent({}),
            "momentum_pulse": MomentumPulseAgent({}),
            "mean_reversion": MeanReversionAgent({}),
            "sentiment_agent": SentimentAgent({}),
        }
        if weights.get("ml_signal", 0) > 0:
            try:
                from src.agents.ml_signal_agent import MLSignalAgent

                ml_agent = MLSignalAgent({})
                if ml_agent.is_active:
                    agents["ml_signal"] = ml_agent
            except Exception:
                pass

        engine = FeatureEngine()
        trade_returns: list[float] = []
        window = 50
        max_hold = 8
        i = window
        closes = test_df["close"].values.astype(float)
        highs = test_df["high"].values.astype(float)
        lows = test_df["low"].values.astype(float)
        symbol = test_df.get("symbol", ["EUR/USD"])[0] if "symbol" in test_df.columns else "EUR/USD"

        while i < len(test_df) - 1:
            chunk = test_df.iloc[i - window : i + 1].copy()
            features = engine.compute(symbol, "M15", chunk)
            if "sentiment_agent" in agents:
                features.extras["sentiment_snapshot"] = {
                    "score": 0.3,
                    "confidence": 0.7,
                    "headline_count": 3,
                    "summary": "walk-forward fixture",
                    "macro_bias": "neutral",
                }
                features.extras["event_gate"] = {"allowed": True}
            score = 0.0
            best_signal = None
            for name, agent in agents.items():
                sig = agent.analyze(features)
                w = weights.get(name, 0.25)
                if sig.direction == Direction.BUY:
                    score += sig.confidence * w
                elif sig.direction == Direction.SELL:
                    score -= sig.confidence * w
                if sig.is_actionable and (
                    best_signal is None or sig.confidence > best_signal.confidence
                ):
                    best_signal = sig

            if abs(score) < 0.05 or best_signal is None or not best_signal.is_actionable:
                i += 1
                continue

            entry = closes[i]
            atr = max(features.atr_14, 1e-9)
            direction = best_signal.direction
            sl = best_signal.stop_loss
            tp = best_signal.take_profit
            if sl is None or tp is None:
                if direction == Direction.BUY:
                    sl = entry - atr * 1.5
                    tp = entry + atr * 2.5
                else:
                    sl = entry + atr * 1.5
                    tp = entry - atr * 2.5

            exit_idx = None
            exit_price = entry
            for j in range(i + 1, min(i + 1 + max_hold, len(test_df))):
                bar_high = highs[j]
                bar_low = lows[j]
                if direction == Direction.BUY:
                    if bar_low <= sl:
                        exit_price = sl
                        exit_idx = j
                        break
                    if bar_high >= tp:
                        exit_price = tp
                        exit_idx = j
                        break
                else:
                    if bar_high >= sl:
                        exit_price = sl
                        exit_idx = j
                        break
                    if bar_low <= tp:
                        exit_price = tp
                        exit_idx = j
                        break

            if exit_idx is None:
                exit_idx = min(i + max_hold, len(test_df) - 1)
                exit_price = closes[exit_idx]

            if direction == Direction.BUY:
                trade_returns.append((exit_price - entry) / max(entry, 1e-9))
            else:
                trade_returns.append((entry - exit_price) / max(entry, 1e-9))
            i = exit_idx + 1

        return np.array(trade_returns)

    def _slice_test_window(self, df: Any, train_days: int, test_days: int) -> Any:
        train_bars = train_days * self.BARS_PER_DAY
        test_bars = test_days * self.BARS_PER_DAY
        if len(df) < train_bars + test_bars:
            return df.iloc[-test_bars:]
        return df.iloc[train_bars:train_bars + test_bars]

    def validate(
        self,
        run_id: str,
        params: dict[str, float],
        historical_data_path: str,
        baseline_weights: dict[str, float] | None = None,
    ) -> WalkForwardResult:
        path = Path(historical_data_path)
        empty = WalkForwardResult(
            run_id=run_id,
            dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
            params_changed=str(list(params.keys())),
            oos_return=0.0,
            oos_sharpe=0.0,
            oos_max_dd=0.0,
            baseline_sharpe=0.0,
            promoted=False,
        )
        if not path.exists():
            logger.warning("Historical data not found: %s", path)
            return empty

        try:
            import pandas as pd
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            elif path.suffix == ".csv":
                df = pd.read_csv(path)
            else:
                df = pd.read_json(path)
        except Exception:
            logger.warning("Failed to load historical data", exc_info=True)
            return empty

        if "close" not in df.columns or len(df) < 100:
            return empty

        train_days, test_days = self.adjust_windows_for_data(len(df))
        test_df = self._slice_test_window(df, train_days, test_days)

        baseline = baseline_weights or {k: 0.25 for k in params}
        baseline_returns = self._replay_weighted_returns(test_df, baseline)
        proposed_returns = self._replay_weighted_returns(test_df, params)

        baseline_sharpe = self._non_annualized_sharpe(baseline_returns)
        oos_sharpe = self._non_annualized_sharpe(proposed_returns)

        if len(proposed_returns) < 2:
            oos_return, oos_max_dd = 0.0, 0.0
        else:
            cumulative = np.cumprod(1 + proposed_returns)
            oos_return = float(cumulative[-1] - 1)
            running_max = np.maximum.accumulate(cumulative)
            drawdowns = (cumulative - running_max) / running_max
            oos_max_dd = float(abs(drawdowns.min()))

        sharpe_delta = oos_sharpe - baseline_sharpe
        promoted = (
            sharpe_delta >= self.OOS_SHARPE_DELTA_GATE
            and oos_return > 0
            and oos_max_dd < self.OOS_MAX_DD_GATE
        )

        result = WalkForwardResult(
            run_id=run_id,
            dataset_window=f"train={train_days}d, test={test_days}d",
            params_changed=str(list(params.keys())),
            oos_return=oos_return,
            oos_sharpe=oos_sharpe,
            oos_max_dd=oos_max_dd,
            baseline_sharpe=baseline_sharpe,
            promoted=promoted,
            symbol_count=1,
        )

        logger.info(
            "Walk-forward %s: return=%.2f%% sharpe=%.3f (delta=%.3f) max_dd=%.2f%% promoted=%s",
            run_id, oos_return * 100, oos_sharpe, sharpe_delta, oos_max_dd * 100, promoted,
        )
        return result

    def validate_all_symbols(
        self,
        run_id: str,
        params: dict[str, float],
        data_dir: str | Path,
        baseline_weights: dict[str, float] | None = None,
    ) -> WalkForwardResult:
        """Run walk-forward across all symbol files and aggregate OOS Sharpe."""
        path = Path(data_dir)
        files = sorted(path.glob("*.parquet")) + sorted(path.glob("*.csv"))
        if not files:
            logger.warning("No historical files in %s", path)
            return WalkForwardResult(
                run_id=run_id,
                dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
                params_changed=str(list(params.keys())),
                oos_return=0.0,
                oos_sharpe=0.0,
                oos_max_dd=0.0,
                baseline_sharpe=0.0,
                promoted=False,
            )

        sharpe_deltas: list[float] = []
        returns: list[float] = []
        max_dds: list[float] = []
        baseline_sharpes: list[float] = []
        oos_sharpes: list[float] = []
        train_days = self.train_window_days
        test_days = self.test_window_days

        for fpath in files:
            result = self.validate(
                run_id=f"{run_id}_{fpath.stem}",
                params=params,
                historical_data_path=str(fpath),
                baseline_weights=baseline_weights,
            )
            if result.oos_sharpe == 0.0 and result.baseline_sharpe == 0.0:
                continue
            sharpe_deltas.append(result.oos_sharpe - result.baseline_sharpe)
            returns.append(result.oos_return)
            max_dds.append(result.oos_max_dd)
            baseline_sharpes.append(result.baseline_sharpe)
            oos_sharpes.append(result.oos_sharpe)
            # Parse window from first successful file
            if "train=" in result.dataset_window:
                parts = result.dataset_window.replace("train=", "").split(", test=")
                if len(parts) == 2:
                    train_days = int(parts[0].replace("d", ""))
                    test_days = int(parts[1].replace("d", ""))

        if not sharpe_deltas:
            return WalkForwardResult(
                run_id=run_id,
                dataset_window=f"train={train_days}d, test={test_days}d",
                params_changed=str(list(params.keys())),
                oos_return=0.0,
                oos_sharpe=0.0,
                oos_max_dd=0.0,
                baseline_sharpe=0.0,
                promoted=False,
            )

        agg_baseline = float(np.mean(baseline_sharpes))
        agg_oos_sharpe = float(np.mean(oos_sharpes))
        agg_return = float(np.mean(returns))
        agg_max_dd = float(np.max(max_dds))
        sharpe_delta = agg_oos_sharpe - agg_baseline
        promoted = (
            sharpe_delta >= self.OOS_SHARPE_DELTA_GATE
            and agg_return > 0
            and agg_max_dd < self.OOS_MAX_DD_GATE
        )

        result = WalkForwardResult(
            run_id=run_id,
            dataset_window=f"train={train_days}d, test={test_days}d",
            params_changed=str(list(params.keys())),
            oos_return=agg_return,
            oos_sharpe=agg_oos_sharpe,
            oos_max_dd=agg_max_dd,
            baseline_sharpe=agg_baseline,
            promoted=promoted,
            symbol_count=len(sharpe_deltas),
        )
        logger.info(
            "Walk-forward aggregate (%d symbols): return=%.2f%% sharpe=%.3f (delta=%.3f) promoted=%s",
            len(sharpe_deltas), agg_return * 100, agg_oos_sharpe, sharpe_delta, promoted,
        )
        return result

    def save_result(self, result: WalkForwardResult, output_path: str) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "run_id": result.run_id,
                "dataset_window": result.dataset_window,
                "params_changed": result.params_changed,
                "oos_return": result.oos_return,
                "oos_sharpe": result.oos_sharpe,
                "baseline_sharpe": result.baseline_sharpe,
                "oos_max_dd": result.oos_max_dd,
                "promoted": result.promoted,
                "symbol_count": result.symbol_count,
            }, f, indent=2)
