"""A–Z operator guide content for Notion sync (QuantAI Command Center)."""

from __future__ import annotations

# Command Center implementation steps — all merged to main
IMPLEMENTATION_STEPS: list[dict[str, str]] = [
    {"step": "1", "label": "Step 1 — Pre-trade risk gate + blocker UI", "notes": "Unified pre_trade_gate.py, GET /api/risk/check-trade, manual trade UI with blocker cards. PR #3."},
    {"step": "2", "label": "Step 2 — Copilot backend", "notes": "Grounded analysis API POST /api/copilot/analyze-symbol + SSE chat POST /api/copilot/chat. src/copilot/analyzer.py. PR #4."},
    {"step": "3", "label": "Step 3 — Copilot chat UI", "notes": "Right-rail CopilotPanel with streaming, citation chips, MemoryContextStrip. PR #5."},
    {"step": "4", "label": "Step 4 — Agentic memory surfacing", "notes": "Memory API GET /api/memory/context + /api/memory/working, copilot context, MemoryContextCard. PR #6."},
    {"step": "5", "label": "Step 5 — Logfire + launch readiness", "notes": "LaunchReadinessPanel, GET /api/competition/launch-readiness, Logfire spans on all routes. PR #7."},
    {"step": "6", "label": "Step 6 — Between-round adaptation", "notes": "AdaptationPanel, GET/POST /api/adaptation/*, adapt_round.py pipeline. Weight changes capped ±10% per round. PR #8."},
    {"step": "7", "label": "Step 7 — Notion sync panel", "notes": "NotionSyncPanel, GET /api/notion/status + /api/notion/tasks, POST /api/notion/sync/az. PR #9."},
    {"step": "8", "label": "Step 8 — Operator runbook + Northflank", "notes": "OperatorRunbookPanel, GET /api/operator/runbook + /api/deploy/northflank, preflight scripts. PR #10."},
    {"step": "9", "label": "Step 9 — Competition-day automation", "notes": "CompetitionDayPanel, GET/POST /api/operator/verification/*, competition_day_verify.py. PR #11."},
    {"step": "10", "label": "Step 10 — Demo walkthrough + technology prize", "notes": "DemoPage /demo, GET /api/demo/walkthrough + /api/prize/technology-checklist. PR #12."},
    {"step": "11", "label": "Step 11 — Competition rule wiring + trade monitoring", "notes": "Exact compliance tiers (margin 90/95/98, leverage 28/29/30, net directional 95%), margin_level stop-out guard, auto phase (--phase auto), pre_trade_gate on automated trades, PositionManager exit rules documented in Notion A–Z supplement sections."},
]

