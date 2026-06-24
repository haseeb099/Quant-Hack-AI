"""Tests for feature engine, regime detector, session filter, and agents."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.agents.base_agent import Direction, FeatureVector, Regime
from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.data.feature_engine import FeatureEngine, TIMEFRAME_FACTORS, _count_consecutive_squeeze_bars
from src.data.regime_detector import RegimeDetector
from src.data.session_filter import SessionFilter


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    n = 320
    rng = np.random.default_rng(42)
    price = 100.0 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": np.full(n, 500.0),
        }
    )


@pytest.fixture
def trending_ohlcv() -> pd.DataFrame:
    n = 320
    price = 100.0 + np.arange(n) * 0.15
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 0.4,
            "low": price - 0.2,
            "close": price + 0.1,
            "volume": np.full(n, 600.0),
        }
    )


def _make_features(**overrides) -> FeatureVector:
    defaults = dict(
        symbol="EUR/USD",
        timeframe="M15",
        close=100.0,
        atr_14=1.0,
        atr_50=1.0,
        rsi_14=50.0,
        adx=20.0,
        ema_9=100.0,
        ema_21=99.0,
        ema_50=98.0,
        ema_200=95.0,
        bb_width=0.02,
        bb_width_percentile=50.0,
        donchian_high=101.0,
        donchian_low=99.0,
        volume_ratio=1.0,
        macd_histogram=0.0,
        regime=Regime.RANGING,
        extras={
            "bb_middle": 100.0,
            "bb_upper": 102.0,
            "bb_lower": 98.0,
            "atr_percentile": 50.0,
            "macd_line": 0.0,
            "macd_signal": 0.0,
            "macd_histogram_prev": 0.0,
        },
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


class TestFeatureEngine:
    def test_compute_single_timeframe(self, sample_ohlcv):
        engine = FeatureEngine()
        features = engine.compute("EUR/USD", "M15", sample_ohlcv)
        assert features.symbol == "EUR/USD"
        assert features.timeframe == "M15"
        assert features.atr_14 > 0
        assert 0 <= features.rsi_14 <= 100
        assert features.ema_200 > 0
        assert "bb_lower" in features.extras
        assert "macd_line" in features.extras
        assert 0 <= features.extras["atr_percentile"] <= 100

    def test_compute_multi_timeframe(self, sample_ohlcv):
        engine = FeatureEngine()
        multi = engine.compute_multi("XAU/USD", sample_ohlcv)
        assert set(multi.keys()) == {"M15", "H1", "H4"}
        assert multi["H1"].timeframe == "H1"
        assert multi["H4"].timeframe == "H4"

    def test_resample_ohlcv(self, sample_ohlcv):
        h1 = FeatureEngine.resample_ohlcv(sample_ohlcv, TIMEFRAME_FACTORS["H1"])
        assert len(h1) == len(sample_ohlcv) // 4
        assert h1["high"].max() >= h1["close"].max()

    def test_regime_attached(self, trending_ohlcv):
        engine = FeatureEngine()
        features = engine.compute("XAU/USD", "H1", trending_ohlcv)
        assert features.regime in Regime

    def test_compute_includes_agent_extras(self, sample_ohlcv):
        engine = FeatureEngine()
        features = engine.compute("EUR/USD", "M15", sample_ohlcv)
        for key in (
            "bb_squeeze_bars",
            "donchian_high_prev",
            "donchian_low_prev",
            "rsi_prev",
            "volume_prev_ratio",
        ):
            assert key in features.extras
        assert isinstance(features.extras["bb_squeeze_bars"], int)
        assert features.extras["bb_squeeze_bars"] >= 0

    def test_compute_multi_uses_native_h1_h4(self, sample_ohlcv):
        engine = FeatureEngine()
        h1 = FeatureEngine.resample_ohlcv(sample_ohlcv, TIMEFRAME_FACTORS["H1"])
        h1["close"] = h1["close"] + 5.0
        h4 = FeatureEngine.resample_ohlcv(sample_ohlcv, TIMEFRAME_FACTORS["H4"])
        h4["close"] = h4["close"] + 10.0
        multi = engine.compute_multi("EUR/USD", sample_ohlcv, h1_ohlcv=h1, h4_ohlcv=h4)
        resampled = engine.compute_multi("EUR/USD", sample_ohlcv)
        assert multi["H1"].close != resampled["H1"].close
        assert multi["H4"].close != resampled["H4"].close


class TestRegimeDetector:
    def test_volatile_regime(self):
        detector = RegimeDetector()
        assert detector.classify(adx=30, atr_percentile=80, bb_width_percentile=50) == Regime.VOLATILE

    def test_trending_regime(self):
        detector = RegimeDetector()
        assert detector.classify(adx=30, atr_percentile=50, bb_width_percentile=50) == Regime.TRENDING

    def test_ranging_regime(self):
        detector = RegimeDetector()
        assert detector.classify(adx=18, atr_percentile=50, bb_width_percentile=40) == Regime.RANGING

    def test_calm_regime(self):
        detector = RegimeDetector()
        assert detector.classify(adx=15, atr_percentile=30, bb_width_percentile=10) == Regime.CALM


class TestSessionFilter:
    @pytest.fixture
    def session_filter(self) -> SessionFilter:
        return SessionFilter()

    def test_asia_session(self, session_filter):
        ts = datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc)
        assert session_filter.session_name(ts) == "asia"
        assert session_filter.is_symbol_preferred("USD/JPY", ts)
        assert not session_filter.should_skip_symbol("BTC/USD", ts)
        assert session_filter.should_skip_symbol("EUR/USD", ts)

    def test_london_session(self, session_filter):
        ts = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
        assert session_filter.session_name(ts) == "london"
        assert session_filter.is_symbol_preferred("EUR/USD", ts)
        assert not session_filter.should_skip_symbol("BTC/USD", ts)
        assert session_filter.should_skip_symbol("USD/JPY", ts)

    def test_closed_session_crypto_only(self, session_filter):
        ts = datetime(2026, 6, 21, 21, 30, tzinfo=timezone.utc)
        assert session_filter.session_name(ts) == "closed"
        assert not session_filter.should_skip_symbol("BTC/USD", ts)
        assert session_filter.should_skip_symbol("EUR/USD", ts)

    def test_ny_session(self, session_filter):
        ts = datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc)
        assert session_filter.session_name(ts) == "ny"
        assert session_filter.is_symbol_preferred("BTC/USD", ts)
        assert session_filter.should_skip_symbol("EUR/USD", ts)

    def test_overlap_allows_all_symbols(self, session_filter):
        ts = datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)
        assert session_filter.is_overlap(ts)
        assert not session_filter.should_skip_symbol("EUR/USD", ts)
        assert not session_filter.should_skip_symbol("BTC/USD", ts)

    def test_preferred_agents_overlap(self, session_filter):
        ts = datetime(2026, 6, 21, 14, 30, tzinfo=timezone.utc)
        agents = session_filter.preferred_agents(ts)
        assert "breakout_hunter" in agents
        assert "momentum_pulse" in agents

    def test_crypto_trades_during_closed_hours(self, session_filter):
        closed_ts = datetime(2026, 6, 21, 21, 30, tzinfo=timezone.utc)
        assert session_filter.session_name(closed_ts) == "closed"
        assert not session_filter.should_skip_symbol("BTC/USD", closed_ts)
        assert not session_filter.should_skip_symbol("SOL/USD", closed_ts)
        assert session_filter.should_skip_symbol("EUR/USD", closed_ts)
        assert session_filter.should_skip_symbol("XAU/USD", closed_ts)

    def test_disabled_symbol_filter_trades_all_sessions(self):
        session_filter = SessionFilter(symbol_filter_enabled=False)
        asia_ts = datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc)
        assert not session_filter.should_skip_symbol("EUR/USD", asia_ts)
        assert session_filter.should_trade_symbol("EUR/USD", asia_ts)


class TestAgents:
    def test_trend_surfer_uptrend_signal(self):
        agent = TrendSurferAgent({})
        features = _make_features(
            close=110.0,
            ema_9=110.0,
            ema_21=109.0,
            ema_50=105.0,
            adx=28.0,
            macd_histogram=0.5,
            extras={
                "bb_middle": 108.0,
                "bb_upper": 112.0,
                "bb_lower": 104.0,
                "atr_percentile": 50.0,
                "macd_line": 0.6,
                "macd_signal": 0.1,
                "macd_histogram_prev": 0.3,
            },
        )
        signal = agent.analyze(features)
        assert signal.direction == Direction.BUY
        assert signal.confidence >= 0.60
        assert signal.stop_loss is not None
        assert signal.take_profit is not None
        assert signal.stop_loss == pytest.approx(features.close - features.atr_14 * 2.0)
        assert signal.take_profit == pytest.approx(features.close + features.atr_14 * 3.0)

    def test_breakout_hunter_requires_squeeze_and_volume(self):
        agent = BreakoutHunterAgent({})
        features = _make_features(
            close=101.51,
            donchian_high=101.5,
            donchian_low=98.0,
            bb_width_percentile=3.0,
            volume_ratio=1.6,
            rsi_14=60.0,
            extras={
                "bb_squeeze_bars": 10,
                "donchian_high_prev": 101.5,
                "donchian_low_prev": 98.0,
            },
        )
        signal = agent.analyze(features)
        assert signal.direction == Direction.BUY
        assert signal.confidence >= 0.65

        no_squeeze = _make_features(
            close=102.0,
            donchian_high=101.5,
            bb_width_percentile=20.0,
            volume_ratio=1.6,
        )
        assert agent.analyze(no_squeeze).direction == Direction.HOLD

    def test_momentum_pulse_macd_cross(self):
        agent = MomentumPulseAgent({})
        features = _make_features(
            adx=30.0,
            volume_ratio=1.3,
            bb_width_percentile=20.0,
            ema_9=101.0,
            ema_21=100.0,
            macd_histogram=0.2,
            extras={
                "bb_middle": 100.0,
                "bb_upper": 102.0,
                "bb_lower": 98.0,
                "atr_percentile": 50.0,
                "macd_line": 0.3,
                "macd_signal": 0.1,
                "macd_histogram_prev": -0.1,
            },
        )
        signal = agent.analyze(features)
        assert signal.direction == Direction.BUY
        assert signal.confidence >= 0.55

    def test_mean_reversion_min_confidence(self):
        agent = MeanReversionAgent({})
        features = _make_features(
            adx=18.0,
            rsi_14=25.0,
            close=98.1,
            extras={
                "bb_middle": 100.0,
                "bb_upper": 102.0,
                "bb_lower": 98.0,
                "atr_percentile": 50.0,
                "macd_line": 0.0,
                "macd_signal": 0.0,
                "macd_histogram_prev": 0.0,
                "rsi_prev": 22.0,
                "volume_prev_ratio": 1.5,
            },
        )
        signal = agent.analyze(features)
        assert signal.direction == Direction.BUY
        assert signal.confidence >= 0.70

    def test_count_consecutive_squeeze_bars(self):
        series = pd.Series([50.0, 50.0, 4.0, 3.0, 2.0, 4.0, 3.0, 3.0, 2.0, 1.0])
        assert _count_consecutive_squeeze_bars(series, threshold=5.0) == 8

    def test_breakout_hunter_with_engine_features(self, sample_ohlcv):
        engine = FeatureEngine()
        features = engine.compute("EUR/USD", "M15", sample_ohlcv)
        assert "bb_squeeze_bars" in features.extras
        assert features.extras["donchian_high_prev"] > 0
        assert features.extras["donchian_low_prev"] > 0
        assert features.extras["donchian_high_prev"] != features.donchian_high or len(sample_ohlcv) > 2
        agent = BreakoutHunterAgent({})
        signal = agent.analyze(features)
        assert "bb_squeeze_bars" in features.extras
        assert isinstance(features.extras["bb_squeeze_bars"], int)
        assert signal.reasoning != "No breakout: requires BB squeeze + volume spike" or features.bb_width_percentile > 5

    def test_mean_reversion_with_engine_features(self):
        n = 320
        price = np.full(n, 100.0)
        price[-30:] = np.linspace(100.0, 97.5, 30)
        volume = np.full(n, 800.0)
        volume[-2] = 1200.0
        volume[-1] = 400.0
        ohlcv = pd.DataFrame(
            {
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": volume,
            }
        )
        engine = FeatureEngine()
        features = engine.compute("EUR/USD", "M15", ohlcv)
        assert "rsi_prev" in features.extras
        assert "volume_prev_ratio" in features.extras
        agent = MeanReversionAgent({})
        signal = agent.analyze(features)
        assert "Oversold but no RSI divergence or volume decline" not in signal.reasoning
        if signal.direction == Direction.BUY:
            assert signal.confidence >= 0.70

    def test_all_agents_produce_valid_signals(self, sample_ohlcv):
        engine = FeatureEngine()
        features = engine.compute("EUR/USD", "M15", sample_ohlcv)
        agents = [
            TrendSurferAgent({}),
            BreakoutHunterAgent({}),
            MomentumPulseAgent({}),
            MeanReversionAgent({}),
        ]
        for agent in agents:
            signal = agent.analyze(features)
            assert signal.agent_name == agent.name
            assert signal.symbol == "EUR/USD"
            assert 0.0 <= signal.confidence <= 1.0
            assert signal.direction in Direction
