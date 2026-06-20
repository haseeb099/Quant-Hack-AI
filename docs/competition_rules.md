# AI Trading Competition Rules Summary

## Scoring Formula

```
Final Score = 70% × Return Rank + 15% × Drawdown Rank + 10% × Sharpe Rank + 5% × Risk Discipline
```

## Instruments (15 total)

| Category | Symbols |
|----------|---------|
| Forex (8) | AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY |
| Metals (2) | XAG/USD, XAU/USD |
| Crypto (5) | BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD |

## Account Rules

- Initial funds: $1,000,000 USD
- Maximum leverage: 30×
- Stop-out level: 30% margin level (instant elimination)
- Sharpe: non-annualized, computed from 15-minute equity returns

## Risk Discipline Penalties

| Violation | Penalty |
|-----------|---------|
| Margin >90% for ≥30 min | -20 points |
| Margin >95% for ≥15 min | -30 points |
| Margin >98% for ≥10 min | Compliance review |
| Leverage >28× for ≥30 min | -20 points |
| Leverage >29× for ≥15 min | -30 points |
| Single instrument >90% for ≥30 min | -10 points |
| Net directional >95% for ≥30 min | -10 points |

## Red-Line Rules (Instant Elimination)

- Forced liquidation (30% margin stop-out)
- System exploitation / API abuse
- Multi-account participation
- Unauthorized collusion

## QuantAI Safety Margins

Our caps are deliberately below competition penalty thresholds:

| Metric | QuantAI Cap | Competition Penalty |
|--------|-------------|---------------------|
| Margin | 88% emergency | >90% |
| Leverage | 20× max | >28× |
| Concentration | 40% max | >90% |
| Drawdown | 15% emergency close | 30% stop-out |

## Schedule (BST)

| Date | Event |
|------|-------|
| 21 Jun 22:00 | Competition launch (Round 1) |
| 22 Jun 22:00 | Round 1 cutoff |
| 23 Jun 22:00 | Round 2 cutoff |
| 24 Jun 22:00 | Round 3 cutoff |
| 24–26 Jun | Finals |
| 27 Jun | Results announcement |
