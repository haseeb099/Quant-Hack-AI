"""Tests for pricer tick ingestion."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.ingest_pricer_output import (
    COMPETITION_SYMBOLS,
    pricer_symbol_to_stem,
    resample_ticks_to_m15,
)


def test_pricer_symbol_to_stem():
    assert pricer_symbol_to_stem("EURUSD") == "EUR_USD"
    assert pricer_symbol_to_stem("XAUUSD") == "XAU_USD"
    assert pricer_symbol_to_stem("EURGBP") == "EUR_GBP"


def test_resample_ticks_to_m15():
    n = 2000  # ~33 minutes → multiple M15 bars
    ts = pd.date_range("2026-05-11", periods=n, freq="1s", tz="UTC")
    mid = 1.10 + np.random.randn(n) * 0.0001
    df = pd.DataFrame({
        "time": ts,
        "received": ts,
        "bid": mid - 0.00005,
        "ask": mid + 0.00005,
    })
    ohlcv = resample_ticks_to_m15(df)
    assert list(ohlcv.columns) == ["open", "high", "low", "close", "volume"]
    assert len(ohlcv) >= 1
    assert ohlcv["volume"].iloc[0] >= 1


def test_competition_symbols_count():
    assert len(COMPETITION_SYMBOLS) == 10


@pytest.mark.parametrize("sym", ["BTCUSD", "ETHUSD"])
def test_competition_symbols_exclude_crypto(sym):
    assert sym not in COMPETITION_SYMBOLS