AZ_SECTIONS: list[dict[str, str]] = [
    {
        "letter": "A",
        "title": "Architecture & Autonomous Operation",
        "body": (
            "QuantAI runs a 15-minute decision loop automatically once started. "
            "Five agents vote: TrendSurfer (25%), BreakoutHunter (25%), MomentumPulse (15%), "
            "MeanReversion (20%), SentimentAgent (10%). MetaOrchestrator (Claude Sonnet) resolves conflicts; "
            "MarketIntelligenceService feeds calendar/news/sentiment; risk rails enforce the frozen constitution; "
            "orders go to MT5 via ZeroMQ. Four loops: Research (offline), Memory (every trade), "
            "Decision (every 15 min), Adaptation (between rounds 22:00–23:00 BST). "
            "Start once — monitor dashboard/Logfire. No per-trade approval required. "
            "Trade open path (automatic): features → agent votes → orchestrator → phase rules → "
            "drawdown/margin gates → Kelly sizing → portfolio heat → pre_trade_gate → MT5 send_trade. "
            "One open position per symbol max. Manual path: POST /api/trades/manual (same gate)."
        ),
    },
    {
        "letter": "B",
        "title": "Between-Rounds (22:00–23:00 BST)",
        "body": (
            "Pause engine or confirm adaptation window. Run scripts/adapt_round.py or Agents → Adaptation panel. "
            "Learning pipeline: ingest_historical.py → build_regime_library.py → adapt_round.py. "
            "Weight changes capped ±10% per round. 20GB holdout for walk-forward validation — never during live trading. "
            "API: GET /api/adaptation/plan, GET /api/adaptation/status, POST /api/adaptation/run."
        ),
    },
    {
        "letter": "C",
        "title": "Command Center & Copilot",
        "body": (
            "Dashboard at :8080 (prod) or :5173 (Vite dev). Copilot (right rail) gives grounded read-only analysis "
            "with data citations — never invents prices or P&L. Steps 1–10 complete and merged to main. "
            "Panels: LaunchReadiness, OperatorRunbook, CompetitionDay, NotionSync, Adaptation, EngineHealth, TradingControlBar. "
            "Copilot routes: POST /api/copilot/analyze-symbol, POST /api/copilot/chat (SSE)."
        ),
    },
    {
        "letter": "D",
        "title": "Dashboard Routes & API",
        "body": (
            "Frontend routes: / Overview · /positions · /trades · /agents · /risk · /market · /decisions · /demo. "
            "Core API: GET /api/status, /api/health/engine, /api/account, /api/equity-curve, /api/competition-score. "
            "Control: GET /api/control/state, POST /api/engine/pause|resume|run-cycle, POST /api/bridge/reconnect. "
            "Trades: GET /api/trades, POST /api/trades/manual, POST /api/positions/{ticket}/close, POST /api/positions/close-all. "
            "Intelligence: GET /api/intelligence/snapshot, /calendar, /sentiment, /sentiment/{symbol}. "
            "WebSocket: /ws/live (state ~15s heartbeat + after each cycle)."
        ),
    },
    {
        "letter": "E",
        "title": "Environment Variables",
        "body": (
            "Core: ANTHROPIC_API_KEY, LOGFIRE_TOKEN, DOUBLEWORD_API_KEY (optional), QUANTAI_PHASE=auto (recommended). "
            "Use round1|round2|round3|finals to pin phase; auto follows BST schedule from config/phases.yaml. "
            "MT5 MCP: MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH. "
            "ZeroMQ: ZMQ_HOST=127.0.0.1, ZMQ_COMMAND_PORT=32768, ZMQ_CONFIRM_PORT=32769, ZMQ_TICK_PORT=32770. "
            "Dashboard: DASHBOARD_AUTH_TOKEN, DASHBOARD_PORT=8080, DEMO_MODE=false. "
            "Notion: NOTION_API_KEY, NOTION_TRADE_JOURNAL_DS_ID, NOTION_AGENT_PERF_DS_ID, "
            "NOTION_RISK_EVENTS_DS_ID, NOTION_TASKS_DS_ID, NOTION_AZ_PAGE_ID, NOTION_SYNC_ENABLED. "
            "Intelligence: INTELLIGENCE_ENABLED=true, NEWS_API_KEY, NEWS_API_SOURCE=fixture, "
            "CALENDAR_SOURCE=fixture, FEAR_GREED_ENABLED=true, MACRO_FRED_API_KEY, "
            "INTELLIGENCE_REFRESH_MINUTES=5, INTELLIGENCE_LLM_BUDGET_PER_CYCLE=0.10, "
            "SENTIMENT_AGENT_ENABLED=true, EVENT_RISK_GATE_ENABLED=true, PEER_MONITOR_MOCK=true. "
            "See .env.example for full list."
        ),
    },
    {
        "letter": "F",
        "title": "Forex Instruments (8)",
        "body": (
            "AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY. "
            "Config: config/instruments.yaml. MeanReversion primary agent for ranging forex. "
            "Round 3: all forex active (crypto auto-disabled)."
        ),
    },
    {
        "letter": "G",
        "title": "Go-Live Commands",
        "body": (
            "Live competition (recommended): python main.py --mode live --phase auto --with-dashboard\n"
            "Simulate: python main.py --mode simulate --phase auto --with-dashboard\n"
            "Single cycle: python main.py --mode single-cycle --phase round1\n"
            "Pre-trade what-if: GET /api/risk/check-trade?symbol=EUR/USD&direction=BUY&volume=0.01\n"
            "Dashboard only: ./scripts/start_dashboard.sh --build\n"
            "Frontend dev: cd frontend && npm run dev (proxies /api and /ws to :8080)\n"
            "Preflight: python scripts/preflight_competition.py --zmq-only\n"
            "Competition verify: python scripts/competition_day_verify.py"
        ),
    },
    {
        "letter": "H",
        "title": "Historical Data & Learning",
        "body": (
            "scripts/ingest_historical.py — ingest Parquet to data/historical/\n"
            "scripts/build_regime_library.py — build regime library in data/regime_library/\n"
            "scripts/adapt_round.py --phase round1 — rebalance agent weights between rounds\n"
            "LayeredMemory: working (in-memory) + episodic (SQLite trade_memory.db) + semantic (regime stats). "
            "Walk-forward validation uses 20GB holdout — between rounds only."
        ),
    },
    {
        "letter": "I",
        "title": "Intelligence Layer (News, Sentiment, Calendar)",
        "body": (
            "src/intelligence/: MarketIntelligenceService orchestrates calendar_monitor, news_ingestor, "
            "sentiment_scorer, macro_overlay, event_risk_gate, peer_monitor. "
            "Config: config/intelligence.yaml. Cache: data/intelligence/. "
            "Event tiers: Tier-1 (NFP/FOMC/CPI) blocks ±30min; Tier-2 reduces size 50% ±15min. "
            "SentimentAgent (5th agent) votes on news/sentiment score. "
            "Pricing always from MT5 — external feeds are context/gating only."
        ),
    },
    {
        "letter": "J",
        "title": "Journal & Logging",
        "body": (
            "logs/trades.jsonl — structured trade journal\n"
            "logs/trades.csv — CSV export\n"
            "data/runtime_state.json — live state for dashboard WebSocket\n"
            "data/trade_memory.db — episodic memory SQLite\n"
            "data/intelligence/ — calendar/news/sentiment cache\n"
            "Logfire traces full decision pipeline when LOGFIRE_TOKEN set. Disable: --no-logfire."
        ),
    },
    {
        "letter": "K",
        "title": "Kelly Sizing & Risk Constitution",
        "body": (
            "Half-Kelly position sizing via src/risk/kelly_sizer.py. "
            "Five drawdown tiers: normal (<5%) → elevated (5–10%) → warning (10–12%) → critical (12–15%) → emergency (≥15% close-all). "
            "Internal caps (below competition penalties): margin 88% emergency, leverage 20× max, concentration 40% max, net directional 85% cap. "
            "Competition stop-out: 30% margin level (red-line elimination). QuantAI warns at 50% margin level, emergency reduce at 40%. "
            "ComplianceHeartbeat (every 5 min): margin >90% 30min -20, >95% 15min -30, >98% 10min review; "
            "leverage >28× 30min -20, >29× 15min -30, ~30× 10min review; "
            "single instrument >90% 30min -10; net directional >95% 30min -10. Penalties apply once per tier per round. "
            "SharpeGuard closes losers within 2 min of 15-min equity snapshot if DD>5% and position PnL<-0.3%. "
            "pre_trade_gate.py — unified gate for engine automated trades, manual trades, and copilot. "
            "Config: config/risk.yaml. Learning loop never modifies risk params."
        ),
    },
    {
        "letter": "L",
        "title": "Logfire Observability",
        "body": (
            "Pydantic Logfire on engine cycles: features → agents → orchestrator → risk → execution. "
            "@instrument_span on all API routes. LaunchReadinessPanel shows trace health. "
            "Sponsor demo: full cycle trace URL for judges. Disable: --no-logfire."
        ),
    },
    {
        "letter": "M",
        "title": "Metals (2)",
        "body": (
            "XAG/USD (silver), XAU/USD (gold). Active all rounds. "
            "TrendSurfer + BreakoutHunter primary for metals. "
            "Macro overlay: risk_off favors longs (safe haven). "
            "Static bias in instruments.yaml: XAU bullish, XAG bullish."
        ),
    },
    {
        "letter": "N",
        "title": "Northflank Deploy",
        "body": (
            "Two services: quantai-engine + quantai-dashboard sharing volume at /app/logs and /app/data. "
            "Dockerfiles: Dockerfile.engine, Dockerfile.dashboard. "
            "Set DASHBOARD_AUTH_TOKEN on dashboard ingress. "
            "See docs/northflank_deploy.md. Smoke: ./scripts/deploy_smoke.sh"
        ),
    },
    {
        "letter": "O",
        "title": "Orchestrator (Claude)",
        "body": (
            "MetaOrchestrator in src/agents/meta_orchestrator.py. "
            "Model: claude-sonnet-4-20250514, temperature 0.1. "
            "Claude when agent confidence > 0.65 and disagreement ≥ 30%; rule fallback if API unavailable. "
            "5-min per-symbol cooldown. Max cost $0.05/decision. "
            "Copilot uses Doubleword gateway — Anthropic reserved for engine MetaOrchestrator."
        ),
    },
    {
        "letter": "P",
        "title": "Phases & Instruments by Round",
        "body": (
            "Round 1 (1.2× risk): all 15 symbols. Target 20–30% return.\n"
            "Round 2 (1.0×): all 15. Target +10–15%.\n"
            "Round 3 (0.7×): forex + metals only (10 symbols — crypto auto-disabled). Target +5–10%.\n"
            "Finals (0.9×): all 15. Balance return vs drawdown.\n"
            "Phase config: src/engine/config.py + config/phases.yaml. "
            "Auto-switch: engine calls resolve_phase() each cycle; discipline score resets on round transition. "
            "Override: QUANTAI_PHASE=auto (recommended) or round1|round2|round3|finals."
        ),
    },
    {
        "letter": "Q",
        "title": "Quick Pre-Launch Checklist",
        "body": (
            "python scripts/preflight_competition.py --zmq-only\n"
            "python scripts/competition_day_verify.py\n"
            "python scripts/test_mt5_connection.py\n"
            "python scripts/test_mt5_connection.py --with-cycle\n"
            "python scripts/zmq_diagnose.py\n"
            "pytest tests/ -q (140 tests)\n"
            "cd frontend && npm run build\n"
            "GET /api/competition/launch-readiness → all green"
        ),
    },
    {
        "letter": "R",
        "title": "Repository & Tests",
        "body": (
            "GitHub: haseeb099/Quant-Hack-AI. Local: e:\\Model To Market. "
            "140 tests passing. CI: pytest + frontend npm run build (.github/workflows/ci.yml). "
            "Key test files: test_pre_trade_gate, test_copilot_api, test_intelligence, "
            "test_dashboard_api, test_adaptation_api, test_launch_readiness."
        ),
    },
    {
        "letter": "S",
        "title": "Scoring Formula & Agent Weights",
        "body": (
            "Final Score = 70% Return + 15% Drawdown + 10% Sharpe + 5% Risk Discipline. "
            "Agent weights (config/agents.yaml): TrendSurfer 25%, BreakoutHunter 25%, "
            "MomentumPulse 15%, MeanReversion 20%, SentimentAgent 10%. "
            "Regime boosts applied at runtime (trending/ranging/volatile/calm). "
            "MetaOrchestrator overrides on high-confidence conflicts."
        ),
    },
    {
        "letter": "T",
        "title": "Technology Prize Demo",
        "body": (
            "Dashboard → /demo page. 5-min walkthrough per docs/demo_script.md. "
            "Sponsor checklist: Anthropic (MetaOrchestrator), Pydantic Logfire (traces), "
            "Doubleword (Copilot gateway), Northflank (cloud deploy). "
            "API: GET /api/prize/technology-checklist, GET /api/demo/walkthrough."
        ),
    },
    {
        "letter": "U",
        "title": "Unattended 24h Operation",
        "body": (
            "Designed for full 24h competition rounds with minimal intervention. "
            "Pre-session 21:30 BST: MT5 terminal + DWX_ZeroMQ_Server.mq5 attached as Service, "
            "all 15 symbols in MarketWatch (recompile EA after margin_level update). "
            "Launch 22:00 BST: python main.py --mode live --phase auto --with-dashboard. "
            "Monitor Overview/Risk/Logfire — intervene for bridge offline, margin level <50%, or between-round adaptation. "
            "Pause engine stops new entries only; PositionManager still manages open trade exits each cycle."
        ),
    },
    {
        "letter": "V",
        "title": "Verification & Preflight",
        "body": (
            "GET /api/operator/verification — last verification run results\n"
            "POST /api/operator/verification/run — trigger full suite\n"
            "GET /api/operator/runbook — operator runbook markdown\n"
            "GET /api/operator/preflight — preflight status\n"
            "GET /api/competition/launch-readiness — go/no-go checklist\n"
            "GET /api/deploy/northflank — deploy status\n"
            "Scripts: preflight_competition.py, competition_day_verify.py"
        ),
    },
    {
        "letter": "W",
        "title": "WebSocket Live Feed",
        "body": (
            "WS /ws/live broadcasts state on engine publish (~15s heartbeat + after each cycle). "
            "state_publisher.py flattens risk.margin → margin_usage_pct for REST/WebSocket consumers. "
            "Frontend useWebSocket hook reconnects automatically. "
            "Includes: equity, positions (live PnL from MT5), agents, risk tier, discipline score, "
            "margin_level_pct, net_directional_pct, compliance_review flags, intelligence snapshot, competition score."
        ),
    },
    {
        "letter": "X",
        "title": "Crypto Instruments (5)",
        "body": (
            "BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD. "
            "Dropped automatically in Round 3 phase config (10 symbols remain). "
            "BreakoutHunter + TrendSurfer primary for crypto trends. "
            "Fear & Greed Index via macro_overlay when FEAR_GREED_ENABLED=true."
        ),
    },
    {
        "letter": "Y",
        "title": "Your Role as Operator",
        "body": (
            "1. Start MT5 → attach DWX_ZeroMQ_Server.mq5 as Service\n"
            "2. Verify 15/15 symbols in MarketWatch\n"
            "3. Run: python main.py --mode live --phase auto --with-dashboard\n"
            "4. Watch Overview/Risk/Logfire — intervene only for emergencies\n"
            "5. Between rounds (22:00–23:00): run adaptation or review AdaptationPanel\n"
            "6. Sync Notion: python scripts/sync_notion_az.py or POST /api/notion/sync/az"
        ),
    },
    {
        "letter": "Z",
        "title": "ZeroMQ / MT5 Bridge",
        "body": (
            "mql5/DWX_ZeroMQ_Server.mq5 — MQL5 Service (not EA). "
            "Ports: 32768 (PULL commands from Python), 32769 (PUSH confirmations), 32770 (PUB ticks). "
            "Requires ZMQ library: Furious-Production-LTD mql-zmq fork for MT5 build 5100+. "
            "Python connector: src/bridges/zeromq_connector.py. "
            "Commands: TRADE, CLOSE_ALL, MODIFY, POSITIONS, ACCOUNT (includes margin_level), DATA. "
            "All 15 symbols must be in MarketWatch. Troubleshoot: scripts/zmq_diagnose.py, scripts/test_mt5_connection.py. "
            "MT5 MCP (Cursor): pip install metatrader5-mcp, enable in .cursor/mcp.json for dev/testing."
        ),
    },
]

