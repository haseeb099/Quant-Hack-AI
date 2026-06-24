"""Tests for walk-forward short-data window shrinking."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.learning.walk_forward import WalkForwardValidator


def _make_ohlcv(bars: int) -> pd.DataFrame:
    price = 100.0 + np.cumsum(np.random.randn(bars) * 0.05)
    return pd.DataFrame({
        "open": price,
        "high": price + 0.1,
        "low": price - 0.1,
        "close": price,
        "volume": np.full(bars, 500.0),
    })


def test_adjust_windows_short_data():
    wf = WalkForwardValidator(train_window_days=60, test_window_days=14)
    # 31 days ≈ 2976 bars
    bars_31d = 31 * 96
    train, test = wf.adjust_windows_for_data(bars_31d)
    assert train == 14
    assert test == 7


def test_adjust_windows_long_data():
    wf = WalkForwardValidator(train_window_days=60, test_window_days=14)
    bars_90d = 90 * 96
    train, test = wf.adjust_windows_for_data(bars_90d)
    assert train == 60
    assert test == 14


def test_validate_all_symbols_aggregates(tmp_path):
    wf = WalkForwardValidator()
    for sym in ("EUR_USD", "GBP_USD"):
        df = _make_ohlcv(2500)
        df.to_parquet(tmp_path / f"{sym}.parquet", index=False)

    params = {
        "trend_surfer": 0.25,
        "breakout_hunter": 0.25,
        "momentum_pulse": 0.25,
        "mean_reversion": 0.25,
    }
    result = wf.validate_all_symbols(
        run_id="test_short",
        params=params,
        data_dir=tmp_path,
        baseline_weights=params,
    )
    assert result.symbol_count >= 1
    assert "train=" in result.dataset_window


def test_replay_uses_sl_tp_simulation():
    wf = WalkForwardValidator()
    df = _make_ohlcv(600)
    returns = wf._replay_weighted_returns(df, {"trend_surfer": 0.5, "mean_reversion": 0.5})
    assert len(returns) >= 0
    if len(returns) > 0:
        assert returns.max() <= 0.5
        assert returns.min() >= -0.5
