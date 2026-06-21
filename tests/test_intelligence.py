"""Tests for market intelligence layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.agents.base_agent import Direction, FeatureVector, Regime
from src.agents.sentiment_agent import SentimentAgent
from src.intelligence.calendar_monitor import CalendarMonitor
from src.intelligence.event_risk_gate import EventRiskGate
from src.intelligence.market_intelligence import MarketIntelligenceService
from src.intelligence.models import CalendarEvent, NewsItem
from src.intelligence.news_ingestor import NewsIngestor
from src.intelligence.sentiment_scorer import SentimentScorer
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    write_state(default_state(), state_path)
    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)
    app = create_app()
    assert app is not None
    return TestClient(app)


@pytest.fixture
def intel_config(tmp_path):
    return {
        "enabled": True,
        "cache_dir": str(tmp_path),
        "calendar": {"source": "fixture", "tier_1_window_minutes": 30, "tier_2_window_minutes": 15},
        "news": {"source": "fixture", "max_headlines_per_symbol": 10, "lookback_hours": 4},
        "sentiment": {"min_headlines": 3, "llm_enabled": False, "lexicon_fallback": True},
        "macro": {"fear_greed_enabled": False},
        "event_impact_tiers": {
            "tier_1": ["CPI", "FOMC"],
            "tier_2": ["PMI"],
            "tier_3": ["Consumer Confidence"],
        },
        "symbol_queries": {"BTC/USD": ["bitcoin"], "XAU/USD": ["gold"]},
        "currency_symbols": {
            "USD": ["BTC/USD", "XAU/USD", "EUR/USD"],
            "EUR": ["EUR/USD"],
        },
    }


def test_calendar_monitor_fixture_events(intel_config):
    monitor = CalendarMonitor(intel_config)
    events = monitor.refresh(force=True)
    assert len(events) >= 1
    upcoming = monitor.upcoming(hours=24)
    assert all(e.impact in ("tier_1", "tier_2", "tier_3") for e in upcoming)


def test_event_gate_blocks_tier_1(intel_config):
    monitor = CalendarMonitor(intel_config)
    now = datetime.now(timezone.utc)
    monitor._events = [
        CalendarEvent(
            name="CPI",
            currency="USD",
            impact="tier_1",
            scheduled_at=(now + timedelta(minutes=10)).isoformat(),
        )
    ]
    gate = EventRiskGate(monitor, intel_config)
    result = gate.evaluate("BTC/USD", now)
    assert result.allowed is False
    assert result.blocking_event is not None


def test_event_gate_reduces_tier_2(intel_config):
    monitor = CalendarMonitor(intel_config)
    now = datetime.now(timezone.utc)
    monitor._events = [
        CalendarEvent(
            name="PMI",
            currency="USD",
            impact="tier_2",
            scheduled_at=(now + timedelta(minutes=5)).isoformat(),
        )
    ]
    gate = EventRiskGate(monitor, intel_config)
    result = gate.evaluate("XAU/USD", now)
    assert result.allowed is True
    assert result.size_multiplier == 0.5
    assert result.min_confidence_override == 0.80


def test_news_ingestor_fixture(intel_config):
    ingestor = NewsIngestor(intel_config)
    headlines = ingestor.refresh(["BTC/USD", "XAU/USD"], force=True)
    assert "BTC/USD" in headlines
    assert len(headlines["BTC/USD"]) >= 2


def test_sentiment_scorer_lexicon(intel_config):
    scorer = SentimentScorer(intel_config)
    now = datetime.now(timezone.utc)
    headlines = [
        NewsItem("Bitcoin surge rally gains bullish momentum", "Test", "http://x", (now - timedelta(minutes=30)).isoformat(), "BTC/USD"),
        NewsItem("Crypto rally continues with strong inflows", "Test", "http://y", (now - timedelta(minutes=20)).isoformat(), "BTC/USD"),
        NewsItem("BTC bullish breakout on volume spike", "Test", "http://z", (now - timedelta(minutes=10)).isoformat(), "BTC/USD"),
    ]
    snap = scorer.score("BTC/USD", headlines, macro_bias="risk_on")
    assert snap.score > 0
    assert snap.confidence > 0
    assert snap.headline_count == 3


def test_sentiment_agent_bullish_signal(intel_config):
    agent = SentimentAgent({
        "min_score": 0.4,
        "min_confidence": 0.70,
        "stop_atr_mult": 1.5,
        "target_atr_mult": 2.5,
        "max_confidence": 0.85,
    })
    features = FeatureVector(
        symbol="BTC/USD",
        timeframe="M15",
        close=65000.0,
        atr_14=500.0,
        atr_50=450.0,
        rsi_14=55.0,
        adx=28.0,
        ema_9=64800.0,
        ema_21=64500.0,
        ema_50=64000.0,
        ema_200=62000.0,
        bb_width=0.02,
        bb_width_percentile=50.0,
        donchian_high=66000.0,
        donchian_low=63000.0,
        volume_ratio=1.2,
        macd_histogram=10.0,
        regime=Regime.VOLATILE,
        extras={
            "sentiment_snapshot": {
                "score": 0.65,
                "confidence": 0.75,
                "headline_count": 5,
                "summary": "Bullish crypto headlines",
                "macro_bias": "risk_on",
            },
            "event_gate": {"allowed": True},
            "macro_regime": {"bias": "risk_on"},
        },
    )
    signal = agent.analyze(features)
    assert signal.direction == Direction.BUY
    assert signal.confidence > 0
    assert signal.stop_loss is not None


def test_market_intelligence_service_refresh(intel_config):
    service = MarketIntelligenceService(intel_config)
    service.refresh(["BTC/USD", "XAU/USD"], force=True)
    snap = service.snapshot()
    assert snap["enabled"] is True
    assert "sentiment" in snap
    assert "BTC/USD" in snap["sentiment"]
    assert service.evaluate_event_gate("BTC/USD").allowed in (True, False)


def test_intelligence_api_snapshot(client):
    resp = client.get("/api/intelligence/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data


def test_intelligence_api_calendar(client):
    resp = client.get("/api/intelligence/calendar")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
