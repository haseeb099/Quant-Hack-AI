"""Tests for ML signal model."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.agents.base_agent import FeatureVector, Regime
from src.learning.signal_model import FEATURE_NAMES, SignalModel, features_to_row


def _sample_features() -> FeatureVector:
    return FeatureVector(
        symbol="EUR/USD",
        timeframe="M15",
        close=1.10,
        atr_14=0.001,
        atr_50=0.001,
        rsi_14=55.0,
        adx=22.0,
        ema_9=1.101,
        ema_21=1.099,
        ema_50=1.098,
        ema_200=1.095,
        bb_width=0.02,
        bb_width_percentile=50.0,
        donchian_high=1.105,
        donchian_low=1.095,
        volume_ratio=1.1,
        macd_histogram=0.0001,
        regime=Regime.RANGING,
    )


def test_features_to_row_shape():
    row = features_to_row(_sample_features())
    assert row.shape == (len(FEATURE_NAMES),)


def test_signal_model_train_predict(tmp_path):
    model_path = tmp_path / "signal_model.pkl"
    model = SignalModel(model_path)

    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (80, len(FEATURE_NAMES)))
    y = rng.integers(0, 3, size=80)
    model.fit(X, y)
    model.save()

    loaded = SignalModel(model_path)
    assert loaded.is_loaded
    label, conf = loaded.predict(_sample_features())
    assert label in ("HOLD", "BUY", "SELL")
    assert 0.0 <= conf <= 1.0


def test_build_training_matrix_from_ohlcv():
    n = 250
    price = 100.0 + np.cumsum(np.random.randn(n) * 0.1)
    df = pd.DataFrame({
        "open": price,
        "high": price + 0.2,
        "low": price - 0.2,
        "close": price,
        "volume": np.full(n, 500.0),
    })
    model = SignalModel()
    X, y = model.build_training_matrix(df, "EUR/USD", None)
    assert X.shape[1] == len(FEATURE_NAMES)
    assert len(y) == len(X)
    assert len(X) > 0


def test_ml_signal_agent_active_after_training(tmp_path):
    from src.agents.ml_signal_agent import MLSignalAgent

    n = 550
    price = 100.0 + np.cumsum(np.random.default_rng(1).normal(0, 0.1, n))
    df = pd.DataFrame({
        "open": price,
        "high": price + 0.2,
        "low": price - 0.2,
        "close": price,
        "volume": np.full(n, 500.0),
    })
    parquet_path = tmp_path / "EUR_USD.parquet"
    df.to_parquet(parquet_path, index=False)

    model_path = tmp_path / "signal_model.pkl"
    model = SignalModel(model_path)
    samples = model.train_from_directory(tmp_path)
    assert samples > 0

    agent = MLSignalAgent({"model_path": str(model_path)})
    assert agent.is_active is True
