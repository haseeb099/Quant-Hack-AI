# AI Trading Competition Rules (Official Summary)

All dates/times are **British Summer Time (BST)** unless noted.

## Core Objective

Simulated $1M account, real quotes. Rankings are **purely formulaic** — no discretionary penalties. Strategy intent is not judged; only public metrics matter.

## Final Score (100% formula)

```
Final Score = 70% × Return Rank + 15% × Drawdown Rank + 10% × Sharpe Rank + 5% × Risk Discipline
```

| Component | Weight | QuantAI finals priority |
|-----------|--------|-------------------------|
| Return Rank | **70%** | **Primary** — size + conviction on best setups |
| Drawdown Rank | 15% | Keep MaxDD under ~12–15% (stop-out at 30% margin level) |
| Sharpe Rank | 10% | Steady 15-min equity curve; ≥30 trades helps awards |
| Risk Discipline | 5% | Stay at 100; penalties are explicit thresholds |

**Tie-breakers:** Return → lower MaxDD → higher Sharpe → discipline → activity.

## Account Rules

| Item | Rule |
|------|------|
| Initial funds | $1,000,000 USD |
| Max leverage | 30× |
| Stop-out | **30% margin level** → instant elimination |
| Return | `(Equity_final - Equity_initial) / Equity_initial` |
| Sharpe | Non-annualized, from **15-minute equity returns** |

## Instruments (15)

| Category | Symbols |
|----------|---------|
| Forex (8) | AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY |
| Metals (2) | XAG/USD, XAU/USD |
| Crypto (5) | BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD |

## Schedule (BST)

| Date | Phase |
|------|-------|
| 21 Jun 22:00 | Launch (Round 1) |
| 22 Jun 22:00 | Round 1 cutoff + audit |
| 23 Jun 22:00 | Round 2 cutoff + audit |
| 24 Jun 22:00 | Round 3 cutoff + audit |
| 24 Jun 22:00 – 26 Jun 22:00 | **Finals (Top 100)** — blind peer logs |
| 27 Jun | Results |

## Risk Discipline (starts at 100 each round)

| Violation | Penalty |
|-----------|---------|
| Margin usage >90% for ≥30 min | -20 |
| Margin usage >95% for ≥15 min | -30 |
| Margin usage >98% for ≥10 min | Compliance review |
| Leverage >28× for ≥30 min | -20 |
| Leverage >29× for ≥15 min | -30 |
| Leverage ~30× for ≥10 min | Compliance review |
| Single instrument >90% gross for ≥30 min | -10 |
| Net directional >95% for ≥30 min | -10 |

## Red Lines (instant elimination / DQ)

- Forced liquidation (30% margin stop-out)
- System exploitation, API abuse (>500 req/s safe harbor unless causes harm)
- Multi-account, collusion
- Inactive 8h after start

## QuantAI Safety Margins (below penalty thresholds)

| Metric | QuantAI cap | Competition penalty |
|--------|-------------|---------------------|
| Margin emergency | 88% | >90% |
| Leverage max | 24× | >28× |
| Single-symbol concentration | 40% | >90% |
| Net directional internal cap | 85% | >95% |
| Drawdown emergency close | 15% | 30% stop-out |
| API rate | 100/s (500/s safe harbor) | abuse |

## QuantAI Finals — Top 5 Strategy (Big Wins, Limited Losses)

1. **Return first (70%)** — multi-lot entries on audit winners at full size.
2. **Loss limits** — cut at **-0.5R** max adverse; **-0.28R** after 3 bars; breakeven at **+0.75R**; **3% daily loss halt**.
3. **Quality + volume** — up to **6 trades/cycle**, every **5 min**; 10 min cooldown after a losing close on same symbol.
4. **Winners run** — 15% partial at **2R**, trail the rest.
5. **Pause entries** if **3+ open losers** until they close.
6. **Red lines** — margin 88%, leverage 24×, concentration 40%, stop-out 30%.

Target: **25–40% return**, MaxDD **&lt;12%**, discipline **100**.
