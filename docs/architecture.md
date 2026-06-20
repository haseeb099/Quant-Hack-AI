# QuantAI System Architecture

## Four Loops

### 1. Research Loop (offline)
20 GB historical data → walk-forward optimization → feature selection → parameter search

### 2. Memory Loop (every trade)
Trade close → store regime + features + outcome → agent performance tables

### 3. Decision Loop (every 15 min)
MT5 data → features → 4 agents → MetaOrchestrator → risk engine → execute

### 4. Adaptation Loop (between rounds)
Memory + research → validate new weights → deploy for next round (22:00–23:00 audit window)

## Layer Stack

| Layer | Components | Technology |
|-------|-----------|------------|
| Data | ZeroMQ Bridge, Feature Engine, Regime Detector | MT5, NumPy, Pandas |
| Agents | TrendSurfer, BreakoutHunter, MomentumPulse, MeanReversion | Pydantic AI |
| Meta | MetaOrchestrator (Claude + rule fallback) | Anthropic Claude |
| Risk | Kelly Sizer, Drawdown Guard, Margin Monitor, Compliance | Custom Python |
| Execution | Order Manager, Position Tracker | ZeroMQ, MT5 |
| Observability | Logfire, Trade Memory DB | Pydantic Logfire |
| Learning | Trade Memory, Weight Optimizer, Walk-Forward | SQLite, scikit-learn |

## Data Flow

```
MT5 Market Data
    → ZeroMQ Bridge
    → Feature Engine (M15/H1/H4)
    → Regime Detector
    → [TrendSurfer | BreakoutHunter | MomentumPulse | MeanReversion]
    → MetaOrchestrator
    → Risk Engine (Kelly + Drawdown + Margin + Compliance)
    → Order Execution
    → Logfire + Trade Memory
    → Offline Learning (between rounds)
```

## Agent Weights (base)

| Agent | Weight | Best Regime | Instruments |
|-------|--------|-------------|-------------|
| TrendSurfer | 30% | Trending | XAU, XAG, crypto trends |
| BreakoutHunter | 30% | Volatile | BTC, ETH, SOL, XAU |
| MomentumPulse | 15% | Trending | Crypto, metals |
| MeanReversion | 20% | Ranging | Forex pairs |
| MetaOrchestrator | Override | All | Conflict resolution |

## Risk Constitution (FROZEN)

Drawdown tiers: Normal (<5%) → Elevated (5–10%) → Warning (10–12%) → Critical (12–15%) → Emergency (≥15%)

Hard caps: Margin 88% emergency | Leverage 20× max | Concentration 40% max

## Self-Learning Boundaries

**Learns offline:** agent weights, parameter tables, confidence thresholds, allocation caps

**Never learns:** entry/exit rules, risk red-lines, stop-out thresholds, position sizing formula