INSTRUMENTS_TABLE = """Competition instruments (15 total — ONLY these pairs):

Forex (8): AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY
Metals (2): XAG/USD, XAU/USD
Crypto (5): BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD

Round 3 auto-disables crypto (10 symbols: forex + metals only).
Config: config/instruments.yaml · Preflight validates exact 15-symbol universe.
Allocation and bias per symbol in instruments.yaml."""

PROJECT_STRUCTURE = """Project structure (e:\\Model To Market):

src/agents/ — TrendSurfer, BreakoutHunter, MomentumPulse, MeanReversion, SentimentAgent, MetaOrchestrator, ContextBuilder
src/bridges/ — zeromq_connector.py (MT5 bridge)
src/intelligence/ — MarketIntelligenceService, calendar, news, sentiment, macro, event_risk_gate, peer_monitor
src/engine/ — trading_engine.py, config.py
src/risk/ — kelly_sizer, drawdown guard, margin_monitor, pre_trade_gate, compliance
src/learning/ — layered_memory, walk_forward, weight_optimizer, trade_memory
src/copilot/ — analyzer, context (grounded AI chat)
src/web/ — FastAPI dashboard (routes/, ws.py, state_publisher.py)
src/operator/ — verification, runbook
src/demo/ — walkthrough for technology prize
config/ — agents.yaml, instruments.yaml, intelligence.yaml
scripts/ — ingest, adapt, preflight, sync_notion_az, test_mt5_connection
mql5/ — DWX_ZeroMQ_Server.mq5
frontend/ — React + Vite + shadcn/ui command center
tests/ — 140 tests
docs/ — architecture, mt5_testing, competition_rules, northflank_deploy, demo_script"""

