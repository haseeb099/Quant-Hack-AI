# QuantAI Demo Video Script

**Duration:** 5 minutes  
**Audience:** Technology prize judges (per [Notion Doc 13](https://app.notion.com/p/385dd43e0a9d81919c57e63babf0e696))

---

## 1. Architecture Overview (45s)

> "QuantAI is a regime-aware multi-agent trading system. Four specialized agents generate signals, a Claude-powered MetaOrchestrator resolves conflicts, deterministic risk rails enforce the constitution, and offline self-learning adapts weights between rounds."

**Show:** Architecture diagram (`docs/architecture_diagram.png` or `docs/architecture.md`)

---

## 2. Live Decision Cycle — Logfire Trace (60s)

> "Every decision is fully traced. Here is one complete cycle in Logfire — from market data ingestion through feature computation to the final orchestrator call."

**Run:** `python main.py --mode single-cycle --phase round1`  
**Show:** Logfire dashboard with spans for feature compute, agent analysis, orchestrator, risk, execution (or console `DECISION` logs if Logfire unavailable)

---

## 3. Signals → Orchestrator → Risk → Execution (90s)

> "Watch the pipeline: four agents vote on BTC/USD — TrendSurfer, BreakoutHunter, MomentumPulse, MeanReversion. When confidence exceeds the gate, Claude receives full context including regime, session, and layered memory. The decision passes through half-Kelly sizing, drawdown tier checks, and margin monitoring before the ZeroMQ bridge sends the order to MT5."

**Show:**
- Console agent votes per symbol
- Orchestrator reasoning (Logfire span or decision log)
- Risk tier and position size in output
- `logs/trades.jsonl` entry after execution

---

## 4. Trade Memory & Offline Learning (60s)

> "Closed trades feed three memory layers — working, episodic, and semantic. Between rounds, adapt_round.py rebuilds semantic weights, runs walk-forward validation on the 20 GB holdout, and promotes changes only if out-of-sample performance improves. Weight shifts are capped at ±10% per round."

**Run:** `python scripts/adapt_round.py --phase round1`  
**Show:** `data/trade_memory.db` schema, weight changes in console output

---

## 5. Risk Constitution & Compliance (45s)

> "Risk parameters are frozen — the learning loop never touches them. Five drawdown tiers from normal to emergency close-all at 15%. Compliance heartbeat tracks sustained violations every 5 minutes. SharpeGuard closes losers near snapshot boundaries to protect the 10% Sharpe rank."

**Show:** Drawdown tier transition (test output or dashboard at `localhost:8080`)

---

## 6. Sponsor Technologies (30s)

> "Built with Anthropic Claude for orchestration, Pydantic Logfire for observability, Doubleword for optional inference routing, and Northflank for the live monitoring dashboard."

**Show:** Dashboard (`http://localhost:8080`), Logfire project view

---

## Closing (10s)

> "QuantAI: deterministic risk rails, bounded self-learning, auditable AI orchestration — ready for 24-hour unattended competition deployment."
