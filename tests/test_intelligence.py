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
from src.intelligence.rapidapi_client import parse_yahoo_pub_date
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


def test_sentiment_scorer_fixture_headlines_neutral(intel_config):
    scorer = SentimentScorer(intel_config)
    now = datetime.now(timezone.utc)
    headlines = [
        NewsItem(
            f"GBP/USD consolidates in low-volatility session",
            "MarketWatch",
            "https://example.com/news/GBP-USD/0",
            (now - timedelta(minutes=30)).isoformat(),
            "GBP/USD",
        ),
        NewsItem(
            "Traders await macro catalyst for GBP/USD",
            "Reuters",
            "https://example.com/news/GBP-USD/1",
            (now - timedelta(minutes=20)).isoformat(),
            "GBP/USD",
        ),
        NewsItem(
            "Session liquidity thins for GBP/USD ahead of data",
            "Bloomberg",
            "https://example.com/news/GBP-USD/2",
            (now - timedelta(minutes=10)).isoformat(),
            "GBP/USD",
        ),
    ]
    snap = scorer.score("GBP/USD", headlines)
    assert snap.score == 0.0
    assert snap.confidence <= 0.35
    assert "Fixture" in snap.summary or "neutral" in snap.summary.lower()


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


def test_news_ingestor_jblanked_maps_calendar_events(intel_config, monkeypatch):
    intel_config = dict(intel_config)
    intel_config["news"] = {
        **intel_config["news"],
        "source": "jblanked",
        "jblanked_mode": "calendar",
        "jblanked_source": "mql5",
    }
    sample_events = [
        {
            "Name": "CPI",
            "Currency": "USD",
            "Date": "2026.06.22 13:30:00",
            "Actual": "0.3",
            "Forecast": "0.2",
            "Previous": "0.1",
            "Impact": "High",
            "Category": "Inflation",
        },
        {
            "Name": "ECB Rate Decision",
            "Currency": "EUR",
            "Date": "2026.06.22 14:15:00",
            "Actual": "4.25",
            "Forecast": "4.25",
            "Previous": "4.25",
            "Impact": "High",
            "Category": "Interest Rate",
        },
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return __import__("json").dumps(sample_events).encode()

    monkeypatch.setenv("JBLANKED_API_KEY", "test-jblanked-key-with-enough-length")
    monkeypatch.setattr(
        "src.intelligence.jblanked_client.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    ingestor = NewsIngestor(intel_config)
    headlines = ingestor.refresh(["EUR/USD", "XAU/USD"], force=True)

    assert any("USD: CPI" in item.title for item in headlines["EUR/USD"])
    assert any("USD: CPI" in item.title for item in headlines["XAU/USD"])
    assert all(item.source == "JBlanked/mql5" for item in headlines["EUR/USD"])


def test_news_ingestor_live_mode_no_fixture_without_key(intel_config):
    intel_config = dict(intel_config)
    intel_config["news"] = {
        **intel_config["news"],
        "source": "newsapi",
    }
    intel_config["live_mode"] = True
    ingestor = NewsIngestor(intel_config)
    headlines = ingestor.refresh(["EUR/USD"], force=True)
    assert len(headlines["EUR/USD"]) >= 2
    assert headlines["EUR/USD"][0].url.startswith("https://example.com/news/")


def test_news_ingestor_rapidapi_yahoo_filters_by_symbol(intel_config, monkeypatch):
    intel_config = dict(intel_config)
    intel_config["news"] = {
        **intel_config["news"],
        "source": "rapidapi_yahoo",
    }
    sample = [
        {
            "title": "Bitcoin surge lifts crypto markets",
            "source": "CoinDesk",
            "url": "https://finance.yahoo.com/btc",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "summary": "BTC rally continues",
        },
        {
            "title": "Euro steady ahead of ECB decision",
            "source": "Reuters",
            "url": "https://finance.yahoo.com/eur",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "summary": "EUR/USD range-bound",
        },
    ]
    monkeypatch.setenv("RAPIDAPI_KEY", "test-rapidapi-key")
    monkeypatch.setattr(
        "src.intelligence.news_ingestor.fetch_yahoo_news",
        lambda **kwargs: sample,
    )
    ingestor = NewsIngestor(intel_config)
    headlines = ingestor.refresh(["BTC/USD", "EUR/USD"], force=True)
    assert headlines["BTC/USD"][0].title.startswith("Bitcoin")
    assert headlines["EUR/USD"][0].title.startswith("Euro")


def test_calendar_monitor_rapidapi_forex_factory(intel_config, monkeypatch):
    intel_config = dict(intel_config)
    intel_config["calendar"] = {
        **intel_config["calendar"],
        "source": "rapidapi_forex_factory",
    }
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=3)
    sample = [
        {
            "date": future.strftime("%Y-%m-%d"),
            "time": future.strftime("%I:%M%p").lower(),
            "currency": "USD",
            "impact": "High Impact Expected",
            "name": "CPI",
            "actual": "",
            "forecast": "0.3%",
            "previous": "0.2%",
        }
    ]
    monkeypatch.setenv("RAPIDAPI_KEY", "test-rapidapi-key")
    monkeypatch.setattr(
        "src.intelligence.calendar_monitor.fetch_forex_factory_calendar_window",
        lambda **kwargs: sample,
    )
    monitor = CalendarMonitor(intel_config)
    events = monitor.refresh(force=True)
    assert any(e.name == "CPI" and e.currency == "USD" for e in events)


def test_calendar_monitor_prefers_fresh_cache(intel_config, tmp_path):
    intel_config = dict(intel_config)
    intel_config["cache_dir"] = str(tmp_path)
    intel_config["calendar"] = {
        **intel_config["calendar"],
        "source": "cache",
    }
    now = datetime.now(timezone.utc)
    cache_payload = {
        "refreshed_at": now.isoformat(),
        "events": [
            {
                "name": "NFP",
                "currency": "USD",
                "impact": "tier_1",
                "scheduled_at": (now + timedelta(hours=2)).isoformat(),
                "actual": None,
                "forecast": None,
                "previous": None,
            }
        ],
    }
    (tmp_path / "calendar_cache.json").write_text(
        __import__("json").dumps(cache_payload),
        encoding="utf-8",
    )
    monitor = CalendarMonitor(intel_config)
    events = monitor.refresh(force=True)
    assert any(e.name == "NFP" for e in events)


def test_parse_yahoo_pub_date_formats():
    iso = parse_yahoo_pub_date("2026-06-23T14:30:00Z")
    assert "2026-06-23" in iso
    epoch_ms = parse_yahoo_pub_date(1719150000000)
    assert "2024" in epoch_ms
    rfc = parse_yahoo_pub_date("Mon, 23 Jun 2025 12:00:00 GMT")
    assert "2025" in rfc


def test_sentiment_macro_fallback_when_no_headlines(intel_config):
    intel_config = dict(intel_config)
    intel_config["sentiment"] = {
        **intel_config["sentiment"],
        "min_headlines": 3,
        "min_headlines_with_macro": 1,
    }
    scorer = SentimentScorer(intel_config)
    snap = scorer.score("BTC/USD", [], macro_bias="risk_on", usd_strength="weak")
    assert snap.headline_count == 0
    assert snap.confidence > 0
    assert "Macro-only" in snap.summary
    assert snap.score > 0


def test_news_rapidapi_live_mode_zero_matches_returns_empty(intel_config, monkeypatch, caplog):
    intel_config = dict(intel_config)
    intel_config["news"] = {**intel_config["news"], "source": "rapidapi_yahoo"}
    intel_config["live_mode"] = True
    sample = [
        {
            "title": "Unrelated corporate earnings beat expectations",
            "source": "Reuters",
            "url": "https://finance.yahoo.com/x",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "summary": "Tech sector update",
        },
    ]
    monkeypatch.setenv("RAPIDAPI_KEY", "test-rapidapi-key")
    monkeypatch.setattr(
        "src.intelligence.news_ingestor.fetch_yahoo_news",
        lambda **kwargs: sample,
    )
    ingestor = NewsIngestor(intel_config)
    with caplog.at_level("INFO"):
        headlines = ingestor.refresh(["BTC/USD"], force=True)
    assert headlines["BTC/USD"] == []
    assert any("News filter BTC/USD" in r.message for r in caplog.records)


def test_market_intelligence_live_macro_fallback(intel_config, monkeypatch):
    from src.intelligence.models import MacroRegime

    intel_config = dict(intel_config)
    service = MarketIntelligenceService(intel_config)
    monkeypatch.setattr(
        service.news,
        "refresh",
        lambda symbols, force=False: {s: [] for s in symbols},
    )
    monkeypatch.setattr(service.calendar, "refresh", lambda force=False: [])
    monkeypatch.setattr(
        service.macro,
        "refresh",
        lambda force=False: MacroRegime(
            bias="risk_on",
            usd_strength="weak",
            fear_greed=65,
            notes="test macro",
        ),
    )
    service.refresh(["BTC/USD"], force=True)
    snap = service.get_sentiment("BTC/USD")
    assert snap is not None
    assert snap.headline_count == 0
    assert snap.confidence > 0
    assert "Macro-only" in snap.summary


def test_calendar_rapidapi_empty_jblanked_fallback(intel_config, monkeypatch):
    intel_config = dict(intel_config)
    intel_config["calendar"] = {
        **intel_config["calendar"],
        "source": "rapidapi_forex_factory",
    }
    now = datetime.now(timezone.utc)
    jblanked_event = [
        {
            "Name": "GDP",
            "Currency": "USD",
            "Date": now.strftime("%Y.%m.%d %H:%M:%S"),
            "Impact": "Medium",
        },
    ]

    monkeypatch.setenv("RAPIDAPI_KEY", "test-rapidapi-key")
    monkeypatch.setenv("JBLANKED_API_KEY", "test-jblanked-key-with-enough-length")
    monkeypatch.setattr(
        "src.intelligence.calendar_monitor.fetch_forex_factory_calendar_window",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "src.intelligence.calendar_monitor.fetch_jblanked_events",
        lambda **kwargs: jblanked_event,
    )
    monitor = CalendarMonitor(intel_config)
    events = monitor.refresh(force=True)
    assert any(e.name == "GDP" and e.currency == "USD" for e in events)


def test_state_publisher_normalizes_instrument_health():
    from src.web.state_publisher import _enrich_instruments, _normalize_instrument_health

    fresh = _normalize_instrument_health({"tick_age_ms": 500, "last_close": None})
    assert fresh["market_health"] == "green"

    stale_tick = _normalize_instrument_health({"tick_age_ms": 8000, "last_close": 1.08})
    assert stale_tick["market_health"] == "amber"

    enriched = _enrich_instruments(
        {"EUR/USD": {"tick_age_ms": 800, "last_close": None}},
        {
            "decisions": [
                {
                    "symbol": "EUR/USD",
                    "status": "skipped",
                    "skip_reason": "Open position already exists",
                },
            ],
        },
    )
    assert enriched["EUR/USD"]["market_health"] == "green"
    assert enriched["EUR/USD"]["skip_category"] == "open_position"
