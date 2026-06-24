# Northflank Deployment — QuantAI Dashboard + Engine

Deploy the trading engine and dashboard as two services sharing a volume on [Northflank](https://northflank.com).

## Architecture

```
┌─────────────────────┐     shared volume      ┌──────────────────────┐
│  Engine service     │ ── logs/, data/ ────── │  Dashboard sidecar   │
│  main.py --live     │     runtime_state.json  │  FastAPI :8080       │
│  + --with-dashboard │                         │  React SPA at /      │
└──────────┬──────────┘                         └──────────┬───────────┘
           │ ZeroMQ (VPN/tunnel)                            │ HTTPS ingress
           ▼                                                ▼
    Local MT5 + DWX EA                              Public dashboard URL
```

MT5 stays on your machine. The engine connects via ZeroMQ; the dashboard reads published state files only.

## Services

### 1. Engine (`Dockerfile.engine`)

```bash
docker build -f Dockerfile.engine -t quantai-engine .
```

**CMD:** `python main.py --mode live --phase round1 --with-dashboard`

For cloud-only engine (dashboard separate):

```bash
python main.py --mode live --phase round1
```

**Volume mounts:**
- `/app/logs` → shared
- `/app/data` → shared (includes `runtime_state.json`, `trade_memory.db`)

**Env:** `ANTHROPIC_API_KEY`, `QUANTAI_LLM_ALLOW_ANTHROPIC=true`, `QUANTAI_LLM_PROVIDER=anthropic`, `ZMQ_HOST`, `ZMQ_*_PORT`, `QUANTAI_PHASE`, plus optional integrations below.

#### Core engine secrets

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (Claude routing) | MetaOrchestrator Claude API key |
| `QUANTAI_LLM_ALLOW_ANTHROPIC` | Yes (Claude routing) | Set `true` to include Claude in orchestrator provider chain |
| `QUANTAI_LLM_PROVIDER` | Recommended | `anthropic` for Claude-first; `doubleword` for Doubleword-first |
| `META_ORCHESTRATOR_MODEL` | Optional | Anthropic model id (e.g. `claude-sonnet-4-6`) — not a Doubleword model name |
| `DOUBLEWORD_MODEL` / `DOUBLEWORD_MODEL_COMPLEX` | Optional | Doubleword models when using Doubleword provider |
| `META_ORCHESTRATOR_COMPLEX_MODEL` | Optional | Set `true` to use `DOUBLEWORD_MODEL_COMPLEX` (default `false`) |
| `ZMQ_HOST` | Yes (live) | Tunnel endpoint to local MT5 DWX bridge |
| `ZMQ_COMMAND_PORT` | Yes (live) | Default `32768` |
| `ZMQ_CONFIRM_PORT` | Yes (live) | Default `32769` |
| `ZMQ_TICK_PORT` | Yes (live) | Default `32770` |
| `QUANTAI_PHASE` | Yes | `round1`, `round2`, etc. |
| `LOGFIRE_TOKEN` | Optional | Pydantic Logfire — traces on engine cycles and API routes |

#### Notion sync (engine service)

Auto-enables when `NOTION_API_KEY` and at least one database ID are set (unless `NOTION_SYNC_ENABLED=false`):

| Variable | Description |
|----------|-------------|
| `NOTION_API_KEY` | Integration secret (`secret_...`) |
| `NOTION_TRADE_JOURNAL_DS_ID` | Trade Journal database ID |
| `NOTION_AGENT_PERF_DS_ID` | Agent Performance database ID |
| `NOTION_RISK_EVENTS_DS_ID` | Risk Events database ID |
| `NOTION_TASKS_DS_ID` | Tasks / implementation steps database ID |
| `NOTION_AZ_PAGE_ID` | Optional page for A–Z operator guide blocks |
| `NOTION_SYNC_ENABLED` | Set `false` to disable; empty/`true` auto-enables when configured |

Validate locally: `python scripts/setup_notion_check.py` — see [NOTION_SETUP.md](../docs/NOTION_SETUP.md) for full steps.

#### Intelligence layer (engine service)

Context feeds for gating and sentiment — **not** pricing. See [data_usage.md](data_usage.md) Gate A policy.

| Variable | Default | Description |
|----------|---------|-------------|
| `INTELLIGENCE_ENABLED` | `true` | Master switch for intelligence layer |
| `NEWS_API_KEY` | — | NewsAPI key when `NEWS_API_SOURCE=newsapi`, or JBlanked fallback |
| `NEWS_API_SOURCE` | `rapidapi_yahoo` | `fixture`, `newsapi`, `jblanked`, or `rapidapi_yahoo` |
| `RAPIDAPI_KEY` | — | RapidAPI key for Yahoo news, Forex Factory calendar, cash-flow macro |
| `RAPIDAPI_FOREX_FACTORY_TIMEZONE` | Central Time | Must match Forex Factory scraper supported timezone string |
| `RAPIDAPI_FINANCE_CASH_FLOW_SYMBOL` | `AAPL:NASDAQ` | Macro context symbol (not used for pricing) |
| `JBLANKED_API_KEY` | — | JBlanked News API key (fallback) |
| `JBLANKED_NEWS_SOURCE` | `mql5` | `mql5`, `forex-factory`, or `fxstreet` |
| `CALENDAR_SOURCE` | `rapidapi_forex_factory` | `fixture`, `cache`, `jblanked`, or `rapidapi_forex_factory` |
| `FEAR_GREED_ENABLED` | `true` | Crypto Fear & Greed macro overlay |
| `MACRO_FRED_API_KEY` | — | Optional FRED macro data |
| `INTELLIGENCE_REFRESH_MINUTES` | `5` | Snapshot refresh interval |
| `INTELLIGENCE_LLM_BUDGET_PER_CYCLE` | `0.10` | USD cap for LLM sentiment per cycle |
| `SENTIMENT_AGENT_ENABLED` | `true` | SentimentAgent participation |
| `EVENT_RISK_GATE_ENABLED` | `true` | Block entries around high-impact events |

Set `INTELLIGENCE_ENABLED=false` before a round if competition rules forbid external context feeds.

#### Peer monitor (engine service)

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPETITION_LEADERBOARD_URL` | — | Competition leaderboard API URL |
| `PEER_MONITOR_MOCK` | `true` | `false` for live peer-relative sizing adjustments |
| `PEER_MONITOR_FALLBACK` | `mock` | When live fetch fails: `mock` (simulated peers) or `neutral` (no peer sizing adj) |

For production competition, set `PEER_MONITOR_MOCK=false` and provide `COMPETITION_LEADERBOARD_URL` from the competition portal.

### 2. Dashboard (`Dockerfile.dashboard`)

```bash
docker build -f Dockerfile.dashboard -t quantai-dashboard .
```

**Port:** 8080  
**Health:** `GET /api/status`

**Volume mounts (read-only OK):**
- `/app/logs`
- `/app/data`

**Env:**
- `DASHBOARD_AUTH_TOKEN` — optional Bearer token for ingress protection
- `DEMO_MODE=true` — force **Demo** badge when running API without engine (cloud dev)
- `LOGFIRE_TOKEN` — optional Pydantic Logfire on dashboard API routes
- `PORT` — default 8080

The dashboard reads `runtime_state.json` from the shared volume; it does not need MT5, Notion, or intelligence env vars unless you run a combined single-container setup.

Clients with auth enabled:

```bash
curl -H "Authorization: Bearer $DASHBOARD_AUTH_TOKEN" https://dashboard.your-domain.com/api/status
```

## Manual deploy checklist

Use this before Round 1 if judges need a public dashboard URL:

- [ ] Build images locally: `docker build -f Dockerfile.engine -t quantai-engine .` and `docker build -f Dockerfile.dashboard -t quantai-dashboard .`
- [ ] Run `./scripts/deploy_smoke.sh` (or dashboard smoke test below)
- [ ] Create Northflank **shared volume**; mount `/app/logs` and `/app/data` on engine + dashboard
- [ ] **Engine service**: internal only; set `ANTHROPIC_API_KEY`, `ZMQ_*`, `QUANTAI_PHASE`, `NOTION_*`, `INTELLIGENCE_*`, `LOGFIRE_TOKEN`, `PEER_MONITOR_*`
- [ ] **Dashboard service**: public `:8080`; set `DASHBOARD_AUTH_TOKEN`, `PORT=8080`
- [ ] Configure **ingress** → public HTTPS URL for judges
- [ ] Local MT5 + DWX EA running; ZMQ tunnel from Northflank engine to your machine
- [ ] `curl -H "Authorization: Bearer $TOKEN" https://<dashboard>/api/status` returns live/simulate state
- [ ] Overview → NotionSyncPanel green (after Notion setup — see [NOTION_SETUP.md](NOTION_SETUP.md))

## Northflank Setup

1. Create a **shared volume** (e.g. `quantai-data`).
2. **Engine service**
   - Image: `quantai-engine`
   - Mount volume at `/app/logs` and `/app/data`
   - Internal only (no public HTTP)
   - Set ZeroMQ host to your tunnel endpoint
3. **Dashboard service**
   - Image: `quantai-dashboard`
   - Same volume mounts
   - Public HTTP on port 8080
   - Add `DASHBOARD_AUTH_TOKEN` in secrets
4. **Ingress**
   - Route `https://dashboard.your-domain.com` → dashboard service
   - Clients send `Authorization: Bearer <token>` when auth is enabled

## Local Development

```bash
# One-shot dashboard (builds frontend, serves API + SPA on :8080)
./scripts/start_dashboard.sh

# Engine + live state publishing
python main.py --mode simulate --phase round1 --with-dashboard

# Frontend hot reload (proxies /api and /ws to :8080)
cd frontend && npm run dev
```

The status bar shows **Live**, **Simulate**, or **Demo** based on engine mode and `DEMO_MODE`.

Production: `cd frontend && npm run build` — FastAPI serves `frontend/dist` at `/`.

## Smoke Test

```bash
docker build -f Dockerfile.dashboard -t quantai-dashboard .
docker run --rm -p 8080:8080 -v "$(pwd)/logs:/app/logs" -v "$(pwd)/data:/app/data" quantai-dashboard
curl http://localhost:8080/api/status
curl http://localhost:8080/health
```

## Notion Sync

Notion variables belong on the **engine** service (see env tables above). Quick validation:

```bash
python scripts/setup_notion_check.py
python scripts/sync_notion_az.py --guide-page
```

Dashboard: Overview → `NotionSyncPanel` confirms status via `GET /api/notion/status`.
