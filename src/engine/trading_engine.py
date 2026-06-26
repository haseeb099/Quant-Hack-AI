"""Main trading engine — phase-aware decision loop."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.base_agent import Direction
from src.agents.context_builder import ContextBuilder
from src.agents.debate_orchestrator import DebateOrchestrator
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.meta_orchestrator import MetaOrchestrator
from src.agents.ml_signal_agent import MLSignalAgent
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.bridges.factory import create_live_connector, connector_bridge_type
from src.bridges.fill_price import resolve_fill_price
from src.bridges.mt5_direct_connector import Mt5DirectConnector
from src.bridges.zeromq_connector import (
    ZeroMQConnector,
    account_equity,
    OHLCV_BAR_COUNT,
    FILL_RECOVERY_POLLS,
    FILL_RECOVERY_POLL_SEC,
    VOLUME_EPS,
)
from src.data.feature_engine import FeatureEngine
from src.data.live_feed import LiveFeed
from src.data.market_validator import MarketValidator
from src.data.session_filter import SessionFilter
from src.engine.adaptation_loader import apply_adaptation_to_config, load_adaptation_plan
from src.engine.config import QuantAIConfig, load_yaml, resolve_phase
from src.learning.competition_strategy import CompetitionStrategy
from src.learning.entry_quality import passes_quality_gate, score_entry
from src.engine.trade_journal import (
    build_tracked_from_mt5_deals,
    closed_tickets_from_jsonl,
    context_from_jsonl,
    display_symbol,
    mt5_closed_tickets,
)
from src.intelligence.market_intelligence import MarketIntelligenceService
from src.intelligence.peer_monitor import PeerMonitor
from src.learning.layered_memory import LayeredMemory, TradeRecord, build_trade_attribution
from src.risk.account_profile import (
    AccountProfile,
    detect_profile,
    position_notional,
    position_notional_from_dict,
)
from src.risk.margin_watcher import MarginWatcher
from src.risk.compliance import ComplianceEngine
from src.risk.compliance_heartbeat import ComplianceHeartbeat
from src.risk.drawdown_guard import DrawdownGuard, DrawdownState
from src.risk.kelly_sizer import KellySizer
from src.risk.lot_sizer import pnl_pct, risk_to_lots
from src.risk.margin_monitor import MarginMonitor, MarginState
from src.risk.portfolio_heat import PortfolioHeat
from src.risk.position_manager import PositionManager
from src.risk.sharpe_guard import SharpeGuard
from src.utils.logger import instrument_span, log_trade_decision
from src.utils.trade_logger import TradeLogger
from src.web.state_publisher import StatePublisher

logger = logging.getLogger(__name__)

PHASE_FILTER_PACKS: dict[str, Path] = {
    "round3": Path("data/live_filters_round3.json"),
    "finals": Path("data/live_filters_finals.json"),
}
LIVE_FILTERS_PATH = Path("data/live_competition_filters.json")


class TradingEngine:
    """Orchestrates the full decision loop on a phase-configured interval."""

    def __init__(
        self,
        config: QuantAIConfig,
        simulation: bool = False,
        cycle_minutes: int | None = None,
        auto_phase: bool = True,
    ) -> None:
        self.config = config
        self.simulation = simulation
        self.feature_engine = FeatureEngine()
        self.connector: ZeroMQConnector | Mt5DirectConnector = ZeroMQConnector()
        self.memory = LayeredMemory(round_id=config.current_phase)
        self.context_builder = ContextBuilder(self.memory)
        self.debate_orchestrator = DebateOrchestrator()
        self.peer_monitor = PeerMonitor(round_id=config.current_phase)
        self.intelligence = MarketIntelligenceService(live_mode=not simulation)
        self.trade_logger = TradeLogger()
        self.sharpe_guard = SharpeGuard()
        self.compliance_heartbeat = ComplianceHeartbeat(config.risk)

        self.market_validator = MarketValidator()
        self.kelly_sizer = KellySizer(config.risk.get("sizing", {}))
        self.compliance = ComplianceEngine(config.risk.get("compliance", {}))
        self.competition_strategy = CompetitionStrategy()
        self.portfolio_heat = PortfolioHeat(self._portfolio_heat_config(1_000_000))
        self.account_profile: AccountProfile | None = None
        self._auto_phase = auto_phase
        self._cycle_minutes = cycle_minutes if cycle_minutes is not None else config.cycle_minutes()
        self.state_publisher = StatePublisher(cycle_minutes=self._cycle_minutes)
        self._size_multiplier = 1.0
        self._open_trades: dict[int, dict] = {}
        self._peak_equity: float = 0.0
        self._prev_dd_tier: str = "normal"
        self._warning_reduce_applied: bool = False
        self._entries_blocked: bool = False
        self._margin_watcher: MarginWatcher | None = None
        self._cycle_decisions: list[dict] = []
        self._cycle_votes: list[dict] = []
        self._instrument_regimes: dict[str, str] = {}
        self._ohlcv_meta: dict[str, dict] = {}
        self._ohlcv_source: dict[str, str] = {}
        self._symbol_info_cache: dict[str, dict[str, float]] = {}
        self._last_known_equity: float | None = None
        self._cycle_symbols_attempted: int = 0
        self._symbol_cooldown_until: dict[str, datetime] = {}
        self._momentum_flags: dict[str, datetime] = {}
        self._running = False
        self._fill_overshoot_block = False
        self._fill_undershoot_block = False
        self._fx_shorts_opened_this_cycle = 0
        self._chf_entries_opened_this_cycle = 0
        self._crypto_entries_opened_this_cycle = 0
        self._runner_entries_opened_this_cycle = 0
        self._aa_plus_entries_opened_this_cycle = 0
        self._finalized_tickets: set[int] = closed_tickets_from_jsonl(self.trade_logger.jsonl_path)
        self._paused = False
        self._cycle_in_progress = False
        self._cycle_lock = threading.Lock()
        self._last_cycle_at: str | None = None
        self._next_cycle_at: str | None = None
        self._live_filters: dict = {}
        self._pending_limit_orders: dict[str, dict] = {}
        self._cycle_events: list[dict] = []
        self._position_diagnostics: list[dict] = []
        self._cycle_diag_equity: float | None = None
        self._cycle_diag_dd_state = None
        self._cycle_diag_drawdown_pct: float = 0.0

        self._rebuild_runtime_for_phase()

    def _sync_cycle_minutes(self) -> None:
        """Keep engine loop and dashboard countdown aligned with phase rules."""
        self._cycle_minutes = self.config.cycle_minutes()
        self.state_publisher.cycle_minutes = self._cycle_minutes

    def _rebuild_runtime_for_phase(self) -> None:
        """Reload agents, session filter, live feed symbols, and risk components for current phase."""
        phases_cfg = load_yaml("phases.yaml")
        engine_cfg = phases_cfg.get("engine", {})
        phase_rules = self.config.phase_rules
        self._sync_cycle_minutes()

        symbol_filter = phase_rules.get("session_symbol_filter")
        if symbol_filter is None:
            symbol_filter = engine_cfg.get("session_symbol_filter", True)
        self.session_filter = SessionFilter(
            phases_cfg.get("sessions", {}),
            symbol_filter_enabled=bool(symbol_filter),
        )

        adaptation_plan = load_adaptation_plan()
        apply_adaptation_to_config(self.config, adaptation_plan)

        agent_weights = {
            name: float(
                (phase_rules.get("agent_weights") or {}).get(name, cfg.get("weight", 0.25))
            )
            for name, cfg in self.config.agents.items()
            if name != "meta_orchestrator"
        }
        agent_best_regimes = {
            name: cfg.get("best_regimes", [])
            for name, cfg in self.config.agents.items()
            if name != "meta_orchestrator"
        }
        orch_cfg = dict(self.config.agent_config("meta_orchestrator"))
        orch_cfg.pop("anthropic_api_key", None)
        orch_cfg["agent_weights"] = agent_weights
        orch_cfg["agent_best_regimes"] = agent_best_regimes
        if phase_rules.get("min_agent_confidence") is not None:
            orch_cfg["min_agent_confidence"] = phase_rules["min_agent_confidence"]
        if phase_rules.get("orchestrator_cooldown_minutes") is not None:
            orch_cfg["cooldown_minutes"] = phase_rules["orchestrator_cooldown_minutes"]

        self.agents = [
            TrendSurferAgent(self.config.agent_config("trend_surfer")),
            BreakoutHunterAgent(self.config.agent_config("breakout_hunter")),
            MomentumPulseAgent(self.config.agent_config("momentum_pulse")),
            MeanReversionAgent(self.config.agent_config("mean_reversion")),
        ]
        ml_agent = MLSignalAgent(self.config.agent_config("ml_signal"))
        if ml_agent.is_active and self.config.is_agent_enabled("ml_signal"):
            self.agents.append(ml_agent)
        if self.intelligence.enabled and os.getenv("SENTIMENT_AGENT_ENABLED", "true").lower() not in ("0", "false"):
            self.agents.append(SentimentAgent(self.config.agent_config("sentiment_agent")))
        self.orchestrator = MetaOrchestrator(
            orch_cfg, self.config.regime_boosts, agent_weights, agent_best_regimes,
        )

        new_symbols = list(self.config.active_symbols)
        if not hasattr(self, "live_feed"):
            self.live_feed = LiveFeed(
                self.connector,
                symbols=new_symbols,
                feature_update_seconds=self.config.feature_update_seconds,
                simulation=self.simulation,
            )
        else:
            old_symbols = set(self.live_feed.symbols)
            self.live_feed.symbols = new_symbols
            if set(new_symbols) != old_symbols and self.live_feed._running:
                self.live_feed.stop()
                self.live_feed.start()

        risk = self.config.risk
        self.drawdown_guard = DrawdownGuard(risk.get("drawdown", {}))
        self.margin_monitor = MarginMonitor(
            risk.get("margin", {}),
            risk.get("leverage", {}),
            risk.get("concentration", {}),
            risk.get("drawdown", {}),
        )
        self.compliance_heartbeat = ComplianceHeartbeat(self.config.risk)
        self.position_manager = PositionManager(self.config.phase_rules)
        self.sharpe_guard.set_phase(self.config.current_phase)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def cycle_in_progress(self) -> bool:
        return self._cycle_in_progress

    def pause_trading(self) -> None:
        self._paused = True
        logger.info("Engine paused — new entries disabled")
        self._publish_state()

    def resume_trading(self) -> None:
        self._paused = False
        logger.info("Engine resumed — new entries enabled")
        self._publish_state()

    def force_run_cycle(self) -> dict[str, str]:
        if not self.run_cycle():
            return {"status": "busy"}
        return {"status": "ok"}

    def get_open_trades(self) -> dict:
        return {
            "count": len(self._open_trades),
            "tickets": list(self._open_trades.keys()),
            "trades": {str(k): v for k, v in self._open_trades.items()},
        }

    def operator_close_position(self, ticket: int) -> dict:
        positions = self.connector.get_positions()
        pos = next((p for p in positions if p.get("ticket") == ticket), {})
        before_vol = float(pos.get("volume", 0))
        result = self.connector.close_position(ticket)
        if result.get("status") in ("ok", "simulated"):
            account = self.connector.get_account_info()
            equity = float(account.get("equity", 0) or self._last_equity or 0)
            if not pos:
                pos = {
                    "profit": 0,
                    "symbol": self._open_trades.get(ticket, {}).get("symbol", ""),
                }
            if self._close_position_confirmed(ticket, before_vol, result):
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)
        self._publish_state()
        return result

    def operator_close_all(self) -> dict:
        positions = self.connector.get_positions()
        result = self.connector.close_all()
        if result.get("status") in ("ok", "simulated"):
            account = self.connector.get_account_info()
            equity = float(account.get("equity", 0) or self._last_equity or 0)
            for pos in positions:
                ticket = pos.get("ticket")
                if ticket:
                    self._finalize_trade(ticket, pos, equity)
                    self.position_manager.on_close(ticket)
        self._publish_state()
        return result

    def operator_modify_position(
        self,
        ticket: int,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict:
        result = self.connector.modify_position(ticket, sl=sl, tp=tp)
        self._publish_state()
        return result

    def operator_manual_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        skip_risk_check: bool = False,
    ) -> dict:
        if not skip_risk_check:
            from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate

            check = get_pre_trade_gate().evaluate_from_engine(
                self,
                TradeCheckRequest(symbol=symbol, direction=direction, volume=volume, sl=sl, tp=tp),
            )
            if not check.allowed:
                return {
                    "status": "blocked",
                    "message": check.blockers[0].message if check.blockers else "Risk gate blocked trade",
                    "risk_check": check.to_dict(),
                }
        result = self.connector.send_trade(symbol, direction, volume, sl=sl, tp=tp)
        if result.get("status") in ("ok", "simulated"):
            ticket = result.get("ticket")
            if ticket:
                ticket = self._validate_open_ticket(symbol, direction, int(ticket))
                result["ticket"] = ticket
                fill_price = resolve_fill_price(
                    result, ticket, symbol, 0.0, self.connector,
                )
                session = self.session_filter.current_session()
                self._open_trades[int(ticket)] = {
                    "symbol": symbol,
                    "direction": direction.upper(),
                    "entry_price": fill_price,
                    "volume": float(result.get("volume", volume) or volume),
                    "sl": sl,
                    "session": session.name,
                    "regime": self._instrument_regimes.get(symbol, "unknown"),
                    "agent": "manual",
                    "features_snapshot": {},
                    "agent_votes": [],
                    "attribution_json": {},
                    "reasoning": "Operator manual trade",
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                }
        self._publish_state()
        return result

    def operator_reconnect_mt5(self) -> dict:
        ok = self.connector.reconnect()
        self._publish_state()
        return {
            "status": "ok" if ok else "error",
            "connected": ok,
            "message": self.connector.last_error or ("Connected" if ok else "Reconnect failed"),
        }

    def start(self) -> None:
        if not self.simulation:
            self.connector = create_live_connector()
            if connector_bridge_type(self.connector) == "zmq":
                time.sleep(1.5)  # ZMQ slow-joiner warmup
            self._init_mt5_session()
        self._running = True
        account = self.connector.get_account_info()
        equity = account_equity(account, simulation=self.simulation)
        if equity is None:
            raise RuntimeError(
                account.get("message", "Account equity unavailable — check ZeroMQ bridge and MT5 account")
            )
        self.account_profile = detect_profile(equity)
        self.portfolio_heat = PortfolioHeat(self._portfolio_heat_config(equity))
        self.drawdown_guard.reset(equity)
        self.margin_monitor.reset_session(equity)
        self._initial_equity = self._resolve_initial_equity(equity)
        self._peak_equity = equity
        self._maybe_reset_stale_peak(equity)
        self.position_manager = PositionManager(self.config.phase_rules)
        self.sharpe_guard.reset_round(equity)
        self.sharpe_guard.set_phase(self.config.current_phase)

        if not self.simulation:
            self.live_feed.start()
            self.compliance_heartbeat.start(
                metrics_fn=self._compliance_metrics,
                action_callback=self._handle_compliance_actions,
            )
            self._margin_watcher = MarginWatcher(
                self.connector,
                self.margin_monitor,
                self.config.risk.get("margin", {}),
                simulation=self.simulation,
                on_reduce_worst_losers=self._reduce_worst_losers,
                on_fail_closed=self._margin_fail_closed,
                is_data_stale=self._is_market_data_stale,
            )
            self._margin_watcher.start()

        logger.info(
            "QuantAI engine started — phase=%s profile=%s equity=%.2f",
            self.config.current_phase,
            self.account_profile.kind if self.account_profile else "unknown",
            equity,
        )
        self._publish_state()

    def _init_mt5_session(self) -> None:
        """Optional MT5 Python session for lot-size conversion."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session, load_mt5_credentials

            creds = load_mt5_credentials()
            if not all([creds.login, creds.password, creds.server]):
                return
            ok, detail = ensure_mt5_session(require_login=True)
            if ok:
                logger.info("MT5 lot-size helper ready: %s", detail)
            else:
                logger.warning("MT5 lot-size helper unavailable: %s", detail)
        except ImportError:
            logger.warning("MetaTrader5 package not installed — lot sizes may be approximate")

    @staticmethod
    def _load_live_competition_filters(phase: str | None = None) -> dict:
        pack_map = {
            "round3": Path("data/live_filters_round3.json"),
            "finals": Path("data/live_filters_finals.json"),
        }
        path = pack_map.get(phase or "", Path("data/live_competition_filters.json"))
        if not path.exists():
            path = Path("data/live_competition_filters.json")
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _objective_runtime_overrides(self) -> dict[str, Any]:
        objective = str(self.config.phase_rules.get("objective", "maximize_return"))
        phase = self.config.current_phase
        return_push = bool(
            self.config.phase_rules.get("return_focus")
            and phase in ("round1", "round2", "round3", "finals")
        )
        presets: dict[str, dict[str, Any]] = {
            "maximize_return": {
                "max_entries": int(self.config.phase_rules.get("max_new_entries_per_cycle", 4)),
                "risk_mult": 1.50 if return_push and phase == "finals" else (1.20 if return_push else 1.0),
                "min_confidence_floor": 0.54 if return_push and phase == "finals" else 0.55,
            },
            "avoid_elimination": {
                "max_entries": 2,
                "risk_mult": 0.75,
                "min_confidence_floor": 0.62,
            },
            "optimize_composite": {
                "max_entries": 3,
                "risk_mult": 0.95,
                "min_confidence_floor": 0.60,
            },
        }
        return presets.get(objective, presets["maximize_return"])

    def _merge_objective_filters(self, live_filters: dict) -> dict:
        merged = dict(live_filters)
        overrides = self._objective_runtime_overrides()
        floor = overrides.get("min_confidence_floor")
        if floor is not None:
            merged["min_confidence"] = max(float(merged.get("min_confidence") or 0), float(floor))
        obj_max = overrides.get("max_entries")
        if obj_max is not None:
            current = merged.get("max_new_entries_per_cycle")
            merged["max_new_entries_per_cycle"] = (
                min(int(current), int(obj_max)) if current is not None else int(obj_max)
            )
        return merged

    @staticmethod
    def _apply_phase_filter_pack(phase: str) -> None:
        pack_path = PHASE_FILTER_PACKS.get(phase)
        if pack_path is None or not pack_path.exists():
            return
        try:
            with open(pack_path, encoding="utf-8") as f:
                pack = json.load(f)
            if not isinstance(pack, dict):
                return
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load phase filter pack %s", pack_path)
            return
        existing: dict = {}
        if LIVE_FILTERS_PATH.exists():
            try:
                with open(LIVE_FILTERS_PATH, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    existing = raw
            except (json.JSONDecodeError, OSError):
                existing = {}
        merged = {**existing, **pack}
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        LIVE_FILTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LIVE_FILTERS_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.write("\n")
        logger.info("Applied phase filter pack for %s", phase)

    def _log_exit_action(self, action, pos: dict, ticket: int) -> None:
        tracked = self._open_trades.get(ticket, {})
        symbol = tracked.get("symbol") or str(pos.get("symbol", ""))
        self.trade_logger.log(
            symbol=symbol,
            regime=tracked.get("regime", self._instrument_regimes.get(symbol, "")),
            session=tracked.get("session", ""),
            direction=tracked.get("direction", str(pos.get("type", "BUY"))),
            confidence=0.0,
            agent_votes=tracked.get("agent_votes", []),
            status="exit_action",
            reasoning=action.reason,
            extra={
                "ticket": ticket,
                "exit_action": action.action,
                "exit_rule": action.reason,
                "new_sl": action.new_sl,
                "volume": action.volume,
            },
        )

    def _position_manager_config(self) -> dict[str, Any]:
        cfg = dict(self.config.phase_rules)
        lf = self._live_filters or {}
        for key in (
            "time_stop_bars",
            "time_stop_m15_bars",
            "time_stop_min_r",
            "partial_take_r",
            "partial_fraction",
            "trail_after_r",
            "trail_atr_mult",
            "enable_partial_takes",
            "enable_trailing",
            "enable_breakeven",
            "breakeven_r",
            "regime_flip_enabled",
            "max_hold_m15_bars",
            "profit_lock_m15_bars",
            "profit_lock_min_r",
            "adverse_stop_m15_bars",
            "adverse_stop_r",
            "max_adverse_r",
            "never_green_bars",
            "never_green_peak_r",
            "never_green_max_r",
        ):
            if key in lf:
                cfg[key] = lf[key]
        return cfg

    def _reload_phase_playbook(self) -> None:
        """Hot-reload phase YAML when competition playbook changes without a phase transition."""
        phase = self.config.current_phase
        fresh = QuantAIConfig.load(phase=phase, auto_phase=False)
        before = (
            self.config.objective,
            self.config.phase_multiplier,
            tuple(self.config.active_symbols),
            tuple(self.config.phase_rules.get("disabled_agents") or []),
        )
        self.config.phases = fresh.phases
        self.config.engine = fresh.engine
        after = (
            self.config.objective,
            self.config.phase_multiplier,
            tuple(self.config.active_symbols),
            tuple(self.config.phase_rules.get("disabled_agents") or []),
        )
        if before != after:
            logger.info(
                "Phase playbook hot-reloaded (%s): objective=%s risk_mult=%.2f symbols=%d",
                phase,
                self.config.objective,
                self.config.phase_multiplier,
                len(self.config.active_symbols),
            )
            self._rebuild_runtime_for_phase()
            self.sharpe_guard.set_phase(phase)

    def _sync_position_manager_config(self) -> None:
        if hasattr(self, "position_manager"):
            self.position_manager.apply_runtime_config(self._position_manager_config())

    def _log_cycle_event(
        self,
        event_type: str,
        symbol: str,
        *,
        direction: str = "",
        reason: str = "",
        ticket: int | None = None,
        extra: dict | None = None,
    ) -> None:
        self._cycle_events.append({
            "type": event_type,
            "symbol": symbol,
            "direction": direction,
            "reason": reason,
            "ticket": ticket,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        })

    def _build_scan_meta(
        self,
        symbol: str,
        signals: list,
        decision,
        live_filters: dict,
        phase_rules: dict,
    ) -> dict[str, Any]:
        min_consensus = self._min_consensus_for_symbol(symbol, live_filters, phase_rules)
        if live_filters.get("use_audit_routing", True):
            audit_min = self.competition_strategy.min_consensus_for_symbol(
                symbol,
                min_consensus,
                tier_a_consensus=int(live_filters.get("tier_a_min_consensus", 1)),
                tier_b_consensus=int(live_filters.get("tier_b_min_consensus", 2)),
                tier_c_consensus=int(live_filters.get("tier_c_min_consensus", 2)),
            )
            solo_syms = set(live_filters.get("audit_solo_consensus_symbols") or [])
            if symbol in solo_syms:
                min_consensus = audit_min
            elif self._is_crypto_symbol(symbol) or self._is_fx_symbol(symbol):
                min_consensus = max(min_consensus, audit_min)
            else:
                min_consensus = audit_min

        direction = getattr(getattr(decision, "direction", None), "value", "HOLD")
        agreeing_agents = [
            s.agent_name
            for s in signals
            if s.is_actionable and s.direction.value == direction
        ]
        sym_conf = (live_filters.get("symbol_min_confidence") or {}).get(symbol)
        min_conf = sym_conf if sym_conf is not None else live_filters.get("min_confidence")

        return {
            "symbol_tier": self.competition_strategy.symbol_tier(symbol),
            "consensus_required": int(min_consensus),
            "consensus_agreeing": len(agreeing_agents),
            "agreeing_agents": agreeing_agents,
            "min_confidence_required": float(min_conf) if min_conf is not None else None,
            "orchestrator_confidence": float(getattr(decision, "confidence", 0) or 0),
        }

    def _symbol_cooldown_minutes(self) -> int:
        lf = getattr(self, "_live_filters", {}) or {}
        raw = lf.get("symbol_cooldown_minutes")
        if raw is not None:
            return int(raw)
        return int(self.config.phase_rules.get("symbol_cooldown_minutes", 0) or 0)

    def _momentum_phases(self) -> set[str]:
        return {"round1", "round2", "finals"}

    def _momentum_flag_active(self, symbol: str, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        until = self._momentum_flags.get(symbol)
        if until is None:
            return False
        if now >= until:
            del self._momentum_flags[symbol]
            return False
        return True

    def _effective_cooldown_minutes(self, symbol: str, now: datetime | None = None) -> int:
        phase_rules = self.config.phase_rules
        if self._momentum_flag_active(symbol, now):
            return int(phase_rules.get("momentum_cooldown_minutes", 2))
        return self._symbol_cooldown_minutes()

    def _position_r_multiple(self, ticket: int, pos: dict) -> float | None:
        tracked = self._open_trades.get(ticket, {})
        entry = float(tracked.get("entry_price") or pos.get("price_open", 0) or 0)
        sl = tracked.get("sl")
        if sl is None:
            sl = pos.get("sl")
        sl = float(sl) if sl is not None else 0.0
        price = float(pos.get("price_current", entry) or entry)
        direction = str(tracked.get("direction") or pos.get("type", "BUY")).upper()
        sl_dist = abs(entry - sl) if sl else 0.0
        if entry <= 0 or sl_dist <= 0:
            return None
        if "BUY" in direction or direction in ("LONG", "0"):
            return (price - entry) / sl_dist
        return (entry - price) / sl_dist

    def _write_cycle_diagnostics(
        self,
        cycle_start: datetime,
        equity: float,
        dd_state,
        drawdown_pct: float,
    ) -> None:
        symbols_skipped: dict[str, str] = {}
        signals_generated: dict[str, dict] = {}
        trades_opened: list[dict] = []
        trades_closed: list[dict] = []
        symbols_evaluated: list[str] = []

        for decision in self._cycle_decisions:
            sym = decision.get("symbol", "")
            if sym and sym != "*" and sym not in symbols_evaluated:
                symbols_evaluated.append(sym)
            status = decision.get("status", "")
            if status == "skipped" and sym:
                symbols_skipped[sym] = str(
                    decision.get("skip_reason") or decision.get("reasoning") or "skipped"
                )
            elif status in ("executed", "simulated", "pending"):
                trades_opened.append({
                    "symbol": sym,
                    "direction": decision.get("direction"),
                    "confidence": decision.get("confidence"),
                    "size": decision.get("size"),
                })
            direction = decision.get("direction", "HOLD")
            if direction != "HOLD" and sym and sym != "*":
                blocked_at = None
                if status == "skipped":
                    reason = str(decision.get("skip_reason") or "")
                    if "confidence" in reason.lower() or "minimum" in reason.lower():
                        blocked_at = "confidence_floor"
                    elif "consensus" in reason.lower():
                        blocked_at = "consensus"
                    elif "cooldown" in reason.lower():
                        blocked_at = "cooldown"
                    else:
                        blocked_at = "gate"
                signals_generated[sym] = {
                    "direction": direction,
                    "confidence": decision.get("confidence"),
                    "blocked_at": blocked_at,
                }

        for event in self._cycle_events:
            if event.get("type") == "close":
                trades_closed.append({
                    "symbol": event.get("symbol"),
                    "ticket": event.get("ticket"),
                    "reason": event.get("reason"),
                })
            elif event.get("type") == "entry":
                if not any(t.get("symbol") == event.get("symbol") for t in trades_opened):
                    trades_opened.append({
                        "symbol": event.get("symbol"),
                        "direction": event.get("direction"),
                        "ticket": event.get("ticket"),
                    })

        eval_count = len(symbols_evaluated)
        skip_count = len(symbols_skipped)
        signal_count = len(signals_generated)
        open_count = len(trades_opened)
        hold_count = sum(
            1 for d in self._cycle_decisions
            if d.get("direction") == "HOLD" and d.get("status") != "skipped"
        )

        record = {
            "timestamp": cycle_start.isoformat(),
            "phase": self.config.current_phase,
            "equity": equity,
            "drawdown_pct": drawdown_pct,
            "drawdown_tier": dd_state.tier,
            "symbols_evaluated": symbols_evaluated,
            "symbols_skipped_why": symbols_skipped,
            "signals_generated": signals_generated,
            "trades_opened": trades_opened,
            "trades_closed": trades_closed,
        }

        log_path = Path("logs/cycle_diagnostics.jsonl")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        print(
            f"[CYCLE] eq=${equity:,.0f} dd={drawdown_pct:.1%} | "
            f"eval={eval_count} skip={skip_count} signal={signal_count} "
            f"open={open_count} hold={hold_count}",
            flush=True,
        )

    def _sync_finals_loss_limits(self) -> None:
        if self.config.current_phase != "finals":
            self.margin_monitor.set_daily_loss_limit(
                float(self.config.risk.get("drawdown", {}).get("daily_loss_limit", 0.05)),
            )
            return
        lf = self._live_filters or {}
        phase_limit = self.config.phase_rules.get("daily_loss_limit_pct")
        limit = lf.get("daily_loss_halt_pct", phase_limit)
        if limit is not None:
            self.margin_monitor.set_daily_loss_limit(float(limit))

    def _open_loser_count(self) -> int:
        return sum(
            1 for p in self.connector.get_positions()
            if float(p.get("profit", 0) or 0) < 0
        )

    def _finals_loss_guard_blocks_entries(self) -> tuple[bool, str]:
        if self.config.current_phase != "finals":
            return False, ""
        lf = self._live_filters or {}
        if not lf.get("loss_guard_enabled", True):
            return False, ""
        max_losers = int(lf.get("max_open_losers_before_halt", 4))
        losers = self._open_loser_count()
        if losers >= max_losers:
            return True, f"Loss guard: {losers} open losers (max {max_losers}) — entries paused"
        return False, ""

    def _intraday_loss_size_mult(self) -> float:
        lf = self._live_filters or {}
        if not lf.get("loss_guard_enabled", True):
            return 1.0
        start = self.margin_monitor._session_start_equity
        if not start or start <= 0:
            return 1.0
        account = self.connector.get_account_info()
        equity = float(account.get("equity", 0) or 0)
        if equity <= 0:
            return 1.0
        loss_pct = max(0.0, (start - equity) / start)
        warn = float(lf.get("daily_loss_warn_pct", 0.015))
        if loss_pct >= warn:
            return float(lf.get("intraday_loss_size_mult", 0.70))
        return 1.0

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def _blocked_symbols(self) -> set[str]:
        phase_rules = self.config.phase_rules
        return set(self._live_filters.get("blocked_symbols", [])) | set(
            phase_rules.get("blocked_symbols", []),
        )

    def _close_positions_on_blocked_symbols(self) -> None:
        """Close carry-over positions on symbols blocked for the active phase."""
        if self.simulation:
            return
        blocked = self._blocked_symbols()
        if not blocked:
            return
        blocked_norm = {self._normalize_symbol(s) for s in blocked}
        pos_snapshot = self._positions_snapshot()
        if not pos_snapshot.trusted:
            return
        account = self.connector.get_account_info()
        equity = float(account.get("equity", 0) or 0)
        for pos in pos_snapshot.positions:
            sym = str(pos.get("symbol", ""))
            if self._normalize_symbol(sym) not in blocked_norm:
                continue
            ticket = pos.get("ticket")
            volume = float(pos.get("volume", 0))
            if not ticket or volume <= 0:
                continue
            logger.warning(
                "Closing blocked-symbol position %s ticket=%s (phase policy)",
                sym,
                ticket,
            )
            self._log_cycle_event(
                "blocked_symbol_close",
                sym,
                reason="Symbol blocked for current phase — closing carry-over",
                ticket=int(ticket),
            )
            result = self.connector.close_position(ticket)
            self._log_position_reconcile(ticket, volume, "CLOSE", result)
            if self._close_position_confirmed(ticket, volume, result):
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)

    def _close_stub_positions_for_resize(self) -> None:
        """Close min-lot stub positions so finals can re-enter at full aggressive size."""
        if self.simulation or self.config.current_phase != "finals":
            return
        if not self.config.phase_rules.get("return_focus"):
            return
        lf = self._live_filters or {}
        if not lf.get("close_stub_positions", True):
            return
        max_notional_pct = float(lf.get("stub_max_notional_pct_equity", 0.0015))
        pos_snapshot = self._positions_snapshot()
        if not pos_snapshot.trusted:
            return
        account = self.connector.get_account_info()
        equity = float(account.get("equity", 0) or 0)
        if equity <= 0:
            return
        cap_notional = equity * max_notional_pct
        for pos in pos_snapshot.positions:
            sym = str(pos.get("symbol", ""))
            ticket = pos.get("ticket")
            volume = float(pos.get("volume", 0))
            if not ticket or volume <= 0:
                continue
            specs = self._get_symbol_specs(sym)
            if not specs:
                continue
            price = float(pos.get("price_current") or pos.get("price_open") or 0)
            if price <= 0:
                continue
            notional = position_notional(volume, specs["contract_size"], price)
            vol_min = float(specs["volume_min"])
            at_min_lot = volume <= vol_min * 1.05
            if not at_min_lot:
                continue
            if notional > cap_notional:
                continue
            logger.warning(
                "Closing stub position %s ticket=%s vol=%.4f notional=%.2f (<%0.2f%% equity) for resize",
                sym,
                ticket,
                volume,
                notional,
                max_notional_pct * 100,
            )
            self._log_cycle_event(
                "stub_position_close",
                sym,
                reason="Stub/min lot — freeing symbol for full-size finals entry",
                ticket=int(ticket),
            )
            result = self.connector.close_position(ticket)
            self._log_position_reconcile(ticket, volume, "CLOSE", result)
            if self._close_position_confirmed(ticket, volume, result):
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)

    def _positions_snapshot(self):
        getter = getattr(self.connector, "get_positions_snapshot", None)
        if getter is not None:
            return getter()
        from src.bridges.positions_snapshot import PositionsSnapshot

        return PositionsSnapshot(self.connector.get_positions(), True)

    @staticmethod
    def _is_crypto_symbol(symbol: str) -> bool:
        return symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}

    @staticmethod
    def _is_metal_symbol(symbol: str) -> bool:
        return symbol in {"XAU/USD", "XAG/USD"}

    @staticmethod
    def _is_chf_symbol(symbol: str) -> bool:
        return symbol in {"USD/CHF", "EUR/CHF"}

    @staticmethod
    def _is_fx_symbol(symbol: str) -> bool:
        return symbol in {
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD",
            "AUD/USD", "EUR/GBP", "EUR/CHF",
        }

    def _min_consensus_for_symbol(
        self,
        symbol: str,
        live_filters: dict,
        phase_rules: dict,
    ) -> int:
        default = int(
            live_filters.get("min_consensus_agents")
            or phase_rules.get("min_consensus_agents", 1)
        )
        symbol_overrides = live_filters.get("symbol_min_consensus_agents") or {}
        if symbol in symbol_overrides:
            return int(symbol_overrides[symbol])
        if self._is_fx_symbol(symbol):
            return int(live_filters.get("fx_min_consensus_agents", default))
        if self._is_crypto_symbol(symbol):
            return int(live_filters.get("crypto_min_consensus_agents", default))
        return default

    def _symbol_has_position(self, symbol: str, open_positions: list[dict]) -> bool:
        target = self._normalize_symbol(symbol)
        for pos in open_positions:
            if self._normalize_symbol(str(pos.get("symbol", ""))) == target:
                return True
        return False

    def _contract_size_for_symbol(self, symbol: str) -> float:
        specs = self._get_symbol_specs(symbol)
        return specs["contract_size"] if specs else 1.0

    def _position_notional_value(self, pos: dict) -> float:
        symbol = str(pos.get("symbol", ""))
        cs = float(pos.get("contract_size", 0)) or self._contract_size_for_symbol(symbol)
        return position_notional_from_dict(pos, cs)

    def _contract_lookup(self, symbol: str) -> float:
        return self._contract_size_for_symbol(symbol)

    def _executable_price(self, symbol: str, direction: str) -> float | None:
        sizing_cfg = self.config.risk.get("sizing", {})
        if not sizing_cfg.get("use_executable_prices", True):
            return self._current_price(symbol)
        tick = self.live_feed.get_tick(symbol)
        if not tick:
            return self._current_price(symbol)
        direction = direction.upper()
        if direction == "BUY":
            return tick.ask
        if direction == "SELL":
            return tick.bid
        return tick.mid

    def _spread_for_symbol(self, symbol: str) -> float:
        tick = self.live_feed.get_tick(symbol)
        if tick and tick.spread is not None:
            return float(tick.spread)
        return 0.0

    def _position_volume(self, ticket: int) -> float:
        for pos in self.connector.get_positions():
            if pos.get("ticket") == ticket:
                return float(pos.get("volume", 0))
        return 0.0

    def _volume_for_symbol_direction(self, symbol: str, direction: str) -> float:
        target = symbol.replace("/", "").upper()
        dir_u = direction.upper()
        total = 0.0
        for pos in self.connector.get_positions():
            sym = str(pos.get("symbol", "")).replace("/", "").upper()
            if sym != target:
                continue
            if str(pos.get("type", "")).upper() == dir_u:
                total += float(pos.get("volume", 0) or 0)
        return total

    def _resolve_open_ticket(
        self,
        symbol: str,
        direction: str,
        ticket: int,
    ) -> int | None:
        """Resolve ticket from open MT5 position; reject order/deal ids with no open position."""
        target = symbol.replace("/", "").upper()
        dir_u = direction.upper()
        matching = [
            p for p in self.connector.get_positions()
            if str(p.get("symbol", "")).replace("/", "").upper() == target
            and str(p.get("type", "")).upper() == dir_u
        ]
        if not matching:
            return None
        if ticket and any(int(p.get("ticket", 0)) == ticket for p in matching):
            return ticket
        latest = max(matching, key=lambda p: int(p.get("time", 0) or 0))
        return int(latest.get("ticket", 0) or 0) or None

    def _ensure_position_stops(
        self,
        ticket: int,
        symbol: str,
        sl: float | None,
        tp: float | None,
    ) -> None:
        """Attach SL/TP when broker fill omitted stops (e.g. connectivity test or partial EA ack)."""
        if self.simulation or (sl is None and tp is None):
            return
        try:
            positions = self.connector.get_positions()
            pos = next((p for p in positions if int(p.get("ticket", 0)) == ticket), None)
            if not pos:
                return
            cur_sl = float(pos.get("sl") or 0)
            cur_tp = float(pos.get("tp") or 0)
            need_sl = sl is not None and cur_sl <= 0
            need_tp = tp is not None and cur_tp <= 0
            if not need_sl and not need_tp:
                return
            mod = self.connector.modify_position(
                ticket,
                sl=sl if need_sl else None,
                tp=tp if need_tp else None,
            )
            if mod.get("status") in ("ok", "simulated"):
                logger.info("Attached stops ticket=%d %s sl=%s tp=%s", ticket, symbol, sl, tp)
            else:
                logger.warning(
                    "Failed to attach stops ticket=%d %s: %s",
                    ticket,
                    symbol,
                    mod.get("message"),
                )
        except Exception as exc:
            logger.warning("ensure_position_stops failed ticket=%d: %s", ticket, exc)

    def _validate_open_ticket(
        self,
        symbol: str,
        direction: str,
        ticket: int,
    ) -> int | None:
        resolved = self._resolve_open_ticket(symbol, direction, ticket)
        if resolved is None:
            logger.warning(
                "Open ticket %d not found on %s %s — rejecting orphan ledger id",
                ticket,
                direction,
                symbol,
            )
        return resolved

    def _log_position_reconcile(
        self,
        ticket: int,
        intended_volume: float,
        action: str,
        result: dict,
        *,
        symbol: str = "",
        direction: str = "",
        baseline_volume: float | None = None,
    ) -> float:
        after = self._position_volume(ticket)
        remaining = result.get("remaining_volume")
        if remaining is not None:
            after = float(remaining)

        if (
            result.get("status") == "ok"
            and action == "OPEN"
            and after <= VOLUME_EPS
        ):
            for _ in range(FILL_RECOVERY_POLLS):
                time.sleep(FILL_RECOVERY_POLL_SEC)
                after = self._position_volume(ticket)
                if after > VOLUME_EPS:
                    break
            if after <= VOLUME_EPS and symbol and direction:
                current = self._volume_for_symbol_direction(symbol, direction)
                baseline = baseline_volume if baseline_volume is not None else 0.0
                delta = current - baseline
                if delta > VOLUME_EPS:
                    resolved = self._resolve_open_ticket(symbol, direction, ticket)
                    if resolved:
                        ticket = resolved
                        after = self._position_volume(ticket) or delta
                    else:
                        after = delta

        logger.info(
            "Position reconcile ticket=%d action=%s intended_vol=%.4f remaining=%.4f status=%s",
            ticket,
            action,
            intended_volume,
            after,
            result.get("status"),
        )
        if (
            result.get("status") == "ok"
            and action == "OPEN"
            and after > intended_volume + VOLUME_EPS
        ):
            logger.critical(
                "Fill overshoot ticket=%d — intended %.4f lots but position is %.4f lots",
                ticket,
                intended_volume,
                after,
            )
            self._fill_overshoot_block = True
        if (
            result.get("status") == "ok"
            and action == "OPEN"
            and after <= VOLUME_EPS
        ):
            logger.critical(
                "Fill failure ticket=%d — intended %.4f lots but position is %.4f lots",
                ticket,
                intended_volume,
                after,
            )
            self._fill_undershoot_block = True
        elif (
            result.get("status") == "ok"
            and action == "OPEN"
            and 0 < after < intended_volume - VOLUME_EPS
        ):
            logger.warning(
                "Partial fill ticket=%d — intended %.4f lots, got %.4f lots (continuing)",
                ticket,
                intended_volume,
                after,
            )
        if result.get("status") == "ok" and action in ("CLOSE_PARTIAL", "CLOSE") and after >= intended_volume - 1e-6:
            logger.warning("Position reconcile mismatch ticket=%d — volume did not decrease", ticket)
        return after

    def _reduce_with_reconcile(self, ticket: int, volume: float, symbol: str) -> dict:
        before = self._position_volume(ticket)
        if before <= 0:
            return {"status": "error", "message": "Position not found", "confirmed": False}

        def _after_volume(result: dict) -> float:
            after = self._position_volume(ticket)
            remaining = result.get("remaining_volume")
            if remaining is not None:
                after = float(remaining)
            return after

        def _volume_decreased(after: float) -> bool:
            return after < before - VOLUME_EPS

        result = self.connector.reduce_position(ticket, volume, symbol)
        if result.get("status") == "simulated":
            after = _after_volume(result)
            self._log_position_reconcile(ticket, before, "CLOSE_PARTIAL", result)
            result["confirmed"] = True
            result["escalated_to_full"] = False
            result["before_volume"] = before
            result["after_volume"] = after
            return result
        if result.get("status") not in ("ok",):
            logger.warning(
                "Partial reduce failed for ticket %d — deferring: %s",
                ticket,
                result.get("message", result.get("status")),
            )
            result["confirmed"] = False
            result["escalated_to_full"] = False
            result["before_volume"] = before
            result["after_volume"] = before
            return result

        after = _after_volume(result)
        if not _volume_decreased(after) and result.get("status") == "ok":
            for _ in range(3):
                time.sleep(FILL_RECOVERY_POLL_SEC)
                after = self._position_volume(ticket)
                if _volume_decreased(after):
                    break

        self._log_position_reconcile(ticket, before, "CLOSE_PARTIAL", result)
        confirmed = _volume_decreased(after)

        if not confirmed and result.get("status") == "ok" and before > 0:
            specs = self._get_symbol_info(symbol) if symbol else None
            retry_vol = volume
            if specs:
                step = specs.get("volume_step", 0.01)
                if step > 0:
                    retry_vol = math.floor(volume / step) * step
            logger.warning(
                "Partial reduce unconfirmed on ticket %d — retrying %.4f lots",
                ticket,
                retry_vol,
            )
            retry_result = self.connector.reduce_position(ticket, retry_vol, symbol)
            after = _after_volume(retry_result)
            if not _volume_decreased(after):
                for _ in range(3):
                    time.sleep(FILL_RECOVERY_POLL_SEC)
                    after = self._position_volume(ticket)
                    if _volume_decreased(after):
                        break
            self._log_position_reconcile(ticket, before, "CLOSE_PARTIAL", retry_result)
            if _volume_decreased(after):
                result = retry_result
                confirmed = True

        if not confirmed and result.get("status") == "ok" and before > 0:
            logger.warning("Reduce had no effect on ticket %d — escalating to full close", ticket)
            result = self.connector.close_position(ticket)
            after = _after_volume(result)
            self._log_position_reconcile(ticket, before, "CLOSE", result)
            result["escalated_to_full"] = True
            result["confirmed"] = self._close_position_confirmed(ticket, before, result)
            result["before_volume"] = before
            result["after_volume"] = after
            return result

        result["confirmed"] = confirmed
        result["escalated_to_full"] = False
        result["before_volume"] = before
        result["after_volume"] = after
        return result

    def _reduce_worst_losers(self, count: int = 3) -> None:
        positions = self.connector.get_positions()
        losers = sorted(
            [p for p in positions if float(p.get("profit", 0)) < 0],
            key=lambda p: float(p.get("profit", 0)),
        )
        equity = float(self.connector.get_account_info().get("equity", 0) or 0)
        for pos in losers[:count]:
            ticket = pos.get("ticket")
            if not ticket:
                continue
            volume = float(pos.get("volume", 0))
            symbol = str(pos.get("symbol", ""))
            logger.warning("Emergency reduce worst loser ticket %d (%s)", ticket, symbol)
            if volume > 0:
                result = self._reduce_with_reconcile(ticket, volume, symbol)
                if self._close_position_confirmed(ticket, volume, result):
                    self._finalize_trade(
                        ticket, pos, equity, close_reason="emergency_reduce",
                    )
                    self.position_manager.on_close(ticket)
            else:
                result = self.connector.close_position(ticket)
                if self._close_position_confirmed(ticket, volume, result):
                    self._finalize_trade(
                        ticket, pos, equity, close_reason="emergency_reduce",
                    )
                    self.position_manager.on_close(ticket)

    def _is_market_data_stale(self) -> bool:
        stale_sec = self.config.risk.get("margin", {}).get("stale_data_sec", 10)
        max_age_ms = stale_sec * 1000
        from src.data.session_filter import _CRYPTO_SYMBOLS

        check_symbols: list[str] = []
        for symbol in list(_CRYPTO_SYMBOLS) + self.config.active_symbols[:5]:
            if symbol not in check_symbols:
                check_symbols.append(symbol)
        for symbol in check_symbols:
            tick = self.live_feed.get_tick(symbol)
            if tick and tick.tick_age_ms <= max_age_ms:
                return False
        return True

    def _margin_fail_closed(self) -> None:
        self._entries_blocked = True
        self._reduce_largest_position(fraction=0.25)

    def _portfolio_heat_config(self, equity: float) -> dict[str, float | list]:
        risk = self.config.risk
        net_dir = risk.get("net_directional", {})
        conc = risk.get("concentration", {})
        phase_rules = self.config.phase_rules
        return {
            "reference_equity": equity,
            "correlation_threshold": float(risk.get("sizing", {}).get("correlation_threshold", 0.70)),
            "correlation_pairs": risk.get("correlation_pairs", []),
            "cluster_cap": float(conc.get("max_pct", 0.40)),
            "metals_cluster_max_pct": float(conc.get("metals_cluster_max_pct", 0.50)),
            "metals_single_max_pct": float(conc.get("metals_single_max_pct", 0.25)),
            "chf_cluster_max_pct": float(conc.get("chf_cluster_max_pct", 0.35)),
            "net_directional_cap": float(net_dir.get("internal_cap", 0.85)),
            "net_directional_min_gross_pct": float(
                phase_rules.get(
                    "net_directional_enforce_min_gross_pct",
                    net_dir.get("enforce_min_gross_pct", 0.08),
                )
            ),
        }

    def _get_symbol_specs(self, symbol: str) -> dict[str, float] | None:
        info = self._get_symbol_info(symbol)
        if info is None:
            return None
        return {
            "contract_size": info["contract_size"],
            "volume_min": info["volume_min"],
            "volume_step": info["volume_step"],
            "volume_max": info["volume_max"],
        }

    def _prefer_mt5_market_data(self) -> bool:
        """Use MT5 Python API for bars/specs so the ZMQ EA queue stays clear for TRADE."""
        if self.simulation:
            return False
        if isinstance(self.connector, ZeroMQConnector):
            return True
        return os.getenv("OHLCV_PREFER_MT5", "").lower() in ("1", "true", "yes")

    def _get_symbol_info(self, symbol: str) -> dict[str, float] | None:
        cached = self._symbol_info_cache.get(symbol)
        if cached:
            return cached

        if not self.simulation and self._prefer_mt5_market_data():
            info = self._get_symbol_info_mt5(symbol)
            if info:
                return info

        if not self.simulation:
            info = self.connector.get_symbol_info(symbol)
            if info:
                self._symbol_info_cache[symbol] = info
                return info

        return self._get_symbol_info_mt5(symbol)

    def _get_symbol_info_mt5(self, symbol: str) -> dict[str, float] | None:
        try:
            import MetaTrader5 as mt5

            mt5_symbol = self._normalize_symbol(symbol)
            if not mt5.symbol_select(mt5_symbol, True):
                return None
            info = mt5.symbol_info(mt5_symbol)
            if info is None:
                return None
            parsed = {
                "contract_size": float(info.trade_contract_size),
                "volume_min": float(info.volume_min),
                "volume_step": float(info.volume_step),
                "volume_max": float(info.volume_max),
                "digits": float(info.digits),
                "point": float(info.point),
                "stops_level": float(info.trade_stops_level),
            }
            self._symbol_info_cache[symbol] = parsed
            return parsed
        except Exception:
            return None

    def _normalize_price(self, symbol: str, price: float | None) -> float | None:
        if price is None:
            return None
        info = self._get_symbol_info(symbol)
        digits = int(info["digits"]) if info else 5
        return round(price, digits)

    def _sanitize_stops(
        self,
        symbol: str,
        direction: str,
        entry: float,
        sl: float | None,
        tp: float | None,
        atr: float,
    ) -> tuple[float | None, float | None]:
        """Ensure SL/TP are on the correct side of entry and meet broker minimum distance."""
        info = self._get_symbol_info(symbol)
        point = info["point"] if info else 0.0001
        stops_level = info["stops_level"] if info else 0.0
        spread = self._spread_for_symbol(symbol)
        spread_mult = float(self.config.risk.get("sizing", {}).get("spread_buffer_mult", 1.0))
        min_dist = max(stops_level * point, point * 10, atr * 0.25, spread * spread_mult)

        if direction == "BUY":
            if sl is not None and sl >= entry - min_dist:
                sl = entry - max(min_dist, atr * 1.5)
            if tp is not None and tp <= entry + min_dist:
                tp = entry + max(min_dist * 2, atr * 1.5)
        elif direction == "SELL":
            if sl is not None and sl <= entry + min_dist:
                sl = entry + max(min_dist, atr * 1.5)
            if tp is not None and tp >= entry - min_dist:
                tp = entry - max(min_dist * 2, atr * 1.5)

        return self._normalize_price(symbol, sl), self._normalize_price(symbol, tp)

    def _risk_to_lots(
        self,
        symbol: str,
        risk_amount: float,
        entry: float,
        stop_loss: float | None,
        direction: str = "BUY",
    ) -> float:
        specs = self._get_symbol_specs(symbol)
        if specs is None:
            logger.warning("No symbol specs for %s — cannot size trade safely", symbol)
            return 0.0
        spread = self._spread_for_symbol(symbol)
        spread_mult = float(self.config.risk.get("sizing", {}).get("spread_buffer_mult", 1.0))
        effective_sl = stop_loss
        if stop_loss is not None and spread > 0:
            sl_dist = abs(entry - stop_loss) + spread * spread_mult / 2
            if direction.upper() == "BUY":
                effective_sl = entry - sl_dist
            else:
                effective_sl = entry + sl_dist
        return risk_to_lots(
            risk_amount=risk_amount,
            entry=entry,
            stop_loss=effective_sl,
            contract_size=specs["contract_size"],
            volume_min=specs["volume_min"],
            volume_step=specs["volume_step"],
            volume_max=specs["volume_max"],
        )

    def _cap_lots_to_concentration(
        self,
        symbol: str,
        lots: float,
        price: float,
        equity: float,
        open_positions: list[dict],
    ) -> float:
        """Shrink lot size so symbol notional stays within the single-position concentration cap."""
        if lots <= 0 or equity <= 0:
            return lots
        conc = self.config.risk.get("concentration", {})
        if self._is_metal_symbol(symbol):
            conc_max = float(conc.get("metals_single_max_pct", 0.25))
        else:
            conc_max = float(conc.get("max_pct", 0.40))
        specs = self._get_symbol_specs(symbol)
        contract = specs["contract_size"] if specs else 1.0
        volume_step = specs["volume_step"] if specs else 0.01
        volume_min = specs["volume_min"] if specs else volume_step

        cap_notional = equity * conc_max
        target = self._normalize_symbol(symbol)
        existing_on_symbol = 0.0
        for pos in open_positions:
            sym = str(pos.get("symbol", ""))
            if self._normalize_symbol(sym) != target:
                continue
            existing_on_symbol += position_notional_from_dict(pos, self._contract_lookup(sym))

        room = max(cap_notional - existing_on_symbol, 0.0)
        proposed = position_notional(lots, contract, price)
        if proposed <= room:
            return lots
        if room <= 0:
            return 0.0

        target_lots = lots * (room / proposed)
        if volume_step > 0:
            target_lots = math.floor(target_lots / volume_step) * volume_step
        if target_lots < volume_min:
            return 0.0
        return round(target_lots, 8)

    def _account_margin_state(self, account: dict) -> MarginState:
        equity_val = account_equity(account, simulation=self.simulation)
        if equity_val is None:
            equity_val = getattr(self, "_last_equity", None) or getattr(self, "_initial_equity", None)
        equity = float(equity_val if equity_val is not None else account.get("equity", 0) or 0)
        if equity <= 0 and getattr(self, "_last_equity", 0) > 0:
            equity = float(self._last_equity)
        return self.margin_monitor.check(
            equity=equity,
            used_margin=account.get("margin", 0),
            gross_exposure=account.get("gross_exposure", 0),
            largest_position_pct=account.get("largest_position_pct", 0),
            margin_level_pct=account.get("margin_level"),
        )

    def _compliance_metrics(self) -> dict[str, float]:
        account = self.connector.get_account_info()
        positions = self.connector.get_positions()
        margin_state = self._account_margin_state(account)
        equity_val = account_equity(account, simulation=self.simulation)
        equity = float(
            equity_val if equity_val is not None
            else getattr(self, "_last_equity", 0) or account.get("equity", 0) or 0
        )
        gross = float(account.get("gross_exposure", 0) or 0)
        gross_exposure_pct = gross / equity if equity > 0 else 0.0
        return {
            "margin_usage_pct": margin_state.margin_usage_pct,
            "effective_leverage": margin_state.effective_leverage,
            "concentration_pct": margin_state.concentration_pct,
            "net_directional_pct": PortfolioHeat.net_directional_ratio(
                positions, self._contract_lookup,
            ),
            "margin_level_pct": margin_state.margin_level_pct,
            "gross_exposure_pct": gross_exposure_pct,
        }

    def _resolve_initial_equity(self, equity: float) -> float:
        """Competition return baseline: platform ($1M) or session (live equity at start/transition)."""
        baseline_mode = os.getenv("ROUND_EQUITY_BASELINE", "platform").lower()
        if baseline_mode == "session":
            return equity if equity > 0 else getattr(self, "_initial_equity", 1_000_000.0)
        return 1_000_000.0

    def _maybe_refresh_phase(self) -> None:
        """Auto-switch competition phase by BST schedule."""
        if not self._auto_phase:
            return
        resolved = resolve_phase(auto=True)
        if resolved != self.config.current_phase:
            old_phase = self.config.current_phase
            logger.info("Competition phase transition: %s -> %s", old_phase, resolved)

            account = self.connector.get_account_info()
            equity = account_equity(account, simulation=self.simulation) or 0.0
            initial_equity = self._resolve_initial_equity(equity)

            self.compliance_heartbeat.reset_round()
            self.config = QuantAIConfig.load(phase=resolved, auto_phase=True)
            self.memory = LayeredMemory(round_id=self.config.current_phase)
            self.peer_monitor = PeerMonitor(round_id=self.config.current_phase)
            self._rebuild_runtime_for_phase()

            self._initial_equity = initial_equity
            self._peak_equity = equity if equity > 0 else initial_equity
            if equity > 0:
                self.drawdown_guard.reset(equity)
            self.sharpe_guard.reset_round(equity if equity > 0 else initial_equity)
            self.sharpe_guard.set_phase(resolved)
            self._symbol_cooldown_until.clear()
            self._momentum_flags.clear()
            self._pending_limit_orders.clear()
            self._prev_dd_tier = "normal"
            self._apply_phase_filter_pack(resolved)
            self._live_filters = self._merge_objective_filters(
                self._load_live_competition_filters(resolved),
            )
            self._sync_finals_loss_limits()
            self._close_positions_on_blocked_symbols()

            self.trade_logger.log(
                symbol="*",
                regime="",
                session="",
                direction="HOLD",
                confidence=0.0,
                status="phase_transition",
                reasoning=f"Phase transition {old_phase} -> {resolved}",
                extra={
                    "from_phase": old_phase,
                    "to_phase": resolved,
                    "initial_equity": initial_equity,
                    "equity": equity,
                },
            )

    def _handle_compliance_actions(self, actions: list[str]) -> None:
        if "EMERGENCY_CLOSE_ALL" in actions:
            logger.critical("ComplianceHeartbeat: EMERGENCY_CLOSE_ALL")
            self._sync_risk_event("EMERGENCY_CLOSE_ALL", "Compliance heartbeat triggered emergency close", "critical", actions)
            self.connector.close_all()
        elif "REDUCE_MARGIN" in actions:
            logger.warning("ComplianceHeartbeat: REDUCE_MARGIN — closing 50% of largest position")
            self._sync_risk_event("REDUCE_MARGIN", "Sustained margin violation", "warning", actions)
            self._reduce_largest_position(fraction=0.5)
        elif "REDUCE_LEVERAGE" in actions:
            logger.warning("ComplianceHeartbeat: REDUCE_LEVERAGE — closing 25% of largest position")
            self._reduce_largest_position(fraction=0.25)
        elif "REDUCE_CONCENTRATION" in actions:
            logger.warning("ComplianceHeartbeat: REDUCE_CONCENTRATION — closing 25% of largest position")
            self._reduce_largest_position(fraction=0.25)
        elif "REDUCE_DIRECTIONAL" in actions:
            logger.warning("ComplianceHeartbeat: REDUCE_DIRECTIONAL — closing 25% of dominant-side position")
            self._reduce_dominant_side_position(fraction=0.25)
        self._publish_state()

    def _reduce_dominant_side_position(self, fraction: float = 0.25) -> None:
        positions = self.connector.get_positions()
        if not positions:
            return
        long_notional = 0.0
        short_notional = 0.0
        for pos in positions:
            notional = self._position_notional_value(pos)
            direction = str(pos.get("type", "BUY")).upper()
            is_long = "BUY" in direction or direction in ("LONG", "0")
            if is_long:
                long_notional += notional
            else:
                short_notional += notional
        dominant_long = long_notional >= short_notional
        candidates = [
            p for p in positions
            if ("BUY" in str(p.get("type", "")).upper() or str(p.get("type", "")).upper() in ("LONG", "0"))
            == dominant_long
        ]
        if not candidates:
            return
        target = max(candidates, key=self._position_notional_value)
        ticket = target.get("ticket")
        volume = float(target.get("volume", 0))
        symbol = str(target.get("symbol", ""))
        if not ticket or volume <= 0:
            return
        close_vol = max(volume * fraction, 0.01)
        if close_vol >= volume:
            result = self.connector.close_position(ticket)
            self._log_position_reconcile(ticket, volume, "CLOSE", result)
        else:
            before_vol = volume
            result = self._reduce_with_reconcile(ticket, close_vol, symbol)
            self._log_partial_close_if_confirmed(
                ticket, symbol, target, result, before_vol, "margin_reduce_dominant",
            )

    def _reduce_largest_position(self, fraction: float = 0.5) -> None:
        positions = self.connector.get_positions()
        if not positions:
            return
        equity = self.connector.get_account_info().get("equity", 1)
        largest = max(positions, key=self._position_notional_value)
        ticket = largest.get("ticket")
        volume = float(largest.get("volume", 0))
        if not ticket or volume <= 0:
            return
        close_vol = max(volume * fraction, 0.01)
        symbol = str(largest.get("symbol", ""))
        if close_vol >= volume:
            result = self.connector.close_position(ticket)
            self._log_position_reconcile(ticket, volume, "CLOSE", result)
            account = self.connector.get_account_info()
            equity = float(account.get("equity", 0) or 0)
            if self._close_position_confirmed(ticket, volume, result):
                self._finalize_trade(ticket, largest, equity)
                self.position_manager.on_close(ticket)
        else:
            before_vol = volume
            result = self._reduce_with_reconcile(ticket, close_vol, symbol)
            self._log_partial_close_if_confirmed(
                ticket, symbol, largest, result, before_vol, "margin_reduce_largest",
            )
            if result.get("escalated_to_full") and self._close_position_confirmed(
                ticket, before_vol, result,
            ):
                account = self.connector.get_account_info()
                equity = float(account.get("equity", 0) or 0)
                self._finalize_trade(ticket, largest, equity)
                self.position_manager.on_close(ticket)

    def _position_deal_profit(self, ticket: int) -> float:
        try:
            import MetaTrader5 as mt5

            deals = mt5.history_deals_get(position=ticket)
            if deals:
                return sum(float(getattr(d, "profit", 0) or 0) for d in deals)
        except Exception:
            pass
        return 0.0

    def _resolve_exit_price(self, ticket: int, pos: dict) -> float:
        current = pos.get("price_current")
        if current:
            return float(current)
        try:
            import MetaTrader5 as mt5

            deals = mt5.history_deals_get(position=ticket)
            if deals:
                return float(deals[-1].price)
        except Exception:
            pass
        profit = float(pos.get("profit", 0))
        entry = float(pos.get("price_open", 0))
        volume = float(pos.get("volume", 0))
        symbol = pos.get("symbol", "")
        specs = self._get_symbol_specs(symbol)
        contract = specs["contract_size"] if specs else 1.0
        direction = str(pos.get("type", pos.get("direction", "BUY"))).upper()
        if volume > 0 and contract > 0 and entry > 0 and profit != 0:
            price_delta = profit / (volume * contract)
            if direction in ("BUY", "0", "LONG"):
                return entry + price_delta
            return entry - price_delta
        return entry

    def _close_position_confirmed(self, ticket: int, before_volume: float, result: dict) -> bool:
        if result.get("status") not in ("ok", "simulated"):
            return False
        remaining = result.get("remaining_volume")
        if remaining is not None:
            return float(remaining) < before_volume - 1e-6
        for pos in self.connector.get_positions():
            if pos.get("ticket") == ticket:
                return float(pos.get("volume", 0)) < before_volume - 1e-6
        return True

    def _recover_tracked_context(self, ticket: int) -> dict | None:
        jsonl_ctx = context_from_jsonl(ticket, self.trade_logger.jsonl_path)
        tracked = build_tracked_from_mt5_deals(ticket, jsonl_context=jsonl_ctx)
        if tracked:
            return tracked
        return jsonl_ctx or None

    def _minimal_tracked_context(self, ticket: int, pos: dict) -> dict | None:
        """Last-resort ledger context from MT5 deal profit when full recovery fails."""
        symbol = display_symbol(str(pos.get("symbol", "")))
        if not symbol:
            symbol = "UNKNOWN"
        direction = str(pos.get("type", pos.get("direction", "BUY"))).upper()
        entry_price = float(pos.get("price_open", 0) or 0)
        if entry_price <= 0:
            ctx = build_tracked_from_mt5_deals(ticket)
            if ctx:
                return ctx
        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "sl": pos.get("sl"),
            "session": "unknown",
            "regime": "unknown",
            "agent": "recovered",
            "features_snapshot": {},
            "agent_votes": [],
            "attribution_json": {},
            "reasoning": "Minimal finalize from MT5 deal history",
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "volume": float(pos.get("volume", 0) or 0),
        }

    def _scan_mt5_closed_deals_for_journal(self, equity: float) -> None:
        if self.simulation:
            return
        open_tickets = {
            int(p["ticket"])
            for p in self.connector.get_positions()
            if p.get("ticket")
        }
        since = datetime.now(timezone.utc) - timedelta(days=7)
        orphans = mt5_closed_tickets(
            since=since,
            open_tickets=open_tickets,
            finalized_tickets=self._finalized_tickets,
        )
        for item in orphans:
            ticket = int(item["ticket"])
            logger.warning(
                "Journal backfill: closed MT5 ticket %d (%s) missing from ledger",
                ticket,
                item.get("symbol", ""),
            )
            pos = {
                "profit": item.get("profit", 0),
                "symbol": item.get("symbol", ""),
                "price_current": item.get("exit_price"),
            }
            self._finalize_trade(ticket, pos, equity)

    def _maybe_reset_stale_peak(self, equity: float) -> None:
        """Reset inflated peak equity after sim→live switches or profile mismatches."""
        peak = self.drawdown_guard.peak_equity
        if peak <= 0 or equity <= 0:
            return

        ratio = peak / equity
        implied_dd = (peak - equity) / peak
        should_reset = False
        reason = ""

        if ratio > 10 and implied_dd >= 0.50:
            should_reset = True
            reason = f"peak/equity={ratio:.1f} implied_dd={implied_dd:.1%}"
        elif self.account_profile and self.account_profile.kind == "micro":
            bound = max(equity * 2, 1000)
            if peak > bound:
                should_reset = True
                reason = f"micro account peak={peak:.2f} exceeds bound={bound:.2f}"

        if should_reset:
            logger.warning(
                "PEAK_EQUITY_RESET: %s — resetting peak from %.2f to %.2f",
                reason,
                peak,
                equity,
            )
            self.drawdown_guard.reset(equity)
            self._peak_equity = equity
            self._initial_equity = equity

    def _sync_risk_event(
        self,
        event_type: str,
        message: str,
        severity: str = "warning",
        extra: list[str] | None = None,
    ) -> None:
        try:
            from src.integrations.notion_sync import get_notion_sync

            get_notion_sync().sync_risk_event(event_type, message, severity, extra={"actions": extra or []})
        except Exception:
            logger.debug("Notion risk sync skipped", exc_info=True)

    def _publish_state(self, cycle_start: datetime | None = None) -> None:
        account = self.connector.get_account_info()
        equity_raw = account_equity(account, simulation=self.simulation)
        account_stale = False
        if equity_raw is not None:
            self._last_known_equity = equity_raw
            equity = equity_raw
        elif self._last_known_equity is not None:
            equity = self._last_known_equity
            account_stale = True
        else:
            equity = 0.0
            account_stale = True
        if equity_raw is not None:
            dd_state = self.drawdown_guard.update(equity)
        elif equity > 0:
            dd_state = self.drawdown_guard.update(equity)
        else:
            dd_state = DrawdownState(
                tier=self.drawdown_guard.current_tier,
                size_multiplier=0.0,
                allow_new_trades=False,
                allow_crypto=False,
                message="Equity unavailable",
            )
        drawdown_pct = (
            (self.drawdown_guard.peak_equity - equity) / max(self.drawdown_guard.peak_equity, 1)
            if equity > 0
            else 0.0
        )
        margin_state = self._account_margin_state(account)
        positions = self.connector.get_positions()
        net_directional = PortfolioHeat.net_directional_ratio(positions, self._contract_lookup)
        compliance = self.compliance_heartbeat.state
        now = datetime.now(timezone.utc)

        if dd_state.tier != self._prev_dd_tier:
            self._sync_risk_event(
                "DRAWDOWN_TIER_CHANGE",
                f"Tier changed from {self._prev_dd_tier} to {dd_state.tier}",
                "critical" if dd_state.tier in ("critical", "emergency") else "warning",
                extra=[dd_state.tier],
            )
            self._prev_dd_tier = dd_state.tier

        next_cycle_at = None
        if cycle_start is not None:
            from datetime import timedelta

            self._last_cycle_at = cycle_start.isoformat()
            self._next_cycle_at = (
                cycle_start + timedelta(minutes=self._cycle_minutes)
            ).isoformat()
            next_cycle_at = self._next_cycle_at
        elif self._next_cycle_at:
            next_cycle_at = self._next_cycle_at

        mt5_connected = self.connector.is_connected and not self.simulation
        zmq_error = self.connector.last_error if not self.simulation else ""
        snapshot = {
            "phase": self.config.current_phase,
            "mode": "simulate" if self.simulation else "live",
            "timestamp": now.isoformat(),
            "last_cycle_at": self._last_cycle_at,
            "next_cycle_at": next_cycle_at,
            "connected": self._running and (self.simulation or mt5_connected),
            "engine_running": self._running,
            "engine_paused": self._paused,
            "cycle_in_progress": self._cycle_in_progress,
            "mt5_connected": mt5_connected,
            "zmq_last_error": zmq_error,
            "account_profile": self.account_profile.kind if self.account_profile else None,
            "account": {
                "equity": equity if equity > 0 else None,
                "balance": account.get("balance") if equity_raw is not None else None,
                "margin": account.get("margin", 0),
                "free_margin": account.get("free_margin"),
                "gross_exposure": account.get("gross_exposure", 0),
                "margin_level": account.get("margin_level"),
                "initial_equity": getattr(self, "_initial_equity", equity if equity > 0 else None),
                "equity_available": equity_raw is not None,
                "account_stale": account_stale,
            },
            "positions": positions,
            "risk": {
                "dd_tier": dd_state.tier,
                "drawdown_pct": drawdown_pct,
                "sharpe": self.sharpe_guard.compute_running_sharpe(),
                "discipline": compliance.risk_discipline_score,
                "margin": {
                    "margin_usage_pct": margin_state.margin_usage_pct,
                    "effective_leverage": margin_state.effective_leverage,
                    "concentration_pct": margin_state.concentration_pct,
                    "margin_level_pct": margin_state.margin_level_pct,
                    "net_directional_pct": net_directional,
                    "action": margin_state.action,
                },
                "violations": compliance.active_violations,
                "compliance_review": compliance.compliance_review,
            },
            "last_cycle": {
                "symbols_processed": len(self._cycle_decisions),
                "symbols_attempted": self._cycle_symbols_attempted,
                "decisions": self._cycle_decisions,
                "agent_votes": self._cycle_votes,
                "skip_summary": self._cycle_skip_summary(),
                "cycle_events": self._cycle_events,
            },
            "position_monitor": self._position_diagnostics,
            "instruments": self._build_instruments_state(),
            "market": {
                "last_tick_at": now.isoformat(),
                "last_tick_age_ms": self.live_feed.youngest_tick_age_ms(),
            },
            "intelligence": self.intelligence.snapshot() if self.intelligence.enabled else {"enabled": False},
            "engine_config": {
                "cycle_minutes": self._cycle_minutes,
                "session_symbol_filter": getattr(
                    getattr(self, "session_filter", None), "symbol_filter_enabled", None
                ),
                "round_equity_baseline": os.getenv("ROUND_EQUITY_BASELINE", "platform").lower(),
                "risk_multiplier": self.config.phase_multiplier,
                "max_new_entries_per_cycle": self.config.phase_rules.get("max_new_entries_per_cycle"),
                "bridge": connector_bridge_type(self.connector),
                "blocked_symbols": sorted(
                    set(self.config.phase_rules.get("blocked_symbols", []))
                    | set(getattr(self, "_live_filters", {}).get("blocked_symbols", [])),
                ),
            },
        }
        self.state_publisher.publish(snapshot)

    def _build_instruments_state(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for symbol in self.config.active_symbols:
            regime = self._instrument_regimes.get(symbol, "unknown")
            tick = self.live_feed.get_tick(symbol)
            sentiment = self.intelligence.get_sentiment(symbol) if self.intelligence.enabled else None
            ohlcv = self._ohlcv_meta.get(symbol, {})
            last_close = ohlcv.get("last_close")
            tick_mid = tick.mid if tick else None
            market_health = "red"
            if tick and tick.tick_age_ms < 2000:
                market_health = "green"
            elif tick and tick.tick_age_ms < 5000:
                market_health = "amber"
            elif last_close is not None:
                market_health = "amber"
            out[symbol] = {
                "last_regime": regime,
                "session_active": self.session_filter.should_trade_symbol(symbol),
                "bid": tick.bid if tick else None,
                "ask": tick.ask if tick else None,
                "mid": tick_mid,
                "spread": tick.spread if tick else None,
                "tick_age_ms": tick.tick_age_ms if tick else None,
                "health": market_health,
                "market_health": market_health,
                "last_close": last_close,
                "change_pct": ohlcv.get("change_pct"),
                "bar_age_sec": ohlcv.get("bar_age_sec"),
                "sentiment_score": sentiment.score if sentiment else None,
                "sentiment_confidence": sentiment.confidence if sentiment else None,
                "sentiment_summary": sentiment.summary if sentiment else None,
                "ohlcv_source": ohlcv.get("source"),
            }
        return out

    def _cycle_skip_summary(self) -> dict[str, int]:
        """Aggregate skip reasons from the current cycle for dashboard visibility."""
        summary: dict[str, int] = {}
        for decision in self._cycle_decisions:
            if decision.get("status") != "skipped":
                continue
            reason = str(decision.get("skip_reason") or decision.get("reasoning") or "Unknown")
            if reason.startswith("Live filter:"):
                key = "Live filter"
            elif reason.startswith("Net directional"):
                key = "Net directional"
            elif "Insufficient OHLCV" in reason:
                key = "Insufficient OHLCV"
            elif reason.startswith("Session inactive"):
                key = "Session inactive"
            elif "Open position already exists" in reason:
                key = "Open position"
            elif "Symbol cooldown" in reason:
                key = "Symbol cooldown"
            elif reason == "HOLD decision":
                key = "HOLD decision"
            else:
                key = reason.split("(")[0].split(":")[0].strip() or "Other"
            summary[key] = summary.get(key, 0) + 1
        return summary

    def _record_cycle_skip(
        self,
        symbol: str,
        skip_reason: str,
        session_name: str = "",
        regime: str = "unknown",
        reasoning: str = "",
        scan_stage: str = "blocked",
        **extra: Any,
    ) -> None:
        self._cycle_decisions.append({
            "symbol": symbol,
            "direction": "HOLD",
            "confidence": 0.0,
            "regime": regime,
            "session": session_name,
            "reasoning": reasoning or skip_reason,
            "agent_votes": extra.pop("agent_votes", []),
            "status": "skipped",
            "skip_reason": skip_reason,
            "scan_stage": scan_stage,
            **extra,
        })

    @staticmethod
    def _bar_timestamp_from_df(df: pd.DataFrame) -> datetime | None:
        if df is None or df.empty:
            return None
        if "timestamp" not in df.columns:
            return None
        raw = df["timestamp"].iloc[-1]
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        if hasattr(raw, "to_pydatetime"):
            ts = raw.to_pydatetime()
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts
        return None

    def _update_ohlcv_meta(self, symbol: str, df: pd.DataFrame | None) -> None:
        if df is None or len(df) < 2:
            return
        close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
        bar_ts = self._bar_timestamp_from_df(df)
        self._ohlcv_meta[symbol] = {
            "last_close": close,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "bar_timestamp": bar_ts.isoformat() if bar_ts else None,
            "bar_count": len(df),
            "source": self._ohlcv_source.get(symbol, "unknown"),
        }

    def _refresh_ohlcv_meta_all_symbols(self) -> None:
        """Refresh bar metadata for every active symbol (including skipped ones)."""
        if self.simulation:
            return
        for symbol in self.config.active_symbols:
            m15_df = self._get_ohlcv(symbol, "M15")
            self._update_ohlcv_meta(symbol, m15_df)
            if m15_df is not None and len(m15_df) >= 2:
                bar_ts = self._bar_timestamp_from_df(m15_df)
                if bar_ts is not None:
                    bar_age = max(
                        0.0,
                        (datetime.now(timezone.utc) - bar_ts).total_seconds(),
                    )
                    self._ohlcv_meta.setdefault(symbol, {})["bar_age_sec"] = bar_age

    def _net_directional_balance_context(self) -> tuple[bool, bool]:
        """Return (should_balance, dominant_side_is_long) when net exposure is one-sided."""
        positions = self.connector.get_positions()
        if not positions:
            return False, False
        net_pct = PortfolioHeat.net_directional_ratio(positions, self._contract_lookup)
        cap = float(self.config.phase_rules.get("net_directional_cap", 0.85))
        min_gross_pct = float(
            self.config.phase_rules.get("net_directional_enforce_min_gross_pct", 0.20),
        )
        account = self.connector.get_account_info()
        equity_val = account_equity(account, simulation=self.simulation)
        equity = float(equity_val if equity_val is not None else getattr(self, "_last_equity", 0) or 0)
        gross = float(account.get("gross_exposure", 0) or 0)
        gross_pct = gross / equity if equity > 0 else 0.0
        extreme_net = net_pct >= 0.95
        if net_pct <= cap:
            return False, False
        if equity <= 0:
            return False, False
        if gross_pct < min_gross_pct:
            return False, False
        if not extreme_net:
            return False, False
        long_notional = 0.0
        short_notional = 0.0
        for pos in positions:
            notional = self._position_notional_value(pos)
            direction = str(pos.get("type", "BUY")).upper()
            is_long = "BUY" in direction or direction in ("LONG", "0")
            if is_long:
                long_notional += notional
            else:
                short_notional += notional
        return True, long_notional >= short_notional

    def _balancing_direction(self) -> str | None:
        """Direction that reduces net directional imbalance, if balancing is active."""
        should_balance, dominant_long = self._net_directional_balance_context()
        if not should_balance:
            return None
        return "SELL" if dominant_long else "BUY"

    def run_cycle(self) -> bool:
        """Execute one decision cycle across all active symbols."""
        if not self._cycle_lock.acquire(blocking=False):
            logger.info("Cycle already in progress — skipping")
            return False
        try:
            self._run_cycle_body()
            return True
        finally:
            self._cycle_lock.release()

    @instrument_span("quantai.run_cycle")
    def _run_cycle_body(self) -> None:
        cycle_start = datetime.now(timezone.utc)
        self._cycle_decisions = []
        self._cycle_votes = []
        self._cycle_events = []
        self._position_diagnostics = []
        self._cycle_symbols_attempted = 0
        self._cycle_diag_equity = None
        self._cycle_diag_dd_state = None
        self._cycle_diag_drawdown_pct = 0.0
        self._fx_shorts_opened_this_cycle = 0
        self._chf_entries_opened_this_cycle = 0
        self._crypto_entries_opened_this_cycle = 0
        self._runner_entries_opened_this_cycle = 0
        self._aa_plus_entries_opened_this_cycle = 0
        self._cycle_in_progress = True
        try:
            if not self.compliance.record_api_request():
                logger.warning("API rate limit approached — skipping cycle")
                return

            self._maybe_refresh_phase()
            self._reload_phase_playbook()
            self._live_filters = self._merge_objective_filters(
                self._load_live_competition_filters(self.config.current_phase),
            )
            self._sync_finals_loss_limits()
            self._sync_position_manager_config()
            if not self.simulation:
                self._refresh_ohlcv_meta_all_symbols()

            if not self.simulation:
                pos_snap = self._positions_snapshot()
                if pos_snap.trusted and not pos_snap.positions:
                    if self._fill_undershoot_block or self._fill_overshoot_block:
                        logger.info("Flat book — clearing fill reconcile entry block")
                    self._fill_undershoot_block = False
                    self._fill_overshoot_block = False

            account = self.connector.get_account_info()
            equity = account_equity(account, simulation=self.simulation)
            entries_allowed = True
            equity_read_ok = equity is not None
            if not self.simulation and not account.get("trade_allowed", True):
                logger.warning("MT5 trade_allowed=false — sync/monitor only, no new entries")
                entries_allowed = False
            if equity is None:
                logger.error("Cannot read account equity — skipping new entries")
                self.connector._last_error = account.get("message", "Account equity unavailable")
                entries_allowed = False
                equity = max(
                    self.drawdown_guard.peak_equity,
                    getattr(self, "_initial_equity", 0.0),
                    0.01,
                )
            else:
                self._last_equity = equity
                if self._entries_blocked:
                    logger.info("Account equity restored — clearing fail-closed entry block")
                    self._entries_blocked = False
            dd_state = self.drawdown_guard.update(equity)
            drawdown_pct = (self.drawdown_guard.peak_equity - equity) / max(self.drawdown_guard.peak_equity, 1)
            self._cycle_diag_equity = equity
            self._cycle_diag_dd_state = dd_state
            self._cycle_diag_drawdown_pct = drawdown_pct

            if equity > self._peak_equity:
                self._peak_equity = equity
            self.sharpe_guard.set_phase(self.config.current_phase)
            self.sharpe_guard.record_equity(equity)
            self._apply_sharpe_guard_closes(equity)

            if dd_state.tier == "warning" and self._prev_dd_tier != "warning" and equity_read_ok:
                logger.warning("Drawdown warning tier — proactive 15%% reduce of largest position")
                self._reduce_largest_position(fraction=0.15)

            if dd_state.tier == "emergency" and equity_read_ok:
                logger.critical("EMERGENCY: %s — closing all positions", dd_state.message)
                self._sync_risk_event("EMERGENCY_DRAWDOWN", dd_state.message, "critical")
                self.connector.close_all()
                return

            margin_state = self._account_margin_state(account)
            self.account_profile = detect_profile(equity)

            if margin_state.stop_out_risk and margin_state.margin_level_pct <= self.config.risk.get("margin", {}).get("stop_out_emergency_pct", 40):
                logger.critical(
                    "STOP-OUT RISK: margin level %.0f%% — reducing exposure before platform liquidation",
                    margin_state.margin_level_pct,
                )
                self._sync_risk_event(
                    "STOP_OUT_RISK",
                    f"Margin level {margin_state.margin_level_pct:.0f}% approaching 30% stop-out",
                    "critical",
                )
                self._reduce_worst_losers(3)

            conc_max = self.config.risk.get("concentration", {}).get("max_pct", 0.40)
            if (
                self.account_profile.kind == "micro"
                and margin_state.block_new_trades
                and margin_state.concentration_pct >= conc_max
            ):
                target_pct = 0.35
                current = margin_state.concentration_pct
                if current > target_pct:
                    fraction = max(0.01, min(0.99, 1.0 - target_pct / current))
                    logger.warning(
                        "Micro auto-deconcentrate: %.0f%% -> target ~%.0f%%, closing %.0f%% of largest position",
                        current * 100,
                        target_pct * 100,
                        fraction * 100,
                    )
                    self._sync_risk_event(
                        "REDUCE_CONCENTRATION",
                        f"Micro profile auto-deconcentration: {current:.0%} -> ~{target_pct:.0%}",
                        "warning",
                        [f"fraction={fraction:.2f}"],
                    )
                    self._reduce_largest_position(fraction=fraction)
                    account = self.connector.get_account_info()
                    equity = account.get("equity", equity)
                    margin_state = self._account_margin_state(account)

            if margin_state.action != "normal":
                logger.warning("Margin: %s", margin_state.message)
                self.state_publisher.publish_risk_event(
                    "margin",
                    margin_state.message,
                    "warning",
                    {"margin_state": margin_state.action, "margin_usage_pct": margin_state.margin_usage_pct},
                )

            if margin_state.close_worst_loser or margin_state.action.startswith("EMERGENCY"):
                self._reduce_worst_losers(3)
            elif margin_state.reduce_positions_pct > 0:
                self._reduce_largest_position(fraction=margin_state.reduce_positions_pct)

            self._sync_open_trades_from_mt5()
            self._reconcile_open_trades_with_mt5(equity)
            self._scan_mt5_closed_deals_for_journal(equity)
            self._close_positions_on_blocked_symbols()
            self._close_stub_positions_for_resize()
            self._manage_positions(equity, dd_state, margin_state)
            self._apply_sharpe_guard_closes(equity)

            peer_adj = 1.0
            peer_sentiment = "mixed"
            peer_data = self._build_peer_data(equity)
            peer_unavailable = peer_data is not None and peer_data.get("peer_count", 0) == 0
            if peer_data:
                peer_snapshot = self.peer_monitor.update(peer_data)
                catch_up = self.peer_monitor.catch_up_multiplier(dd_state.tier)
                peer_adj = self.peer_monitor.sizing_adjustment() * catch_up
                peer_sentiment = peer_snapshot.crowd_bias
                if peer_unavailable:
                    peer_adj = min(peer_adj, 1.0)

            if self.intelligence.enabled:
                self.intelligence.refresh(self.config.active_symbols)
                self.intelligence.persist_snapshot()

            if self._paused:
                logger.info("Engine paused — managing exits only, no new entries")
                self._record_cycle_skip("*", "Engine paused — no new entries")
            elif entries_allowed and not self._entries_blocked:
                loss_blocked, loss_reason = self._finals_loss_guard_blocks_entries()
                if loss_blocked:
                    logger.warning("%s", loss_reason)
                    self._record_cycle_skip("*", loss_reason)
                if not loss_blocked:
                    if not self.simulation:
                        self.live_feed._mt5_tick_fallback()
                    session = self.session_filter.current_session()
                    pos_snapshot = self._positions_snapshot()
                    if not self.simulation and not pos_snapshot.trusted:
                        logger.warning("Positions unavailable — skipping new entries this cycle (fail-closed)")
                        self._record_cycle_skip("*", "Position state unavailable (fail-closed)")
                    elif self._fill_overshoot_block and not self.simulation:
                        logger.warning("Fill overshoot block active — skipping new entries this cycle")
                        self._record_cycle_skip("*", "Prior fill overshoot — entries blocked")
                    elif self._fill_undershoot_block and not self.simulation:
                        logger.warning("Fill undershoot block active — skipping new entries this cycle")
                        self._record_cycle_skip("*", "Prior fill undershoot — entries blocked")
                    else:
                        open_positions = pos_snapshot.positions
                        phase_rules = self.config.phase_rules
                        blocked_symbols = set(self._live_filters.get("blocked_symbols", [])) | set(
                            phase_rules.get("blocked_symbols", []),
                        )
                        obj_overrides = self._objective_runtime_overrides()
                        max_new = int(
                            self._live_filters.get("max_new_entries_per_cycle")
                            or phase_rules.get("max_new_entries_per_cycle")
                            or obj_overrides["max_entries"]
                        )
                        entries_opened = 0
                        session_agents = (
                            None
                            if phase_rules.get("ignore_session_agents")
                            else session.preferred_agents
                        )
                        now_utc = datetime.now(timezone.utc)

                        candidates: list[str] = []
                        for symbol in self.config.active_symbols:
                            self._cycle_symbols_attempted += 1
                            if symbol in blocked_symbols:
                                self._record_cycle_skip(
                                    symbol,
                                    f"Blocked symbol {symbol}",
                                    session.name,
                                )
                                continue
                            if not self.session_filter.should_trade_symbol(symbol):
                                logger.debug("Session filter skip: %s (session=%s)", symbol, session.name)
                                self._record_cycle_skip(
                                    symbol,
                                    f"Session inactive ({session.name})",
                                    session.name,
                                )
                                continue
                            cooldown_until = self._symbol_cooldown_until.get(symbol)
                            if cooldown_until and now_utc < cooldown_until:
                                mins_left = (cooldown_until - now_utc).total_seconds() / 60
                                self._record_cycle_skip(
                                    symbol,
                                    f"Symbol cooldown ({mins_left:.0f}m remaining)",
                                    session.name,
                                )
                                continue
                            if cooldown_until and now_utc >= cooldown_until:
                                del self._symbol_cooldown_until[symbol]
                            if self._symbol_has_position(symbol, open_positions):
                                logger.debug("Skip %s — position already open", symbol)
                                self._record_cycle_skip(
                                    symbol,
                                    "Open position already exists",
                                    session.name,
                                )
                                continue
                            candidates.append(symbol)

                        if phase_rules.get("prioritize_by_opportunity", False) and len(candidates) > 1:
                            opp_scores = {s: self._quick_opportunity_score(s) for s in candidates}
                            prefer = self._live_filters.get("prefer_symbols") or []
                            prefer_rank = {sym: len(prefer) - i for i, sym in enumerate(prefer)}
                            candidates.sort(
                                key=lambda s: (
                                    1 if self._momentum_flag_active(s, now_utc) else 0,
                                    prefer_rank.get(s, 0),
                                    opp_scores[s],
                                ),
                                reverse=True,
                            )
                            logger.info(
                                "Opportunity rank (top 5): %s",
                                ", ".join(
                                    f"{s}={opp_scores[s]:.2f}"
                                    for s in candidates[:5]
                                ),
                            )

                        for symbol in candidates:
                            if entries_opened >= max_new:
                                logger.info(
                                    "Max new entries per cycle reached (%d) — remaining symbols deferred",
                                    max_new,
                                )
                                break
                            max_crypto = self._live_filters.get("max_crypto_entries_per_cycle")
                            if (
                                max_crypto is not None
                                and self._is_crypto_symbol(symbol)
                                and self._crypto_entries_opened_this_cycle >= int(max_crypto)
                            ):
                                self._record_cycle_skip(
                                    symbol,
                                    f"Max crypto entries per cycle ({max_crypto})",
                                    session.name,
                                )
                                continue
                            opened = self._process_symbol(
                                symbol, equity, dd_state, margin_state, session.name, drawdown_pct,
                                peer_adj=peer_adj, peer_sentiment=peer_sentiment,
                                preferred_agents=session_agents,
                                peer_conservative=peer_unavailable,
                            )
                            if opened:
                                entries_opened += 1
                                open_positions = self._positions_snapshot().positions
                                account = self.connector.get_account_info()
                                eq_val = account_equity(account, simulation=self.simulation)
                                if eq_val is not None:
                                    equity = eq_val
                                    margin_state = self._account_margin_state(account)
        finally:
            self._cycle_in_progress = False
            if self._cycle_diag_dd_state is not None and self._cycle_diag_equity is not None:
                self._write_cycle_diagnostics(
                    cycle_start,
                    self._cycle_diag_equity,
                    self._cycle_diag_dd_state,
                    self._cycle_diag_drawdown_pct,
                )
            self._publish_state(cycle_start)

    def _apply_sharpe_guard_closes(self, equity: float) -> None:
        phase_rules = self.config.phase_rules
        if not phase_rules.get("sharpe_guard_enabled", True):
            return
        positions = self.connector.get_positions()
        if not positions:
            return

        min_r = phase_rules.get("sharpe_guard_min_r_to_close")

        def _pnl_pct(pos: dict) -> float:
            symbol = str(pos.get("symbol", ""))
            specs = self._get_symbol_specs(symbol)
            contract = specs["contract_size"] if specs else 1.0
            return pnl_pct(
                float(pos.get("profit", 0)),
                float(pos.get("volume", 0)),
                float(pos.get("price_open", 0)),
                contract,
            )

        for ticket in self.sharpe_guard.evaluate(positions, equity, _pnl_pct):
            pos = next((p for p in positions if p.get("ticket") == ticket), {})
            if min_r is not None:
                r_mult = self._position_r_multiple(int(ticket), pos)
                if r_mult is not None and r_mult > float(min_r):
                    logger.debug(
                        "SharpeGuard skip ticket %d: r=%.2f above min_r=%.2f",
                        ticket, r_mult, min_r,
                    )
                    continue
            logger.info("SharpeGuard closing ticket %d", ticket)
            before_vol = float(pos.get("volume", 0))
            result = self.connector.close_position(ticket)
            self._log_position_reconcile(ticket, before_vol, "CLOSE", result)
            if self._close_position_confirmed(ticket, before_vol, result):
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)

    def _close_worst_loser(self, equity: float) -> None:
        self._reduce_worst_losers(1)

    def _current_price(self, symbol: str) -> float | None:
        tick = self.live_feed.get_tick(symbol)
        if tick:
            return tick.mid
        positions = self.connector.get_positions()
        for pos in positions:
            if self._normalize_symbol(str(pos.get("symbol", ""))) == self._normalize_symbol(symbol):
                current = pos.get("price_current")
                if current:
                    return float(current)
        return None

    def _mock_peer_data(self, our_return: float) -> dict:
        return {
            "peer_count": 100,
            "avg_return": 0.02,
            "avg_drawdown": 0.04,
            "top_performer_return": 0.06,
            "our_return": our_return,
            "our_rank": 55,
        }

    def _neutral_peer_data(self, our_return: float) -> dict:
        return {
            "peer_count": 0,
            "avg_return": 0.0,
            "avg_drawdown": 0.0,
            "top_performer_return": 0.0,
            "our_return": our_return,
            "our_rank": 0,
        }

    def _peer_monitor_fallback(self, our_return: float) -> dict:
        mode = os.getenv("PEER_MONITOR_FALLBACK", "neutral").strip().lower()
        if mode == "mock":
            return self._mock_peer_data(our_return)
        return self._neutral_peer_data(our_return)

    def _build_peer_data(self, equity: float) -> dict | None:
        """Build peer leaderboard payload from env API or simulation defaults."""
        import json
        import urllib.error
        import urllib.request

        our_return = (equity - self._initial_equity) / max(self._initial_equity, 1)

        mock_default = "false" if (self.account_profile and self.account_profile.is_competition) else "true"
        if self.simulation or os.getenv("PEER_MONITOR_MOCK", mock_default).lower() in ("1", "true", "yes"):
            if self.account_profile and self.account_profile.is_competition:
                return self._neutral_peer_data(our_return)
            return self._mock_peer_data(our_return)

        api_url = os.getenv("COMPETITION_LEADERBOARD_URL", "").strip()
        if api_url:
            try:
                with urllib.request.urlopen(api_url, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                return {
                    "peer_count": data.get("peer_count", 0),
                    "avg_return": data.get("avg_return", 0.0),
                    "avg_drawdown": data.get("avg_drawdown", 0.0),
                    "top_performer_return": data.get("top_performer_return", 0.0),
                    "our_return": our_return,
                    "our_rank": data.get("our_rank", 0),
                }
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                logger.warning("Leaderboard fetch failed — using neutral peer data")
                return self._neutral_peer_data(our_return)

        return self._neutral_peer_data(our_return)

    def _inject_agent_extras(
        self,
        features,
        agent_name: str,
        multi_features: dict,
        session_name: str,
        intel_context: dict | None = None,
    ) -> None:
        intel_context = intel_context or {}
        if intel_context:
            features.extras["sentiment_snapshot"] = intel_context.get("sentiment_snapshot", {})
            features.extras["macro_regime"] = intel_context.get("macro_regime", {})
            features.extras["event_gate"] = intel_context.get("event_gate", {})
        h1 = multi_features.get("H1")
        h4 = multi_features.get("H4")
        if h1:
            features.extras["h1_adx"] = h1.adx
            features.extras["h1_trend_bull"] = h1.close > h1.ema_50 and h1.ema_9 > h1.ema_21
            features.extras["h1_trend_bear"] = h1.close < h1.ema_50 and h1.ema_9 < h1.ema_21
        if h4:
            features.extras["h4_trend_bull"] = h4.close > h4.ema_50 and h4.ema_9 > h4.ema_21
            features.extras["h4_trend_bear"] = h4.close < h4.ema_50 and h4.ema_9 < h4.ema_21
        if agent_name == "breakout_hunter":
            features.extras["session_name"] = session_name
        features.extras["instrument_bias"] = self.config.bias_for(features.symbol)

    def _manage_positions(self, equity: float, dd_state, margin_state) -> None:
        positions = self.connector.get_positions()
        atr_by_symbol: dict[str, float] = {}
        current_prices: dict[str, float] = {}
        exit_prices: dict[str, float] = {}
        spreads_by_symbol: dict[str, float] = {}
        volume_mins: dict[str, float] = {}
        for pos in positions:
            sym = str(pos.get("symbol", ""))
            if not sym:
                continue
            specs = self._get_symbol_info(sym)
            if specs:
                volume_mins[sym] = float(specs.get("volume_min", 0.01))
            tick = self.live_feed.get_tick(sym)
            if tick:
                current_prices[sym] = tick.mid
                spreads_by_symbol[sym] = float(tick.spread or 0)
                direction = str(pos.get("type", "BUY")).upper()
                if direction in ("BUY", "LONG", "0"):
                    exit_prices[sym] = tick.bid
                else:
                    exit_prices[sym] = tick.ask
            else:
                price = self._current_price(sym)
                if price is not None:
                    current_prices[sym] = price
                    exit_prices[sym] = price
            ticket = pos.get("ticket")
            tracked = self._open_trades.get(ticket, {}) if ticket else {}
            atr = tracked.get("features_snapshot", {}).get("atr_14")
            if atr:
                atr_by_symbol[sym] = float(atr)

        m15_bar_times: dict[str, datetime] = {}
        for sym, meta in self._ohlcv_meta.items():
            ts_raw = meta.get("bar_timestamp")
            if not ts_raw:
                continue
            try:
                m15_bar_times[sym] = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except ValueError:
                continue

        exit_actions = self.position_manager.evaluate(
            positions,
            self._instrument_regimes,
            atr_by_symbol,
            current_prices,
            exit_prices=exit_prices,
            spreads_by_symbol=spreads_by_symbol,
            volume_mins=volume_mins,
            m15_bar_times=m15_bar_times,
        )
        self._position_diagnostics = self.position_manager.build_diagnostics(
            positions,
            exit_actions,
            self._instrument_regimes,
            atr_by_symbol,
            current_prices,
            exit_prices=exit_prices,
        )
        for action in exit_actions:
            if action.action == "close":
                logger.info("PositionManager closing %d: %s", action.ticket, action.reason)
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                tracked = self._open_trades.get(action.ticket, {})
                sym = tracked.get("symbol", str(pos.get("symbol", "")))
                self._log_cycle_event(
                    "close",
                    sym,
                    direction=tracked.get("direction", str(pos.get("type", "BUY"))),
                    reason=action.reason,
                    ticket=int(action.ticket),
                )
                self.trade_logger.log(
                    symbol=tracked.get("symbol", str(pos.get("symbol", ""))),
                    regime=tracked.get("regime", ""),
                    session=tracked.get("session", ""),
                    direction=tracked.get("direction", str(pos.get("type", "BUY"))),
                    confidence=0.0,
                    agent_votes=tracked.get("agent_votes", []),
                    status="exit_action",
                    reasoning=action.reason,
                    extra={
                        "ticket": action.ticket,
                        "exit_rule": action.action,
                        "close_reason": action.reason,
                    },
                )
                before_vol = float(pos.get("volume", 0))
                result = self.connector.close_position(action.ticket)
                self._log_position_reconcile(action.ticket, before_vol, "CLOSE", result)
                if self._close_position_confirmed(action.ticket, before_vol, result):
                    self._finalize_trade(
                        action.ticket, pos, equity, close_reason=action.reason,
                    )
                    self.position_manager.on_close(action.ticket)
                else:
                    logger.warning(
                        "Close not confirmed for ticket %d — deferring finalize",
                        action.ticket,
                    )
            elif action.action == "partial_close" and action.volume:
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                symbol = str(pos.get("symbol", ""))
                before_vol = float(pos.get("volume", 0))
                result = self._reduce_with_reconcile(action.ticket, action.volume, symbol)
                if result.get("confirmed") and not result.get("escalated_to_full"):
                    closed_vol = max(before_vol - float(result.get("after_volume", before_vol)), 0.0)
                    self.position_manager.confirm_partial(action.ticket, closed_vol)
                    if action.ticket in self._open_trades:
                        self._open_trades[action.ticket]["volume"] = float(
                            result.get("after_volume", before_vol - closed_vol),
                        )
                    tracked = self._open_trades.get(action.ticket, {})
                    sym = tracked.get("symbol", symbol)
                    self._log_cycle_event(
                        "partial_close",
                        sym,
                        direction=tracked.get("direction", str(pos.get("type", "BUY"))),
                        reason=action.reason,
                        ticket=int(action.ticket),
                        extra={"closed_volume": closed_vol},
                    )
                    self.trade_logger.log(
                        symbol=tracked.get("symbol", symbol),
                        regime=tracked.get("regime", ""),
                        session=tracked.get("session", ""),
                        direction=tracked.get("direction", str(pos.get("type", "BUY"))),
                        confidence=0.0,
                        agent_votes=tracked.get("agent_votes", []),
                        status="partial_close",
                        reasoning=action.reason,
                        extra={
                            "ticket": action.ticket,
                            "close_reason": action.reason,
                            "closed_volume": closed_vol,
                            "remaining_volume": result.get("after_volume"),
                        },
                    )
                elif result.get("escalated_to_full") and self._close_position_confirmed(
                    action.ticket, before_vol, result,
                ):
                    self._finalize_trade(
                        action.ticket, pos, equity,
                        close_reason="partial_escalated_full_close",
                    )
                    self.position_manager.on_close(action.ticket)
            elif action.action == "modify_sl" and action.new_sl is not None:
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                tracked = self._open_trades.get(action.ticket, {})
                self.trade_logger.log(
                    symbol=tracked.get("symbol", str(pos.get("symbol", ""))),
                    regime=tracked.get("regime", ""),
                    session=tracked.get("session", ""),
                    direction=tracked.get("direction", str(pos.get("type", "BUY"))),
                    confidence=0.0,
                    agent_votes=tracked.get("agent_votes", []),
                    status="exit_action",
                    reasoning=action.reason,
                    extra={
                        "ticket": action.ticket,
                        "exit_rule": action.action,
                        "new_sl": action.new_sl,
                        "close_reason": action.reason,
                    },
                )
                self.connector.modify_position(action.ticket, sl=action.new_sl, tp=pos.get("tp"))
                if action.ticket in self._open_trades:
                    self._open_trades[action.ticket]["sl"] = action.new_sl

        positions = self.connector.get_positions()
        for pos in positions:
            ticket = pos.get("ticket")
            if not ticket:
                continue

            if dd_state.tier == "critical" and float(pos.get("profit", 0)) < 0:
                logger.info("Critical tier closing losing position %d", ticket)
                before_vol = float(pos.get("volume", 0))
                result = self.connector.close_position(ticket)
                self._log_position_reconcile(ticket, before_vol, "CLOSE", result)
                if self._close_position_confirmed(ticket, before_vol, result):
                    self._finalize_trade(
                        ticket, pos, equity, close_reason="critical_tier_losing",
                    )
                    self.position_manager.on_close(ticket)

    def _sync_open_trades_from_mt5(self) -> None:
        """Register MT5 positions missing from the engine ledger (bridge recovery)."""
        if self.simulation:
            return
        session = self.session_filter.current_session()
        for pos in self.connector.get_positions():
            ticket = pos.get("ticket")
            if not ticket or ticket in self._open_trades:
                continue
            symbol = display_symbol(str(pos.get("symbol", "")))
            jsonl_ctx = context_from_jsonl(int(ticket), self.trade_logger.jsonl_path)
            pos_time = int(pos.get("time", 0) or 0)
            if pos_time > 0:
                entry_time = datetime.fromtimestamp(pos_time, tz=timezone.utc).isoformat()
            else:
                entry_time = jsonl_ctx.get("entry_time", datetime.now(timezone.utc).isoformat())
            logger.warning(
                "Registering untracked MT5 position %s on %s for finalize on close",
                ticket,
                symbol,
            )
            direction = jsonl_ctx.get("direction") or str(pos.get("type", "BUY")).upper()
            entry_price = float(jsonl_ctx.get("entry_price", 0) or pos.get("price_open", 0) or 0)
            regime = jsonl_ctx.get("regime", self._instrument_regimes.get(symbol, "unknown"))
            self._open_trades[int(ticket)] = {
                "symbol": jsonl_ctx.get("symbol") or symbol,
                "direction": direction,
                "entry_price": entry_price,
                "volume": float(jsonl_ctx.get("volume", 0) or pos.get("volume", 0) or 0),
                "sl": jsonl_ctx.get("sl") or pos.get("sl"),
                "session": jsonl_ctx.get("session", session.name),
                "regime": regime,
                "agent": jsonl_ctx.get("agent", "recovered"),
                "features_snapshot": jsonl_ctx.get("features_snapshot", {}),
                "agent_votes": jsonl_ctx.get("agent_votes", []),
                "attribution_json": jsonl_ctx.get("attribution_json", {}),
                "reasoning": jsonl_ctx.get("reasoning", "Recovered from MT5 position sync"),
                "entry_time": entry_time,
            }
            if self.position_manager.get_meta(int(ticket)) is None:
                sl_val = jsonl_ctx.get("sl") or pos.get("sl")
                self.position_manager.register_entry(
                    int(ticket),
                    symbol,
                    direction,
                    entry_price,
                    float(sl_val) if sl_val else None,
                    float(pos.get("volume", 0) or 0),
                    regime,
                )
                meta = self.position_manager.get_meta(int(ticket))
                if meta:
                    meta.entry_time = entry_time

    def _reconcile_open_trades_with_mt5(self, equity: float) -> None:
        """Finalize ledger entries when MT5 no longer has the position (SL/TP/manual close)."""
        mt5_tickets = {p.get("ticket") for p in self.connector.get_positions() if p.get("ticket")}
        for ticket in list(self._open_trades.keys()):
            if ticket in mt5_tickets:
                continue
            tracked = self._open_trades.get(ticket, {})
            logger.warning(
                "Orphan open trade %d (%s) — position closed externally, finalizing",
                ticket,
                tracked.get("symbol", ""),
            )
            pos = {
                "profit": self._position_deal_profit(ticket),
                "symbol": tracked.get("symbol", ""),
                "price_open": tracked.get("entry_price"),
                "type": tracked.get("direction"),
                "volume": tracked.get("volume"),
            }
            self._finalize_trade(
                ticket, pos, equity, close_reason=self._infer_external_close_reason(ticket),
            )
            self.position_manager.on_close(ticket)

    def _infer_external_close_reason(self, ticket: int) -> str:
        try:
            import MetaTrader5 as mt5

            deals = mt5.history_deals_get(position=ticket)
            if deals:
                comment = str(deals[-1].comment or "").lower()
                if "sl" in comment or "stop" in comment:
                    return "stop_loss"
                if "tp" in comment or "take" in comment:
                    return "take_profit"
        except Exception:
            pass
        return "external_close"

    def _resolve_entry_price(self, ticket: int, tracked: dict, pos: dict) -> float:
        entry_price = float(tracked.get("entry_price", 0) or 0)
        if entry_price > 0:
            return entry_price
        entry_price = float(pos.get("price_open", 0) or 0)
        if entry_price > 0:
            return entry_price
        jsonl_ctx = context_from_jsonl(ticket, self.trade_logger.jsonl_path)
        entry_price = float(jsonl_ctx.get("entry_price", 0) or 0)
        if entry_price > 0:
            return entry_price
        extra_entry = float((jsonl_ctx.get("extra") or {}).get("entry_price", 0) or 0)
        if extra_entry > 0:
            return extra_entry
        try:
            import MetaTrader5 as mt5

            deals = mt5.history_deals_get(position=ticket)
            if deals:
                for deal in deals:
                    if int(getattr(deal, "entry", -1)) == 0:
                        return float(deal.price)
        except Exception:
            pass
        return 0.0

    def _infer_close_reason(
        self,
        ticket: int,
        pos: dict,
        tracked: dict,
        exit_price: float,
        explicit: str | None,
    ) -> str:
        if explicit:
            return explicit
        stored = tracked.get("close_reason")
        if stored:
            return str(stored)
        sl = tracked.get("sl")
        tp = pos.get("tp") or tracked.get("tp")
        tol = max(abs(exit_price) * 1e-4, 1e-5)
        if sl is not None and abs(float(exit_price) - float(sl)) <= tol:
            return "stop_loss"
        if tp is not None and abs(float(exit_price) - float(tp)) <= tol:
            return "take_profit"
        return "engine_close"

    def _finalize_trade(
        self,
        ticket: int,
        pos: dict,
        equity: float,
        close_reason: str | None = None,
    ) -> None:
        ticket = int(ticket)
        if ticket in self._finalized_tickets:
            logger.debug("Skip duplicate finalize for ticket %d", ticket)
            return

        tracked = self._open_trades.pop(ticket, None)
        if not tracked:
            tracked = self._recover_tracked_context(ticket)
        if not tracked:
            tracked = self._minimal_tracked_context(ticket, pos)
        if not tracked:
            logger.warning("Cannot finalize ticket %d — no ledger, journal, or MT5 history", ticket)
            return

        exit_price = self._resolve_exit_price(ticket, {**pos, **tracked})
        entry_price = self._resolve_entry_price(ticket, tracked, pos)
        direction = tracked.get("direction", "BUY")
        sl = tracked.get("sl")
        sl_dist = abs(entry_price - sl) if sl is not None and entry_price > 0 else 0.0
        pnl = float(pos.get("profit", 0))
        if pnl == 0.0:
            pnl = self._position_deal_profit(ticket)

        if sl_dist > 0 and entry_price > 0:
            price_move = exit_price - entry_price if direction == "BUY" else entry_price - exit_price
            r_multiple = price_move / sl_dist
        else:
            r_multiple = pnl / max(equity * 0.01, 1)

        resolved_close_reason = self._infer_close_reason(
            ticket, pos, tracked, exit_price, close_reason,
        )
        tracked["close_reason"] = resolved_close_reason
        pm_meta = self.position_manager.get_meta(ticket)
        bars_held = pm_meta.bars_held if pm_meta else tracked.get("bars_held")
        exit_regime = self._instrument_regimes.get(tracked.get("symbol", ""), "unknown")

        agent_name = tracked.get("agent", "unknown")
        if agent_name in ("recovered", "unknown") and tracked.get("agent_votes"):
            vote = tracked["agent_votes"][0]
            if isinstance(vote, dict):
                agent_name = str(vote.get("agent", agent_name))

        self.trade_logger.log(
            symbol=tracked.get("symbol", ""),
            regime=tracked.get("regime", ""),
            session=tracked.get("session", ""),
            direction=direction,
            confidence=0.0,
            agent_votes=tracked.get("agent_votes", []),
            sl=sl,
            status="closed",
            reasoning=tracked.get("reasoning", ""),
            extra={
                "ticket": ticket,
                "pnl": pnl,
                "exit_price": exit_price,
                "entry_price": entry_price,
                "r_multiple": r_multiple,
                "close_reason": resolved_close_reason,
                "exit_rule": tracked.get("exit_rule"),
                "bars_held": bars_held,
                "entry_regime": tracked.get("regime", ""),
                "exit_regime": exit_regime,
                "attribution_json": tracked.get("attribution_json", {}),
                "agent": agent_name,
            },
        )
        self._finalized_tickets.add(ticket)

        record = TradeRecord(
            trade_id=str(ticket),
            symbol=tracked.get("symbol", ""),
            session=tracked.get("session", ""),
            regime=tracked.get("regime", ""),
            agent=agent_name,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            r_multiple=r_multiple,
            pnl=pnl,
            features_snapshot=tracked.get("features_snapshot", {}),
            agent_votes=tracked.get("agent_votes", []),
            attribution_json=tracked.get("attribution_json", {}),
            orchestrator_reasoning=tracked.get("reasoning", ""),
            entry_time=tracked.get("entry_time", ""),
            exit_time=datetime.now(timezone.utc).isoformat(),
            round_id=self.config.current_phase,
        )
        self.memory.store_trade(record)

        symbol = tracked.get("symbol", "")
        phase_rules = self.config.phase_rules
        phase = self.config.current_phase
        if symbol and r_multiple > 1.5 and phase in self._momentum_phases():
            self._momentum_flags[symbol] = datetime.now(timezone.utc) + timedelta(minutes=30)
        if symbol:
            if r_multiple > 1.5 and phase in self._momentum_phases():
                cd_min = int(phase_rules.get("momentum_cooldown_minutes", 2))
            elif pnl > 0 or r_multiple > 0:
                cd_min = int(phase_rules.get("win_cooldown_minutes", 3))
            elif pnl < 0 or r_multiple < 0:
                cd_min = int(phase_rules.get("loss_cooldown_minutes", 12))
            else:
                cd_min = self._symbol_cooldown_minutes()
            if cd_min > 0:
                self._symbol_cooldown_until[symbol] = datetime.now(timezone.utc) + timedelta(
                    minutes=cd_min,
                )

    def _quick_opportunity_score(self, symbol: str) -> float:
        """Lightweight pre-scan to rank symbols — highest expected edge first."""
        m15_df = self._get_ohlcv(symbol, "M15")
        if m15_df is None or len(m15_df) < 50:
            return -1.0
        donchian_period = int(self.config.agent_config("breakout_hunter").get("donchian_period", 20))
        phase_rules = self.config.phase_rules
        regime_adx = int(phase_rules.get("regime_adx_period", 14))
        regime_window = int(phase_rules.get("regime_percentile_window", 20 if regime_adx >= 20 else 100))
        multi = self.feature_engine.compute_multi(
            symbol, m15_df, donchian_period,
            adx_period=regime_adx,
            percentile_window=regime_window,
        )
        if not multi:
            return -1.0
        primary = multi.get("M15") or next(iter(multi.values()))
        regime_key = primary.regime.value
        boosts = self.config.regime_boosts.get(regime_key, {})
        best = 0.0
        best_direction: str | None = None
        for agent in self.agents:
            if not self.config.is_agent_enabled(agent.name):
                continue
            sig = agent.analyze(primary)
            if not sig.is_actionable:
                continue
            weight = float(
                (phase_rules.get("agent_weights") or {}).get(
                    agent.name,
                    self.config.agents.get(agent.name, {}).get("weight", 0.2),
                )
            )
            boost = float(boosts.get(agent.name, 1.0))
            score = sig.confidence * weight * boost
            if score > best:
                best = score
                best_direction = sig.direction.value
        if self.intelligence.enabled:
            snap = self.intelligence.get_sentiment(symbol)
            if snap and snap.confidence > 0:
                best += abs(snap.score) * 0.15 * snap.confidence
            macro = self.intelligence.get_macro()
            if best_direction and macro.bias == "risk_off" and macro.usd_strength == "strong":
                if best_direction == "BUY" and self._is_metal_symbol(symbol):
                    best += 0.35
                elif best_direction == "BUY" and not self._is_crypto_symbol(symbol):
                    best -= 0.25
                elif best_direction == "SELL" and self._is_crypto_symbol(symbol):
                    best += 0.15
                elif best_direction == "SELL" and symbol == "USD/CAD":
                    best += 0.20
        lf = self._live_filters or {}
        for sym in lf.get("audit_winner_symbols", []):
            if symbol == sym:
                best += 0.30
        runner_min_adx = lf.get("runner_min_adx")
        if (
            runner_min_adx is not None
            and primary.adx >= float(runner_min_adx)
            and primary.regime.value in ("trending", "volatile")
        ):
            best += 0.25
        should_balance, dominant_long = self._net_directional_balance_context()
        if should_balance and best_direction:
            balancing = "BUY" if not dominant_long else "SELL"
            if best_direction == balancing:
                best += 0.3
            else:
                best -= 0.2
        return best

    def _process_symbol(
        self,
        symbol: str,
        equity: float,
        dd_state,
        margin_state,
        session_name: str,
        drawdown_pct: float,
        peer_adj: float = 1.0,
        peer_sentiment: str = "mixed",
        preferred_agents: list[str] | None = None,
        peer_conservative: bool = False,
    ) -> bool:
        m15_df = self._get_ohlcv(symbol, "M15")
        if m15_df is None or len(m15_df) < 50:
            logger.debug("Insufficient data for %s", symbol)
            self._record_cycle_skip(
                symbol,
                f"Insufficient OHLCV ({len(m15_df) if m15_df is not None else 0}/50 bars)",
                session_name,
            )
            return False

        self._update_ohlcv_meta(symbol, m15_df)
        bar_ts = self._bar_timestamp_from_df(m15_df)
        if bar_ts is not None:
            bar_age = max(0.0, (datetime.now(timezone.utc) - bar_ts).total_seconds())
            self._ohlcv_meta.setdefault(symbol, {})["bar_age_sec"] = bar_age

        event_gate = self.intelligence.evaluate_event_gate(symbol)
        live_filters = self._live_filters
        if live_filters.get("block_tier_c_entries"):
            if self.competition_strategy.symbol_tier(symbol) == "C":
                self._record_cycle_skip(
                    symbol,
                    "Return push: tier-C symbol skipped (focus tier-A/B)",
                    session_name,
                )
                return False
        if not event_gate.allowed and live_filters.get("tier_1_metals_crypto_reduce_only"):
            if self._is_crypto_symbol(symbol) or self._is_metal_symbol(symbol):
                from src.intelligence.models import EventGateResult
                event_gate = EventGateResult(
                    allowed=True,
                    size_multiplier=0.5,
                    min_confidence_override=float(
                        live_filters.get("tier_1_metals_crypto_min_confidence", 0.68),
                    ),
                    reason=(
                        f"{event_gate.reason} — tier-A metal/crypto reduced size only"
                    ),
                    blocking_event=event_gate.blocking_event,
                )
        if not event_gate.allowed:
            logger.warning(
                "Event gate blocked %s: %s (operator visibility)",
                symbol,
                event_gate.reason,
            )
            self._cycle_decisions.append({
                "symbol": symbol,
                "direction": "HOLD",
                "confidence": 0.0,
                "regime": "unknown",
                "session": session_name,
                "reasoning": event_gate.reason,
                "agent_votes": [],
                "status": "skipped",
                "skip_reason": event_gate.reason,
                "scan_stage": "event_gate",
                "event_gate": event_gate.reason,
            })
            return False

        sentiment_snapshot = self.intelligence.get_sentiment(symbol)
        macro_regime = self.intelligence.get_macro().to_dict() if self.intelligence.enabled else {}
        upcoming_events = self.intelligence.upcoming_events()
        intel_context = {
            "sentiment_snapshot": sentiment_snapshot.to_dict() if sentiment_snapshot else {},
            "macro_regime": macro_regime,
            "event_gate": event_gate.to_dict(),
        }

        donchian_period = int(self.config.agent_config("breakout_hunter").get("donchian_period", 20))
        phase_rules = self.config.phase_rules
        regime_adx = int(phase_rules.get("regime_adx_period", 14))
        regime_window = int(phase_rules.get("regime_percentile_window", 20 if regime_adx >= 20 else 100))
        h1_df = None
        h4_df = None
        if not self.simulation:
            h1_df = self._get_ohlcv(symbol, "H1")
            h4_df = self._get_ohlcv(symbol, "H4")
        multi_features = self.feature_engine.compute_multi(
            symbol,
            m15_df,
            donchian_period,
            h1_ohlcv=h1_df,
            h4_ohlcv=h4_df,
            adx_period=regime_adx,
            percentile_window=regime_window,
        )
        if not multi_features:
            self._record_cycle_skip(symbol, "Feature computation failed", session_name)
            return False

        live_filters = self._live_filters
        blocked_symbols = set(live_filters.get("blocked_symbols", [])) | set(
            phase_rules.get("blocked_symbols", []),
        )
        if symbol in blocked_symbols:
            self._record_cycle_skip(symbol, f"Live filter blocked symbol {symbol}", session_name)
            return False

        trade_tiers = live_filters.get("trade_tiers")
        if trade_tiers:
            symbol_tier = self.competition_strategy.symbol_tier(symbol)
            if symbol_tier not in trade_tiers:
                self._record_cycle_skip(
                    symbol,
                    f"Live filter: tier {symbol_tier} not in {trade_tiers}",
                    session_name,
                )
                return False

        disabled_agents = set(phase_rules.get("disabled_agents", []))
        preferred = self.session_filter.preferred_agents()

        signals = []
        for agent in self.agents:
            if not self.config.is_agent_enabled(agent.name):
                continue
            if preferred_agents and agent.name not in preferred_agents:
                continue
            if agent.name in disabled_agents:
                continue
            if preferred and agent.name not in preferred and not phase_rules.get("ignore_session_agents"):
                continue
            agent_cfg = agent.config
            timeframes = agent_cfg.get("timeframes", ["M15"])
            best_signal = None
            for tf in timeframes:
                features = multi_features.get(tf) or (multi_features.get("M15") if tf != "M15" else None)
                if features is None:
                    continue
                self._inject_agent_extras(
                    features, agent.name, multi_features, session_name, intel_context,
                )
                candidate = agent.analyze(features)
                if best_signal is None or candidate.confidence > best_signal.confidence:
                    best_signal = candidate
            if best_signal is not None:
                signals.append(best_signal)

        block_agent_regime = live_filters.get("block_agent_in_regime", {})
        regime_key = multi_features.get("M15") and multi_features["M15"].regime.value
        if not regime_key and multi_features:
            regime_key = next(iter(multi_features.values())).regime.value
        if block_agent_regime and regime_key:
            m15_feat = multi_features.get("M15")
            rsi_14 = m15_feat.rsi_14 if m15_feat else 50.0
            signals = [
                sig
                for sig in signals
                if regime_key not in block_agent_regime.get(sig.agent_name, [])
                or (
                    sig.agent_name == "mean_reversion"
                    and self._is_metal_symbol(symbol)
                    and rsi_14 < 35
                    and regime_key in ("volatile", "trending")
                )
            ]

        if live_filters.get("use_audit_routing", True):
            blocked_agents = [
                sig.agent_name
                for sig in signals
                if self.competition_strategy.block_agent(symbol, sig.agent_name)
            ]
            if blocked_agents:
                signals = [
                    sig for sig in signals
                    if not self.competition_strategy.block_agent(symbol, sig.agent_name)
                ]
                logger.debug(
                    "Audit routing blocked agents for %s: %s",
                    symbol,
                    sorted(set(blocked_agents)),
                )

        primary_features = multi_features.get("M15") or next(iter(multi_features.values()))
        pos_snapshot = self._positions_snapshot()
        if not self.simulation and not pos_snapshot.trusted:
            self._record_cycle_skip(
                symbol,
                "Position state unavailable (fail-closed)",
                session_name,
                regime=primary_features.regime.value,
            )
            return False
        open_positions = pos_snapshot.positions
        self._instrument_regimes[symbol] = primary_features.regime.value
        self.market_validator.record_bar_time(symbol, bar_ts)

        tick = self.live_feed.get_tick(symbol)
        tick_mid = tick.mid if tick else None
        tick_age = tick.tick_age_ms if tick else 99999.0
        market_status = self.market_validator.validate(
            symbol, tick_mid, primary_features.close, primary_features.atr_14, tick_age,
            require_tick=not self.simulation,
        )
        if market_status.block_entries:
            logger.info("Market health RED for %s — %s", symbol, market_status.message)
            self._record_cycle_skip(
                symbol,
                market_status.message,
                session_name,
                regime=primary_features.regime.value,
            )
            return False

        base_context = self.context_builder.build(
            features=primary_features,
            signals=signals,
            session=session_name,
            drawdown_pct=drawdown_pct,
            risk_tier=dd_state.tier,
            phase_multiplier=self.config.phase_multiplier,
            open_positions=open_positions,
            margin_state=margin_state,
            peer_sentiment=peer_sentiment,
            peer_sizing_adj=peer_adj,
            sentiment_snapshot=intel_context.get("sentiment_snapshot"),
            macro_regime=intel_context.get("macro_regime"),
            upcoming_events=upcoming_events,
            event_gate=intel_context.get("event_gate"),
        )
        debate = self.debate_orchestrator.debate(primary_features, signals, base_context)
        debate_ctx = {
            "winner": debate.winner,
            "confidence": debate.confidence,
            "synthesis": debate.synthesis,
            "bull_reasoning": debate.bull_case.reasoning,
            "bear_reasoning": debate.bear_case.reasoning,
        }
        orch_extra: dict = {}
        for sig in signals:
            if sig.agent_name == "ml_signal" and sig.is_actionable:
                orch_extra["ml_signal_direction"] = sig.direction.value
                orch_extra["ml_signal_confidence"] = sig.confidence
        backtest_rates = self._backtest_agent_win_rates()
        audit_rates = self.competition_strategy.global_agent_win_rates()
        if audit_rates:
            orch_extra["audit_agent_win_rates"] = audit_rates
        if backtest_rates:
            orch_extra["backtest_agent_win_rates"] = backtest_rates
        symbol_rates = self.competition_strategy.symbol_rates(symbol)
        if symbol_rates:
            orch_extra["symbol_agent_win_rates"] = symbol_rates
        orch_extra["symbol_tier"] = self.competition_strategy.symbol_tier(symbol)

        context = self.context_builder.build(
            features=primary_features,
            signals=signals,
            session=session_name,
            drawdown_pct=drawdown_pct,
            risk_tier=dd_state.tier,
            phase_multiplier=self.config.phase_multiplier,
            open_positions=open_positions,
            margin_state=margin_state,
            debate=debate_ctx,
            peer_sentiment=peer_sentiment,
            peer_sizing_adj=peer_adj,
            sentiment_snapshot=intel_context.get("sentiment_snapshot"),
            macro_regime=intel_context.get("macro_regime"),
            upcoming_events=upcoming_events,
            event_gate=intel_context.get("event_gate"),
        )
        context.update(orch_extra)
        context["return_focus"] = bool(phase_rules.get("return_focus"))
        context["min_orchestrator_size_scale"] = phase_rules.get("min_orchestrator_size_scale", 0.90)
        context["block_debate_fallback"] = bool(live_filters.get("block_debate_only_entries", False))
        context["solo_ml_metal_sell_min_confidence"] = live_filters.get(
            "solo_ml_metal_sell_min_confidence",
        )
        context["audit_winner_symbols"] = live_filters.get(
            "audit_winner_symbols",
        ) or ["USD/CAD", "XAG/USD"]
        context["audit_solo_trend_surfer_min_confidence"] = live_filters.get(
            "audit_solo_trend_surfer_min_confidence",
        )
        context["audit_winner_dual_min_adx"] = live_filters.get("audit_winner_dual_min_adx")
        context["audit_winner_dual_min_confidence"] = live_filters.get(
            "audit_winner_dual_min_confidence",
        )
        context["block_direction_in_regimes"] = live_filters.get("block_direction_in_regimes") or {}
        ml_sells = [
            s for s in signals
            if getattr(s, "agent_name", "") == "ml_signal"
            and s.is_actionable
            and s.direction.value == "SELL"
        ]
        if ml_sells:
            context["ml_metal_sell_confidence"] = max(s.confidence for s in ml_sells)
        context["risk_tier"] = dd_state.tier
        base_min_conf = phase_rules.get("min_agent_confidence")
        if base_min_conf is not None and self._momentum_flag_active(symbol):
            context["min_confidence_override"] = float(base_min_conf) - 0.05

        decision = self.orchestrator.decide(
            primary_features, signals, dd_state.tier, context=context,
        )
        balance_dir_early = self._balancing_direction()
        return_focus = bool(phase_rules.get("return_focus"))
        if (
            not return_focus
            and balance_dir_early == "BUY"
            and decision.direction == Direction.SELL
        ):
            for agent_name in (
                "sentiment_agent",
                "mean_reversion",
                "momentum_pulse",
                "breakout_hunter",
            ):
                alt = next(
                    (
                        s for s in signals
                        if s.agent_name == agent_name
                        and s.is_actionable
                        and s.direction == Direction.BUY
                    ),
                    None,
                )
                if alt and alt.confidence >= 0.55:
                    decision.direction = Direction.BUY
                    decision.confidence = max(float(alt.confidence), 0.58)
                    decision.reasoning = (
                        f"Balancing BUY via {agent_name} ({alt.confidence:.2f}) — "
                        f"short stack blocked; {decision.reasoning}"
                    )
                    break
        is_balancing_for_direction = (
            balance_dir_early is not None
            and decision.direction.value == balance_dir_early
        )
        logger.info(
            "DEBATE %s: %s | orchestrator=%s conf=%.2f",
            symbol, debate.synthesis, decision.direction.value, decision.confidence,
        )
        log_trade_decision(logger, decision, primary_features)

        vote_summary = [
            {"agent": s.agent_name, "direction": s.direction.value, "confidence": s.confidence}
            for s in signals
        ]
        self._cycle_votes.append({"symbol": symbol, "votes": vote_summary})

        min_consensus = self._min_consensus_for_symbol(symbol, live_filters, phase_rules)
        if live_filters.get("use_audit_routing", True):
            audit_min = self.competition_strategy.min_consensus_for_symbol(
                symbol,
                min_consensus,
                tier_a_consensus=int(live_filters.get("tier_a_min_consensus", 1)),
                tier_b_consensus=int(live_filters.get("tier_b_min_consensus", 2)),
                tier_c_consensus=int(live_filters.get("tier_c_min_consensus", 2)),
            )
            solo_syms = set(live_filters.get("audit_solo_consensus_symbols") or [])
            if symbol in solo_syms:
                min_consensus = audit_min
            elif self._is_crypto_symbol(symbol) or self._is_fx_symbol(symbol):
                min_consensus = max(min_consensus, audit_min)
            else:
                min_consensus = audit_min
        symbol_overrides = live_filters.get("symbol_min_consensus_agents") or {}
        if symbol in symbol_overrides:
            min_consensus = int(symbol_overrides[symbol])
        technical_agents = set(
            live_filters.get("technical_agents")
            or ["trend_surfer", "breakout_hunter", "momentum_pulse", "mean_reversion"]
        )
        ml_technical_min = float(live_filters.get("ml_as_technical_min_confidence", 0.70))
        a_plus_exclude = set(live_filters.get("a_plus_bypass", {}).get("exclude_agents") or [])

        def _counts_as_technical(signal) -> bool:
            if signal.agent_name in technical_agents:
                return True
            return (
                signal.agent_name == "ml_signal"
                and signal.confidence >= ml_technical_min
            )

        a_plus_ok = False
        agreeing = 0
        if decision.direction.value != "HOLD":
            agreeing = sum(
                1 for s in signals
                if s.is_actionable and s.direction == decision.direction
            )
            agreeing_technical = sum(
                1 for s in signals
                if s.is_actionable
                and s.direction == decision.direction
                and _counts_as_technical(s)
            )
            a_plus = live_filters.get("a_plus_bypass") or {}
            a_plus_conf = float(a_plus.get("min_confidence", 0.80))
            require_debate = bool(a_plus.get("require_debate_confirm", True))
            min_technical = int(a_plus.get("min_technical_agents", 0))
            debate_side = "bull" if decision.direction.value == "BUY" else "bear"
            debate_confirms = debate.winner == debate_side
            a_plus_agreeing = sum(
                1 for s in signals
                if s.is_actionable
                and s.direction == decision.direction
                and s.agent_name not in a_plus_exclude
            )
            a_plus_ok = (
                a_plus_agreeing >= 1
                and agreeing_technical >= min_technical
                and decision.confidence >= a_plus_conf
                and (not require_debate or debate_confirms)
            )
            if live_filters.get("elite_only_entries"):
                a_plus_ok = False
            solo_metal_sell_min = live_filters.get("solo_ml_metal_sell_min_confidence")
            ml_solo_conf = max(
                (
                    s.confidence
                    for s in signals
                    if s.is_actionable
                    and s.direction == decision.direction
                    and getattr(s, "agent_name", "") == "ml_signal"
                ),
                default=0.0,
            )
            solo_metal_sell_ok = (
                solo_metal_sell_min is not None
                and self._is_metal_symbol(symbol)
                and decision.direction.value == "SELL"
                and primary_features.regime.value in ("trending", "volatile")
                and agreeing == 1
                and ml_solo_conf >= float(solo_metal_sell_min)
                and all(
                    getattr(s, "agent_name", "") == "ml_signal"
                    for s in signals
                    if s.is_actionable and s.direction == decision.direction
                )
                and debate_confirms
            )
            audit_winners = frozenset(
                live_filters.get("audit_winner_symbols") or ["USD/CAD", "XAG/USD"],
            )
            audit_ts_min = float(
                live_filters.get("audit_solo_trend_surfer_min_confidence") or 0.72,
            )
            ts_solo_conf = max(
                (
                    s.confidence
                    for s in signals
                    if s.is_actionable
                    and s.direction == decision.direction
                    and getattr(s, "agent_name", "") == "trend_surfer"
                ),
                default=0.0,
            )
            audit_solo_trend_surfer_ok = (
                symbol in audit_winners
                and decision.direction.value in ("BUY", "SELL")
                and primary_features.regime.value in ("trending", "volatile")
                and agreeing == 1
                and ts_solo_conf >= audit_ts_min
                and all(
                    getattr(s, "agent_name", "") == "trend_surfer"
                    for s in signals
                    if s.is_actionable and s.direction == decision.direction
                )
            )
            active_size_boost = self.competition_strategy.resolve_size_boost(
                symbol,
                decision.direction.value,
                decision.confidence,
                signals,
                live_filters,
                counts_as_technical=_counts_as_technical,
                adx=primary_features.adx,
                regime=primary_features.regime.value,
            )
            aa_plus_max = live_filters.get("max_aa_plus_entries_per_cycle")
            if (
                aa_plus_max is not None
                and active_size_boost
                and active_size_boost.get("boost_tier") == "tier_aa_plus"
                and self._aa_plus_entries_opened_this_cycle >= int(aa_plus_max)
            ):
                active_size_boost = self.competition_strategy.tier_a_plus_size_boost(
                    symbol,
                    decision.direction.value,
                    decision.confidence,
                    signals,
                    live_filters,
                    counts_as_technical=_counts_as_technical,
                    adx=primary_features.adx,
                    regime=primary_features.regime.value,
                ) or self.competition_strategy.audit_winner_size_boost(
                    symbol,
                    decision.direction.value,
                    decision.confidence,
                    signals,
                    live_filters,
                    counts_as_technical=_counts_as_technical,
                    adx=primary_features.adx,
                    regime=primary_features.regime.value,
                )
        else:
            active_size_boost = None
            solo_metal_sell_ok = False
            audit_solo_trend_surfer_ok = False

        if decision.direction.value != "HOLD" and min_consensus > 1:
            if (
                agreeing < min_consensus
                and not a_plus_ok
                and not solo_metal_sell_ok
                and not audit_solo_trend_surfer_ok
            ):
                skip = f"Live filter: need {min_consensus} agreeing agents, got {agreeing}"
                self.trade_logger.log(
                    symbol=symbol,
                    regime=primary_features.regime.value,
                    session=session_name,
                    direction=decision.direction.value,
                    confidence=decision.confidence,
                    agent_votes=decision.agent_votes,
                    status="skipped",
                    reasoning=skip,
                )
                self._cycle_decisions.append({
                    "symbol": symbol,
                    "direction": decision.direction.value,
                    "confidence": decision.confidence,
                    "regime": primary_features.regime.value,
                    "session": session_name,
                    "reasoning": decision.reasoning,
                    "agent_votes": vote_summary,
                    "status": "skipped",
                    "skip_reason": skip,
                })
                return False

        if (
            live_filters.get("block_debate_only_entries")
            and decision.direction.value != "HOLD"
            and decision.reasoning.startswith("Debate-driven")
            and agreeing < min_consensus
            and not a_plus_ok
        ):
            skip = (
                f"Live filter: debate-only entry blocked "
                f"(need {min_consensus} agreeing agents, got {agreeing})"
            )
            self.trade_logger.log(
                symbol=symbol,
                regime=primary_features.regime.value,
                session=session_name,
                direction=decision.direction.value,
                confidence=decision.confidence,
                agent_votes=decision.agent_votes,
                status="skipped",
                reasoning=skip,
            )
            self._cycle_decisions.append({
                "symbol": symbol,
                "direction": decision.direction.value,
                "confidence": decision.confidence,
                "regime": primary_features.regime.value,
                "session": session_name,
                "reasoning": decision.reasoning,
                "agent_votes": vote_summary,
                "status": "skipped",
                "skip_reason": skip,
            })
            return False

        if (
            self._is_metal_symbol(symbol)
            and decision.direction.value == "BUY"
            and primary_features.regime.value in ("trending", "volatile")
        ):
            ml_sell_conf = max(
                (
                    s.confidence
                    for s in signals
                    if s.agent_name == "ml_signal"
                    and s.is_actionable
                    and s.direction.value == "SELL"
                ),
                default=0.0,
            )
            metal_sell_min = float(
                live_filters.get("solo_ml_metal_sell_min_confidence") or 0.68,
            )
            if ml_sell_conf + 1e-9 >= metal_sell_min:
                skip = (
                    f"Metal BUY blocked — ml SELL {ml_sell_conf:.2f} "
                    "(audit-winning short path)"
                )
                self.trade_logger.log(
                    symbol=symbol,
                    regime=primary_features.regime.value,
                    session=session_name,
                    direction=decision.direction.value,
                    confidence=decision.confidence,
                    agent_votes=decision.agent_votes,
                    status="skipped",
                    reasoning=skip,
                )
                self._cycle_decisions.append({
                    "symbol": symbol,
                    "direction": decision.direction.value,
                    "confidence": decision.confidence,
                    "regime": primary_features.regime.value,
                    "session": session_name,
                    "reasoning": decision.reasoning,
                    "agent_votes": vote_summary,
                    "status": "skipped",
                    "skip_reason": skip,
                })
                return False

        min_confidence = live_filters.get("min_confidence")
        sym_conf = (live_filters.get("symbol_min_confidence") or {}).get(symbol)
        if sym_conf is not None:
            min_confidence = sym_conf
        obj_floor = self._objective_runtime_overrides()["min_confidence_floor"]
        if min_confidence is not None:
            min_confidence = max(float(min_confidence), obj_floor)
        else:
            min_confidence = obj_floor
        if (
            min_confidence is not None
            and decision.direction.value != "HOLD"
            and not solo_metal_sell_ok
            and not audit_solo_trend_surfer_ok
            and decision.confidence + 1e-9 < float(min_confidence)
        ):
            skip = f"Live filter: confidence {decision.confidence:.2f} < {float(min_confidence):.2f}"
            self.trade_logger.log(
                symbol=symbol,
                regime=primary_features.regime.value,
                session=session_name,
                direction=decision.direction.value,
                confidence=decision.confidence,
                agent_votes=decision.agent_votes,
                status="skipped",
                reasoning=skip,
            )
            self._cycle_decisions.append({
                "symbol": symbol,
                "direction": decision.direction.value,
                "confidence": decision.confidence,
                "regime": primary_features.regime.value,
                "session": session_name,
                "reasoning": decision.reasoning,
                "agent_votes": vote_summary,
                "status": "skipped",
                "skip_reason": skip,
            })
            return False

        if (
            live_filters.get("require_technical_agent")
            and decision.direction.value != "HOLD"
        ):
            technical_agreeing = sum(
                1 for s in signals
                if s.is_actionable
                and s.direction == decision.direction
                and _counts_as_technical(s)
            )
            if technical_agreeing < 1:
                metal_long_risk_off = False
                if (
                    live_filters.get("block_metal_shorts_risk_off")
                    and self._is_metal_symbol(symbol)
                    and decision.direction.value == "BUY"
                    and primary_features.rsi_14 < 38
                    and self.intelligence.enabled
                ):
                    macro = self.intelligence.get_macro()
                    metal_long_min = float(
                        live_filters.get("metals_risk_off_long_min_confidence", 0.68),
                    )
                    if (
                        macro.bias == "risk_off"
                        and decision.confidence + 1e-9 >= metal_long_min
                    ):
                        metal_long_risk_off = True
                sentiment_balancing = (
                    is_balancing_for_direction
                    and any(
                        s.agent_name == "sentiment_agent"
                        and s.is_actionable
                        and s.direction == decision.direction
                        for s in signals
                    )
                )
                if not sentiment_balancing and not a_plus_ok and not metal_long_risk_off:
                    skip = "Live filter: need technical agent confirmation"
                    self.trade_logger.log(
                        symbol=symbol,
                        regime=primary_features.regime.value,
                        session=session_name,
                        direction=decision.direction.value,
                        confidence=decision.confidence,
                        agent_votes=decision.agent_votes,
                        status="skipped",
                        reasoning=skip,
                    )
                    self._cycle_decisions.append({
                        "symbol": symbol,
                        "direction": decision.direction.value,
                        "confidence": decision.confidence,
                        "regime": primary_features.regime.value,
                        "session": session_name,
                        "reasoning": decision.reasoning,
                        "agent_votes": vote_summary,
                        "status": "skipped",
                        "skip_reason": skip,
                    })
                    return False

        ml_only_min = live_filters.get("ml_only_min_confidence")
        if (
            ml_only_min is not None
            and decision.direction.value != "HOLD"
            and not a_plus_ok
        ):
            actionable = [s for s in signals if s.is_actionable and s.direction == decision.direction]
            non_ml = [s for s in actionable if s.agent_name != "ml_signal"]
            if not non_ml and decision.confidence + 1e-9 < float(ml_only_min):
                skip = (
                    f"ML-only signal — confidence {decision.confidence:.2f} "
                    f"< {float(ml_only_min):.2f}"
                )
                self.trade_logger.log(
                    symbol=symbol,
                    regime=primary_features.regime.value,
                    session=session_name,
                    direction=decision.direction.value,
                    confidence=decision.confidence,
                    agent_votes=decision.agent_votes,
                    status="skipped",
                    reasoning=skip,
                )
                self._cycle_decisions.append({
                    "symbol": symbol,
                    "direction": decision.direction.value,
                    "confidence": decision.confidence,
                    "regime": primary_features.regime.value,
                    "session": session_name,
                    "reasoning": decision.reasoning,
                    "agent_votes": vote_summary,
                    "status": "skipped",
                    "skip_reason": skip,
                })
                return False

        if (
            live_filters.get("fx_require_trend_surfer_or_ml")
            and self._is_fx_symbol(symbol)
            and decision.direction.value != "HOLD"
            and not a_plus_ok
        ):
            solo_fx = set(live_filters.get("audit_solo_consensus_symbols") or [])
            mp_min = float(live_filters.get("audit_solo_momentum_min_confidence", 0.62))
            has_ts = any(
                s.agent_name == "trend_surfer"
                and s.is_actionable
                and s.direction == decision.direction
                for s in signals
            )
            has_ml = any(
                s.agent_name == "ml_signal"
                and s.is_actionable
                and s.direction == decision.direction
                and s.confidence >= ml_technical_min
                for s in signals
            )
            has_mp = (
                symbol in solo_fx
                and any(
                    s.agent_name == "momentum_pulse"
                    and s.is_actionable
                    and s.direction == decision.direction
                    and s.confidence >= mp_min
                    for s in signals
                )
            )
            if not has_ts and not has_ml and not has_mp:
                skip = "FX entry requires trend_surfer or ML confirmation"
                self.trade_logger.log(
                    symbol=symbol,
                    regime=primary_features.regime.value,
                    session=session_name,
                    direction=decision.direction.value,
                    confidence=decision.confidence,
                    agent_votes=decision.agent_votes,
                    status="skipped",
                    reasoning=skip,
                )
                self._cycle_decisions.append({
                    "symbol": symbol,
                    "direction": decision.direction.value,
                    "confidence": decision.confidence,
                    "regime": primary_features.regime.value,
                    "session": session_name,
                    "reasoning": decision.reasoning,
                    "agent_votes": vote_summary,
                    "status": "skipped",
                    "skip_reason": skip,
                })
                return False

        rsi_block = live_filters.get("block_short_rsi_below")
        if (
            rsi_block is not None
            and decision.direction.value == "SELL"
            and primary_features.rsi_14 < float(rsi_block)
        ):
            min_ts = float(live_filters.get("min_trend_surfer_for_oversold_short", 0.70))
            ts_ok = any(
                s.agent_name == "trend_surfer"
                and s.is_actionable
                and s.direction.value == "SELL"
                and s.confidence >= min_ts
                for s in signals
            )
            multi_min = int(live_filters.get("oversold_short_min_agreeing") or 0)
            multi_ok = multi_min > 0 and agreeing >= multi_min
            if not ts_ok and not multi_ok and not a_plus_ok:
                skip = (
                    f"Live filter: RSI {primary_features.rsi_14:.1f} oversold — "
                    f"short blocked without trend_surfer>={min_ts:.2f}"
                )
                self.trade_logger.log(
                    symbol=symbol,
                    regime=primary_features.regime.value,
                    session=session_name,
                    direction=decision.direction.value,
                    confidence=decision.confidence,
                    agent_votes=decision.agent_votes,
                    status="skipped",
                    reasoning=skip,
                )
                self._cycle_decisions.append({
                    "symbol": symbol,
                    "direction": decision.direction.value,
                    "confidence": decision.confidence,
                    "regime": primary_features.regime.value,
                    "session": session_name,
                    "reasoning": decision.reasoning,
                    "agent_votes": vote_summary,
                    "features": {
                        "adx": primary_features.adx,
                        "rsi_14": primary_features.rsi_14,
                        "atr_14": primary_features.atr_14,
                    },
                    "status": "skipped",
                    "skip_reason": skip,
                })
                return False

        if decision.direction.value == "HOLD":
            self.trade_logger.log(
                symbol=symbol,
                regime=primary_features.regime.value,
                session=session_name,
                direction=decision.direction.value,
                confidence=decision.confidence,
                agent_votes=decision.agent_votes,
                status="skipped",
                reasoning=decision.reasoning,
            )
            self._cycle_decisions.append({
                "symbol": symbol,
                "direction": decision.direction.value,
                "confidence": decision.confidence,
                "regime": primary_features.regime.value,
                "session": session_name,
                "reasoning": decision.reasoning,
                "agent_votes": vote_summary,
                "features": {
                    "adx": primary_features.adx,
                    "rsi_14": primary_features.rsi_14,
                    "atr_14": primary_features.atr_14,
                },
                "status": "skipped",
                "skip_reason": "HOLD decision",
            })
            return False

        self.trade_logger.log(
            symbol=symbol,
            regime=primary_features.regime.value,
            session=session_name,
            direction=decision.direction.value,
            confidence=decision.confidence,
            agent_votes=decision.agent_votes,
            status="decision",
            reasoning=decision.reasoning,
        )

        self._cycle_decisions.append({
            "symbol": symbol,
            "direction": decision.direction.value,
            "confidence": decision.confidence,
            "regime": primary_features.regime.value,
            "session": session_name,
            "reasoning": decision.reasoning,
            "agent_votes": vote_summary,
            "features": {
                "adx": primary_features.adx,
                "rsi_14": primary_features.rsi_14,
                "atr_14": primary_features.atr_14,
            },
            "status": "decision",
            "scan_stage": "analyzed",
            **self._build_scan_meta(symbol, signals, decision, live_filters, phase_rules),
        })
        decision_record = self._cycle_decisions[-1]
        if active_size_boost:
            decision_record["size_boost_tier"] = active_size_boost.get("boost_tier")
            tier = active_size_boost.get("boost_tier")
            decision_record["tier_a_plus_boost"] = tier in ("tier_a_plus", "tier_aa_plus")
            decision_record["tier_aa_plus_boost"] = tier == "tier_aa_plus"
            decision_record["size_boost"] = {
                k: v for k, v in active_size_boost.items() if v is not None
            }
        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        balancing_dir = self._balancing_direction()
        is_balancing_trade = (
            balancing_dir is not None and decision.direction.value == balancing_dir
        )
        elite_entry = bool(
            active_size_boost
            and active_size_boost.get("boost_tier")
            in ("tier_aa_plus", "tier_a_plus")
        ) or solo_metal_sell_ok or audit_solo_trend_surfer_ok
        if (
            live_filters.get("elite_only_entries")
            and decision.direction.value != "HOLD"
            and not elite_entry
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                "Live filter: elite-only — requires A+ or AA+ confluence setup"
            )
            return False
        if (
            live_filters.get("require_confluence_boost_for_entry")
            and decision.direction.value != "HOLD"
            and not elite_entry
            and not a_plus_ok
            and not solo_metal_sell_ok
            and not audit_solo_trend_surfer_ok
            and not is_balancing_trade
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                "Live filter: requires A+/AA+ confluence setup"
            )
            return False
        if (
            return_focus
            and is_balancing_trade
            and not live_filters.get("enable_balancing_entries_return_focus", False)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                "Return-focus: balancing entries disabled"
            )
            return False
        balance_conf_discount = float(
            live_filters.get("balancing_confidence_discount", 0.10),
        )

        if balancing_dir == "BUY" and decision.direction.value == "SELL":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                "Net directional balance — new shorts blocked while book is one-sided"
            )
            return False
        if balancing_dir == "SELL" and decision.direction.value == "BUY":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                "Net directional balance — new longs blocked while book is one-sided"
            )
            return False

        if decision.direction.value == "BUY":
            buy_min = None
            if self._is_metal_symbol(symbol):
                buy_min = live_filters.get("buy_min_confidence_metals")
            elif self._is_fx_symbol(symbol):
                buy_min = live_filters.get("buy_min_confidence_fx")
                sym_buy = (live_filters.get("symbol_buy_min_confidence") or {}).get(symbol)
                if sym_buy is not None:
                    buy_min = sym_buy
            if buy_min is not None:
                buy_min_val = float(buy_min)
                if is_balancing_trade:
                    buy_min_val = max(0.50, buy_min_val - balance_conf_discount)
                if decision.confidence < buy_min_val:
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        f"Live filter: BUY confidence {decision.confidence:.2f} < {buy_min_val:.2f}"
                    )
                    return False
            if self.intelligence.enabled and not self._is_crypto_symbol(symbol):
                macro = self.intelligence.get_macro()
                usd_long_exempt = set(
                    live_filters.get("risk_off_usd_long_exempt_symbols")
                    or ["USD/CAD", "USD/JPY", "USD/CHF"],
                )
                if (
                    macro.bias == "risk_off"
                    and macro.usd_strength == "strong"
                    and symbol not in usd_long_exempt
                ):
                    risk_off_buy_min = float(buy_min or min_confidence or 0.55) + 0.08
                    if is_balancing_trade:
                        risk_off_buy_min = max(0.50, risk_off_buy_min - balance_conf_discount)
                    if decision.confidence < risk_off_buy_min:
                        decision_record["status"] = "skipped"
                        decision_record["skip_reason"] = (
                            f"Macro risk-off — BUY requires confidence >= {risk_off_buy_min:.2f}"
                        )
                        return False

        long_rsi_block = live_filters.get("block_long_rsi_above")
        if (
            long_rsi_block is not None
            and decision.direction.value == "BUY"
            and primary_features.rsi_14 > float(long_rsi_block)
        ):
            min_ts = float(live_filters.get("min_trend_surfer_for_overbought_long", 0.70))
            ts_ok = any(
                s.agent_name == "trend_surfer"
                and s.is_actionable
                and s.direction.value == "BUY"
                and s.confidence >= min_ts
                for s in signals
            )
            if not ts_ok and not is_balancing_trade:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"Live filter: RSI {primary_features.rsi_14:.1f} overbought — "
                    f"long blocked without trend_surfer>={min_ts:.2f}"
                )
                return False

        if regime_key == "trending":
            trend_min_conf = live_filters.get("trending_min_confidence")
            audit_solo_exempt = solo_metal_sell_ok or audit_solo_trend_surfer_ok
            if (
                trend_min_conf is not None
                and decision.confidence < float(trend_min_conf)
                and not is_balancing_trade
                and not audit_solo_exempt
            ):
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"Trending regime requires confidence >= {float(trend_min_conf):.2f}"
                )
                return False
            trend_min_consensus = live_filters.get("trending_min_consensus_agents")
            if trend_min_consensus is not None:
                agreeing_technical = sum(
                    1 for s in signals
                    if s.is_actionable
                    and s.direction == decision.direction
                    and _counts_as_technical(s)
                )
                required_consensus = int(trend_min_consensus)
                if is_balancing_trade:
                    required_consensus = min(required_consensus, 1)
                    agreeing_technical += sum(
                        1 for s in signals
                        if s.is_actionable
                        and s.direction == decision.direction
                        and s.agent_name == "sentiment_agent"
                    )
                if agreeing_technical < required_consensus:
                    if not (audit_solo_trend_surfer_ok or solo_metal_sell_ok):
                        decision_record["status"] = "skipped"
                        decision_record["skip_reason"] = (
                            f"Trending regime requires {required_consensus} technical agents, "
                            f"got {agreeing_technical}"
                        )
                        return False

        if event_gate.min_confidence_override and decision.confidence < event_gate.min_confidence_override:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Event gate requires confidence>={event_gate.min_confidence_override}"
            )
            return False

        min_size_scale = phase_rules.get("min_orchestrator_size_scale")
        if min_size_scale and phase_rules.get("return_focus") and decision.direction.value != "HOLD":
            decision.size_scale = max(decision.size_scale, float(min_size_scale))

        event_size_mult = event_gate.size_multiplier
        size_mult = decision.size_scale * peer_adj * event_size_mult
        if self.intelligence.enabled:
            macro_adj = self.intelligence.macro.size_adjustment(symbol, decision.direction.value)
            size_mult *= macro_adj
            macro_cap = 1.12
            if live_filters.get("return_push"):
                macro_cap = float(live_filters.get("return_push_macro_scale_cap", 1.28))
            size_mult = min(size_mult, macro_cap * peer_adj * event_size_mult)
        if peer_conservative:
            size_mult = min(size_mult, peer_adj * event_size_mult)

        if active_size_boost:
            size_mult *= active_size_boost["orchestrator_scale_mult"]
            logger.info(
                "%s size boost for %s: orchestrator_scale x%.2f (conf=%.2f, agreeing=%d)",
                active_size_boost.get("boost_tier", "confluence"),
                symbol,
                active_size_boost["orchestrator_scale_mult"],
                decision.confidence,
                agreeing,
            )

        size_mult *= self._intraday_loss_size_mult()

        if self.intelligence.enabled and self._is_crypto_symbol(symbol):
            macro = self.intelligence.get_macro()
            fear_cutoff = phase_rules.get("macro_block_crypto_long_fear_below")
            if (
                macro.bias == "risk_off"
                and macro.usd_strength == "strong"
                and decision.direction.value == "BUY"
            ):
                if (
                    phase_rules.get("return_focus")
                    and fear_cutoff is not None
                    and macro.fear_greed is not None
                    and macro.fear_greed <= int(fear_cutoff)
                ):
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        f"Extreme fear ({macro.fear_greed}) — crypto long blocked in return-focus phase"
                    )
                    return False
                if decision.confidence < 0.78:
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        "Macro risk-off — crypto long blocked below 0.78 confidence"
                    )
                    return False

        instrument_bias = self.config.bias_for(symbol)
        bearish_long_min = float(
            live_filters.get("bearish_bias_long_min_confidence") or 0.85
        )
        bullish_short_min = float(
            live_filters.get("bullish_bias_short_min_confidence")
            or (0.90 if self._is_metal_symbol(symbol) else 0.85)
        )
        if instrument_bias == "bearish" and decision.direction.value == "BUY":
            bearish_long_threshold = bearish_long_min
            if is_balancing_trade:
                bearish_long_threshold = max(0.50, bearish_long_min - balance_conf_discount)
            if decision.confidence < bearish_long_threshold:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"Instrument bias {instrument_bias} — long requires confidence >= {bearish_long_threshold:.2f}"
                )
                return False
        elif instrument_bias == "bullish" and decision.direction.value == "SELL":
            if decision.confidence < bullish_short_min:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"Instrument bias {instrument_bias} — short requires confidence >= {bullish_short_min:.2f}"
                )
                return False

        if (
            self.intelligence.enabled
            and self._is_metal_symbol(symbol)
            and decision.direction.value == "SELL"
        ):
            macro = self.intelligence.get_macro()
            if macro.bias == "risk_off" and macro.usd_strength == "strong":
                agreeing_names = {
                    s.agent_name
                    for s in signals
                    if s.is_actionable and s.direction == decision.direction
                }
                dual_metal_audit_sell = (
                    agreeing >= 2
                    and "ml_signal" in agreeing_names
                    and "trend_surfer" in agreeing_names
                )
                metal_short_exempt = (
                    solo_metal_sell_ok
                    or audit_solo_trend_surfer_ok
                    or dual_metal_audit_sell
                    or "ML-metal SELL anchor" in (decision.reasoning or "")
                )
                if live_filters.get("block_metal_shorts_risk_off") and not metal_short_exempt:
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        "Macro risk-off — metal shorts blocked (safe-haven regime)"
                    )
                    return False
                metal_short_min = float(live_filters.get("macro_metal_short_min_confidence") or 0.92)
                if not metal_short_exempt and decision.confidence < metal_short_min:
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        f"Macro risk-off — metal short requires confidence >= {metal_short_min:.2f}"
                    )
                    return False

        if (
            live_filters.get("metals_mr_short_requires_trend_confirm")
            and self._is_metal_symbol(symbol)
            and decision.direction.value == "SELL"
        ):
            mr_sell = any(
                s.agent_name == "mean_reversion"
                and s.is_actionable
                and s.direction.value == "SELL"
                for s in signals
            )
            if mr_sell:
                trend_confirm = any(
                    s.agent_name in ("trend_surfer", "breakout_hunter")
                    and s.is_actionable
                    and s.direction.value == "SELL"
                    and s.confidence >= 0.70
                    for s in signals
                )
                if not trend_confirm:
                    decision_record["status"] = "skipped"
                    decision_record["skip_reason"] = (
                        "Metals MR short requires trend/breakout SELL confirm >= 0.70"
                    )
                    return False

        if (
            live_filters.get("block_ml_disagreement_on_crypto")
            and is_crypto
            and decision.direction.value in ("BUY", "SELL")
        ):
            ml_sig = next(
                (s for s in signals if s.agent_name == "ml_signal" and s.is_actionable),
                None,
            )
            if (
                ml_sig is not None
                and ml_sig.direction != decision.direction
                and ml_sig.confidence >= decision.confidence
            ):
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"ML signal disagrees ({ml_sig.direction.value} {ml_sig.confidence:.2f})"
                )
                return False

        block_dir_regimes = live_filters.get("block_direction_in_regimes") or {}
        sym_blocks = block_dir_regimes.get(symbol) or {}
        dir_blocks = sym_blocks.get(decision.direction.value) or []
        regime_key = primary_features.regime.value
        if decision.direction.value != "HOLD" and regime_key in dir_blocks:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: {decision.direction.value} blocked in {regime_key} regime"
            )
            return False

        trend_min_adx = live_filters.get("trending_min_adx")
        if (
            trend_min_adx is not None
            and regime_key == "trending"
            and decision.direction.value != "HOLD"
            and primary_features.adx < float(trend_min_adx)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: trending ADX {primary_features.adx:.1f} < {float(trend_min_adx):.0f}"
            )
            return False

        crypto_short_max_rsi = live_filters.get("crypto_short_max_rsi")
        if (
            is_crypto
            and crypto_short_max_rsi is not None
            and decision.direction.value == "SELL"
            and primary_features.rsi_14 > float(crypto_short_max_rsi)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: crypto RSI {primary_features.rsi_14:.1f} > "
                f"{float(crypto_short_max_rsi):.0f} — short into strength"
            )
            return False

        crypto_min_adx = live_filters.get("crypto_min_adx")
        if (
            is_crypto
            and crypto_min_adx is not None
            and decision.direction.value in ("BUY", "SELL")
            and primary_features.adx < float(crypto_min_adx)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: crypto ADX {primary_features.adx:.1f} < {float(crypto_min_adx):.0f} — no trend"
            )
            return False

        crypto_short_min_rsi = live_filters.get("crypto_short_min_rsi")
        if (
            is_crypto
            and crypto_short_min_rsi is not None
            and decision.direction.value == "SELL"
            and primary_features.rsi_14 < float(crypto_short_min_rsi)
            and agreeing < 3
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: crypto RSI {primary_features.rsi_14:.1f} < "
                f"{float(crypto_short_min_rsi):.0f} — short bounce risk"
            )
            return False

        crypto_short_min_conf = live_filters.get("crypto_short_min_confidence")
        if (
            is_crypto
            and crypto_short_min_conf is not None
            and decision.direction.value == "SELL"
            and decision.confidence < float(crypto_short_min_conf)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: crypto short confidence {decision.confidence:.2f} "
                f"< {float(crypto_short_min_conf):.2f}"
            )
            return False

        if (
            live_filters.get("entry_quality_enabled", True)
            and decision.direction.value != "HOLD"
        ):
            debate_side = "bull" if decision.direction.value == "BUY" else "bear"
            debate_confirms_q = debate.winner == debate_side
            agreeing_names = [
                s.agent_name
                for s in signals
                if s.is_actionable and s.direction == decision.direction
            ]
            symbol_rates = self.competition_strategy.symbol_rates(symbol)
            audit_rates: dict[str, float] = {}
            q = score_entry(
                symbol=symbol,
                direction=decision.direction.value,
                regime=primary_features.regime.value,
                adx=float(primary_features.adx),
                rsi=float(primary_features.rsi_14),
                confidence=float(decision.confidence),
                agreeing_agents=agreeing_names,
                symbol_rates=symbol_rates,
                audit_rates=audit_rates,
                debate_confirms=debate_confirms_q,
                solo_metal_sell_ok=bool(solo_metal_sell_ok),
                audit_solo_trend_surfer_ok=bool(audit_solo_trend_surfer_ok),
                audit_winner_symbols=frozenset(
                    live_filters.get("audit_winner_symbols") or ["USD/CAD", "XAG/USD"],
                ),
            )
            min_q = float(live_filters.get("min_entry_quality_score", 0.72))
            if not passes_quality_gate(
                q,
                min_score=min_q,
                allow_solo_metal_sell=bool(solo_metal_sell_ok),
                allow_audit_solo_trend_surfer=bool(audit_solo_trend_surfer_ok),
            ):
                skip = (
                    f"Entry quality {q.score:.2f} < {min_q:.2f} ({q.tier}) — "
                    + "; ".join(q.reasons[:3])
                )
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = skip
                decision_record["entry_quality_score"] = q.score
                decision_record["entry_quality_tier"] = q.tier
                return False
            decision_record["entry_quality_score"] = q.score
            decision_record["entry_quality_tier"] = q.tier
            if q.tier == "gold":
                size_mult *= float(live_filters.get("gold_quality_size_mult", 1.25))

        max_fx_shorts = live_filters.get("max_fx_shorts_per_cycle")
        if (
            max_fx_shorts is not None
            and self._is_fx_symbol(symbol)
            and decision.direction.value == "SELL"
            and self._fx_shorts_opened_this_cycle >= int(max_fx_shorts)
        ):
            skip = (
                f"Live filter: max FX shorts per cycle ({int(max_fx_shorts)}) reached"
            )
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = skip
            return False

        max_chf_entries = live_filters.get("max_chf_entries_per_cycle")
        if (
            max_chf_entries is not None
            and self._is_chf_symbol(symbol)
            and self._chf_entries_opened_this_cycle >= int(max_chf_entries)
        ):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Live filter: max CHF entries per cycle ({int(max_chf_entries)}) reached"
            )
            return False

        low_alloc_symbols = phase_rules.get("low_allocation_symbols", set())
        if phase_rules.get("low_allocation_requires_a_plus") and symbol in low_alloc_symbols:
            min_a_plus = phase_rules.get("min_confidence_a_plus", 0.80)
            if decision.confidence < min_a_plus:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = f"Low-allocation symbol requires A+ conf>={min_a_plus}"
                return False

        if phase_rules.get("crypto_only_if_dd_normal") and is_crypto and dd_state.tier != "normal":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Round 3 — crypto only at Normal DD tier"
            return False

        discipline_halt = phase_rules.get("discipline_halt_below")
        if discipline_halt and self.compliance_heartbeat.state.risk_discipline_score < discipline_halt:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Discipline score below {discipline_halt}"
            return False

        if not dd_state.allow_new_trades:
            logger.info("New trades blocked at tier %s", dd_state.tier)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Blocked at tier {dd_state.tier}"
            return False

        if is_crypto and not dd_state.allow_crypto:
            logger.info("Crypto blocked at drawdown tier %s — skipping %s", dd_state.tier, symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Crypto blocked at drawdown tier"
            return False

        if margin_state.block_new_trades or margin_state.action.startswith("EMERGENCY") or "hard stop" in margin_state.action.lower():
            logger.info("Margin block — skipping %s", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Margin block"
            return False

        if self._fill_undershoot_block and not self.simulation:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Prior fill undershoot — entries blocked"
            return False

        if self._fill_overshoot_block and not self.simulation:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Prior fill overshoot — entries blocked"
            return False

        if self.margin_monitor.concentration_blocks_entries(margin_state.concentration_pct):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Concentration above 40% cap"
            return False

        pre_send_snapshot = self._positions_snapshot()
        if not self.simulation and not pre_send_snapshot.trusted:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Position state unavailable (fail-closed)"
            return False
        open_positions = pre_send_snapshot.positions

        if self._symbol_has_position(symbol, open_positions):
            logger.info("Already have open position on %s — skipping duplicate entry", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Open position already exists"
            return False

        allocation = self.config.allocation_for(symbol)
        micro_cfg = self.config.risk.get("micro", {})
        if self.account_profile and self.account_profile.kind == "micro":
            max_risk_pct = micro_cfg.get("max_risk_per_trade", 0.005) * allocation
        else:
            base_max_risk = phase_rules.get("max_risk_pct", self.config.max_risk_pct())
            obj_risk_mult = self._objective_runtime_overrides()["risk_mult"]
            max_risk_pct = base_max_risk * obj_risk_mult * allocation

        if active_size_boost:
            max_risk_pct *= active_size_boost["max_risk_pct_mult"]
            max_risk_pct = min(max_risk_pct, active_size_boost["max_risk_pct_ceiling"] * allocation)

        specs = self._get_symbol_specs(symbol)
        if (
            specs
            and self.account_profile
            and self.account_profile.kind == "micro"
        ):
            max_notional_pct = micro_cfg.get("max_position_notional_pct", 0.25)
            min_notional = position_notional(
                specs["volume_min"],
                specs["contract_size"],
                primary_features.close,
            )
            if min_notional > equity * max_notional_pct:
                logger.info(
                    "Min lot notional %.4f exceeds %.0f%% equity cap for %s — skipping",
                    min_notional,
                    max_notional_pct * 100,
                    symbol,
                )
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = (
                    f"Min lot notional exceeds {max_notional_pct:.0%} equity cap"
                )
                return False

        win_rate = 0.55
        actionable = [s for s in signals if s.is_actionable and s.direction == decision.direction]
        if actionable:
            actionable.sort(key=lambda s: abs((s.stop_loss or primary_features.close) - primary_features.close))
        sl = actionable[0].stop_loss if actionable else None
        tp = actionable[0].take_profit if actionable else None
        agent_name = actionable[0].agent_name if actionable else "orchestrator"

        perf = self.memory.agent_performance(agent_name)
        if perf["sample_size"] >= 5:
            win_rate = perf["win_rate"]
        else:
            semantic = self.memory.get_semantic_context(
                primary_features.regime.value, symbol, session_name,
            )
            if semantic.get("best_agent"):
                best_perf = self.memory.agent_performance(semantic["best_agent"])
                if best_perf["sample_size"] >= 5:
                    win_rate = best_perf["win_rate"]

        if not self.simulation:
            exec_entry = self._executable_price(symbol, decision.direction.value) or primary_features.close
            sl, tp = self._sanitize_stops(
                symbol,
                decision.direction.value,
                exec_entry,
                sl,
                tp,
                primary_features.atr_14,
            )
        else:
            exec_entry = primary_features.close

        reward_risk_ratio = 1.5
        if sl is not None and tp is not None and exec_entry > 0:
            risk_dist = abs(exec_entry - sl)
            reward_dist = abs(tp - exec_entry)
            if risk_dist > 0:
                reward_risk_ratio = max(reward_dist / risk_dist, 0.1)

        size = self.kelly_sizer.compute_size(
            equity=equity,
            win_rate=win_rate,
            reward_risk_ratio=reward_risk_ratio,
            atr_14=primary_features.atr_14,
            atr_50=primary_features.atr_50,
            confidence=decision.confidence,
            phase_multiplier=self.config.phase_multiplier,
            drawdown_multiplier=dd_state.size_multiplier,
            orchestrator_scale=size_mult,
            allocation_cap=allocation,
            leverage_haircut=margin_state.leverage_haircut,
            margin_size_multiplier=margin_state.size_multiplier * self._size_multiplier,
            max_risk_override=max_risk_pct,
            competition_mode=self.config.current_phase in ("round1", "round2", "round3", "finals"),
            competition_mode_boost=float(
                self.config.phase_rules.get("competition_mode_boost", 1.4),
            ),
        )

        if not self.simulation:
            lots = self._risk_to_lots(symbol, size, exec_entry, sl, decision.direction.value)
            notional_price = exec_entry
        else:
            lots = size  # simulation keeps legacy behaviour
            notional_price = primary_features.close

        if lots > 0 and not self.simulation:
            lots = self._cap_lots_to_concentration(
                symbol, lots, notional_price, equity, open_positions,
            )
            max_fx_lots = live_filters.get("max_fx_lots")
            if active_size_boost and active_size_boost.get("max_fx_lots") is not None:
                max_fx_lots = active_size_boost["max_fx_lots"]
            if max_fx_lots is not None and self._is_fx_symbol(symbol):
                lots = min(lots, float(max_fx_lots))
            max_crypto_lots = live_filters.get("max_crypto_lots")
            if active_size_boost and active_size_boost.get("max_crypto_lots") is not None:
                max_crypto_lots = active_size_boost["max_crypto_lots"]
            if max_crypto_lots is not None and self._is_crypto_symbol(symbol):
                lots = min(lots, float(max_crypto_lots))
            max_metal_lots = live_filters.get("max_metal_lots")
            if active_size_boost and active_size_boost.get("max_metal_lots") is not None:
                max_metal_lots = active_size_boost["max_metal_lots"]
            if max_metal_lots is not None and self._is_metal_symbol(symbol):
                lots = min(lots, float(max_metal_lots))

        if lots <= 0 and not self.simulation and specs:
            bump_key = None
            bump_risk_override = None
            if self._is_crypto_symbol(symbol):
                bump_key = "crypto_min_lot_bump"
                if active_size_boost:
                    bump_risk_override = active_size_boost.get("crypto_min_lot_bump_risk_pct")
            elif self._is_fx_symbol(symbol):
                bump_key = "fx_min_lot_bump"
                if active_size_boost:
                    bump_risk_override = active_size_boost.get("fx_min_lot_bump_risk_pct")
            elif self._is_metal_symbol(symbol) and active_size_boost:
                bump_key = "fx_min_lot_bump"
                bump_risk_override = active_size_boost.get("metal_min_lot_bump_risk_pct")
            if bump_key:
                bump_cfg = (self._live_filters.get(bump_key) or {})
                if bump_cfg.get("enabled") or bump_risk_override is not None:
                    min_conf = float(bump_cfg.get("min_orchestrator_confidence", 0.78))
                    if active_size_boost:
                        boost_conf = float(
                            (live_filters.get("tier_a_plus_size_boost") or {}).get("min_confidence", 0.85)
                            if active_size_boost.get("boost_tier") == "tier_a_plus"
                            else (live_filters.get("audit_winner_size_boost") or {}).get("min_confidence", 0.80)
                        )
                        min_conf = min(min_conf, boost_conf)
                    max_risk_frac = float(bump_cfg.get("max_risk_pct_equity", 0.005))
                    if bump_risk_override is not None:
                        max_risk_frac = float(bump_risk_override)
                    sl_dist = abs(exec_entry - sl) if sl is not None else 0.0
                    min_lot_risk = specs["volume_min"] * sl_dist * specs["contract_size"]
                    if (
                        decision.confidence >= min_conf
                        and sl_dist > 0
                        and min_lot_risk <= equity * max_risk_frac
                    ):
                        lots = specs["volume_min"]
                        logger.info(
                            "Min-lot bump (%s) for %s: %.4f lots (risk=%.2f, cap=%.2f)",
                            bump_key,
                            symbol,
                            lots,
                            min_lot_risk,
                            equity * max_risk_frac,
                        )

        if lots <= 0:
            logger.info("Size below min lot for %s (risk=%.4f)", symbol, size)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Size below minimum lot"
            return False

        specs = self._get_symbol_specs(symbol)
        contract = specs["contract_size"] if specs else 1.0
        trade_notional = position_notional(lots, contract, notional_price)
        heat_ok, heat_reason = self.portfolio_heat.pre_trade_check(
            equity,
            open_positions,
            float(self.connector.get_account_info().get("gross_exposure", 0)),
            symbol,
            decision.direction.value,
            trade_notional,
            volume=lots,
            price=notional_price,
            contract_size=contract,
            get_contract_size=self._contract_lookup,
        )
        if not heat_ok:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = heat_reason or "Portfolio heat cap"
            return False

        from src.risk.pre_trade_gate import TradeCheckRequest, get_pre_trade_gate

        gate_check = get_pre_trade_gate().evaluate_from_engine(
            self,
            TradeCheckRequest(
                symbol=symbol,
                direction=decision.direction.value,
                volume=lots,
                sl=sl,
                tp=tp,
                price=notional_price,
                atr_14=primary_features.atr_14,
            ),
        )
        if not gate_check.allowed:
            decision_record["status"] = "skipped"
            blocker_msg = (
                gate_check.blockers[0].message if gate_check.blockers else "Pre-trade gate blocked"
            )
            decision_record["skip_reason"] = blocker_msg
            projected = gate_check.projected or {}
            if projected.get("projected_net_directional_pct") is not None:
                decision_record["projected_net_directional_pct"] = projected[
                    "projected_net_directional_pct"
                ]
            return False

        entry_mode = "market"
        limit_price: float | None = None
        pending = self._pending_limit_orders.get(symbol)
        if pending and not self.simulation:
            pending["cycles"] = int(pending.get("cycles", 0)) + 1
            if self._symbol_has_position(symbol, open_positions):
                self._pending_limit_orders.pop(symbol, None)
            elif pending["cycles"] >= 1:
                order_ticket = pending.get("order_ticket")
                if order_ticket and hasattr(self.connector, "cancel_pending_order"):
                    self.connector.cancel_pending_order(int(order_ticket))
                self._pending_limit_orders.pop(symbol, None)
                logger.info(
                    "Limit order unfilled for %s after 1 cycle — falling back to market",
                    symbol,
                )
            else:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = "Awaiting limit fill"
                return False

        if not self.simulation and pending is None:
            tick = self.live_feed.get_tick(symbol)
            atr = primary_features.atr_14
            if tick and atr > 0:
                spread = self._spread_for_symbol(symbol)
                if spread / atr > 0.10:
                    spread_buf = 0.3 * spread
                    if decision.direction.value == "BUY":
                        limit_price = tick.mid - spread_buf
                    else:
                        limit_price = tick.mid + spread_buf
                    entry_mode = "limit"
                    logger.info(
                        "Wide spread/ATR for %s (%.2f) — limit entry at %.5f",
                        symbol,
                        spread / atr,
                        limit_price,
                    )

        baseline_volume = 0.0
        if not self.simulation:
            baseline_volume = self._volume_for_symbol_direction(
                symbol, decision.direction.value,
            )

        result = self.connector.send_trade(
            symbol=symbol,
            direction=decision.direction.value,
            volume=lots,
            sl=sl,
            tp=tp,
            entry_mode=entry_mode,
            limit_price=limit_price,
        )
        if (
            entry_mode == "limit"
            and result.get("status") == "ok"
            and result.get("order_pending")
        ):
            self._pending_limit_orders[symbol] = {
                "order_ticket": result.get("order_ticket"),
                "cycles": 0,
                "direction": decision.direction.value,
                "volume": lots,
                "sl": sl,
                "tp": tp,
            }
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Limit order placed at {limit_price:.5f}"
            return False

        ticket = result.get("ticket")
        actual_volume = lots
        fill_confirmed = self.simulation
        if not self.simulation and result.get("status") in ("ok", "simulated"):
            validated: int | None = None
            if ticket:
                validated = self._validate_open_ticket(
                    symbol, decision.direction.value, int(ticket),
                )
            elif result.get("status") == "ok":
                validated = self._resolve_open_ticket(
                    symbol, decision.direction.value, 0,
                )
            if validated:
                ticket = validated
                actual_volume = self._log_position_reconcile(
                    int(ticket),
                    lots,
                    "OPEN",
                    result,
                    symbol=symbol,
                    direction=decision.direction.value,
                    baseline_volume=baseline_volume,
                )
                partial_min = float(os.getenv("PARTIAL_FILL_MIN_RATIO", "0.8") or 0)
                if os.getenv("PARTIAL_FILL_ABORT", "true").lower() not in ("1", "true", "yes"):
                    partial_min = 0.0
                if (
                    partial_min > 0
                    and actual_volume > VOLUME_EPS
                    and actual_volume < lots * partial_min
                ):
                    logger.warning(
                        "Partial fill below threshold ticket=%d — intended %.4f, got %.4f (min %.0f%%)",
                        ticket,
                        lots,
                        actual_volume,
                        partial_min * 100,
                    )
                    fill_confirmed = False
                    self._sync_open_trades_from_mt5()
                elif actual_volume > VOLUME_EPS:
                    fill_confirmed = True
                    if actual_volume < lots - VOLUME_EPS:
                        logger.warning(
                            "Partial fill ticket=%d — intended %.4f lots, got %.4f lots (ledger synced)",
                            ticket,
                            lots,
                            actual_volume,
                        )
                        lots = actual_volume
                else:
                    fill_confirmed = False
                    self._sync_open_trades_from_mt5()
            else:
                fill_confirmed = False
                ticket = None
        elif self.simulation and ticket:
            fill_confirmed = True

        exec_status = result.get("status", "executed")
        error_msg = result.get("message")
        if exec_status not in ("ok", "simulated"):
            if not self.simulation:
                for delay in (0.5, 1.0, 2.5):
                    time.sleep(delay)
                    recovered_ticket = self._resolve_open_ticket(
                        symbol, decision.direction.value, 0,
                    )
                    if not recovered_ticket:
                        continue
                    new_vol = self._volume_for_symbol_direction(
                        symbol, decision.direction.value,
                    )
                    if new_vol > baseline_volume + 1e-4:
                        ticket = recovered_ticket
                        fill_confirmed = True
                        exec_status = "ok"
                        error_msg = None
                        logger.warning(
                            "Recovered late fill for %s ticket=%d after ZMQ error",
                            symbol,
                            ticket,
                        )
                        break
        if exec_status not in ("ok", "simulated"):
            logger.error("Trade failed for %s: %s", symbol, error_msg or exec_status)
            exec_status = "error"
        elif not fill_confirmed and not self.simulation:
            exec_status = "error"
            error_msg = error_msg or "Fill not confirmed after OPEN reconcile"
            logger.error("Fill abort for %s: %s", symbol, error_msg)
            ticket = None

        fill_price = resolve_fill_price(
            result,
            int(ticket) if ticket else None,
            symbol,
            notional_price,
            self.connector,
        )

        self.trade_logger.log(
            symbol=symbol,
            regime=primary_features.regime.value,
            session=session_name,
            direction=decision.direction.value,
            confidence=decision.confidence,
            agent_votes=decision.agent_votes,
            size=lots,
            sl=sl,
            tp=tp,
            slippage=result.get("slippage", 0),
            latency_ms=result.get("latency_ms", 0),
            status=exec_status,
            reasoning=decision.reasoning,
            extra={
                "ticket": ticket,
                "entry_price": fill_price,
                **({"error": error_msg} if error_msg else {}),
            },
        )

        decision_record["status"] = exec_status
        decision_record["size"] = lots
        if error_msg:
            decision_record["skip_reason"] = error_msg

        if ticket and fill_confirmed:
            decision_record["scan_stage"] = "executed"
            self._log_cycle_event(
                "entry",
                symbol,
                direction=decision.direction.value,
                reason=decision.reasoning,
                ticket=int(ticket),
                extra={
                    "confidence": decision.confidence,
                    "consensus_agreeing": decision_record.get("consensus_agreeing"),
                    "consensus_required": decision_record.get("consensus_required"),
                    "size": lots,
                },
            )
            semantic_ctx = self.memory.get_semantic_context(
                primary_features.regime.value, symbol, session_name,
            )
            attribution = build_trade_attribution(
                signals=signals,
                decision_direction=decision.direction.value,
                primary_agent=agent_name,
                orchestrator_used_ai=getattr(decision, "used_ai", False),
                semantic_best_agent=semantic_ctx.get("best_agent"),
            )
            self.position_manager.register_entry(
                ticket, symbol, decision.direction.value,
                fill_price, sl, lots,
                primary_features.regime.value,
            )
            self._ensure_position_stops(int(ticket), symbol, sl, tp)
            self._open_trades[ticket] = {
                "symbol": symbol,
                "direction": decision.direction.value,
                "entry_price": fill_price,
                "volume": lots,
                "sl": sl,
                "session": session_name,
                "regime": primary_features.regime.value,
                "agent": agent_name,
                "features_snapshot": {
                    "adx": primary_features.adx,
                    "rsi_14": primary_features.rsi_14,
                    "atr_14": primary_features.atr_14,
                },
                "agent_votes": [
                    {"agent": s.agent_name, "direction": s.direction.value, "confidence": s.confidence}
                    for s in signals
                ],
                "attribution_json": attribution,
                "reasoning": decision.reasoning,
                "entry_time": datetime.now(timezone.utc).isoformat(),
            }
            if self._is_fx_symbol(symbol) and decision.direction.value == "SELL":
                self._fx_shorts_opened_this_cycle += 1
            if self._is_chf_symbol(symbol):
                self._chf_entries_opened_this_cycle += 1
            if self._is_crypto_symbol(symbol):
                self._crypto_entries_opened_this_cycle += 1
            if active_size_boost and active_size_boost.get("boost_tier") == "tier_aa_plus":
                self._aa_plus_entries_opened_this_cycle += 1
                self._open_trades[ticket]["attribution_json"]["trade_style"] = "aa_plus"
            elif active_size_boost and active_size_boost.get("boost_tier") == "tier_a_plus":
                self._open_trades[ticket]["attribution_json"]["trade_style"] = "a_plus"
            elif active_size_boost and active_size_boost.get("boost_tier") == "runner":
                self._runner_entries_opened_this_cycle += 1
                self._open_trades[ticket]["attribution_json"]["trade_style"] = "runner"

        logger.info("Executed: %s", result)
        return exec_status in ("ok", "simulated") and bool(ticket) and fill_confirmed

    def _backtest_agent_win_rates(self) -> dict[str, float]:
        """Win rates from pricer_backtest round trades in layered memory."""
        rates: dict[str, float] = {}
        for agent_name in ("trend_surfer", "breakout_hunter", "momentum_pulse", "mean_reversion", "ml_signal"):
            perf = self.memory.agent_performance(agent_name)
            if perf["sample_size"] >= 3:
                rates[agent_name] = perf["win_rate"]
        return rates

    def _get_ohlcv(self, symbol: str, timeframe: str = "M15") -> pd.DataFrame | None:
        if self.simulation:
            import numpy as np

            n = 200
            price = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
            return pd.DataFrame({
                "open": price,
                "high": price + np.abs(np.random.randn(n) * 0.3),
                "low": price - np.abs(np.random.randn(n) * 0.3),
                "close": price + np.random.randn(n) * 0.1,
                "volume": np.random.randint(100, 1000, n).astype(float),
            })

        if self._prefer_mt5_market_data():
            mt5_df = self._get_ohlcv_mt5_fallback(symbol, timeframe)
            if mt5_df is not None and len(mt5_df) >= 50:
                if timeframe == "M15":
                    self._ohlcv_source[symbol] = "mt5_primary"
                return mt5_df

        df = self.connector.get_ohlcv(symbol, timeframe=timeframe, count=OHLCV_BAR_COUNT)
        zmq_bars = len(df) if df is not None else 0
        if df is not None and zmq_bars >= 50:
            if timeframe == "M15":
                self._ohlcv_source[symbol] = "zmq"
            return df
        if zmq_bars > 0:
            logger.debug(
                "ZMQ OHLCV insufficient for %s %s (%d/50 bars) — trying MT5 fallback",
                symbol,
                timeframe,
                zmq_bars,
            )
        fallback = self._get_ohlcv_mt5_fallback(symbol, timeframe)
        if fallback is not None and len(fallback) >= 50:
            if timeframe == "M15":
                self._ohlcv_source[symbol] = "mt5_fallback"
            logger.info(
                "OHLCV fallback via MT5 API for %s %s (%d bars, zmq had %d)",
                symbol,
                timeframe,
                len(fallback),
                zmq_bars,
            )
            return fallback
        parquet_df = self._get_ohlcv_parquet_fallback(symbol, timeframe)
        if parquet_df is not None and len(parquet_df) >= 50:
            if timeframe == "M15":
                self._ohlcv_source[symbol] = "parquet_fallback"
            logger.info(
                "OHLCV parquet fallback for %s %s (%d bars)",
                symbol,
                timeframe,
                len(parquet_df),
            )
            return parquet_df
        if timeframe == "M15":
            self._ohlcv_source[symbol] = "none"
        return None

    def _get_ohlcv_parquet_fallback(
        self,
        symbol: str,
        timeframe: str = "M15",
    ) -> pd.DataFrame | None:
        """Tail historical parquet when live bridges fail (48h stale guard)."""
        if timeframe != "M15":
            return None
        path = Path("data/historical") / f"{symbol.replace('/', '_')}.parquet"
        if not path.exists():
            return None
        try:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours > 48:
                logger.debug("Parquet fallback stale for %s (%.1fh old)", symbol, age_hours)
                return None
            df = pd.read_parquet(path).tail(OHLCV_BAR_COUNT)
            if df.empty:
                return None
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = df[col].astype(float)
            return df if len(df) >= 50 else None
        except Exception:
            logger.debug("Parquet OHLCV fallback failed for %s", symbol, exc_info=True)
            return None

    def _get_ohlcv_mt5_fallback(self, symbol: str, timeframe: str = "M15") -> pd.DataFrame | None:
        """Read bars from MT5 Python API when the ZeroMQ DATA command is contended or slow."""
        try:
            from src.integrations.mt5_session import ensure_mt5_session

            ok, _ = ensure_mt5_session(require_login=False)
            if not ok:
                return None
            import MetaTrader5 as mt5

            tf_map = {
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            mt5_sym = symbol.replace("/", "").upper()
            tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)
            mt5.symbol_select(mt5_sym, True)
            rates = mt5.copy_rates_from_pos(mt5_sym, tf, 0, OHLCV_BAR_COUNT)
            if rates is None or len(rates) == 0:
                return None
            df = pd.DataFrame(rates)
            df = df.rename(columns={"time": "timestamp", "tick_volume": "volume"})
            for col in ("open", "high", "low", "close", "volume"):
                if col in df.columns:
                    df[col] = df[col].astype(float)
            return df if len(df) >= 50 else None
        except Exception:
            logger.debug("MT5 OHLCV fallback failed for %s", symbol, exc_info=True)
            return None

    def run(self, cycle_minutes: int | None = None) -> None:
        """Run the engine in a continuous loop."""
        import threading

        if cycle_minutes is not None:
            self._cycle_minutes = cycle_minutes
            self.state_publisher.cycle_minutes = cycle_minutes

        self.start()
        self._running = True
        self._publish_state()

        def heartbeat() -> None:
            while self._running:
                time.sleep(15)
                if self._running:
                    try:
                        if not self.simulation:
                            if not self.connector.refresh_health():
                                logger.warning(
                                    "ZeroMQ bridge offline: %s",
                                    self.connector.last_error,
                                )
                        self._publish_state()
                    except Exception:
                        logger.debug("Heartbeat publish failed", exc_info=True)

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            daemon=True,
            name="quantai-state-heartbeat",
        )
        heartbeat_thread.start()

        interval = self._cycle_minutes
        logger.info("Running decision loop every %d minutes", interval)
        try:
            while True:
                cycle_start = datetime.now(timezone.utc)
                logger.info("--- Cycle start: %s ---", cycle_start.isoformat())
                self.run_cycle()
                elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
                sleep_secs = max(0, interval * 60 - elapsed)
                logger.info("Cycle complete in %.1fs — sleeping %.0fs", elapsed, sleep_secs)
                time.sleep(sleep_secs)
        except KeyboardInterrupt:
            logger.info("Engine stopped by user")
        finally:
            self._running = False
            self.live_feed.stop()
            if self._margin_watcher:
                self._margin_watcher.stop()
            self._publish_state()
            self.compliance_heartbeat.stop()
            self.connector.close()
