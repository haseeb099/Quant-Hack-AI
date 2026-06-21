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
- **Start once:** `python main.py --mode live --phase round1 --with-dashboard`
- **Intervene only** for emergencies: Pause, bridge reconnect, between-round adaptation

## Command Center Steps (all Done)

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

## A–Z Quick Reference

See `src/integrations/notion_az_content.py` for full section text pushed to Notion Tasks DB.
