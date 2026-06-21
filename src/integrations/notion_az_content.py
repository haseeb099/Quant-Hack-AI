"""A–Z operator guide content for Notion sync (QuantAI Command Center)."""

from __future__ import annotations

# Command Center implementation steps — all merged to main
IMPLEMENTATION_STEPS: list[dict[str, str]] = [
    {"step": "1", "label": "Step 1 — Pre-trade risk gate + blocker UI", "notes": "Unified pre_trade_gate.py, blocker API, manual trade UI. PR #3."},
    {"step": "2", "label": "Step 2 — Copilot backend", "notes": "Grounded analysis API + SSE chat. PR #4."},
    {"step": "3", "label": "Step 3 — Copilot chat UI", "notes": "Right-rail CopilotPanel with streaming. PR #5."},
    {"step": "4", "label": "Step 4 — Agentic memory surfacing", "notes": "Memory API, copilot context, MemoryContextCard. PR #6."},
    {"step": "5", "label": "Step 5 — Logfire + launch readiness", "notes": "LaunchReadinessPanel, competition go/no-go API. PR #7."},
    {"step": "6", "label": "Step 6 — Between-round adaptation", "notes": "AdaptationPanel, adapt_round dashboard API. PR #8."},
    {"step": "7", "label": "Step 7 — Notion sync panel", "notes": "Tasks API, sync stats, copilot roadmap. PR #9."},
    {"step": "8", "label": "Step 8 — Operator runbook + Northflank", "notes": "Preflight, deploy status, operator runbook. PR #10."},
    {"step": "9", "label": "Step 9 — Competition-day automation", "notes": "Verification suite, CompetitionDayPanel, pytest automation. PR #11."},
    {"step": "10", "label": "Step 10 — Demo walkthrough + technology prize", "notes": "Judge demo page, sponsor checklist. PR #12."},
]

