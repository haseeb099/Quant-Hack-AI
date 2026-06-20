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

**Env:** `ANTHROPIC_API_KEY`, `ZMQ_HOST`, `ZMQ_*_PORT`, `QUANTAI_PHASE`

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
- `PORT` — default 8080

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
# Terminal 1 — engine + API
python main.py --mode simulate --phase round1 --with-dashboard

# Terminal 2 — frontend dev (proxies /api and /ws)
cd frontend && npm run dev
```

Production: `cd frontend && npm run build` — FastAPI serves `frontend/dist` at `/`.

## Smoke Test

```bash
docker build -f Dockerfile.dashboard -t quantai-dashboard .
docker run --rm -p 8080:8080 -v "$(pwd)/logs:/app/logs" -v "$(pwd)/data:/app/data" quantai-dashboard
curl http://localhost:8080/api/status
curl http://localhost:8080/health
```

## Notion Sync

Set on the **engine** service (not dashboard):

```
NOTION_SYNC_ENABLED=true
NOTION_API_KEY=secret_...
NOTION_TRADE_JOURNAL_DS_ID=...
NOTION_AGENT_PERF_DS_ID=...
NOTION_RISK_EVENTS_DS_ID=...
```

Trades, agent stats, and risk events sync automatically during live/simulate cycles.
