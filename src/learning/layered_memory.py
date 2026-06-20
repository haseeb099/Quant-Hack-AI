"""FinMem 3-layer memory: Working, Episodic (SQLite), Semantic."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    session: str
    regime: str
    agent: str
    direction: str
    entry_price: float
    exit_price: float | None = None
    r_multiple: float | None = None
    pnl: float | None = None
    features_snapshot: dict[str, Any] = field(default_factory=dict)
    agent_votes: list[dict[str, Any]] = field(default_factory=list)
    orchestrator_reasoning: str = ""
    entry_time: str = ""
    exit_time: str = ""
    round_id: str = ""


class LayeredMemory:
    """Three-layer trade memory per Doc 14 SOTA upgrade."""

    MIN_SEMANTIC_SAMPLES = 5
    WORKING_MEMORY_SIZE = 3

    def __init__(self, db_path: str | Path = "data/trade_memory.db", round_id: str = "round1") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.round_id = round_id
        self._working: list[TradeRecord] = []
        self._semantic: dict[str, dict[str, Any]] = {}
        self._init_db()
        self.rebuild_semantic_layer()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    session TEXT,
                    regime TEXT,
                    agent TEXT,
                    direction TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    r_multiple REAL,
                    pnl REAL,
                    features_json TEXT,
                    votes_json TEXT,
                    reasoning TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    round_id TEXT
                )
            """)

    def store_trade(self, record: TradeRecord) -> None:
        record.round_id = record.round_id or self.round_id
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.trade_id, record.symbol, record.session, record.regime,
                    record.agent, record.direction, record.entry_price, record.exit_price,
                    record.r_multiple, record.pnl,
                    json.dumps(record.features_snapshot),
                    json.dumps(record.agent_votes),
                    record.orchestrator_reasoning,
                    record.entry_time or datetime.now(timezone.utc).isoformat(),
                    record.exit_time,
                    record.round_id,
                ),
            )

        self._working.append(record)
        if len(self._working) > self.WORKING_MEMORY_SIZE:
            self._working = self._working[-self.WORKING_MEMORY_SIZE:]

        key = self._semantic_key(record.regime, record.symbol, record.session)
        if key not in self._semantic:
            self._semantic[key] = {"agents": defaultdict(lambda: {"wins": 0, "total": 0, "avg_r": 0.0})}
        agent_stats = self._semantic[key]["agents"][record.agent]
        agent_stats["total"] += 1
        if record.r_multiple and record.r_multiple > 0:
            agent_stats["wins"] += 1
        if record.r_multiple is not None:
            n = agent_stats["total"]
            agent_stats["avg_r"] = (
                agent_stats["avg_r"] * (n - 1) + record.r_multiple
            ) / n

        try:
            from src.integrations.notion_sync import get_notion_sync

            stats = self.agent_performance(record.agent)
            get_notion_sync().sync_agent_performance(
                record.agent,
                stats,
                trade={
                    "symbol": record.symbol,
                    "direction": record.direction,
                    "r_multiple": record.r_multiple,
                    "pnl": record.pnl,
                },
            )
        except Exception:
            logger.debug("Notion agent sync skipped", exc_info=True)

    def get_working_memory(self) -> list[TradeRecord]:
        return list(self._working)

    def retrieve_similar_setups(
        self,
        regime: str,
        symbol: str,
        session: str,
        top_k: int = 5,
    ) -> list[TradeRecord]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE regime = ? AND symbol = ? AND session = ?
                   ORDER BY exit_time DESC LIMIT ?""",
                (regime, symbol, session, top_k * 3),
            ).fetchall()

        records = [self._row_to_record(r) for r in rows]
        scored: list[tuple[float, TradeRecord]] = []
        for rec in records:
            score = 1.0
            if rec.r_multiple is not None:
                score += abs(rec.r_multiple)
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def get_semantic_context(self, regime: str, symbol: str, session: str) -> dict[str, Any]:
        key = self._semantic_key(regime, symbol, session)
        data = self._semantic.get(key, {})
        agents = data.get("agents", {})
        best_agent = None
        best_score = -999.0

        for agent, stats in agents.items():
            if stats["total"] < self.MIN_SEMANTIC_SAMPLES:
                continue
            win_rate = stats["wins"] / stats["total"]
            score = win_rate * 0.6 + stats["avg_r"] * 0.4
            if score > best_score:
                best_score = score
                best_agent = agent

        return {
            "best_agent": best_agent,
            "best_agent_score": best_score if best_agent else 0.0,
            "sample_count": sum(s["total"] for s in agents.values()),
            "agents": dict(agents),
        }

    def rebuild_semantic_layer(self) -> None:
        self._semantic = {}
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM trades").fetchall()

        for row in rows:
            rec = self._row_to_record(row)
            key = self._semantic_key(rec.regime, rec.symbol, rec.session)
            if key not in self._semantic:
                self._semantic[key] = {"agents": defaultdict(lambda: {"wins": 0, "total": 0, "avg_r": 0.0})}
            stats = self._semantic[key]["agents"][rec.agent]
            stats["total"] += 1
            if rec.r_multiple and rec.r_multiple > 0:
                stats["wins"] += 1
            if rec.r_multiple is not None:
                n = stats["total"]
                stats["avg_r"] = (stats["avg_r"] * (n - 1) + rec.r_multiple) / n

    def agent_performance(self, agent: str, regime: str | None = None) -> dict[str, float]:
        query = "SELECT r_multiple FROM trades WHERE agent = ?"
        params: list[str] = [agent]
        if regime:
            query += " AND regime = ?"
            params.append(regime)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        r_values = [r[0] for r in rows if r[0] is not None]
        if not r_values:
            return {"win_rate": 0.5, "avg_r": 0.0, "sample_size": 0}

        wins = sum(1 for r in r_values if r > 0)
        return {
            "win_rate": wins / len(r_values),
            "avg_r": sum(r_values) / len(r_values),
            "sample_size": len(r_values),
        }

    @staticmethod
    def _semantic_key(regime: str, symbol: str, session: str) -> str:
        return f"{regime}|{symbol}|{session}"

    @staticmethod
    def _row_to_record(row: tuple) -> TradeRecord:
        return TradeRecord(
            trade_id=row[0], symbol=row[1], session=row[2], regime=row[3],
            agent=row[4], direction=row[5], entry_price=row[6], exit_price=row[7],
            r_multiple=row[8], pnl=row[9],
            features_snapshot=json.loads(row[10] or "{}"),
            agent_votes=json.loads(row[11] or "[]"),
            orchestrator_reasoning=row[12] or "",
            entry_time=row[13] or "", exit_time=row[14] or "",
            round_id=row[15] if len(row) > 15 else "",
        )

    def working_memory_summary(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in self._working]
