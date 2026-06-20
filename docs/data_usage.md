# Data Usage Policy

How QuantAI uses the competition's ~20 GB historical dataset and live MT5 feeds.

## Data Sources

| Source | When Used | Purpose |
|--------|-----------|---------|
| Competition historical dataset (~20 GB) | Offline only (between rounds) | Learning, validation, regime library |
| MT5 live feed (ZeroMQ) | Competition hours only (22:00–22:00 BST) | Real-time bars, ticks, execution |
| Anthropic API | During live cycles | Orchestrator reasoning (no market data) |
| Pydantic Logfire | Continuous when enabled | Internal traces and metrics |

**No external market data providers** (Yahoo Finance, CoinGecko, etc.) are used. All pricing comes from the competition MT5 platform.

---

## Historical Dataset (~20 GB)

Provided by the competition for all 15 instruments. Used exclusively for offline work — never replayed during live trading.

### Uses (not a single backtest)

1. **Regime library** — per-bar regime labels (`data/regime_library/`)
2. **Feature importance** — which indicators predict breakout/trend success
3. **Similar-setup retrieval** — top-K analog trades at decision time via layered memory
4. **Walk-forward validation** — out-of-sample check before weight promotion
5. **News impact analysis** — breakout failure rates around high-impact events

### Pipeline

```
Raw CSV/JSON → scripts/ingest_historical.py → Parquet (data/historical/)
                                            → scripts/build_regime_library.py → Regime labels
                                            → scripts/adapt_round.py → Weight updates (±10% cap)
```

### Storage

| Path | Contents | Size (est.) |
|------|----------|-------------|
| `data/historical/` | Per-symbol OHLCV Parquet | ~5 GB |
| `data/regime_library/` | Per-bar regime labels | ~1 GB |
| `data/trade_memory.db` | Closed-trade episodic memory | <100 MB |
| `logs/trades.jsonl` | Live trade journal | <50 MB |

---

## Live Data (Competition Only)

During competition rounds, all market data flows through the MT5 ZeroMQ bridge:

- M15 base bars resampled to H1/H4 for multi-timeframe features
- Tick stream on port 32770 (monitoring only)
- Order execution via ports 32768/32769
- Session filter (`src/data/session_filter.py`) gates signals by trading session

Between rounds (22:00–23:00 BST), the engine stops live trading and runs `scripts/adapt_round.py` against historical data.

---

## Privacy & Retention

- No personal data collected or stored
- Trade memory holds market features and agent decisions only
- Logfire traces may include Claude prompts — review before sharing externally
- Data stays local unless explicitly deployed to Northflank or Logfire
- Trade memory persists across rounds; historical data retained for competition duration
