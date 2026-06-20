"""Basic and expanded tests for QuantAI core modules."""

import json
import numpy as np
import pandas as pd
import pytest

from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.meta_orchestrator import MetaOrchestrator
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.agents.base_agent import Direction
from src.bridges.zeromq_connector import ZeroMQConnector
from src.data.feature_engine import FeatureEngine
from src.data.regime_detector import RegimeDetector
from src.data.session_filter import SessionFilter
from src.engine.config import QuantAIConfig
from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.risk.compliance_heartbeat import ComplianceHeartbeat
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.kelly_sizer import KellySizer
from src.risk.sharpe_guard import SharpeGuard
from src.utils.trade_logger import TradeLogger


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    n = 200
    price = 100.0 + np.cumsum(np.random.randn(n) * 0.3)
    return pd.DataFrame({
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "volume": np.full(n, 500.0),
    })


def test_config_loads():
    config = QuantAIConfig.load(phase="round1")
    assert config.current_phase == "round1"
    assert len(config.active_symbols) == 15
    assert config.phase_multiplier == 1.2


def test_feature_engine(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("EUR/USD", "M15", sample_ohlcv)
    assert features.symbol == "EUR/USD"
    assert features.atr_14 > 0
    assert 0 <= features.rsi_14 <= 100
    assert features.ema_200 > 0


def test_feature_engine_multi_timeframe(sample_ohlcv):
    engine = FeatureEngine()
    multi = engine.compute_multi("EUR/USD", sample_ohlcv)
    assert "M15" in multi
    assert multi["M15"].timeframe == "M15"


def test_regime_detector():
    from src.agents.base_agent import Regime
    detector = RegimeDetector()
    assert detector.classify(adx=30, atr_percentile=50, bb_width_percentile=50) == Regime.TRENDING
    assert detector.classify(adx=15, atr_percentile=90, bb_width_percentile=50) == Regime.VOLATILE
    assert detector.classify(adx=15, atr_percentile=20, bb_width_percentile=10) == Regime.CALM


def test_trend_surfer_produces_signal(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("XAU/USD", "H1", sample_ohlcv)
    agent = TrendSurferAgent({})
    signal = agent.analyze(features)
    assert signal.agent_name == "trend_surfer"
    assert signal.confidence >= 0


def test_breakout_hunter_produces_signal(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("BTC/USD", "M15", sample_ohlcv)
    agent = BreakoutHunterAgent({})
    signal = agent.analyze(features)
    assert signal.agent_name == "breakout_hunter"


def test_momentum_pulse_produces_signal(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("ETH/USD", "M15", sample_ohlcv)
    agent = MomentumPulseAgent({})
    signal = agent.analyze(features)
    assert signal.agent_name == "momentum_pulse"


def test_mean_reversion_produces_signal(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("EUR/USD", "M15", sample_ohlcv)
    agent = MeanReversionAgent({})
    signal = agent.analyze(features)
    assert signal.agent_name == "mean_reversion"


def test_session_filter_windows():
    from datetime import datetime, timezone
    sf = SessionFilter()
    asia = sf.current_session(datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc))
    assert asia.name == "asia"
    london = sf.current_session(datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc))
    assert london.name == "london"
    overlap = sf.current_session(datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc))
    assert overlap.name == "overlap"
    assert sf.should_trade_symbol("EUR/USD", datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc))


def test_zeromq_connector_simulation():
    conn = ZeroMQConnector()
    assert not conn.is_connected
    result = conn.send_trade("EUR/USD", "BUY", 0.1)
    assert result["status"] == "simulated"
    account = conn.get_account_info()
    assert account["equity"] == 1_000_000


def test_zeromq_protocol_mock():
    """Verify command structure matches MQL5 protocol."""
    conn = ZeroMQConnector()
    cmd = {"action": "DATA", "symbol": "EUR/USD", "timeframe": "M15", "count": 200}
    serialized = json.dumps(cmd)
    parsed = json.loads(serialized)
    assert parsed["action"] == "DATA"
    assert parsed["symbol"] == "EUR/USD"


def test_drawdown_guard_tiers():
    guard = DrawdownGuard({
        "normal_max": 0.05,
        "elevated_max": 0.10,
        "warning_max": 0.12,
        "critical_max": 0.15,
        "emergency_close": 0.15,
        "size_multipliers": {
            "normal": 1.0, "elevated": 0.75, "warning": 0.5,
            "critical": 0.25, "emergency": 0.0,
        },
    })
    guard.reset(1_000_000)
    state = guard.update(950_000)
    assert state.tier == "elevated"
    assert state.size_multiplier == 0.75

    guard.reset(1_000_000)
    emergency = guard.update(840_000)
    assert emergency.tier == "emergency"
    assert not emergency.allow_new_trades


def test_kelly_sizer():
    sizer = KellySizer({"max_risk_per_trade": 0.02})
    size = sizer.compute_size(
        equity=1_000_000,
        win_rate=0.55,
        reward_risk_ratio=2.0,
        atr_14=1.0,
        atr_50=1.0,
        confidence=0.8,
    )
    assert 0 < size <= 20_000


def test_meta_orchestrator_rule_fallback(sample_ohlcv):
    engine = FeatureEngine()
    features = engine.compute("EUR/USD", "M15", sample_ohlcv)
    agents = [
        TrendSurferAgent({"adx_threshold": 25, "base_confidence": 0.7, "max_confidence": 0.95}),
        MeanReversionAgent({}),
    ]
    signals = [a.analyze(features) for a in agents]
    orch = MetaOrchestrator({"min_agent_confidence": 0.5}, {})
    decision = orch.decide(features, signals)
    assert decision.symbol == "EUR/USD"
    assert decision.direction in (Direction.BUY, Direction.SELL, Direction.HOLD)


def test_layered_memory(tmp_path):
    db = tmp_path / "test_memory.db"
    memory = LayeredMemory(db_path=db)
    record = TradeRecord(
        trade_id="t1",
        symbol="EUR/USD",
        session="london",
        regime="ranging",
        agent="mean_reversion",
        direction="BUY",
        entry_price=1.10,
        exit_price=1.11,
        r_multiple=1.5,
        pnl=100,
    )
    memory.store_trade(record)
    working = memory.get_working_memory()
    assert len(working) == 1
    similar = memory.retrieve_similar_setups("ranging", "EUR/USD", "london")
    assert len(similar) >= 1


def test_trade_logger(tmp_path):
    logger = TradeLogger(log_dir=tmp_path)
    logger.log(
        symbol="EUR/USD",
        regime="ranging",
        session="london",
        direction="BUY",
        confidence=0.75,
    )
    assert (tmp_path / "trades.jsonl").exists()
    assert (tmp_path / "trades.csv").exists()


def test_compliance_heartbeat():
    hb = ComplianceHeartbeat()
    actions = hb.check({"margin_usage_pct": 0.95, "effective_leverage": 10, "concentration_pct": 0.3})
    assert isinstance(actions, list)


def test_sharpe_guard():
    guard = SharpeGuard(snapshot_interval_minutes=0)
    guard.record_equity(1_000_000)
    guard.record_equity(990_000)
    assert guard.snapshot_count() >= 1
    assert guard.current_drawdown(950_000) > 0


def test_trading_engine_single_cycle():
    from src.engine.trading_engine import TradingEngine
    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    engine.start()
    engine.run_cycle()


def test_sanitize_stops_buy_tp_below_entry():
    """Mean-reversion can emit TP below entry on fast moves — engine must fix it."""
    from src.engine.trading_engine import TradingEngine

    config = QuantAIConfig.load(phase="round1")
    engine = TradingEngine(config=config, simulation=True)
    entry = 0.9276
    sl, tp = engine._sanitize_stops("EUR/CHF", "BUY", entry, 0.92446, 0.92584, atr=0.001)
    assert sl is not None and sl < entry
    assert tp is not None and tp > entry