TRADE_LIFECYCLE = """How trades open and close

OPEN (automatic — every 15 min cycle):
1. Intelligence refresh (news, calendar, sentiment, macro)
2. Risk pre-checks (drawdown tier, margin, stop-out risk)
3. PositionManager manages existing trades first (see Open Position Monitoring)
4. For each active symbol (session-filtered, no duplicate position):
   - Fetch M15/H1/H4 features → 4 agents vote → MetaOrchestrator decides
   - Phase rules (R1 aggressive, R3 crypto-only-if-normal-DD, finals discipline halt <95)
   - Kelly sizing → lot conversion → portfolio heat → pre_trade_gate
   - ZeroMQ TRADE to MT5 with SL/TP attached

OPEN (manual):
- Dashboard control bar or POST /api/trades/manual
- Same pre_trade_gate; returns 422 with blockers if rejected
- Copilot uses GET /api/risk/check-trade before suggesting trades

CLOSE (five paths):
1. MT5 broker — SL/TP hit or platform 30% margin stop-out (continuous, always on)
2. PositionManager — regime flip, time stop, partial take (+1R), breakeven SL, trailing (+2R)
3. SharpeGuard — loser closed within 2 min of 15-min snapshot if DD>5% and PnL<-0.3%
4. Risk emergency — drawdown emergency (close all), margin emergency (worst loser), compliance actions
5. Operator — POST /api/positions/{ticket}/close or close-all from Positions page

On close: _finalize_trade() stores R-multiple + agent context to LayeredMemory and logs/trades.jsonl."""