AZ_SECTIONS: list[dict[str, str]] = [
    {
        "letter": "A",
        "title": "Architecture & Autonomous Operation",
        "body": (
            "QuantAI runs a 15-minute decision loop automatically once started. "
            "Four agents (TrendSurfer, BreakoutHunter, MomentumPulse, MeanReversion) vote; "
            "MetaOrchestrator (Claude) resolves conflicts; risk rails enforce the constitution; "
            "orders go to MT5 via ZeroMQ. You do NOT approve each trade — start once, monitor dashboard/Logfire."
        ),
    },
    {
        "letter": "B",
        "title": "Between-Rounds (22:00–23:00 BST)",
        "body": (
            "Pause engine or confirm adaptation window. Run adapt_round.py or use Agents → Adaptation panel. "
            "Learning pipeline: scripts/run_learning_pipeline.sh. Weight changes capped ±10% per round."
        ),
    },
    {
        "letter": "C",
        "title": "Command Center & Copilot",
        "body": (
            "Dashboard at :8080. Copilot (right rail) gives grounded read-only analysis with data citations. "
            "Steps 1–10 complete and merged to main. Overview: Launch Readiness, Operator Runbook, "
            "Competition Day Automation, Notion Sync."
        ),
    },
    {
        "letter": "D",
        "title": "Dashboard Routes",
        "body": (
            "/ Overview · /positions · /trades · /agents · /risk · /market · /decisions · /demo (technology prize). "
            "API: /api/status, /api/copilot/*, /api/operator/*, /api/prize/technology-checklist."
        ),
    },
    {
        "letter": "E",
        "title": "Environment Variables",
        "body": (
            "ANTHROPIC_API_KEY, LOGFIRE_TOKEN, DOUBLEWORD_API_KEY (optional), QUANTAI_PHASE=round1, "
            "ZMQ_HOST/ports, DASHBOARD_AUTH_TOKEN, NOTION_API_KEY + database IDs. See .env.example."
        ),
    },
    {
        "letter": "F",
        "title": "Forex Instruments (8)",
        "body": "AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY",
    },
    {
        "letter": "G",
        "title": "Go-Live Commands",
        "body": (
            "Live competition: python main.py --mode live --phase round1 --with-dashboard\n"
            "Simulate: python main.py --mode simulate --phase round1 --with-dashboard\n"
            "One cycle: python main.py --mode single-cycle --phase round1\n"
            "Dashboard only: ./scripts/start_dashboard.sh --build"
        ),
    },
    {
        "letter": "H",
        "title": "Historical Data & Learning",
        "body": (
            "scripts/ingest_historical.py · build_regime_library.py · adapt_round.py. "
            "20GB holdout for walk-forward validation between rounds only — never during live trading."
        ),
    },
    {
        "letter": "I",
        "title": "Intervene Controls (Optional)",
        "body": (
            "Dashboard Trading Control Bar: Pause (stops new entries, manages exits), Resume, Run cycle now, "
            "Reconnect bridge, Manual trade, Close positions. Use only for emergencies or between rounds — "
            "not required each cycle."
        ),
    },
    {
        "letter": "J",
        "title": "Journal & Logging",
        "body": "logs/trades.jsonl, trades.csv, data/runtime_state.json, data/trade_memory.db. Logfire traces full decision pipeline when LOGFIRE_TOKEN set.",
    },
    {
        "letter": "K",
        "title": "Kelly Sizing & Risk Constitution",
        "body": (
            "Half-Kelly position sizing. Five drawdown tiers: normal → elevated → warning → critical → emergency (15% close-all). "
            "Margin cap 88%, leverage 20×, concentration 40%. Learning loop never modifies risk params."
        ),
    },
    {
        "letter": "L",
        "title": "Logfire Observability",
        "body": "Pydantic Logfire on engine cycles: features → agents → orchestrator → risk → execution. Disable: --no-logfire.",
    },
    {
        "letter": "M",
        "title": "Metals (2)",
        "body": "XAG/USD (silver), XAU/USD (gold). Active all rounds except crypto-only restrictions in Round 3 logic applies to crypto only.",
    },
    {
        "letter": "N",
        "title": "Northflank Deploy",
        "body": (
            "Two services: quantai-engine + quantai-dashboard sharing volume at /app/logs and /app/data. "
            "See docs/northflank_deploy.md. Smoke: ./scripts/deploy_smoke.sh"
        ),
    },
    {
        "letter": "O",
        "title": "Orchestrator (Claude)",
        "body": "MetaOrchestrator in src/agents/meta_orchestrator.py. Claude when agent confidence > 0.65; rule fallback if API unavailable.",
    },
    {
        "letter": "P",
        "title": "Phases & Instruments by Round",
        "body": (
            "Round 1 (1.2× risk): all 15 symbols. Round 2 (1.0×): all 15. "
            "Round 3 (0.7×): forex + metals only (10 symbols — crypto auto-disabled). Finals (0.9×): all 15."
        ),
    },
    {
        "letter": "Q",
        "title": "Quick Pre-Launch Checklist",
        "body": (
            "python scripts/preflight_competition.py --zmq-only\n"
            "python scripts/competition_day_verify.py\n"
            "python scripts/test_mt5_connection.py\n"
            "pytest tests/ -q"
        ),
    },
    {
        "letter": "R",
        "title": "Repository & Tests",
        "body": "GitHub: haseeb099/Quant-Hack-AI. 93 tests passing. CI: pytest + frontend build.",
    },
    {
        "letter": "S",
        "title": "Scoring Formula",
        "body": "Final Score = 70% Return + 15% Drawdown + 10% Sharpe + 5% Risk Discipline",
    },
    {
        "letter": "T",
        "title": "Technology Prize Demo",
        "body": (
            "Dashboard → Demo page. 5-min walkthrough per docs/demo_script.md. "
            "Sponsor checklist: Anthropic, Pydantic Logfire, Doubleword, Northflank."
        ),
    },
    {
        "letter": "U",
        "title": "Unattended 24h Operation",
        "body": (
            "Designed for full 24h competition rounds with minimal intervention. "
            "Pre-session 21:30 BST: MT5 + bridge. Launch 22:00 BST: start engine. Monitor alerts only."
        ),
    },
    {
        "letter": "V",
        "title": "Verification & Preflight",
        "body": "GET /api/operator/verification · POST /api/operator/verification/run · GET /api/operator/runbook · GET /api/competition/launch-readiness",
    },
    {
        "letter": "W",
        "title": "WebSocket Live Feed",
        "body": "WS /ws/live broadcasts state every ~5s to dashboard. Heartbeat publishes runtime_state.json.",
    },
    {
        "letter": "X",
        "title": "Crypto Instruments (5)",
        "body": "BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD. Dropped automatically in Round 3 phase config.",
    },
    {
        "letter": "Y",
        "title": "Your Role as Operator",
        "body": (
            "Start MT5 EA → run main.py once → watch Overview/Risk/Logfire. "
            "Intervene only on bridge offline, margin critical, or between-round adaptation."
        ),
    },
    {
        "letter": "Z",
        "title": "ZeroMQ / MT5 Bridge",
        "body": (
            "mql5/DWX_ZeroMQ_Server.mq5 on ports 32768 (cmd), 32769 (confirm), 32770 (ticks). "
            "All 15 symbols must be in MarketWatch. scripts/zmq_diagnose.py for troubleshooting."
        ),
    },
]

INSTRUMENTS_TABLE = """Competition instruments (15 total — ONLY these pairs):

Forex (8): AUD/USD, EUR/CHF, EUR/GBP, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY
Metals (2): XAG/USD, XAU/USD
Crypto (5): BAR/USD, BTC/USD, ETH/USD, SOL/USD, XRP/USD

Config: config/instruments.yaml · Preflight validates exact 15-symbol universe."""

GUIDE_TITLE = "QuantAI A–Z Operator Guide (Command Center)"
