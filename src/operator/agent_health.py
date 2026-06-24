"""Agent health suite — smoke-test all six trading agents on competition symbols."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.agents.base_agent import Direction
from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.ml_signal_agent import MLSignalAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.data.feature_engine import FeatureEngine
from src.engine.config import QuantAIConfig, load_yaml

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("data/agent_health.json")
AGENT_NAMES = [
    "trend_surfer",
    "breakout_hunter",
    "momentum_pulse",
    "mean_reversion",
    "sentiment_agent",
    "ml_signal",
]


def _competition_symbols() -> list[str]:
    instruments = load_yaml("instruments.yaml").get("instruments", [])
    return [
        str(i["symbol"])
        for i in instruments
        if i.get("active", True) and i.get("symbol")
    ]


def _load_bars(symbol: str, data_dir: Path) -> pd.DataFrame | None:
    stem = symbol.replace("/", "_")
    for suffix in (".parquet", ".csv"):
        path = data_dir / f"{stem}{suffix}"
        if not path.exists():
            continue
        df = pd.read_parquet(path) if suffix == ".parquet" else pd.read_csv(path)
        if len(df) >= 50:
            return df
    return None


def _fixture_bars(kind: str, n: int = 220) -> pd.DataFrame:
    rng = np.random.default_rng(42 if kind == "trending" else 7)
    if kind == "trending":
        price = 100.0 + np.arange(n) * 0.12
    elif kind == "volatile":
        price = 100.0 + np.cumsum(rng.normal(0, 0.8, n))
    else:
        price = 100.0 + np.sin(np.arange(n) / 8.0) * 2.0
    return pd.DataFrame({
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price + rng.normal(0, 0.05, n),
        "volume": np.full(n, 600.0),
    })


def _inject_mtf_extras(features, multi: dict) -> None:
    h1 = multi.get("H1")
    h4 = multi.get("H4")
    if h1:
        features.extras["h1_adx"] = h1.adx
        features.extras["h1_trend_bull"] = h1.close > h1.ema_50 and h1.ema_9 > h1.ema_21
        features.extras["h1_trend_bear"] = h1.close < h1.ema_50 and h1.ema_9 < h1.ema_21
    if h4:
        features.extras["h4_trend_bull"] = h4.close > h4.ema_50 and h4.ema_9 > h4.ema_21
        features.extras["h4_trend_bear"] = h4.close < h4.ema_50 and h4.ema_9 < h4.ema_21


def _mock_sentiment(features) -> None:
    features.extras["sentiment_snapshot"] = {
        "score": 0.45,
        "confidence": 0.72,
        "headline_count": 5,
        "summary": "Health-check fixture sentiment",
        "macro_bias": "neutral",
    }
    features.extras["event_gate"] = {"allowed": True, "reason": ""}
    features.extras["macro_regime"] = {"bias": "neutral"}


class AgentHealthSuite:
    """Verify all six agents produce valid signals on competition symbols."""

    FIXTURES = {
        "trend_surfer": "trending",
        "breakout_hunter": "volatile",
        "momentum_pulse": "trending",
        "mean_reversion": "ranging",
        "sentiment_agent": "ranging",
        "ml_signal": "trending",
    }

    def __init__(
        self,
        config: QuantAIConfig | None = None,
        data_dir: str | Path = "data/historical",
    ) -> None:
        self.config = config or QuantAIConfig.load()
        self.data_dir = Path(data_dir)
        self.engine = FeatureEngine()
        agent_cfg = self.config.agents
        self.agents = {
            "trend_surfer": TrendSurferAgent(agent_cfg.get("trend_surfer", {})),
            "breakout_hunter": BreakoutHunterAgent(agent_cfg.get("breakout_hunter", {})),
            "momentum_pulse": MomentumPulseAgent(agent_cfg.get("momentum_pulse", {})),
            "mean_reversion": MeanReversionAgent(agent_cfg.get("mean_reversion", {})),
            "sentiment_agent": SentimentAgent(agent_cfg.get("sentiment_agent", {})),
            "ml_signal": MLSignalAgent(agent_cfg.get("ml_signal", {})),
        }

    def _analyze_agent(self, name: str, symbol: str, df: pd.DataFrame) -> dict[str, Any]:
        agent = self.agents[name]
        multi = self.engine.compute_multi(symbol, df, donchian_period=20)
        if not multi:
            return {"fired": False, "direction": "HOLD", "confidence": 0.0, "reason": "no features"}
        primary = multi.get("M15") or next(iter(multi.values()))
        cfg = agent.config
        best = None
        for tf in cfg.get("timeframes", ["M15"]):
            features = multi.get(tf) or primary
            _inject_mtf_extras(features, multi)
            if name == "sentiment_agent":
                _mock_sentiment(features)
            sig = agent.analyze(features)
            if best is None or sig.confidence > best.confidence:
                best = sig
        if best is None:
            return {"fired": False, "direction": "HOLD", "confidence": 0.0, "reason": "no signal"}
        return {
            "fired": best.is_actionable,
            "direction": best.direction.value,
            "confidence": best.confidence,
            "reason": best.reasoning[:120],
        }

    def run(self, symbols: list[str] | None = None) -> dict[str, Any]:
        symbols = symbols or _competition_symbols()
        intelligence_enabled = os.getenv("INTELLIGENCE_ENABLED", "true").lower() in ("1", "true", "yes")
        agents_report: dict[str, dict[str, Any]] = {}

        for name in AGENT_NAMES:
            firing = 0
            issues: list[str] = []
            if name == "ml_signal" and not self.agents["ml_signal"].is_active:
                agents_report[name] = {
                    "active": False,
                    "symbols_firing": 0,
                    "symbols_tested": len(symbols),
                    "issue": "ML model not loaded",
                }
                continue
            if name == "sentiment_agent" and not intelligence_enabled:
                agents_report[name] = {
                    "active": False,
                    "symbols_firing": 0,
                    "symbols_tested": len(symbols),
                    "issue": "INTELLIGENCE_ENABLED=false",
                }
                continue

            for symbol in symbols:
                df = _load_bars(symbol, self.data_dir)
                if df is None:
                    df = _fixture_bars(self.FIXTURES.get(name, "ranging"))
                result = self._analyze_agent(name, symbol, df.iloc[-220:].copy())
                if result["fired"]:
                    firing += 1
                elif result["direction"] == "HOLD" and name not in ("sentiment_agent",):
                    pass

            fixture_df = _fixture_bars(self.FIXTURES.get(name, "ranging"))
            fixture = self._analyze_agent(name, "HEALTH/CHECK", fixture_df)
            if not fixture["fired"] and name != "sentiment_agent":
                issues.append(f"fixture not actionable: {fixture['reason'][:80]}")

            active = firing > 0 or fixture["fired"]
            agents_report[name] = {
                "active": active,
                "symbols_firing": firing,
                "symbols_tested": len(symbols),
                "fixture_fired": fixture["fired"],
                "issue": issues[0] if issues and not active else None,
            }

        red_agents = [n for n, r in agents_report.items() if not r.get("active")]
        if not red_agents:
            status = "GREEN"
        elif len(red_agents) <= 2:
            status = "YELLOW"
        else:
            status = "RED"

        return {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols": symbols,
            "agents": agents_report,
            "red_agents": red_agents,
        }


def run_agent_health(
    output_path: str | Path = DEFAULT_OUTPUT,
    data_dir: str | Path = "data/historical",
    persist: bool = True,
) -> dict[str, Any]:
    report = AgentHealthSuite(data_dir=data_dir).run()
    if persist:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Agent health report written to %s (status=%s)", path, report["status"])
    return report


def load_agent_health(path: str | Path = DEFAULT_OUTPUT) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