OPEN_POSITION_MONITORING = """Monitoring running trades — three clocks

CLOCK 1 — MT5 broker (continuous, 24/7):
- SL and TP on every order monitored by MT5 tick-by-tick
- Platform forced liquidation at 30% margin level (competition red line — elimination)
- QuantAI de-risks earlier: block entries at margin level <50%, reduce at <40%

CLOCK 2 — Dashboard state (~15 seconds):
- Engine heartbeat calls connector.get_positions() → unrealized PnL, price_current
- Published to data/runtime_state.json + WebSocket /ws/live
- Positions page polls every 10s — this is monitoring for YOU, not automated exit logic
- LiveFeed caches ticks every ~6s for price freshness checks

CLOCK 3 — Engine decisions (periodic):
Every 15 min cycle — _manage_positions() via PositionManager (src/risk/position_manager.py):
- Regime flip vs entry regime → full close
- Time stop: 4+ cycle bars held with R < +0.5 → full close
- Partial take at +1R → close 50% (Round 2+ when enable_partial_takes=true)
- Breakeven at +1R → move SL to entry
- Trailing at +2R → SL trails at 1.5× ATR
- SharpeGuard + critical drawdown checks on each open position after PositionManager

Every 5 min — ComplianceHeartbeat (background thread):
- Tracks sustained margin/leverage/concentration/net-directional violations
- Auto-actions: REDUCE_MARGIN, REDUCE_LEVERAGE, REDUCE_CONCENTRATION, REDUCE_DIRECTIONAL, EMERGENCY_CLOSE_ALL
- Decrements discipline score per competition rules (resets each round)

Engine PAUSED: no new entries, but PositionManager + compliance exits still run each cycle.

Dashboard pages for open trades:
- /positions — live PnL, close, modify SL/TP
- /risk — margin/leverage/concentration gauges, what-if trade checker
- /decisions — per-symbol skip/execute reasons each cycle
- /trades — closed trade journal"""

