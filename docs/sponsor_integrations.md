# Sponsor Technology Integrations

Technology prize deliverable per [Notion Doc 13](https://app.notion.com/p/385dd43e0a9d81919c57e63babf0e696). All four sponsor technologies are integrated in production code paths.

## Overview

| Sponsor | Perk | Integration | File |
|---------|------|-------------|------|
| Anthropic | $50 API credits | MetaOrchestrator — Claude trade decisions | `src/agents/meta_orchestrator.py` |
| Pydantic | $50 Logfire credits | Full-system observability | `src/utils/logger.py` |
| Doubleword | Inference API | Model routing via Pydantic AI | `src/agents/meta_orchestrator.py` |
| Northflank | $100 platform credit | Cloud trading dashboard (React + FastAPI) | `src/web/`, `Dockerfile.dashboard` |

---

## Anthropic (Claude)

**Role:** Cognitive layer for signal aggregation when agents disagree.

- **Component:** `MetaOrchestrator` in `src/agents/meta_orchestrator.py`
- **Model:** `claude-sonnet-4-20250514` (configurable in `config/agents.yaml`)
- **Trigger:** Claude is called when at least one agent signal exceeds the 0.65 confidence gate
- **Context:** Regime, session, layered memory (working/episodic/semantic), and agent votes
- **Fallback:** Regime-weighted rule-based voting if API unavailable or budget exhausted
- **Cost controls:** 5-minute per-symbol cooldown; ~$0.03/decision (~1,600 calls on $50 credit)

```bash
export ANTHROPIC_API_KEY=your_key
```

---

## Pydantic (Logfire)

**Role:** Structured tracing across the full decision pipeline.

- **Component:** `src/utils/logger.py` — auto-tracing on all `src/` modules
- **Spans:** Feature compute → agent analysis → orchestrator → risk checks → execution
- **Logged data:** Agent prompts/reasoning, trade fills (slippage, P&L), margin/drawdown, cycle latency, API token usage
- **Disable:** `python main.py --no-logfire` or omit `LOGFIRE_TOKEN`

```bash
export LOGFIRE_TOKEN=your_token
```

---

## Doubleword (Inference Routing)

**Role:** Optional OpenAI-compatible gateway for model routing through Pydantic AI.

- **Component:** `MetaOrchestrator._call_claude()` in `src/agents/meta_orchestrator.py`
- **Routing:** When `DOUBLEWORD_API_KEY` is set, requests route to `https://api.doubleword.ai/v1`
- **Fallback:** Direct Anthropic API when key is unset
- **Priority:** Doubleword key takes precedence over Anthropic key for AI calls

```bash
export DOUBLEWORD_API_KEY=your_key
```

---

## Northflank (Trading Dashboard)

**Role:** Production trading command center — live equity, positions, agent votes, risk state, and decision feed during competition.

### Components

| Layer | Path | Purpose |
|-------|------|---------|
| React SPA | `frontend/` | 7-page dashboard (Overview, Positions, Trades, Agents, Risk, Market, Decisions) |
| FastAPI API | `src/web/app.py` | REST routes + WebSocket broadcaster |
| State bridge | `src/web/state_publisher.py` | Engine writes `data/runtime_state.json` each cycle |
| Docker | `Dockerfile.dashboard`, `Dockerfile.engine` | Multi-stage build + engine sidecar |

### Data sources

- `data/runtime_state.json` — live account, positions, risk, last-cycle decisions
- `logs/trades.jsonl` — paginated trade journal
- `data/trade_memory.db` — agent performance stats

### Local development

```bash
# Engine + state publishing
python main.py --mode simulate --phase round1 --with-dashboard

# Frontend dev (proxies /api and /ws)
cd frontend && npm run dev
```

### Cloud deployment (Northflank)

Two services share a persistent volume at `/app/logs` and `/app/data`:

1. **Engine** — `Dockerfile.engine`, runs `main.py --mode live --with-dashboard`
2. **Dashboard** — `Dockerfile.dashboard`, public HTTP ingress on port 8080

Set `DASHBOARD_AUTH_TOKEN` for Bearer auth on public routes. MT5 stays local; engine connects via ZeroMQ tunnel.

```bash
docker build -f Dockerfile.dashboard -t quantai-dashboard .
docker run -p 8080:8080 \
  -v ./logs:/app/logs -v ./data:/app/data \
  -e DASHBOARD_AUTH_TOKEN=dev-token quantai-dashboard
```

Full guide: [docs/northflank_deploy.md](northflank_deploy.md)

### API reference

```
GET  /api/status, /api/account, /api/positions, /api/trades
GET  /api/agents, /api/risk, /api/instruments, /api/equity-curve
WS   /ws/live  →  { type, payload } every ~5s
```

---

## MetaTrader 5 (Execution Bridge)

Not a sponsor, but required for live competition execution.

- **MQL5:** `mql5/DWX_ZeroMQ_Server.mq5` (requires [mql-zmq](https://github.com/dingmaotu/mql-zmq))
- **Python:** `src/bridges/zeromq_connector.py`
- **Ports:** 32768 (commands), 32769 (confirmations), 32770 (ticks)
