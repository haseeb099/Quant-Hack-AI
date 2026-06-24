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
    attribution_json: dict[str, Any] = field(default_factory=dict)
    orchestrator_reasoning: str = ""
    entry_time: str = ""
    exit_time: str = ""
    round_id: str = ""


def build_trade_attribution(
    *,
    signals: list[Any],
    decision_direction: str,
    primary_agent: str,
    orchestrator_used_ai: bool,
    semantic_best_agent: str | None = None,
) -> dict[str, Any]:
    """Build vote-aware attribution blob for a closed trade."""
    buy = sum(
        1 for s in signals
        if getattr(getattr(s, "direction", None), "value", s.get("direction") if isinstance(s, dict) else None) == "BUY"
        and (getattr(s, "is_actionable", False) or (isinstance(s, dict) and s.get("confidence", 0) >= 0.65))
    )
    sell = sum(
        1 for s in signals
        if getattr(getattr(s, "direction", None), "value", s.get("direction") if isinstance(s, dict) else None) == "SELL"
        and (getattr(s, "is_actionable", False) or (isinstance(s, dict) and s.get("confidence", 0) >= 0.65))
    )
    actionable = buy + sell

    contributing: list[str] = []
    for s in signals:
        if isinstance(s, dict):
            direction = str(s.get("direction", "HOLD"))
            agent = str(s.get("agent", ""))
            conf = float(s.get("confidence", 0))
            is_actionable = conf >= 0.65 and direction in ("BUY", "SELL")
        else:
            direction = s.direction.value
            agent = s.agent_name
            is_actionable = s.is_actionable
        if is_actionable and direction == decision_direction and agent:
            contributing.append(agent)

    return {
        "primary_agent": primary_agent,
        "contributing_agents": sorted(set(contributing)),
        "vote_consensus": {"buy": buy, "sell": sell, "actionable": actionable},
        "orchestrator_used_ai": orchestrator_used_ai,
        "semantic_best_agent": semantic_best_agent,
    }


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
            cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()}
            if "round_id" not in cols:
                conn.execute("ALTER TABLE trades ADD COLUMN round_id TEXT")
            if "attribution_json" not in cols:
                conn.execute("ALTER TABLE trades ADD COLUMN attribution_json TEXT")

    def store_trade(self, record: TradeRecord) -> None:
        record.round_id = record.round_id or self.round_id
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades (
                    trade_id, symbol, session, regime, agent, direction,
                    entry_price, exit_price, r_multiple, pnl,
                    features_json, votes_json, attribution_json, reasoning,
                    entry_time, exit_time, round_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.trade_id, record.symbol, record.session, record.regime,
                    record.agent, record.direction, record.entry_price, record.exit_price,
                    record.r_multiple, record.pnl,
                    json.dumps(record.features_snapshot),
                    json.dumps(record.agent_votes),
                    json.dumps(record.attribution_json or {}),
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
            columns = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE regime = ? AND symbol = ? AND session = ?
                   ORDER BY exit_time DESC LIMIT ?""",
                (regime, symbol, session, top_k * 3),
            ).fetchall()

        records = [self._row_to_record(r, columns) for r in rows]
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
            columns = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
            rows = conn.execute("SELECT * FROM trades").fetchall()

        for row in rows:
            rec = self._row_to_record(row, columns)
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

    def agent_vote_attribution(self, agent: str, regime: str | None = None) -> dict[str, float]:
        """Credit win/loss to agents that voted with the trade direction (fractional)."""
        query = "SELECT direction, r_multiple, attribution_json FROM trades WHERE 1=1"
        params: list[str] = []
        if regime:
            query += " AND regime = ?"
            params.append(regime)

        wins = 0.0
        losses = 0.0
        total_credit = 0.0
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        for direction, r_multiple, attr_raw in rows:
            if r_multiple is None:
                continue
            try:
                attr = json.loads(attr_raw or "{}")
            except json.JSONDecodeError:
                attr = {}
            contributors = attr.get("contributing_agents") or []
            if not contributors and attr.get("primary_agent"):
                contributors = [attr["primary_agent"]]
            if agent not in contributors:
                continue
            credit = 1.0 / len(contributors)
            total_credit += credit
            if r_multiple > 0:
                wins += credit
            else:
                losses += credit

        if total_credit <= 0:
            return {"win_rate": None, "avg_r": 0.0, "sample_size": 0, "credit_total": 0.0}

        query_r = "SELECT r_multiple, attribution_json FROM trades WHERE 1=1"
        params_r: list[str] = []
        if regime:
            query_r += " AND regime = ?"
            params_r.append(regime)
        r_weighted = 0.0
        with sqlite3.connect(self.db_path) as conn:
            for r_multiple, attr_raw in conn.execute(query_r, params_r).fetchall():
                if r_multiple is None:
                    continue
                try:
                    attr = json.loads(attr_raw or "{}")
                except json.JSONDecodeError:
                    attr = {}
                contributors = attr.get("contributing_agents") or []
                if not contributors and attr.get("primary_agent"):
                    contributors = [attr["primary_agent"]]
                if agent in contributors:
                    r_weighted += float(r_multiple) / len(contributors)

        return {
            "win_rate": wins / total_credit,
            "avg_r": r_weighted / total_credit,
            "sample_size": int(round(total_credit)),
            "credit_total": total_credit,
        }

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
            return {"win_rate": None, "avg_r": 0.0, "sample_size": 0}

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
    def _row_to_record(row: tuple, columns: list[str] | None = None) -> TradeRecord:
        if columns:
            data = dict(zip(columns, row, strict=False))
            try:
                attribution = json.loads(data.get("attribution_json") or "{}")
            except json.JSONDecodeError:
                attribution = {}
            return TradeRecord(
                trade_id=data.get("trade_id", ""),
                symbol=data.get("symbol", ""),
                session=data.get("session", ""),
                regime=data.get("regime", ""),
                agent=data.get("agent", ""),
                direction=data.get("direction", ""),
                entry_price=data.get("entry_price", 0.0),
                exit_price=data.get("exit_price"),
                r_multiple=data.get("r_multiple"),
                pnl=data.get("pnl"),
                features_snapshot=json.loads(data.get("features_json") or "{}"),
                agent_votes=json.loads(data.get("votes_json") or "[]"),
                attribution_json=attribution,
                orchestrator_reasoning=data.get("reasoning") or "",
                entry_time=data.get("entry_time") or "",
                exit_time=data.get("exit_time") or "",
                round_id=data.get("round_id") or "",
            )
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

    def trade_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return int(row[0]) if row else 0

    def semantic_key_count(self) -> int:
        return len(self._semantic)
