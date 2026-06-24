# Data Usage Policy

How QuantAI uses the competition's ~20 GB historical dataset and live MT5 feeds.

## Data Sources

| Source | When Used | Purpose |
|--------|-----------|---------|
| Competition historical dataset (~20 GB) | Offline only (between rounds) | Learning, validation, regime library |
| MT5 live feed (ZeroMQ) | Competition hours only (22:00–22:00 BST) | Real-time bars, ticks, execution |
| Anthropic API | During live cycles | Orchestrator reasoning (no market data) |
| Pydantic Logfire | Continuous when enabled | Internal traces and metrics |
| Intelligence layer (optional) | During live cycles when enabled | News, calendar, Fear & Greed for **context and gating only** — not pricing |

**Pricing and execution** use the competition MT5 platform only. No external market data providers (Yahoo Finance, CoinGecko, etc.) feed prices, bars, or order fills.

### Gate A — external context policy

Competition rules distinguish **pricing** from **context**:

| Category | Allowed sources | Used for |
|----------|-----------------|----------|
| **Pricing** | MT5 live feed (ZeroMQ) only | Bars, ticks, mid prices, SL/TP, execution |
| **Context / gating** | News, economic calendar, Crypto Fear & Greed (when enabled) | Sentiment scoring, event-risk gates, macro overlay sizing — **never** as a price feed |

When `INTELLIGENCE_ENABLED=true` (default), the intelligence layer may fetch headlines, calendar events, and Fear & Greed indices. These adjust agent confidence, block entries around high-impact events, and apply macro sizing adjustments. They do **not** replace or override MT5 quotes.

**Before each round**, confirm with competition rules that external context feeds are permitted:

- **If allowed:** keep `INTELLIGENCE_ENABLED=true`, configure `NEWS_API_*` / `CALENDAR_SOURCE` as needed, set `FEAR_GREED_ENABLED=true`.
- **If forbidden:** set `INTELLIGENCE_ENABLED=false` and `SENTIMENT_AGENT_ENABLED=false` in `.env` before the round starts. The engine continues on MT5 pricing alone.

See `src/intelligence/market_intelligence.py` and `src/integrations/notion_az_content.py` for the operator-facing summary.

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
Pricer ticks → scripts/ingest_pricer_output.py → M15 OHLCV (data/historical/)
Raw CSV/JSON → scripts/ingest_historical.py → Parquet (data/historical/)
                                            → scripts/build_regime_library.py → Regime labels
                                            → scripts/run_historical_backtest.py → Trade memory
                                            → scripts/train_signal_model.py → ML signal model
                                            → scripts/adapt_round.py → Weight updates (±10% cap)
```

Full orchestration: `python scripts/run_learning_pipeline.py`

### Pricer tick ingestion

The pricer output folder (`pricer-output-2026-05-11_2026-06-10` by default) contains per-day tick parquet files named `{SYMBOL}_{YYYY}_{MM}_{DD}.parquet` (e.g. `EURUSD_2026_05_11.parquet`).

```bash
python scripts/ingest_pricer_output.py
# or
python scripts/ingest_pricer_output.py --input pricer-output-2026-05-11_2026-06-10 --output data/historical
```

- Parses `time`/`received` as UTC; mid price = (bid + ask) / 2
- Resamples to M15 OHLCV; volume = tick count per bar
- Maps compact symbols to file stems (`EURUSD` → `EUR_USD.parquet`)
- Filters to 10 competition symbols present in pricer data (no crypto)
- Check coverage: `python scripts/check_adapt_readiness.py`


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