COMPETITION_COMPLIANCE = """Competition scoring & compliance (wired in code)

Final Score = 70% Return Rank + 15% Drawdown Rank + 10% Sharpe Rank + 5% Risk Discipline

Sharpe: non-annualized, from 15-minute equity returns (SharpeGuard snapshots each cycle).

Risk Discipline starts at 100 each round. Sustained violations (ComplianceHeartbeat):
| Violation | Duration | Penalty |
| Margin >90% | ≥30 min | -20 |
| Margin >95% | ≥15 min | -30 |
| Margin >98% | ≥10 min | Compliance review |
| Leverage >28× | ≥30 min | -20 |
| Leverage >29× | ≥15 min | -30 |
| Leverage ~30× | ≥10 min | Compliance review |
| Single instrument >90% | ≥30 min | -10 |
| Net directional >95% | ≥30 min | -10 |

QuantAI internal safety margins (config/risk.yaml):
| Metric | Our cap | Competition penalty |
| Margin usage | 88% emergency | >90% |
| Leverage | 20× max | >28× |
| Concentration | 40% max | >90% |
| Net directional | 85% cap (with open book) | >95% |
| Drawdown | 15% emergency close | 30% stop-out |

Red lines (instant elimination): forced liquidation, API abuse, multi-account, collusion.
See docs/competition_rules.md for full official rules."""

GUIDE_TITLE = "QuantAI A–Z Operator Guide (Command Center — Complete Reference)"
