"""Memory API integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.web.app import create_app
from src.web.runtime_state import default_state, write_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime_state.json"
    db_path = tmp_path / "trade_memory.db"
    state = default_state()
    state["engine_running"] = True
    state["timestamp"] = datetime.now(timezone.utc).isoformat()
    state["instruments"] = {
        "XAU/USD": {
            "mid": 2350.5,
            "tick_age_ms": 120,
            "last_regime": "trending",
        },
    }
    write_state(state, state_path)

    from src.data.session_filter import SessionFilter

    session = SessionFilter().session_name()
    memory = LayeredMemory(db_path=db_path)
    for i in range(6):
        memory.store_trade(TradeRecord(
            trade_id=f"t{i}",
            symbol="XAU/USD",
            session=session,
            regime="trending",
            agent="trend_surfer",
            direction="BUY",
            entry_price=2300.0,
            exit_price=2310.0,
            r_multiple=1.2 if i % 2 == 0 else -0.5,
            pnl=100.0,
        ))

    monkeypatch.setattr("src.web.runtime_state.STATE_PATH", state_path)
    monkeypatch.setattr("src.web.state_publisher.STATE_PATH", state_path)
    monkeypatch.setattr("src.copilot.memory_context.LayeredMemory", lambda: memory)
    monkeypatch.setattr("src.web.routes.memory._builder", __import__(
        "src.copilot.memory_context", fromlist=["MemoryContextBuilder"]
    ).MemoryContextBuilder(memory))

    from src.copilot.analyzer import CopilotAnalyzer
    import src.web.routes.copilot as copilot_routes
    monkeypatch.setattr(copilot_routes, "_analyzer", CopilotAnalyzer())

    app = create_app()
    assert app is not None
    return TestClient(app)


def test_memory_context_with_symbol(client):
    r = client.get("/api/memory/context?symbol=XAU/USD")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "XAU/USD"
    assert body["total_trades_in_db"] == 6
    assert body["semantic"]["best_agent"] == "trend_surfer"
    assert body["semantic"]["sample_count"] >= 6
    assert len(body["working_memory"]) <= 3


def test_memory_working_endpoint(client):
    r = client.get("/api/memory/working")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] <= 3
    assert body["capacity"] == 3


def test_copilot_analysis_includes_memory(client):
    r = client.post("/api/copilot/analyze-symbol?symbol=XAU/USD&use_llm=false")
    assert r.status_code == 200
    body = r.json()
    assert "memory" in body
    assert body["memory"]["total_trades_in_db"] == 6
    sources = {c["source"] for c in body["data_citations"]}
    assert "layered_memory" in sources
