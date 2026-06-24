# QuantAI A–Z Operator Guide

Synced to Notion via `python scripts/sync_notion_az.py` or `POST /api/notion/sync/az`.

## Competition Instruments (15 only)

| Category | Symbols |
|----------|---------|
| Forex (8) | AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY |
| Metals (2) | XAG/USD, XAU/USD |
| Crypto (5) | BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD |

Round 3 auto-disables crypto (10 symbols: forex + metals only).

## Autonomous Operation

- **15-minute cycles** — no per-trade approval needed
- **Start once:** `python main.py --mode live --phase auto --with-dashboard`
- **Intervene only** for emergencies: Pause, bridge reconnect, margin level critical, between-round adaptation

## Trade Lifecycle (synced to Notion)

**Open (automatic):** features → agents → orchestrator → phase rules → Kelly → heat → pre_trade_gate → MT5 with SL/TP.

**Open (manual):** `POST /api/trades/manual` or dashboard control bar (same gate).

**Close paths:** MT5 SL/TP · PositionManager · SharpeGuard · risk emergency · operator close.

## Open Position Monitoring (synced to Notion)

| Clock | Interval | What it does |
|-------|----------|--------------|
| MT5 broker | Continuous | SL/TP, 30% stop-out |
| Dashboard state | ~15s | Live PnL for operator |
| PositionManager | 15 min | Trailing, partials, time stop, regime flip |
| ComplianceHeartbeat | 5 min | Margin/leverage/concentration/directional violations |

Engine **paused** still runs exit management — no new entries only.

## Command Center Steps

1. Pre-trade risk gate  
2. Copilot backend  
3. Copilot UI  
4. Agentic memory  
5. Logfire + launch readiness  
6. Between-round adaptation  
7. Notion sync panel  
8. Operator runbook + Northflank  
9. Competition-day automation  
10. Demo walkthrough + technology prize  
11. Competition rule wiring + trade monitoring docs  

## A–Z Quick Reference

Full guide synced to Notion page **A–Z Operator Guide (Complete Reference)** and Tasks DB (Steps 1–11 + A–Z).

Supplement sections on Notion guide page:
- Trade Lifecycle — Open & Close
- Open Position Monitoring
- Competition Compliance (Wired)

Source: `src/integrations/notion_az_content.py`

Re-sync:

```bash
python scripts/sync_notion_az.py --guide-page
```

Or from dashboard: **Notion Sync** panel → sync A–Z guide.
