# QuantAI

Regime-aware multi-agent trading system for the AI Trading Competition.

**Tagline:** Deterministic risk rails + bounded self-learning + auditable AI orchestration.

## Scoring Target

```
Final Score = 70% Return + 15% Drawdown + 10% Sharpe + 5% Risk Discipline
```

## Architecture

- **4 Trading Agents:** TrendSurfer, BreakoutHunter, MomentumPulse, MeanReversion
- **MetaOrchestrator:** Claude-powered conflict resolution with rule-based fallback
- **Risk Constitution:** Frozen 5-tier drawdown ladder + margin/leverage caps
- **Self-Learning:** Layered memory + offline weight reoptimization between rounds
- **Execution:** MetaTrader 5 via ZeroMQ bridge

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys

# Simulation (no MT5 required)
python main.py --mode simulate --phase round1

# Single decision cycle
python main.py --mode single-cycle --phase round1

# Live trading (requires MT5 + ZeroMQ EA)
python main.py --mode live --phase round1
```

## MT5 Setup

### Cursor MCP (development & testing)

1. `pip install metatrader5-mcp MetaTrader5`
2. Set `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` in `.env`
3. Enable **metatrader5** in Cursor Settings → MCP (uses `.cursor/mcp.json`)

### ZeroMQ bridge (live competition)

1. Install ZMQ library for MQL5 — use the [Furious-Production-LTD mql-zmq fork](https://github.com/Furious-Production-LTD/mql-zmq) on MT5 build 5100+ (original [mql-zmq](https://github.com/dingmaotu/mql-zmq) fails to compile)
2. Compile `mql5/DWX_ZeroMQ_Server.mq5` and attach as Service
3. Verify all 15 symbols in MarketWatch
4. Ports: 32768 (commands), 32769 (confirmations), 32770 (ticks)

### Pre-competition test

```bash
python scripts/test_mt5_connection.py
python scripts/test_mt5_connection.py --with-cycle   # includes one simulation cycle
```

See [MT5 Testing Guide](docs/mt5_testing.md) for the full checklist.

## Between-Round Learning

```bash
# Ingest historical data
python scripts/ingest_historical.py --input /path/to/dataset

# Build regime library
python scripts/build_regime_library.py

# Adapt weights between rounds
python scripts/adapt_round.py --phase round1
```

## Trading Dashboard

React command center (Vite + shadcn/ui) wired to the FastAPI backend via REST + WebSocket.

### Local development

```bash
# Terminal 1 — engine with live state publishing
python main.py --mode simulate --phase round1 --with-dashboard

# Terminal 2 — frontend dev server (proxies /api and /ws to :8080)
cd frontend && npm install && npm run dev
# Open http://localhost:5173
```

### Production / API only

```bash
./scripts/start_dashboard.sh          # build + serve on :8080
# or with engine:
python main.py --mode simulate --phase round1 --with-dashboard
```

Set `DEMO_MODE=true` when running the API alone (no engine) so the dashboard shows a **Demo** badge instead of stale live state.

### Northflank deployment

Two services share a volume (`logs/`, `data/runtime_state.json`):

```bash
docker build -f Dockerfile.dashboard -t quantai-dashboard .
docker build -f Dockerfile.engine -t quantai-engine .
```

Set `DASHBOARD_AUTH_TOKEN` on the dashboard ingress. See [Northflank Deploy Guide](docs/northflank_deploy.md).

### Dashboard routes

| Route | View |
|-------|------|
| `/` | Overview — equity, P&L, drawdown tier, competition score |
| `/positions` | Open positions with SL/TP and unrealized P&L |
| `/trades` | Trade journal with agent votes and reasoning |
| `/agents` | Agent performance cards + last-cycle votes |
| `/risk` | Drawdown ladder, margin/leverage gauges |
| `/market` | 15-instrument grid with session/regime status |
| `/decisions` | Live per-symbol decision feed |

API: `GET /api/status`, `/api/competition-score`, `/api/health/engine`, `/api/integrations`, `/api/account`, `/api/trades`, `/api/agents/attribution`, `/api/risk`, `/api/instruments` · WebSocket: `/ws/live`

## Project Structure

```
quantai/
├── src/
│   ├── agents/          # Trading agents + MetaOrchestrator + ContextBuilder
│   ├── bridges/         # MT5 ZeroMQ connector
│   ├── data/            # Feature engine, regime detector, session_filter
│   ├── engine/          # Trading engine + config
│   ├── intelligence/    # Peer crowd monitor
│   ├── learning/        # layered_memory, walk-forward, weight optimizer
│   ├── risk/            # Kelly sizer, drawdown guard, SharpeGuard, compliance
│   ├── web/             # Northflank monitoring dashboard
│   └── utils/           # Logging (Logfire) + trade journal
├── scripts/             # ingest_historical, build_regime_library, adapt_round
├── config/              # YAML configuration
├── data/                # Historical Parquet, regime library, trade memory
├── logs/                # trades.jsonl, trades.csv, runtime logs
├── mql5/                # MT5 ZeroMQ Service (requires mql-zmq)
├── tests/
├── docs/
└── main.py
```

## Competition Schedule

| Phase | Dates | Risk Multiplier | Target |
|-------|-------|-----------------|--------|
| Round 1 | Jun 21–22 | 1.2× | 20–30% |
| Round 2 | Jun 22–23 | 1.0× | +10–15% |
| Round 3 | Jun 23–24 | 0.7× | +5–10% |
| Finals | Jun 24–26 | 0.9× | Balance return vs DD |

## Testing

```bash
pytest tests/ -v
```

CI runs pytest and `frontend/npm run build` on push (see `.github/workflows/ci.yml`).

## Documentation

- [Architecture](docs/architecture.md)
- [MT5 Testing Guide](docs/mt5_testing.md)
- [Competition Rules](docs/competition_rules.md)
- [Sponsor Integrations](docs/sponsor_integrations.md)
- [Data Usage](docs/data_usage.md)
- [Demo Script](docs/demo_script.md)
- [Northflank Deploy Guide](docs/northflank_deploy.md)
- [Full Report](report.md)
- [Notion Project](https://app.notion.com/p/385dd43e0a9d80148faae47e7a3faa0b)

## Sponsor Technologies

| Sponsor | Integration |
|---------|-------------|
| Anthropic | MetaOrchestrator (Claude) |
| Pydantic | Logfire observability |
| Doubleword | Inference API routing |
| Northflank | Cloud dashboard (React + FastAPI sidecar) |

## License

Proprietary — All rights reserved.
