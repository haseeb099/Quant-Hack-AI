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


class WalkForwardValidator:
    """Validates weight changes via agent-signal replay on historical bars."""

    OOS_SHARPE_DELTA_GATE = 0.05

    def __init__(self, train_window_days: int = 60, test_window_days: int = 14) -> None:
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days

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
        """Proxy: weight-scaled bar returns as stand-in for agent signal replay."""
        from src.data.feature_engine import FeatureEngine
        from src.agents.trend_surfer import TrendSurferAgent
        from src.agents.breakout_hunter import BreakoutHunterAgent
        from src.agents.momentum_pulse import MomentumPulseAgent
        from src.agents.mean_reversion import MeanReversionAgent

        agents = {
            "trend_surfer": TrendSurferAgent({}),
            "breakout_hunter": BreakoutHunterAgent({}),
            "momentum_pulse": MomentumPulseAgent({}),
            "mean_reversion": MeanReversionAgent({}),
        }
        engine = FeatureEngine()
        bar_returns: list[float] = []
        closes = test_df["close"].values.astype(float)

        window = 50
        for i in range(window, len(test_df)):
            chunk = test_df.iloc[i - window : i + 1].copy()
            symbol = test_df.get("symbol", ["EUR/USD"])[0] if "symbol" in test_df.columns else "EUR/USD"
            features = engine.compute(symbol, "M15", chunk)
            score = 0.0
            for name, agent in agents.items():
                sig = agent.analyze(features)
                w = weights.get(name, 0.25)
                if sig.direction.value == "BUY":
                    score += sig.confidence * w
                elif sig.direction.value == "SELL":
                    score -= sig.confidence * w
            bar_ret = (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-9)
            bar_returns.append(bar_ret * (1.0 + score))

        return np.array(bar_returns)

    def validate(
        self,
        run_id: str,
        params: dict[str, Any],
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

        bars_per_day = 96
        train_bars = self.train_window_days * bars_per_day
        test_bars = self.test_window_days * bars_per_day

        if len(df) < train_bars + test_bars:
            test_df = df.iloc[-test_bars:]
        else:
            test_df = df.iloc[train_bars:train_bars + test_bars]

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
        promoted = sharpe_delta >= self.OOS_SHARPE_DELTA_GATE and oos_return > 0

        result = WalkForwardResult(
            run_id=run_id,
            dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
            params_changed=str(list(params.keys())),
            oos_return=oos_return,
            oos_sharpe=oos_sharpe,
            oos_max_dd=oos_max_dd,
            baseline_sharpe=baseline_sharpe,
            promoted=promoted,
        )

        logger.info(
            "Walk-forward %s: return=%.2f%% sharpe=%.3f (delta=%.3f) max_dd=%.2f%% promoted=%s",
            run_id, oos_return * 100, oos_sharpe, sharpe_delta, oos_max_dd * 100, promoted,
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
            }, f, indent=2)
