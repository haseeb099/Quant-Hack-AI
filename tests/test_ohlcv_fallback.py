"""Tests for OHLCV fallback chain in trading engine."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SENTIMENT_AGENT_ENABLED", "false")
    from src.engine.config import QuantAIConfig
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round1", auto_phase=False)
    return TradingEngine(config=config, simulation=True)


def test_parquet_fallback_used_when_bridges_fail(engine, tmp_path, monkeypatch) -> None:
    hist = tmp_path / "data" / "historical"
    hist.mkdir(parents=True)
    n = 120
    df = pd.DataFrame({
        "open": [1.1] * n,
        "high": [1.11] * n,
        "low": [1.09] * n,
        "close": [1.105] * n,
        "volume": [100.0] * n,
    })
    df.to_parquet(hist / "EUR_USD.parquet")

    monkeypatch.chdir(tmp_path)
    engine.simulation = False
    engine.connector.get_ohlcv = MagicMock(return_value=None)

    with patch.object(engine, "_get_ohlcv_mt5_fallback", return_value=None):
        result = engine._get_ohlcv("EUR/USD", "M15")

    assert result is not None
    assert len(result) >= 50
    assert engine._ohlcv_source.get("EUR/USD") == "parquet_fallback"


def test_parquet_fallback_rejects_stale_file(engine, tmp_path, monkeypatch) -> None:
    hist = tmp_path / "data" / "historical"
    hist.mkdir(parents=True)
    path = hist / "EUR_USD.parquet"
    n = 120
    df = pd.DataFrame({
        "open": [1.1] * n,
        "high": [1.11] * n,
        "low": [1.09] * n,
        "close": [1.105] * n,
        "volume": [100.0] * n,
    })
    df.to_parquet(path)

    old = time.time() - (49 * 3600)
    import os
    os.utime(path, (old, old))

    monkeypatch.chdir(tmp_path)
    engine.simulation = False
    engine.connector.get_ohlcv = MagicMock(return_value=None)

    with patch.object(engine, "_get_ohlcv_mt5_fallback", return_value=None):
        result = engine._get_ohlcv("EUR/USD", "M15")

    assert result is None
