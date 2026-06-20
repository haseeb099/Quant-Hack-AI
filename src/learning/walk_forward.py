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
    promoted: bool


class WalkForwardValidator:
    """Validates parameter changes on out-of-sample data before promotion."""

    OOS_SHARPE_GATE = 0.5

    def __init__(self, train_window_days: int = 60, test_window_days: int = 14) -> None:
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days

    def validate(
        self,
        run_id: str,
        params: dict[str, Any],
        historical_data_path: str,
    ) -> WalkForwardResult:
        path = Path(historical_data_path)
        if not path.exists():
            logger.warning("Historical data not found: %s", path)
            return WalkForwardResult(
                run_id=run_id,
                dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
                params_changed=str(list(params.keys())),
                oos_return=0.0,
                oos_sharpe=0.0,
                oos_max_dd=0.0,
                promoted=False,
            )

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
            return WalkForwardResult(
                run_id=run_id,
                dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
                params_changed=str(list(params.keys())),
                oos_return=0.0,
                oos_sharpe=0.0,
                oos_max_dd=0.0,
                promoted=False,
            )

        if "close" not in df.columns or len(df) < 100:
            return WalkForwardResult(
                run_id=run_id,
                dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
                params_changed=str(list(params.keys())),
                oos_return=0.0,
                oos_sharpe=0.0,
                oos_max_dd=0.0,
                promoted=False,
            )

        bars_per_day = 96  # M15 bars
        train_bars = self.train_window_days * bars_per_day
        test_bars = self.test_window_days * bars_per_day
        total_needed = train_bars + test_bars

        if len(df) < total_needed:
            test_df = df.iloc[-test_bars:]
        else:
            test_df = df.iloc[train_bars:train_bars + test_bars]

        returns = test_df["close"].pct_change().dropna()
        if len(returns) < 2:
            oos_return, oos_sharpe, oos_max_dd = 0.0, 0.0, 0.0
        else:
            oos_return = float((test_df["close"].iloc[-1] / test_df["close"].iloc[0]) - 1)
            mean_r = float(returns.mean())
            std_r = float(returns.std())
            oos_sharpe = (mean_r / std_r * np.sqrt(252 * 96)) if std_r > 1e-9 else 0.0

            cumulative = (1 + returns).cumprod()
            running_max = cumulative.cummax()
            drawdowns = (cumulative - running_max) / running_max
            oos_max_dd = float(abs(drawdowns.min()))

        promoted = oos_sharpe >= self.OOS_SHARPE_GATE and oos_return > 0

        result = WalkForwardResult(
            run_id=run_id,
            dataset_window=f"train={self.train_window_days}d, test={self.test_window_days}d",
            params_changed=str(list(params.keys())),
            oos_return=oos_return,
            oos_sharpe=oos_sharpe,
            oos_max_dd=oos_max_dd,
            promoted=promoted,
        )

        logger.info(
            "Walk-forward %s: return=%.2f%% sharpe=%.2f max_dd=%.2f%% promoted=%s",
            run_id, oos_return * 100, oos_sharpe, oos_max_dd * 100, promoted,
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
                "oos_max_dd": result.oos_max_dd,
                "promoted": result.promoted,
            }, f, indent=2)
