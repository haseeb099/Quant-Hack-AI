"""Tests for metals bias and mean-reversion metal guard."""

from __future__ import annotations

from src.agents.base_agent import FeatureVector, Regime
from src.agents.mean_reversion import MeanReversionAgent


def _features(symbol: str, rsi: float, extras: dict, close: float = 101.8) -> FeatureVector:
    base = {
        "symbol": symbol,
        "timeframe": "M15",
        "close": close,
        "atr_14": 1.0,
        "atr_50": 1.0,
        "rsi_14": rsi,
        "adx": 18.0,
        "ema_9": 100.0,
        "ema_21": 99.5,
        "ema_50": 98.0,
        "ema_200": 97.0,
        "bb_width": 0.02,
        "bb_width_percentile": 50.0,
        "donchian_high": 101.0,
        "donchian_low": 99.0,
        "volume_ratio": 0.9,
        "macd_histogram": 0.0,
        "regime": Regime.RANGING,
        "extras": {
            "bb_lower": 98.0,
            "bb_upper": 102.0,
            "bb_middle": 100.0,
            "volume_prev_ratio": 1.0,
            **extras,
        },
    }
    return FeatureVector(**base)


def test_mr_suppresses_metal_sell_in_risk_off() -> None:
    agent = MeanReversionAgent({"require_divergence": False, "rsi_overbought": 70})
    features = _features(
        "XAU/USD",
        76.0,
        {
            "macro_regime": {"bias": "risk_off", "usd_strength": "strong"},
            "instrument_bias": "bullish",
        },
        close=101.95,
    )
    signal = agent.analyze(features)
    assert signal.direction.value == "HOLD"
    assert "risk-off" in signal.reasoning.lower()


def test_mr_caps_bullish_metal_sell_confidence() -> None:
    agent = MeanReversionAgent({"require_divergence": False, "rsi_overbought": 70, "min_confidence": 0.70})
    features = _features(
        "XAG/USD",
        78.0,
        {
            "macro_regime": {"bias": "neutral", "usd_strength": "neutral"},
            "instrument_bias": "bullish",
        },
    )
    signal = agent.analyze(features)
    if signal.direction.value == "SELL":
        assert signal.confidence <= 0.55
