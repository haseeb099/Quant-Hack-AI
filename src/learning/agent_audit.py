"""Agent audit report from trade memory and jsonl diagnostics."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.learning.layered_memory import LayeredMemory

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("data/agent_audit.json")
AGENT_NAMES = [
    "trend_surfer",
    "breakout_hunter",
    "momentum_pulse",
    "mean_reversion",
    "sentiment_agent",
    "ml_signal",
]


def _load_trades(db_path: Path, round_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
        query = "SELECT * FROM trades"
        params: list[str] = []
        if round_ids:
            placeholders = ",".join("?" * len(round_ids))
            query += f" WHERE round_id IN ({placeholders})"
            params.extend(round_ids)
        rows = conn.execute(query, params).fetchall()

    trades: list[dict[str, Any]] = []
    for row in rows:
        data = dict(zip(columns, row, strict=False))
        try:
            attr = json.loads(data.get("attribution_json") or "{}")
        except json.JSONDecodeError:
            attr = {}
        try:
            votes = json.loads(data.get("votes_json") or "[]")
        except json.JSONDecodeError:
            votes = []
        trades.append({
            "agent": data.get("agent"),
            "symbol": data.get("symbol"),
            "session": data.get("session"),
            "regime": data.get("regime"),
            "direction": data.get("direction"),
            "r_multiple": data.get("r_multiple"),
            "pnl": data.get("pnl"),
            "attribution": attr,
            "votes": votes,
        })
    return trades


def _agent_metrics(trades: list[dict[str, Any]], agent: str) -> dict[str, Any]:
    primary_rows = [t for t in trades if t["agent"] == agent]
    attr_rows = [
        t for t in trades
        if agent in (t["attribution"].get("contributing_agents") or [])
        or t["attribution"].get("primary_agent") == agent
        or t["agent"] == agent
    ]
    rows = attr_rows or primary_rows
    r_vals = [float(t["r_multiple"]) for t in rows if t["r_multiple"] is not None]
    if not r_vals:
        return {
            "agent": agent,
            "sample_size": 0,
            "win_rate": None,
            "avg_r": 0.0,
            "by_regime": {},
            "by_symbol": {},
            "vote_matched_win_rate": None,
            "hold_rate": None,
        }

    wins = sum(1 for r in r_vals if r > 0)
    by_regime: dict[str, list[float]] = defaultdict(list)
    by_symbol: dict[str, list[float]] = defaultdict(list)
    matched: list[float] = []
    opposed: list[float] = []

    for t in rows:
        r = t.get("r_multiple")
        if r is None:
            continue
        by_regime[t.get("regime", "unknown")].append(float(r))
        by_symbol[t.get("symbol", "unknown")].append(float(r))
        contributors = t["attribution"].get("contributing_agents") or [t["agent"]]
        if agent in contributors:
            matched.append(float(r))
        else:
            opposed.append(float(r))

    def _summarize(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"sample_size": 0, "win_rate": None, "avg_r": 0.0}
        w = sum(1 for v in vals if v > 0)
        return {
            "sample_size": len(vals),
            "win_rate": w / len(vals),
            "avg_r": sum(vals) / len(vals),
        }

    return {
        "agent": agent,
        "sample_size": len(r_vals),
        "win_rate": wins / len(r_vals),
        "avg_r": sum(r_vals) / len(r_vals),
        "by_regime": {k: _summarize(v) for k, v in by_regime.items()},
        "by_symbol": {k: _summarize(v) for k, v in by_symbol.items()},
        "vote_matched_win_rate": (
            sum(1 for v in matched if v > 0) / len(matched) if matched else None
        ),
        "opposed_win_rate": (
            sum(1 for v in opposed if v > 0) / len(opposed) if opposed else None
        ),
    }


def _recommendations(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    agent = metrics["agent"]
    for regime, stats in metrics.get("by_regime", {}).items():
        n = stats.get("sample_size", 0)
        wr = stats.get("win_rate")
        if n >= 10 and wr is not None and wr < 0.35:
            recs.append({
                "agent": agent,
                "regime": regime,
                "sample_size": n,
                "win_rate": round(wr, 3),
                "recommendation": f"reduce regime_boost {regime} multiplier",
                "severity": "high" if wr < 0.3 else "medium",
            })
    if metrics.get("sample_size", 0) >= 5 and metrics.get("win_rate") is not None:
        if metrics["win_rate"] < 0.4:
            recs.append({
                "agent": agent,
                "regime": "all",
                "sample_size": metrics["sample_size"],
                "win_rate": round(metrics["win_rate"], 3),
                "recommendation": "reduce agent weight",
                "severity": "medium",
            })
    return recs


class AgentAuditor:
    """Generate per-agent diagnostics from trade memory."""

    def __init__(self, memory: LayeredMemory | None = None) -> None:
        self.memory = memory or LayeredMemory()

    def run(
        self,
        round_ids: list[str] | None = None,
        jsonl_path: str | Path | None = "logs/trades.jsonl",
    ) -> dict[str, Any]:
        trades = _load_trades(self.memory.db_path, round_ids)
        agents: dict[str, Any] = {}
        recommendations: list[dict[str, Any]] = []

        for name in AGENT_NAMES:
            metrics = _agent_metrics(trades, name)
            metrics["attribution"] = self.memory.agent_vote_attribution(name)
            agents[name] = metrics
            recommendations.extend(_recommendations(metrics))

        skip_reasons: dict[str, int] = defaultdict(int)
        jsonl_path = Path(jsonl_path or "logs/trades.jsonl")
        if jsonl_path.exists():
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("status") == "skipped":
                        reason = str(rec.get("skip_reason") or rec.get("reasoning") or "unknown")[:80]
                        skip_reasons[reason] += 1

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_count": len(trades),
            "semantic_keys": self.memory.semantic_key_count(),
            "agents": agents,
            "recommendations": recommendations,
            "skip_reasons": dict(sorted(skip_reasons.items(), key=lambda x: -x[1])[:20]),
        }


def run_agent_audit(
    output_path: str | Path = DEFAULT_OUTPUT,
    round_ids: list[str] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    report = AgentAuditor().run(round_ids=round_ids)
    if persist:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Agent audit written to %s (%d trades)", path, report["trade_count"])
    return report


def load_agent_audit(path: str | Path = DEFAULT_OUTPUT) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
