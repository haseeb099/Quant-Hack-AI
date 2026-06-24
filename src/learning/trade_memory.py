"""SQLite trade memory for offline learning."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


class TradeMemory:
    """Stores closed trades for between-round adaptation."""

    def __init__(self, db_path: str | Path = "data/trade_memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

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
                    exit_time TEXT
                )
            """)

    def store(self, record: TradeRecord) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.trade_id, record.symbol, record.session, record.regime,
                    record.agent, record.direction, record.entry_price, record.exit_price,
                    record.r_multiple, record.pnl,
                    json.dumps(record.features_snapshot),
                    json.dumps(record.agent_votes),
                    record.orchestrator_reasoning,
                    record.entry_time or datetime.now(timezone.utc).isoformat(),
                    record.exit_time,
                ),
            )

    def query_by_regime(self, regime: str) -> list[TradeRecord]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM trades WHERE regime = ?", (regime,)).fetchall()
        return [self._row_to_record(r) for r in rows]

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
    def _row_to_record(row: tuple) -> TradeRecord:
        return TradeRecord(
            trade_id=row[0], symbol=row[1], session=row[2], regime=row[3],
            agent=row[4], direction=row[5], entry_price=row[6], exit_price=row[7],
            r_multiple=row[8], pnl=row[9],
            features_snapshot=json.loads(row[10] or "{}"),
            agent_votes=json.loads(row[11] or "[]"),
            orchestrator_reasoning=row[12] or "",
            entry_time=row[13] or "", exit_time=row[14] or "",
        )
