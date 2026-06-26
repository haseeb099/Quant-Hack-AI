# QuantAI — Complete System Overview for Management

**Document purpose:** This document explains the QuantAI trading system end-to-end — what it is, why it was built this way, how it works at runtime, what it is expected to do, and how it is operated. It is intended for non-developer leadership and technical stakeholders who need full visibility into the system.

**System name:** QuantAI (also referred to as Aurum AI Trader in competition materials)  
**Platform:** AI Trading Competition — simulated $1M account, real MT5 quotes  
**Tagline:** Deterministic risk rails + bounded self-learning + auditable AI orchestration

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Objective & Competition Context](#2-business-objective--competition-context)
3. [Scoring Formula & Strategic Alignment](#3-scoring-formula--strategic-alignment)
4. [High-Level Architecture](#4-high-level-architecture)
5. [The Four Operational Loops](#5-the-four-operational-loops)
6. [Decision Cycle — Step-by-Step (Live Runtime)](#6-decision-cycle--step-by-step-live-runtime)
7. [Trading Agents — What Each One Does](#7-trading-agents--what-each-one-does)
8. [MetaOrchestrator — AI Decision Layer](#8-metaorchestrator--ai-decision-layer)
9. [Risk Constitution — Frozen Safety Rules](#9-risk-constitution--frozen-safety-rules)
10. [Position Management & Exit Rules](#10-position-management--exit-rules)
11. [Data Layer & MT5 Execution Bridge](#11-data-layer--mt5-execution-bridge)
12. [Market Intelligence Layer (Optional Context)](#12-market-intelligence-layer-optional-context)
13. [Memory & Learning System](#13-memory--learning-system)
14. [Between-Round Adaptation](#14-between-round-adaptation)
15. [Competition Phase Playbooks](#15-competition-phase-playbooks)
16. [Instruments & Capital Allocation](#16-instruments--capital-allocation)
17. [Dashboard, Monitoring & Operator Tools](#17-dashboard-monitoring--operator-tools)
18. [Environment, Dependencies & Startup](#18-environment-dependencies--startup)
19. [Expected Behavior by Mode](#19-expected-behavior-by-mode)
20. [Compliance & Safety Margins vs Competition Rules](#20-compliance--safety-margins-vs-competition-rules)
21. [Sponsor Technology Integrations](#21-sponsor-technology-integrations)
22. [Project Structure & Key Files](#22-project-structure--key-files)
23. [Known Boundaries & What the System Does NOT Do](#23-known-boundaries--what-the-system-does-not-do)
24. [Glossary](#24-glossary)

---

## 1. Executive Summary

QuantAI is an **autonomous, multi-agent algorithmic trading system** built specifically for the AI Trading Competition. It runs continuously during competition hours, making trading decisions every **2–15 minutes** (depending on phase), executing orders through **MetaTrader 5 (MT5)**, and managing open positions without human approval for each trade.

### What makes this system different


| Principle                        | Implementation                                                                                                                           |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Return-first strategy**        | 70% of the competition score is Return Rank — the system is designed to pursue return aggressively while staying inside hard risk limits |
| **Multiple strategies, not one** | Six specialized agents vote on each symbol; a MetaOrchestrator resolves conflicts                                                        |
| **AI where it adds value**       | Claude (Anthropic) is used for conflict resolution and reasoning — not for every tick                                                    |
| **Risk is frozen**               | Drawdown tiers, margin caps, leverage limits, and position sizing formulas are **never modified by the learning system**                 |
| **Learning is bounded**          | Between rounds, agent weights and parameters can shift by at most ±10% after walk-forward validation                                     |
| **Full observability**           | Every cycle, trade, and risk event is logged to files, SQLite, and Pydantic Logfire                                                      |


### One-sentence description

> QuantAI ingests live MT5 market data, computes technical features, runs six strategy agents, uses AI to pick the best trade when agents disagree, sizes positions with Kelly criterion under strict risk caps, executes via ZeroMQ to MT5, and learns offline between competition rounds.

---

## 2. Business Objective & Competition Context

### Competition setup


| Parameter          | Value                                             |
| ------------------ | ------------------------------------------------- |
| Starting capital   | $1,000,000 USD (simulated)                        |
| Price source       | Real MT5 platform quotes                          |
| Instruments        | 15 (8 forex, 2 metals, 5 crypto)                  |
| Max leverage       | 30× (competition rule)                            |
| Stop-out           | **30% margin level** → instant elimination        |
| Decision frequency | 15-minute equity snapshots for Sharpe calculation |
| Inactivity rule    | Elimination if inactive 8 hours after start       |


### Competition schedule (British Summer Time)


| Phase   | Dates (BST)                 | Purpose                    |
| ------- | --------------------------- | -------------------------- |
| Round 1 | 21 Jun 22:00 → 22 Jun 22:00 | Qualify — maximize return  |
| Round 2 | 22 Jun 22:00 → 23 Jun 22:00 | Return push                |
| Round 3 | 23 Jun 22:00 → 24 Jun 22:00 | Top 20 push — tighter risk |
| Finals  | 24 Jun 22:00 → 26 Jun 22:00 | Top 100 — blind peer logs  |
| Results | 27 Jun                      | Final rankings             |


The system auto-detects the current phase when started with `--phase auto` (recommended).

---

## 3. Scoring Formula & Strategic Alignment

### Official competition formula

```
Final Score = 70% × Return Rank
            + 15% × Drawdown Rank
            + 10% × Sharpe Rank
            +  5% × Risk Discipline
```

**Tie-breakers:** Return → lower MaxDD → higher Sharpe → discipline → activity.

### Why the system is built around Return Rank (70%)

A strategy returning **40% with 15% drawdown** will typically outrank one returning **10% with 3% drawdown**, because return dominates the formula. Drawdown, Sharpe, and discipline act as **guardrails and tie-breakers**, not primary optimization targets.

### QuantAI target metrics by phase


| Phase   | Target Return | Max Drawdown Target | Risk Discipline |
| ------- | ------------- | ------------------- | --------------- |
| Round 1 | 20–30%        | <15%                | 100             |
| Round 2 | 12–25%        | <15%                | 100             |
| Round 3 | 8–15%         | <12%                | 100             |
| Finals  | 25–40%        | <12%                | 100             |


### Risk discipline penalties (competition)

Starting score: **100 per round**. Penalties for sustained violations:


| Violation                                | Penalty |
| ---------------------------------------- | ------- |
| Margin >90% for ≥30 min                  | −20     |
| Margin >95% for ≥15 min                  | −30     |
| Leverage >28× for ≥30 min                | −20     |
| Leverage >29× for ≥15 min                | −30     |
| Single instrument >90% gross for ≥30 min | −10     |
| Net directional >95% for ≥30 min         | −10     |


QuantAI operates with **internal caps well below** these penalty thresholds (see Section 20).

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         QUANTAI SYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  DATA LAYER                                                             │
│  MT5 (ZeroMQ) → LiveFeed → FeatureEngine → RegimeDetector               │
├─────────────────────────────────────────────────────────────────────────┤
│  AGENT LAYER (6 agents)                                                 │
│  TrendSurfer │ BreakoutHunter │ MomentumPulse │ MeanReversion             │
│  ML Signal  │ Sentiment Agent                                           │
│       ↓ votes                                                           │
│  MetaOrchestrator (Claude AI + rule fallback)                           │
├─────────────────────────────────────────────────────────────────────────┤
│  RISK LAYER (frozen constitution)                                       │
│  DrawdownGuard │ MarginMonitor │ KellySizer │ PortfolioHeat             │
│  PreTradeGate │ ComplianceHeartbeat │ SharpeGuard                       │
├─────────────────────────────────────────────────────────────────────────┤
│  EXECUTION LAYER                                                        │
│  ZeroMQ Connector → MT5 Orders (SL/TP attached)                         │
│  PositionManager (trailing, partials, time stops)                       │
├─────────────────────────────────────────────────────────────────────────┤
│  OBSERVABILITY & LEARNING                                               │
│  Logfire │ Trade Journal │ LayeredMemory (SQLite) │ Dashboard           │
│  Offline: walk-forward, weight optimizer, regime library                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Technology stack


| Layer           | Technology                                              |
| --------------- | ------------------------------------------------------- |
| Language        | Python 3.13                                             |
| AI agents       | Pydantic AI, Anthropic Claude, Doubleword/Groq fallback |
| Observability   | Pydantic Logfire                                        |
| Execution       | MetaTrader 5 via ZeroMQ (MQL5 EA)                       |
| Data processing | NumPy, Pandas                                           |
| ML signals      | scikit-learn (optional trained model)                   |
| Dashboard       | React (Vite) + FastAPI                                  |
| Memory          | SQLite (`data/trade_memory.db`)                         |
| Config          | YAML files in `config/`                                 |


---

## 5. The Four Operational Loops

QuantAI operates through four distinct loops that run at different frequencies:

### Loop 1 — Research Loop (offline, between rounds)

**When:** 22:00–23:00 BST audit window and manual runs  
**Input:** ~20 GB historical competition dataset  
**Process:** Walk-forward optimization, feature selection, parameter search, ML model training  
**Output:** Updated agent weights, regime boosts, parameter tables  
**Why:** Improves strategy based on evidence without changing live risk rules

### Loop 2 — Memory Loop (every closed trade)

**When:** Immediately when a position closes  
**Input:** Trade outcome, regime, features, agent votes, orchestrator reasoning  
**Process:** Store in SQLite episodic memory; update semantic agent performance tables  
**Output:** `data/trade_memory.db`, `logs/trades.jsonl`  
**Why:** Enables context-aware decisions and between-round learning

### Loop 3 — Decision Loop (every 2–15 minutes during competition)

**When:** Continuously during live/simulation mode  
**Input:** Live MT5 bars and ticks  
**Process:** Features → agents → orchestrator → risk checks → execute  
**Output:** New/modified/closed MT5 positions  
**Why:** This is the core autonomous trading engine

### Loop 4 — Adaptation Loop (between rounds)

**When:** After each round cutoff (22:00 BST)  
**Input:** Trade memory + historical data + agent audit  
**Process:** Validate new weights via walk-forward; write adaptation plan  
**Output:** `data/adaptation_plan.json`, optional `data/agents_tuned.yaml`  
**Why:** Bounded self-improvement without touching frozen risk rules

---

## 6. Decision Cycle — Step-by-Step (Live Runtime)

Each cycle is triggered on a timer (phase-configured: **2 min in finals**, **8 min in rounds**, default **15 min**). The engine runs `_run_cycle_body()` which performs the following in order:

### Phase A — Pre-flight checks

1. **API rate limit check** — ensures compliance with 100 req/s internal cap (500/s competition safe harbor)
2. **Phase refresh** — auto-switch phase if BST schedule crossed a boundary
3. **Reload phase playbook** — apply new risk multipliers, blocked symbols, disabled agents
4. **Load live competition filters** — merge objective-specific runtime overrides
5. **Refresh OHLCV metadata** (live only) — verify bar freshness from MT5

### Phase B — Account & risk state

1. **Read account equity** from MT5 — if unavailable, **fail-closed** (no new entries)
2. **Update drawdown guard** — classify tier: normal → elevated → warning → critical → emergency
3. **Record equity for SharpeGuard** — 15-minute equity curve tracking
4. **Emergency drawdown action** — at ≥15% drawdown: close ALL positions and stop
5. **Warning drawdown action** — at warning tier: reduce largest position by 15%
6. **Margin state evaluation** — margin usage, leverage, concentration, net directional exposure
7. **Stop-out prevention** — if margin level approaches 30% stop-out: reduce worst losers
8. **Concentration auto-deconcentrate** — micro accounts get automatic position reduction

### Phase C — Position sync & exit management

1. **Sync open trades from MT5** — reconcile engine state with broker
2. **Reconcile fills** — detect overshoot/undershoot; block new entries if mismatch
3. **Scan closed deals** — finalize trades in journal and memory
4. **Close positions on blocked symbols** — phase may block symbols mid-round
5. **PositionManager evaluate** — trailing stops, partial takes, breakeven, time stops, adverse stops
6. **SharpeGuard closes** — cut positions that harm equity curve smoothness

### Phase D — Intelligence & peer context

1. **Peer monitor update** (R1–R3) — adjust sizing based on crowd behavior
2. **Market intelligence refresh** — news, calendar, Fear & Greed (context only, not pricing)

### Phase E — New entry evaluation (if allowed)

Entries are **skipped** when:

- Engine is paused
- MT5 `trade_allowed=false`
- Equity unreadable
- Drawdown tier is critical/emergency
- Finals daily loss limit hit
- Fill reconcile block active
- Position snapshot untrusted

For each eligible symbol (up to `max_new_entries_per_cycle`):

1. **Session filter** — skip symbols outside active trading session (configurable per phase)
2. **Symbol cooldown** — skip if recent losing close on same symbol
3. **Skip if position already open** on symbol
4. **Opportunity ranking** — sort candidates by quick score + audit preferences
5. **Per-symbol processing** (`_process_symbol`):
  - Compute features (M15/H1/H4)
    - Detect market regime (trending/ranging/volatile/calm)
    - Run all enabled agents → collect signals
    - Build context from layered memory (similar past trades)
    - MetaOrchestrator decides: BUY / SELL / HOLD
    - Apply phase rules (consensus, confidence floors, macro gates)
    - Kelly position sizing with drawdown/margin/peer multipliers
    - Portfolio heat check (correlated exposure)
    - Pre-trade risk gate (final veto)
    - Execute order via ZeroMQ with SL and TP attached
    - Register position in PositionManager

### Phase F — Publish state

1. **Write runtime state** to `data/runtime_state.json` for dashboard
2. **Log cycle summary** to Logfire and file logs

### Expected cycle outcomes


| Outcome      | Meaning                                                     |
| ------------ | ----------------------------------------------------------- |
| Trade opened | At least one symbol passed all gates; order sent to MT5     |
| HOLD / skip  | No symbol met confidence + risk criteria this cycle         |
| Exits only   | Paused or blocked entries; existing positions still managed |
| Emergency    | Drawdown or margin crisis triggered protective closes       |


---

## 7. Trading Agents — What Each One Does

Each agent implements a distinct strategy. All inherit from `BaseTradingAgent` and output an `AgentSignal` (direction, confidence, SL, TP, reasoning).

### Agent summary table


| Agent           | Weight | Best Regime                 | Timeframes | Strategy Type                     |
| --------------- | ------ | --------------------------- | ---------- | --------------------------------- |
| TrendSurfer     | 42%    | Trending, Volatile          | H1, H4     | EMA crossover + ADX trend filter  |
| BreakoutHunter  | 2%     | Volatile                    | M15, H1    | Donchian breakout + BB squeeze    |
| MomentumPulse   | 10%    | Volatile, Ranging, Trending | M15, H1    | ADX + volume continuation         |
| MeanReversion   | 8%     | Ranging, Calm               | M15        | RSI extremes + BB proximity       |
| Sentiment Agent | 8%     | Volatile, Calm, Trending    | M15        | News/sentiment score driven       |
| ML Signal       | 18%    | All regimes                 | M15        | Trained sklearn model on features |


*Weights from `config/agents.yaml`; phase playbooks may disable agents.*

### TrendSurfer (primary agent — 42% weight)

**Purpose:** Capture sustained directional moves on higher timeframes.  
**Why:** Metals (XAU, XAG) and crypto trends are primary return drivers in current market bias.  
**Entry logic:**

- LONG: Price above EMA-50, EMA-9 crossed above EMA-21, ADX > 18, MACD histogram positive
- SHORT: Inverse conditions
- Requires multi-timeframe (MTF) alignment when configured

**Stops:** 1.6× ATR stop, 3.5× ATR target  
**Confidence:** Base 0.58, boosted by strong ADX, volume, distance from EMA-200

### BreakoutHunter (2% weight — often disabled in later rounds)

**Purpose:** Capture volatility expansion after compression.  
**Why:** Low weight because false breakouts are costly; disabled in Round 3 and Finals.  
**Entry logic:**

- Price breaks Donchian 20-period channel
- Bollinger Band width at ≤10th percentile (squeeze)
- Volume spike ≥1.2× average
- RSI filter avoids exhaustion entries

**Stops:** 1.3× ATR stop, 3.2× ATR target

### MomentumPulse (10% weight)

**Purpose:** Ride short-term momentum continuations.  
**Entry logic:** ADX > 18, volume above threshold, continuation patterns allowed  
**Stops:** 1.4× ATR stop, 3.0× ATR target

### MeanReversion (8% weight)

**Purpose:** Fade extremes in range-bound forex.  
**Entry logic:** RSI oversold/overbought (35/65), price near Bollinger Band, ADX < 30  
**Stops:** 1.0× ATR (tightest — reversals must work quickly)  
**Note:** Disabled in Finals phase playbook

### Sentiment Agent (8% weight)

**Purpose:** Trade based on news/sentiment scores from intelligence layer.  
**Requires:** `INTELLIGENCE_ENABLED=true`, news API configured  
**Disabled in:** Finals (by phase config)

### ML Signal Agent (18% weight)

**Purpose:** Machine-learned signal from historical feature patterns.  
**Model:** `data/models/signal_model.pkl` (trained by `scripts/train_signal_model.py`)  
**Inactive if:** Model file missing

### Regime-based weight boosts

When regime is detected, agent weights are multiplied by regime-specific boosts:


| Regime   | TrendSurfer | MeanReversion | MomentumPulse |
| -------- | ----------- | ------------- | ------------- |
| Trending | ×1.45       | ×0.45         | ×1.15         |
| Ranging  | ×0.85       | ×1.45         | ×1.10         |
| Volatile | ×1.15       | ×0.55         | ×1.35         |
| Calm     | ×0.90       | ×1.25         | ×0.80         |


This ensures the right strategy leads in each market condition.

---

## 8. MetaOrchestrator — AI Decision Layer

**File:** `src/agents/meta_orchestrator.py`  
**Model:** Claude Sonnet 4.6 (configurable) via Anthropic API; Doubleword/Groq as alternatives

### What it does

The MetaOrchestrator receives all agent signals for one symbol and produces a single **OrchestratorDecision**:


| Field             | Description                                |
| ----------------- | ------------------------------------------ |
| `direction`       | BUY, SELL, or HOLD                         |
| `confidence`      | 0.0–1.0 (capped to agent evidence ceiling) |
| `size_scale`      | 0.95–1.50× position size multiplier        |
| `reasoning`       | Human-readable explanation                 |
| `risk_assessment` | AI assessment of setup quality             |
| `urgency`         | normal / high / immediate                  |


### When AI (Claude) is called

- At least one agent signal exceeds minimum confidence threshold
- Drawdown tier is NOT critical/emergency
- Per-symbol cooldown elapsed (default 3–10 minutes)
- Optionally: only on agent conflict (`META_ORCHESTRATOR_AI_ON_CONFLICT_ONLY`)

### When rule-based fallback is used

- API unavailable or budget exhausted
- Strong agent consensus (no conflict)
- Cooldown active
- AI call fails after provider fallback chain

**Rule-based logic:** Regime-weighted voting — agents whose `best_regimes` match current regime get higher weight. Conflicting signals reduce size_scale.

### Debate fallback

If orchestrator returns HOLD but agents had actionable signals, a secondary **DebateOrchestrator** may revive a trade when multiple agents agree on direction.

### Cost controls

- Per-symbol cooldown: 3–10 minutes
- Max cost per decision: ~$0.05
- Confidence capped to max agent confidence + 0.08 boost (prevents AI overconfidence)

---

## 9. Risk Constitution — Frozen Safety Rules

**File:** `config/risk.yaml`  
**Critical principle:** These rules are **NEVER modified** by the learning/adaptation system.

### Drawdown tiers (five-tier ladder)


| Tier      | Drawdown Range | Size Multiplier | New Trades  | Crypto    |
| --------- | -------------- | --------------- | ----------- | --------- |
| Normal    | <5%            | 1.00×           | ✅           | ✅         |
| Elevated  | 5–10%          | 0.75×           | ✅           | ✅         |
| Warning   | 10–12%         | 0.50×           | ✅           | ❌ blocked |
| Critical  | 12–14%         | 0.25×           | ❌           | ❌         |
| Emergency | ≥15%           | 0.00×           | ❌ close all | ❌         |


**Why 15% emergency close:** Competition stop-out is at 30% margin level; 15% equity drawdown provides a safety buffer before platform liquidation.

### Margin monitoring


| Level              | Internal Threshold | Competition Penalty              |
| ------------------ | ------------------ | -------------------------------- |
| Alert              | 70% margin usage   | —                                |
| Action             | 80%                | —                                |
| Emergency          | 88%                | >90% for 30 min → −20 discipline |
| Stop-out warn      | 50% margin level   | —                                |
| Stop-out emergency | 40% margin level   | 30% = elimination                |


Poll interval: **1 second** during live trading.

### Leverage caps


| Level     | QuantAI Cap | Competition Penalty   |
| --------- | ----------- | --------------------- |
| Warning   | 18×         | —                     |
| Max       | 24×         | >28× for 30 min → −20 |
| Hard stop | 27×         | >29× for 15 min → −30 |


### Concentration limits


| Level              | Cap                         |
| ------------------ | --------------------------- |
| Warning            | 30% of equity in one symbol |
| Max                | 40%                         |
| Hard stop          | 50%                         |
| Metals cluster max | 50% combined                |
| Single metal max   | 25%                         |


### Position sizing (Kelly criterion)

```
Position size = Half-Kelly × ATR-based risk × drawdown multiplier × phase multiplier
```


| Parameter             | Value                               |
| --------------------- | ----------------------------------- |
| Kelly fraction        | 0.5 (Half-Kelly)                    |
| Max risk per trade    | 2.5% of equity (phase may override) |
| Correlation threshold | 0.70 (portfolio heat)               |
| Max spread/ATR ratio  | 0.15                                |


### Net directional exposure

- Internal cap: **85%** net long or net short vs gross exposure
- Competition penalty: >95% for 30 min → −10 discipline

### API rate compliance

- Internal limit: 100 requests/second
- Competition safe harbor: 500 req/s

---

## 10. Position Management & Exit Rules

**File:** `src/risk/position_manager.py`  
PositionManager runs **every cycle** on all open positions — even when engine is paused (exits always active).

### Exit mechanisms (phase-configurable)


| Rule             | Default                                  | Finals Example       | Purpose                       |
| ---------------- | ---------------------------------------- | -------------------- | ----------------------------- |
| Partial take     | At 1.0R, close 33%                       | At 3.0R, close 12%   | Lock profits, let winners run |
| Breakeven        | At 0.75R                                 | At 0.70R             | Protect capital after move    |
| Trailing stop    | After 2.0R, 1.5× ATR                     | After 2.5R, 2.2× ATR | Capture extended moves        |
| Time stop        | 12 M15 bars if <0.25R                    | 40 bars if <0.15R    | Cut stale trades              |
| Adverse stop     | −0.30R after 3 bars                      | −0.25R after 2 bars  | Limit loss quickly            |
| Max adverse      | −0.65R hard cut                          | −0.45R               | Absolute loss cap             |
| Never-green exit | 3 bars, peak <0.05R                      | 6 bars               | Exit trades that never work   |
| Regime flip      | Close if regime changes against position | Enabled in R3/Finals | Adapt to market shift         |
| Max hold         | 24 M15 bars                              | 64 bars              | Force exit on old positions   |
| Profit lock      | 12 bars at ≥0.75R                        | 96 bars at ≥1.5R     | Secure extended winners       |


### Why these rules exist (Finals strategy)

The Finals playbook implements **"Big Wins, Limited Losses"**:

1. Cut losers fast (−0.25R to −0.45R max adverse)
2. Move to breakeven early (+0.70R)
3. Take small partials at high R (3R) but trail the rest
4. Pause entries after 3+ open losers
5. 3% daily loss halt

---

## 11. Data Layer & MT5 Execution Bridge

### Data flow

```
MT5 Terminal
    ↓ ZeroMQ (ports 32768/32769/32770)
ZeroMQConnector (Python)
    ↓ OHLCV bars + ticks
LiveFeed (continuous, 60s feature refresh)
    ↓
FeatureEngine → FeatureVector (30+ indicators)
    ↓
RegimeDetector → trending | ranging | volatile | calm
```

### ZeroMQ ports


| Port  | Direction    | Purpose                        |
| ----- | ------------ | ------------------------------ |
| 32768 | Python → MT5 | Commands (open, close, modify) |
| 32769 | MT5 → Python | Confirmations and responses    |
| 32770 | MT5 → Python | Tick stream (monitoring)       |


### MQL5 Expert Advisor

**File:** `mql5/DWX_ZeroMQ_Server.mq5`  
Must be compiled and attached as a **Service** in MT5. Requires the [mql-zmq library](https://github.com/Furious-Production-LTD/mql-zmq) (MT5 build 5100+).

### Bridge modes


| Mode     | When Used                                      |
| -------- | ---------------------------------------------- |
| `zmq`    | Live competition (primary)                     |
| `direct` | Windows dev/testing via MetaTrader5 Python API |
| `auto`   | Try ZMQ first, fall back to direct             |


### Feature vector contents

Each symbol gets a `FeatureVector` with:

- Price: close, EMA 9/21/50/200
- Volatility: ATR-14, ATR-50, BB width, BB width percentile
- Momentum: RSI-14, ADX, MACD histogram
- Structure: Donchian high/low, volume ratio
- Regime classification

Timeframes: **M15** (base), resampled to **H1** and **H4**.

### Simulation mode

When `--mode simulate`:

- No MT5 connection required
- Simulated $1M account
- Synthetic or cached bar data
- Orders marked as `"simulated"` — no real execution

---

## 12. Market Intelligence Layer (Optional Context)

**Files:** `src/intelligence/`  
**Enabled by:** `INTELLIGENCE_ENABLED=true` (default)

### Important: pricing vs context


| Category    | Source                       | Used For                                          |
| ----------- | ---------------------------- | ------------------------------------------------- |
| **Pricing** | MT5 only                     | Bars, ticks, execution, SL/TP                     |
| **Context** | News, calendar, Fear & Greed | Confidence adjustment, entry gates, macro overlay |


External data **never replaces MT5 prices**.

### Components


| Component       | Source Options                    | Purpose                                 |
| --------------- | --------------------------------- | --------------------------------------- |
| NewsIngestor    | RapidAPI Yahoo, JBlanked, NewsAPI | Headline ingestion                      |
| CalendarMonitor | RapidAPI Forex Factory, JBlanked  | Economic event schedule                 |
| SentimentScorer | LLM or lexicon                    | Score headlines −1 to +1                |
| EventRiskGate   | Calendar + impact tiers           | Block entries around high-impact events |
| MacroOverlay    | Fear & Greed index, FRED          | Size adjustment for macro regime        |


### Event risk gate

High-impact events (NFP, FOMC, CPI) can:

- Block new entries ±N minutes around event
- Reduce position size for affected currency symbols

### Sentiment agent integration

When enabled, SentimentAgent reads intelligence scores and generates directional signals with confidence based on news sentiment alignment with technical setup.

---

## 13. Memory & Learning System

### Three-layer memory (FinMem-inspired)

**File:** `src/learning/layered_memory.py`


| Layer    | Storage                         | Retention               | Purpose                                         |
| -------- | ------------------------------- | ----------------------- | ----------------------------------------------- |
| Working  | In-memory                       | Last 3 trades           | Immediate context for orchestrator              |
| Episodic | SQLite                          | All closed trades       | Full trade history with features                |
| Semantic | In-memory + rebuilt from SQLite | Per agent/symbol/regime | Win rates, avg R-multiple, best agent per setup |


### What gets stored per trade

- Symbol, session, regime, direction
- Entry/exit price, R-multiple, P&L
- Full feature snapshot at entry
- All agent votes and orchestrator reasoning
- Attribution (which agents contributed to decision)

### What the memory is used for

1. **ContextBuilder** injects similar past setups into orchestrator prompt
2. **CompetitionStrategy** blocks agents with poor symbol-specific win rates
3. **WeightOptimizer** adjusts agent weights between rounds
4. **Dashboard** shows agent attribution and performance cards

---

## 14. Between-Round Adaptation

**Script:** `python scripts/run_learning_pipeline.py`  
**Service:** `src/learning/adaptation_service.py`

### Pipeline steps

1. **Backfill trade memory** from MT5 history
2. **Agent audit** — compute per-agent, per-symbol win rates → `data/agent_audit.json`
3. **Ingest historical data** — Parquet OHLCV in `data/historical/`
4. **Build regime library** — per-bar regime labels
5. **Historical backtest** — validate strategies on past data
6. **Train ML signal model** (optional)
7. **Adapt round** — optimize weights, parameters, regime boosts
8. **Walk-forward validation** — out-of-sample Sharpe check
9. **Promotion gate** — only deploy if OOS Sharpe delta > 0.02, max DD < 12%, agent health not RED

### What CAN be learned (bounded)

- Agent weights (±10% cap per round)
- Regime boost multipliers
- Confidence thresholds
- Parameter tables (EMA periods, ADX thresholds, etc.)
- ML model retraining

### What CANNOT be learned (frozen)

- Entry/exit rule logic
- Risk red-lines and drawdown tiers
- Stop-out thresholds
- Kelly sizing formula
- Margin/leverage/concentration caps

---

## 15. Competition Phase Playbooks

**File:** `config/phases.yaml`

Each phase has a distinct playbook controlling aggression, symbol universe, and exit rules.

### Phase comparison


| Setting               | Round 1  | Round 2  | Round 3         | Finals                              |
| --------------------- | -------- | -------- | --------------- | ----------------------------------- |
| Risk multiplier       | 1.35×    | 1.30×    | 1.28×           | 1.55×                               |
| Cycle interval        | 8 min    | 8 min    | 8 min           | **2 min**                           |
| Max new entries/cycle | 2        | 4        | 3               | 2                                   |
| Max risk per trade    | 3.2%     | 2.0%     | 2.2%            | 2.6%                                |
| Min agent confidence  | 0.40     | default  | 0.55            | 0.58                                |
| Blocked symbols       | 5 crypto | XRP, BAR | +3 forex        | +3 forex                            |
| Disabled agents       | —        | —        | breakout_hunter | breakout, sentiment, mean_reversion |
| Symbol cooldown       | 45 min   | 30 min   | 20 min          | 8 min                               |
| Daily loss halt       | —        | —        | —               | 3%                                  |
| Target return         | 20–30%   | 12–25%   | 8–15%           | 25–40%                              |


### Why phases differ

- **Round 1:** Aggressive return seeking; crypto blocked (focus forex/metals); high risk multiplier
- **Round 2:** More entries per cycle; expand symbol universe
- **Round 3:** Tighter confidence; disable breakout; enable adverse stops; regime flip exits
- **Finals:** Fast 2-min cycles; only trend + momentum + ML agents; strict loss limits; return maximization

---

## 16. Instruments & Capital Allocation

**File:** `config/instruments.yaml`

### All 15 competition instruments


| Symbol  | Category | Bias    | Allocation | Primary Agent |
| ------- | -------- | ------- | ---------- | ------------- |
| XAG/USD | Metals   | Bullish | 18%        | TrendSurfer   |
| USD/CAD | Forex    | Range   | 14%        | TrendSurfer   |
| BTC/USD | Crypto   | Bearish | 14%        | TrendSurfer   |
| ETH/USD | Crypto   | Bearish | 12%        | TrendSurfer   |
| AUD/USD | Forex    | Range   | 10%        | TrendSurfer   |
| XAU/USD | Metals   | Bullish | 10%        | TrendSurfer   |
| SOL/USD | Crypto   | Bearish | 8%         | MomentumPulse |
| EUR/USD | Forex    | Range   | 6%         | ML Signal     |
| GBP/USD | Forex    | Range   | 4%         | MeanReversion |
| EUR/CHF | Forex    | Range   | 2%         | ML Signal     |
| XRP/USD | Crypto   | Mixed   | 1%         | MeanReversion |
| BAR/USD | Crypto   | Mixed   | 1%         | MeanReversion |
| USD/JPY | Forex    | Range   | 1%         | MeanReversion |
| USD/CHF | Forex    | Range   | 1%         | MeanReversion |
| EUR/GBP | Forex    | Range   | 1%         | MeanReversion |


Allocation weights influence opportunity ranking and sizing — they do not guarantee fixed capital allocation.

### Trading sessions (UTC)


| Session | Hours (UTC) | Preferred Instruments     |
| ------- | ----------- | ------------------------- |
| Asia    | 00:00–08:00 | USD/JPY, AUD/USD, XAU/USD |
| London  | 08:00–13:00 | EUR/USD, GBP/USD, XAU/USD |
| NY      | 13:00–21:00 | BTC/USD, ETH/USD, SOL/USD |
| Overlap | 13:00–16:00 | Highest volatility window |
| Closed  | 21:00–24:00 | Crypto + metals focus     |


*Note: Phase playbooks may disable session filtering (`session_symbol_filter: false`) for 24/7 trading.*

---

## 17. Dashboard, Monitoring & Operator Tools

### Web dashboard

**Stack:** React (Vite + shadcn/ui) frontend, FastAPI backend  
**URL:** `http://localhost:8080` (local) or Northflank cloud deployment


| Route        | View                                                     |
| ------------ | -------------------------------------------------------- |
| `/`          | Overview — equity, P&L, drawdown tier, competition score |
| `/positions` | Open positions with SL/TP and unrealized P&L             |
| `/trades`    | Trade journal with agent votes and reasoning             |
| `/agents`    | Agent performance cards + last-cycle votes               |
| `/risk`      | Drawdown ladder, margin/leverage gauges                  |
| `/market`    | 15-instrument grid with session/regime status            |
| `/decisions` | Live per-symbol decision feed                            |


### API endpoints

```
GET  /api/status, /api/account, /api/positions, /api/trades
GET  /api/agents, /api/risk, /api/instruments, /api/competition-score
GET  /api/health/engine, /api/integrations
WS   /ws/live  →  real-time state every ~5 seconds
POST /api/trades/manual  →  manual trade (same risk gate)
POST /api/control/pause, /api/control/resume
POST /api/control/close/{ticket}, /api/control/close-all
```

### Operator watchdog

**Auto-starts** with `--mode live --with-dashboard`


| Check                   | Interval | Action                          |
| ----------------------- | -------- | ------------------------------- |
| MT5 connectivity        | 60s      | Alert if bridge down            |
| Engine heartbeat        | 60s      | Alert if cycle stale            |
| Position reconciliation | 60s      | Detect orphan trades            |
| Equity drift            | 60s      | Alert if MT5 vs engine mismatch |


Alerts: log file (`logs/operator_alerts.log`), Logfire, optional Discord/Slack webhook.

### Operator intervention points

Human intervention is needed only for:

1. **Emergency pause** — dashboard or API
2. **Bridge reconnect** — MT5/ZeroMQ failure
3. **Margin crisis** — if auto-reduction insufficient
4. **Between-round adaptation** — review and approve weight changes
5. **Manual close** — override specific positions

Normal operation requires **no per-trade approval**.

---

## 18. Environment, Dependencies & Startup

### Prerequisites

- Python 3.13+
- MetaTrader 5 (live trading)
- ZeroMQ library for MQL5
- Node.js 18+ (dashboard frontend dev)
- API keys (see `.env.example`)

### Key environment variables


| Variable                    | Purpose                                        |
| --------------------------- | ---------------------------------------------- |
| `QUANTAI_PHASE`             | `auto`, `round1`, `round2`, `round3`, `finals` |
| `MT5_LOGIN/PASSWORD/SERVER` | MT5 account credentials                        |
| `MT5_BRIDGE`                | `auto`, `zmq`, or `direct`                     |
| `ANTHROPIC_API_KEY`         | Claude for MetaOrchestrator                    |
| `LOGFIRE_TOKEN`             | Pydantic Logfire observability                 |
| `INTELLIGENCE_ENABLED`      | News/calendar context layer                    |
| `DASHBOARD_AUTH_TOKEN`      | Production dashboard auth                      |


### Startup commands

```bash
# Simulation (no MT5)
python main.py --mode simulate --phase round1

# Single decision cycle (testing)
python main.py --mode single-cycle --phase round1

# Live autonomous (competition)
python main.py --mode live --phase auto --with-dashboard

# Full autonomous script (Windows)
powershell -ExecutionPolicy Bypass -File scripts/start_live_autonomous.ps1
```

### Engine lock

Only **one live engine instance** may run at a time. Enforced via `data/engine.lock`.

---

## 19. Expected Behavior by Mode

### Simulate mode (`--mode simulate`)


| Aspect         | Expected Behavior                         |
| -------------- | ----------------------------------------- |
| MT5 connection | Not required                              |
| Account        | Simulated $1,000,000                      |
| Orders         | Logged as "simulated", not sent to broker |
| Intelligence   | May use fixture/mock data                 |
| Use case       | Development, testing, demo                |


### Single-cycle mode (`--mode single-cycle`)


| Aspect   | Expected Behavior                       |
| -------- | --------------------------------------- |
| Runs     | Exactly one decision cycle then exits   |
| Use case | Debugging a specific phase/symbol setup |


### Live mode (`--mode live`)


| Aspect      | Expected Behavior                                                    |
| ----------- | -------------------------------------------------------------------- |
| MT5         | Must be logged in, Algo Trading enabled, ZeroMQ EA running           |
| Cycles      | Continuous on phase timer until stopped                              |
| Fail-closed | No entries if equity unreadable, positions untrusted, or bridge down |
| Exits       | Always managed even when paused                                      |
| Watchdog    | Auto-starts with dashboard                                           |


---

## 20. Compliance & Safety Margins vs Competition Rules

QuantAI maintains **deliberate safety margins** below competition penalty thresholds:


| Metric                      | QuantAI Internal Cap | Competition Penalty Threshold |
| --------------------------- | -------------------- | ----------------------------- |
| Margin emergency            | 88%                  | >90% for 30 min               |
| Leverage max                | 24×                  | >28× for 30 min               |
| Single-symbol concentration | 40%                  | >90% for 30 min               |
| Net directional             | 85%                  | >95% for 30 min               |
| Drawdown emergency close    | 15%                  | 30% margin stop-out           |
| API rate                    | 100/s                | 500/s safe harbor             |


### Compliance heartbeat

Every 5 minutes, `ComplianceHeartbeat` tracks sustained violations and logs discipline risk score for dashboard display.

### Red lines (instant elimination)

The system is designed to never trigger:

- 30% margin stop-out (forced liquidation)
- API abuse (>500 req/s causing harm)
- Multi-account or collusion
- 8-hour inactivity

---

## 21. Sponsor Technology Integrations


| Sponsor        | Integration                                              | File(s)                                     |
| -------------- | -------------------------------------------------------- | ------------------------------------------- |
| **Anthropic**  | MetaOrchestrator Claude decisions                        | `src/agents/meta_orchestrator.py`           |
| **Pydantic**   | Logfire full-pipeline tracing                            | `src/utils/logger.py`                       |
| **Doubleword** | LLM inference routing (orchestrator, sentiment, copilot) | `src/utils/llm_providers.py`                |
| **Northflank** | Cloud dashboard deployment                               | `Dockerfile.dashboard`, `Dockerfile.engine` |


---

## 22. Project Structure & Key Files

```
Model To Market/
├── main.py                    # Entry point
├── config/
│   ├── agents.yaml            # Agent weights, parameters, regime boosts
│   ├── phases.yaml            # Round playbooks, sessions, cycle timing
│   ├── risk.yaml              # FROZEN risk constitution
│   ├── instruments.yaml       # 15 symbols, allocations, biases
│   └── intelligence.yaml      # News/calendar/sentiment config
├── src/
│   ├── agents/                # Trading agents + MetaOrchestrator
│   ├── bridges/               # ZeroMQ + MT5 direct connectors
│   ├── data/                  # Feature engine, regime detector, session filter
│   ├── engine/                # TradingEngine, config, trade journal
│   ├── intelligence/          # News, calendar, peer monitor, sentiment
│   ├── learning/              # Memory, adaptation, ML model, audit
│   ├── risk/                  # Kelly, drawdown, margin, compliance, exits
│   ├── operator/              # Watchdog, alerts, reconciliation
│   ├── web/                   # FastAPI dashboard backend
│   └── utils/                 # Logging, LLM providers
├── frontend/                  # React dashboard SPA
├── scripts/                   # Startup, learning pipeline, MT5 tests
├── mql5/                      # ZeroMQ Expert Advisor for MT5
├── data/                      # Runtime state, trade memory, historical data
├── logs/                      # trades.jsonl, trades.csv, alerts
├── tests/                     # pytest suite
└── docs/                      # Documentation (including this file)
```

---

## 23. Known Boundaries & What the System Does NOT Do


| Boundary                  | Explanation                                                    |
| ------------------------- | -------------------------------------------------------------- |
| No discretionary override | Strategy intent is not judged; only public metrics matter      |
| No live learning          | Weights/parameters change only between rounds after validation |
| No external pricing       | All execution prices come from MT5                             |
| No multi-account          | Single competition account only                                |
| No guaranteed returns     | Targets are goals, not promises                                |
| AI not on every decision  | Rule-based fallback always available                           |
| Crypto availability       | Phase-dependent; may be blocked or gated by drawdown tier      |
| Peer data in finals       | Finals use blind peer logs; peer monitor behavior may differ   |


---

## 24. Glossary


| Term                        | Definition                                                            |
| --------------------------- | --------------------------------------------------------------------- |
| **Agent**                   | A rule-based or ML strategy module that outputs BUY/SELL/HOLD signals |
| **MetaOrchestrator**        | AI layer that aggregates agent votes into final decision              |
| **Regime**                  | Market classification: trending, ranging, volatile, or calm           |
| **R-multiple**              | Profit/loss divided by initial risk (distance to stop loss)           |
| **Drawdown tier**           | Risk level based on peak-to-trough equity decline                     |
| **Kelly criterion**         | Mathematical optimal bet sizing based on win rate and payoff ratio    |
| **ZeroMQ bridge**           | Communication layer between Python engine and MT5 terminal            |
| **Phase playbook**          | Round-specific configuration (risk, symbols, agents, exits)           |
| **Fail-closed**             | When uncertain (no equity, no positions), block new entries           |
| **Walk-forward validation** | Out-of-sample test before promoting new weights                       |
| **Layered memory**          | Three-tier trade history: working, episodic, semantic                 |
| **Pre-trade gate**          | Final unified risk check before any order is sent                     |
| **Compliance heartbeat**    | Periodic check for sustained risk discipline violations               |


---

## Document Information


| Field           | Value                                                            |
| --------------- | ---------------------------------------------------------------- |
| Generated       | 25 June 2026                                                     |
| System version  | QuantAI competition build                                        |
| Source of truth | Repository at `Model To Market/`                                 |
| Related docs    | `docs/architecture.md`, `docs/competition_rules.md`, `README.md` |
| Operator guide  | `docs/notion_az_operators_guide.md`                              |


---

*For questions about live operation, refer to the Operator Guide or dashboard health endpoints. For technical deep-dives, see `docs/architecture.md` and `report.md`.*