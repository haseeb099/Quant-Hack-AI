"""Parametrized stop sanitization tests for all competition symbols."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import yaml

from src.engine.config import CONFIG_DIR, QuantAIConfig
from src.engine.trading_engine import TradingEngine

# Representative entry prices and ATR per category (plan: forex ~1.0, JPY ~150, XAU ~2600, BTC ~95000)
CATEGORY_PARAMS: dict[str, dict[str, float | int]] = {
    "crypto": {"entry": 95000.0, "atr": 800.0, "point": 0.01, "digits": 2, "stops_level": 50},
    "metals": {"entry": 2600.0, "atr": 15.0, "point": 0.01, "digits": 2, "stops_level": 50},
    "forex": {"entry": 1.0850, "atr": 0.001, "point": 0.00001, "digits": 5, "stops_level": 10},
}

SYMBOL_OVERRIDES: dict[str, dict[str, float | int]] = {
    "ETH/USD": {"entry": 3500.0, "atr": 50.0},
    "SOL/USD": {"entry": 180.0, "atr": 5.0},
    "XRP/USD": {"entry": 0.55, "atr": 0.02, "point": 0.0001, "digits": 4},
    "BAR/USD": {"entry": 0.12, "atr": 0.005, "point": 0.0001, "digits": 4},
    "XAG/USD": {"entry": 30.0, "atr": 0.3, "point": 0.001, "digits": 3},
    "USD/JPY": {"entry": 150.0, "atr": 0.5, "point": 0.001, "digits": 3},
    "EUR/GBP": {"entry": 0.85, "atr": 0.0008},
    "EUR/CHF": {"entry": 0.9276, "atr": 0.001},
}


def _load_instruments() -> list[dict]:
    path = CONFIG_DIR / "instruments.yaml"
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("instruments", [])


def _symbol_params(symbol: str, category: str) -> dict[str, float | int]:
    base = dict(CATEGORY_PARAMS.get(category, CATEGORY_PARAMS["forex"]))
    base.update(SYMBOL_OVERRIDES.get(symbol, {}))
    return base


@pytest.fixture
def engine() -> TradingEngine:
    config = QuantAIConfig.load(phase="round1")
    return TradingEngine(config=config, simulation=True)


@pytest.mark.parametrize(
    "symbol,category",
    [(inst["symbol"], inst["category"]) for inst in _load_instruments()],
    ids=[inst["symbol"] for inst in _load_instruments()],
)
def test_sanitize_stops_buy_corrects_wrong_side(engine: TradingEngine, symbol: str, category: str) -> None:
    """BUY: TP below entry and SL above entry must be corrected."""
    params = _symbol_params(symbol, category)
    entry = float(params["entry"])
    atr = float(params["atr"])
    point = float(params["point"])
    digits = int(params["digits"])
    stops_level = float(params["stops_level"])

    engine._get_symbol_info = MagicMock(
        return_value={
            "contract_size": 1.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
            "digits": digits,
            "point": point,
            "stops_level": stops_level,
        }
    )

    wrong_sl = entry + atr
    wrong_tp = entry - atr
    sl, tp = engine._sanitize_stops(symbol, "BUY", entry, wrong_sl, wrong_tp, atr=atr)

    assert sl is not None and sl < entry, f"{symbol} BUY SL should be below entry"
    assert tp is not None and tp > entry, f"{symbol} BUY TP should be above entry"


@pytest.mark.parametrize(
    "symbol,category",
    [(inst["symbol"], inst["category"]) for inst in _load_instruments()],
    ids=[inst["symbol"] for inst in _load_instruments()],
)
def test_sanitize_stops_sell_corrects_wrong_side(engine: TradingEngine, symbol: str, category: str) -> None:
    """SELL: TP above entry and SL below entry must be corrected."""
    params = _symbol_params(symbol, category)
    entry = float(params["entry"])
    atr = float(params["atr"])
    point = float(params["point"])
    digits = int(params["digits"])
    stops_level = float(params["stops_level"])

    engine._get_symbol_info = MagicMock(
        return_value={
            "contract_size": 1.0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
            "digits": digits,
            "point": point,
            "stops_level": stops_level,
        }
    )

    wrong_sl = entry - atr
    wrong_tp = entry + atr
    sl, tp = engine._sanitize_stops(symbol, "SELL", entry, wrong_sl, wrong_tp, atr=atr)

    assert sl is not None and sl > entry, f"{symbol} SELL SL should be above entry"
    assert tp is not None and tp < entry, f"{symbol} SELL TP should be below entry"
