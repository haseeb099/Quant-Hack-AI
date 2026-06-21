"""Main trading engine — 15-minute decision loop."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd

from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.context_builder import ContextBuilder
from src.agents.debate_orchestrator import DebateOrchestrator
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.meta_orchestrator import MetaOrchestrator
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.sentiment_agent import SentimentAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.bridges.zeromq_connector import ZeroMQConnector
from src.data.feature_engine import FeatureEngine
from src.data.live_feed import LiveFeed
from src.data.market_validator import MarketValidator
from src.data.session_filter import SessionFilter
from src.engine.adaptation_loader import apply_adaptation_to_config, load_adaptation_plan
from src.engine.config import QuantAIConfig, load_yaml
from src.intelligence.market_intelligence import MarketIntelligenceService
from src.intelligence.peer_monitor import PeerMonitor
from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.risk.account_profile import AccountProfile, detect_profile, position_notional
from src.risk.compliance import ComplianceEngine
from src.risk.compliance_heartbeat import ComplianceHeartbeat
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.kelly_sizer import KellySizer
from src.risk.lot_sizer import pnl_pct, risk_to_lots
from src.risk.margin_monitor import MarginMonitor
from src.risk.portfolio_heat import PortfolioHeat
from src.risk.position_manager import PositionManager
from src.risk.sharpe_guard import SharpeGuard
from src.utils.logger import instrument_span, log_trade_decision
from src.utils.trade_logger import TradeLogger
from src.web.state_publisher import StatePublisher

logger = logging.getLogger(__name__)

CYCLE_MINUTES = 15


class TradingEngine:
    """Orchestrates the full decision loop every 15 minutes."""

    def __init__(self, config: QuantAIConfig, simulation: bool = False) -> None:
        self.config = config
        self.simulation = simulation
        self.feature_engine = FeatureEngine()
        self.connector = ZeroMQConnector()
        self.memory = LayeredMemory(round_id=config.current_phase)
        self.context_builder = ContextBuilder(self.memory)
        self.debate_orchestrator = DebateOrchestrator()
        self.peer_monitor = PeerMonitor(round_id=config.current_phase)
        self.intelligence = MarketIntelligenceService()
        self.trade_logger = TradeLogger()
        self.sharpe_guard = SharpeGuard()
        self.compliance_heartbeat = ComplianceHeartbeat(config.risk)

        phases_cfg = load_yaml("phases.yaml")
        self.session_filter = SessionFilter(phases_cfg.get("sessions", {}))

        adaptation_plan = load_adaptation_plan()
        apply_adaptation_to_config(config, adaptation_plan)

        agent_weights = {
            name: float(cfg.get("weight", 0.25))
            for name, cfg in config.agents.items()
            if name != "meta_orchestrator"
        }
        agent_best_regimes = {
            name: cfg.get("best_regimes", [])
            for name, cfg in config.agents.items()
            if name != "meta_orchestrator"
        }
        orch_cfg = dict(config.agent_config("meta_orchestrator"))
        orch_cfg["anthropic_api_key"] = orch_cfg.get("anthropic_api_key") or __import__("os").getenv("ANTHROPIC_API_KEY")
        orch_cfg["agent_weights"] = agent_weights
        orch_cfg["agent_best_regimes"] = agent_best_regimes

        self.agents = [
            TrendSurferAgent(config.agent_config("trend_surfer")),
            BreakoutHunterAgent(config.agent_config("breakout_hunter")),
            MomentumPulseAgent(config.agent_config("momentum_pulse")),
            MeanReversionAgent(config.agent_config("mean_reversion")),
        ]
        if self.intelligence.enabled and os.getenv("SENTIMENT_AGENT_ENABLED", "true").lower() not in ("0", "false"):
            self.agents.append(SentimentAgent(config.agent_config("sentiment_agent")))
        self.orchestrator = MetaOrchestrator(
            orch_cfg, config.regime_boosts, agent_weights, agent_best_regimes,
        )
        self.market_validator = MarketValidator()
        self.live_feed = LiveFeed(
            self.connector,
            symbols=config.active_symbols,
            feature_update_seconds=config.feature_update_seconds,
            simulation=simulation,
        )

        risk = config.risk
        self.drawdown_guard = DrawdownGuard(risk.get("drawdown", {}))
        self.kelly_sizer = KellySizer(risk.get("sizing", {}))
        self.margin_monitor = MarginMonitor(
            risk.get("margin", {}),
            risk.get("leverage", {}),
            risk.get("concentration", {}),
            risk.get("drawdown", {}),
        )
        self.compliance = ComplianceEngine(risk.get("compliance", {}))
        self.position_manager = PositionManager(config.phase_rules)
        self.portfolio_heat = PortfolioHeat(1_000_000)
        self.account_profile: AccountProfile | None = None
        self.state_publisher = StatePublisher()
        self._size_multiplier = 1.0
        self._open_trades: dict[int, dict] = {}
        self._peak_equity: float = 0.0
        self._prev_dd_tier: str = "normal"
        self._cycle_decisions: list[dict] = []
        self._cycle_votes: list[dict] = []
        self._instrument_regimes: dict[str, str] = {}
        self._running = False
        self._paused = False
        self._cycle_in_progress = False
        self._last_cycle_at: str | None = None
        self._next_cycle_at: str | None = None

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
        if self._cycle_in_progress:
            return {"status": "busy"}
        self.run_cycle()
        return {"status": "ok"}

    def operator_close_position(self, ticket: int) -> dict:
        result = self.connector.close_position(ticket)
        self._publish_state()
        return result

    def operator_close_all(self) -> dict:
        result = self.connector.close_all()
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
            if not self.connector.connect():
                raise RuntimeError("ZeroMQ bridge not connected — start DWX_ZeroMQ_Server in MT5")
            time.sleep(1.5)  # ZMQ slow-joiner warmup
            self._init_mt5_session()
        self._running = True
        account = self.connector.get_account_info()
        equity = account.get("equity", 1_000_000)
        self.account_profile = detect_profile(equity)
        self.portfolio_heat = PortfolioHeat(equity)
        self.drawdown_guard.reset(equity)
        self.margin_monitor.reset_session(equity)
        self._peak_equity = equity
        self._initial_equity = equity
        self.position_manager = PositionManager(self.config.phase_rules)

        if not self.simulation:
            self.live_feed.start()
            self.compliance_heartbeat.start(
                metrics_fn=self._compliance_metrics,
                action_callback=self._handle_compliance_actions,
            )

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
            import os

            import MetaTrader5 as mt5

            path = os.getenv("MT5_PATH")
            login = os.getenv("MT5_LOGIN")
            password = os.getenv("MT5_PASSWORD")
            server = os.getenv("MT5_SERVER")
            if not all([login, password, server]):
                return
            if not mt5.initialize(path=path):
                logger.warning("MT5 lot-size helper init failed: %s", mt5.last_error())
                return
            if not mt5.login(int(login), password=password, server=server):
                logger.warning("MT5 lot-size helper login failed: %s", mt5.last_error())
        except ImportError:
            logger.warning("MetaTrader5 package not installed — lot sizes may be approximate")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return symbol.replace("/", "").upper()

    def _symbol_has_position(self, symbol: str, open_positions: list[dict]) -> bool:
        target = self._normalize_symbol(symbol)
        for pos in open_positions:
            if self._normalize_symbol(str(pos.get("symbol", ""))) == target:
                return True
        return False

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

    def _get_symbol_info(self, symbol: str) -> dict[str, float] | None:
        try:
            import MetaTrader5 as mt5

            mt5_symbol = self._normalize_symbol(symbol)
            if not mt5.symbol_select(mt5_symbol, True):
                return None
            info = mt5.symbol_info(mt5_symbol)
            if info is None:
                return None
            return {
                "contract_size": float(info.trade_contract_size),
                "volume_min": float(info.volume_min),
                "volume_step": float(info.volume_step),
                "volume_max": float(info.volume_max),
                "digits": float(info.digits),
                "point": float(info.point),
                "stops_level": float(info.trade_stops_level),
            }
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
        min_dist = max(stops_level * point, point * 10, atr * 0.25)

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

    def _risk_to_lots(self, symbol: str, risk_amount: float, entry: float, stop_loss: float | None) -> float:
        specs = self._get_symbol_specs(symbol)
        if specs is None:
            logger.warning("No symbol specs for %s — using min lot fallback", symbol)
            return 0.01 if risk_amount > 0 else 0.0
        return risk_to_lots(
            risk_amount=risk_amount,
            entry=entry,
            stop_loss=stop_loss,
            contract_size=specs["contract_size"],
            volume_min=specs["volume_min"],
            volume_step=specs["volume_step"],
            volume_max=specs["volume_max"],
        )

    def _compliance_metrics(self) -> dict[str, float]:
        account = self.connector.get_account_info()
        equity = account.get("equity", 1_000_000)
        margin_state = self.margin_monitor.check(
            equity=equity,
            used_margin=account.get("margin", 0),
            gross_exposure=account.get("gross_exposure", 0),
            largest_position_pct=account.get("largest_position_pct", 0),
        )
        return {
            "margin_usage_pct": margin_state.margin_usage_pct,
            "effective_leverage": margin_state.effective_leverage,
            "concentration_pct": margin_state.concentration_pct,
        }

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
        self._publish_state()

    def _reduce_largest_position(self, fraction: float = 0.5) -> None:
        positions = self.connector.get_positions()
        if not positions:
            return
        equity = self.connector.get_account_info().get("equity", 1)
        largest = max(
            positions,
            key=lambda p: abs(float(p.get("volume", 0)) * float(p.get("price_open", 0))),
        )
        ticket = largest.get("ticket")
        volume = float(largest.get("volume", 0))
        if not ticket or volume <= 0:
            return
        close_vol = max(volume * fraction, 0.01)
        if close_vol >= volume:
            self.connector.close_position(ticket)
            self._finalize_trade(ticket, largest, equity)
        else:
            symbol = largest.get("symbol", "")
            direction = "SELL" if str(largest.get("type", "BUY")).upper() in ("BUY", "0") else "BUY"
            self.connector.send_trade(symbol, direction, close_vol, ticket=ticket)

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
        equity = account.get("equity", 1_000_000)
        dd_state = self.drawdown_guard.update(equity)
        drawdown_pct = (self.drawdown_guard.peak_equity - equity) / max(self.drawdown_guard.peak_equity, 1)
        margin_state = self.margin_monitor.check(
            equity=equity,
            used_margin=account.get("margin", 0),
            gross_exposure=account.get("gross_exposure", 0),
            largest_position_pct=account.get("largest_position_pct", 0),
        )
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
            self._next_cycle_at = (cycle_start + timedelta(minutes=CYCLE_MINUTES)).isoformat()
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
                "equity": equity,
                "balance": account.get("balance", equity),
                "margin": account.get("margin", 0),
                "free_margin": account.get("free_margin", equity),
                "gross_exposure": account.get("gross_exposure", 0),
                "initial_equity": getattr(self, "_initial_equity", equity),
            },
            "positions": self.connector.get_positions(),
            "risk": {
                "dd_tier": dd_state.tier,
                "drawdown_pct": drawdown_pct,
                "sharpe": self.sharpe_guard.compute_running_sharpe(),
                "discipline": compliance.risk_discipline_score,
                "margin": {
                    "margin_usage_pct": margin_state.margin_usage_pct,
                    "effective_leverage": margin_state.effective_leverage,
                    "concentration_pct": margin_state.concentration_pct,
                    "action": margin_state.action,
                },
                "violations": compliance.active_violations,
            },
            "last_cycle": {
                "symbols_processed": len(self._cycle_decisions),
                "decisions": self._cycle_decisions,
                "agent_votes": self._cycle_votes,
            },
            "instruments": self._build_instruments_state(),
            "market": {
                "last_tick_at": now.isoformat(),
                "last_tick_age_ms": self.live_feed.youngest_tick_age_ms(),
            },
            "intelligence": self.intelligence.snapshot() if self.intelligence.enabled else {"enabled": False},
        }
        self.state_publisher.publish(snapshot)

    def _build_instruments_state(self) -> dict[str, dict]:
        session = self.session_filter.current_session()
        out: dict[str, dict] = {}
        for symbol in self.config.active_symbols:
            regime = self._instrument_regimes.get(symbol, "unknown")
            tick = self.live_feed.get_tick(symbol)
            sentiment = self.intelligence.get_sentiment(symbol) if self.intelligence.enabled else None
            out[symbol] = {
                "last_regime": regime,
                "session_active": self.session_filter.should_trade_symbol(symbol),
                "bid": tick.bid if tick else None,
                "ask": tick.ask if tick else None,
                "mid": tick.mid if tick else None,
                "spread": tick.spread if tick else None,
                "tick_age_ms": tick.tick_age_ms if tick else None,
                "health": "green" if tick and tick.tick_age_ms < 2000 else "amber",
                "sentiment_score": sentiment.score if sentiment else None,
                "sentiment_confidence": sentiment.confidence if sentiment else None,
                "sentiment_summary": sentiment.summary if sentiment else None,
            }
        return out

    def run_cycle(self) -> None:
        """Execute one 15-minute decision cycle across all active symbols."""
        self._run_cycle_body()

    @instrument_span("quantai.run_cycle")
    def _run_cycle_body(self) -> None:
        cycle_start = datetime.now(timezone.utc)
        self._cycle_decisions = []
        self._cycle_votes = []
        self._cycle_in_progress = True
        try:
            if not self.compliance.record_api_request():
                logger.warning("API rate limit approached — skipping cycle")
                return

            account = self.connector.get_account_info()
            equity = account.get("equity", 1_000_000)
            dd_state = self.drawdown_guard.update(equity)
            drawdown_pct = (self.drawdown_guard.peak_equity - equity) / max(self.drawdown_guard.peak_equity, 1)

            if equity > self._peak_equity:
                self._peak_equity = equity
            self.sharpe_guard.record_equity(equity)

            if dd_state.tier == "emergency":
                logger.critical("EMERGENCY: %s — closing all positions", dd_state.message)
                self._sync_risk_event("EMERGENCY_DRAWDOWN", dd_state.message, "critical")
                self.connector.close_all()
                return

            margin_state = self.margin_monitor.check(
                equity=equity,
                used_margin=account.get("margin", 0),
                gross_exposure=account.get("gross_exposure", 0),
                largest_position_pct=account.get("largest_position_pct", 0),
            )

            if margin_state.action != "normal":
                logger.warning("Margin: %s", margin_state.message)
                self.state_publisher.publish_risk_event(
                    "margin",
                    margin_state.message,
                    "warning",
                    {"margin_state": margin_state.action, "margin_usage_pct": margin_state.margin_usage_pct},
                )

            if margin_state.close_worst_loser or margin_state.action.startswith("EMERGENCY"):
                self._close_worst_loser(equity)
            elif margin_state.reduce_positions_pct > 0:
                self._reduce_largest_position(fraction=margin_state.reduce_positions_pct)

            self._manage_positions(equity, dd_state, margin_state)

            peer_adj = 1.0
            peer_sentiment = "mixed"
            peer_data = self._build_peer_data(equity)
            if peer_data:
                peer_snapshot = self.peer_monitor.update(peer_data)
                peer_adj = self.peer_monitor.sizing_adjustment()
                peer_sentiment = peer_snapshot.crowd_bias

            if self.intelligence.enabled:
                self.intelligence.refresh(self.config.active_symbols)
                self.intelligence.persist_snapshot()

            if self._paused:
                logger.info("Engine paused — managing exits only, no new entries")
            else:
                session = self.session_filter.current_session()
                open_positions = self.connector.get_positions()
                for symbol in self.config.active_symbols:
                    if not self.session_filter.should_trade_symbol(symbol):
                        logger.debug("Session filter skip: %s (session=%s)", symbol, session.name)
                        continue
                    if self._symbol_has_position(symbol, open_positions):
                        logger.debug("Skip %s — position already open", symbol)
                        continue
                    self._process_symbol(
                        symbol, equity, dd_state, margin_state, session.name, drawdown_pct,
                        peer_adj=peer_adj, peer_sentiment=peer_sentiment,
                        preferred_agents=session.preferred_agents,
                    )
        finally:
            self._cycle_in_progress = False
            self._publish_state(cycle_start)

    def _close_worst_loser(self, equity: float) -> None:
        positions = self.connector.get_positions()
        losers = [p for p in positions if float(p.get("profit", 0)) < 0]
        if not losers:
            return
        worst = min(losers, key=lambda p: float(p.get("profit", 0)))
        ticket = worst.get("ticket")
        if ticket:
            logger.warning("Margin emergency — closing worst loser ticket %d", ticket)
            self.connector.close_position(ticket)
            self._finalize_trade(ticket, worst, equity)

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

    def _build_peer_data(self, equity: float) -> dict | None:
        """Build peer leaderboard payload from env API or simulation defaults."""
        import json
        import os
        import urllib.error
        import urllib.request

        our_return = (equity - self._initial_equity) / max(self._initial_equity, 1)
        api_url = os.getenv("COMPETITION_LEADERBOARD_URL", "").strip()
        if api_url and not self.simulation:
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

        if self.simulation or os.getenv("PEER_MONITOR_MOCK", "true").lower() in ("1", "true", "yes"):
            return {
                "peer_count": 100,
                "avg_return": 0.02,
                "avg_drawdown": 0.04,
                "top_performer_return": 0.06,
                "our_return": our_return,
                "our_rank": 55,
            }
        return None

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

    def _manage_positions(self, equity: float, dd_state, margin_state) -> None:
        positions = self.connector.get_positions()
        atr_by_symbol: dict[str, float] = {}
        current_prices: dict[str, float] = {}
        for pos in positions:
            sym = str(pos.get("symbol", ""))
            if not sym:
                continue
            price = self._current_price(sym)
            if price is not None:
                current_prices[sym] = price
            ticket = pos.get("ticket")
            tracked = self._open_trades.get(ticket, {}) if ticket else {}
            atr = tracked.get("features_snapshot", {}).get("atr_14")
            if atr:
                atr_by_symbol[sym] = float(atr)

        exit_actions = self.position_manager.evaluate(
            positions,
            self._instrument_regimes,
            atr_by_symbol,
            current_prices,
        )
        for action in exit_actions:
            if action.action == "close":
                logger.info("PositionManager closing %d: %s", action.ticket, action.reason)
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                self.connector.close_position(action.ticket)
                self._finalize_trade(action.ticket, pos, equity)
                self.position_manager.on_close(action.ticket)
            elif action.action == "partial_close" and action.volume:
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                symbol = pos.get("symbol", "")
                direction = "SELL" if str(pos.get("type", "BUY")).upper() in ("BUY", "0") else "BUY"
                self.connector.send_trade(symbol, direction, action.volume, ticket=action.ticket)
            elif action.action == "modify_sl" and action.new_sl is not None:
                pos = next((p for p in positions if p.get("ticket") == action.ticket), {})
                self.connector.modify_position(action.ticket, sl=action.new_sl, tp=pos.get("tp"))
                if action.ticket in self._open_trades:
                    self._open_trades[action.ticket]["sl"] = action.new_sl

        positions = self.connector.get_positions()
        for pos in positions:
            ticket = pos.get("ticket")
            if not ticket:
                continue

            symbol = pos.get("symbol", "")
            specs = self._get_symbol_specs(symbol)
            contract = specs["contract_size"] if specs else 1.0
            entry = float(pos.get("price_open", 0))
            volume = float(pos.get("volume", 0))
            profit = float(pos.get("profit", 0))
            position_pnl_pct = pnl_pct(profit, volume, entry, contract)

            if self.sharpe_guard.should_close_for_sharpe(position_pnl_pct, equity):
                logger.info("SharpeGuard closing ticket %d", ticket)
                self.connector.close_position(ticket)
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)
            elif dd_state.tier == "critical" and profit < 0:
                logger.info("Critical tier closing losing position %d", ticket)
                self.connector.close_position(ticket)
                self._finalize_trade(ticket, pos, equity)
                self.position_manager.on_close(ticket)

    def _finalize_trade(self, ticket: int, pos: dict, equity: float) -> None:
        tracked = self._open_trades.pop(ticket, None)
        if not tracked:
            return

        exit_price = self._resolve_exit_price(ticket, pos)
        entry_price = tracked.get("entry_price", exit_price)
        direction = tracked.get("direction", "BUY")
        sl_dist = abs(entry_price - tracked.get("sl", entry_price))
        pnl = float(pos.get("profit", 0))

        if sl_dist > 0:
            price_move = exit_price - entry_price if direction == "BUY" else entry_price - exit_price
            r_multiple = price_move / sl_dist
        else:
            r_multiple = pnl / max(equity * 0.01, 1)

        record = TradeRecord(
            trade_id=str(ticket),
            symbol=tracked.get("symbol", ""),
            session=tracked.get("session", ""),
            regime=tracked.get("regime", ""),
            agent=tracked.get("agent", ""),
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            r_multiple=r_multiple,
            pnl=pnl,
            features_snapshot=tracked.get("features_snapshot", {}),
            agent_votes=tracked.get("agent_votes", []),
            orchestrator_reasoning=tracked.get("reasoning", ""),
            entry_time=tracked.get("entry_time", ""),
            exit_time=datetime.now(timezone.utc).isoformat(),
            round_id=self.config.current_phase,
        )
        self.memory.store_trade(record)

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
    ) -> None:
        m15_df = self._get_ohlcv(symbol, "M15")
        if m15_df is None or len(m15_df) < 50:
            logger.debug("Insufficient data for %s", symbol)
            return

        event_gate = self.intelligence.evaluate_event_gate(symbol)
        if not event_gate.allowed:
            logger.info("Event gate blocked %s: %s", symbol, event_gate.reason)
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
            })
            return

        sentiment_snapshot = self.intelligence.get_sentiment(symbol)
        macro_regime = self.intelligence.get_macro().to_dict() if self.intelligence.enabled else {}
        upcoming_events = self.intelligence.upcoming_events()
        intel_context = {
            "sentiment_snapshot": sentiment_snapshot.to_dict() if sentiment_snapshot else {},
            "macro_regime": macro_regime,
            "event_gate": event_gate.to_dict(),
        }

        donchian_period = int(self.config.agent_config("breakout_hunter").get("donchian_period", 20))
        multi_features = self.feature_engine.compute_multi(symbol, m15_df, donchian_period)
        if not multi_features:
            return

        phase_rules = self.config.phase_rules
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

        primary_features = multi_features.get("M15") or next(iter(multi_features.values()))
        open_positions = self.connector.get_positions()
        self._instrument_regimes[symbol] = primary_features.regime.value
        self.market_validator.record_bar_time(symbol)

        tick = self.live_feed.get_tick(symbol)
        tick_mid = tick.mid if tick else None
        tick_age = tick.tick_age_ms if tick else 99999.0
        market_status = self.market_validator.validate(
            symbol, tick_mid, primary_features.close, primary_features.atr_14, tick_age,
        )
        if market_status.block_entries:
            logger.info("Market health RED for %s — %s", symbol, market_status.message)
            return

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

        decision = self.orchestrator.decide(
            primary_features, signals, dd_state.tier, context=context,
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
        })
        decision_record = self._cycle_decisions[-1]
        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}

        if decision.direction.value == "HOLD":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "HOLD decision"
            return

        if event_gate.min_confidence_override and decision.confidence < event_gate.min_confidence_override:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = (
                f"Event gate requires confidence>={event_gate.min_confidence_override}"
            )
            return

        event_size_mult = event_gate.size_multiplier
        macro_adj = 1.0
        if self.intelligence.enabled:
            macro_adj = self.intelligence.macro.size_adjustment(symbol, decision.direction.value)
        combined_adj = peer_adj * event_size_mult * macro_adj

        low_alloc_symbols = phase_rules.get("low_allocation_symbols", set())
        if phase_rules.get("low_allocation_requires_a_plus") and symbol in low_alloc_symbols:
            min_a_plus = phase_rules.get("min_confidence_a_plus", 0.80)
            if decision.confidence < min_a_plus:
                decision_record["status"] = "skipped"
                decision_record["skip_reason"] = f"Low-allocation symbol requires A+ conf>={min_a_plus}"
                return

        if phase_rules.get("crypto_only_if_dd_normal") and is_crypto and dd_state.tier != "normal":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Round 3 — crypto only at Normal DD tier"
            return

        discipline_halt = phase_rules.get("discipline_halt_below")
        if discipline_halt and self.compliance_heartbeat.state.risk_discipline_score < discipline_halt:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Discipline score below {discipline_halt}"
            return

        if not dd_state.allow_new_trades:
            logger.info("New trades blocked at tier %s", dd_state.tier)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Blocked at tier {dd_state.tier}"
            return

        if is_crypto and not dd_state.allow_crypto:
            logger.info("Crypto blocked at drawdown tier %s — skipping %s", dd_state.tier, symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Crypto blocked at drawdown tier"
            return

        if margin_state.block_new_trades or margin_state.action.startswith("EMERGENCY") or "hard stop" in margin_state.action.lower():
            logger.info("Margin block — skipping %s", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Margin block"
            return

        if self.margin_monitor.concentration_blocks_symbol(symbol, margin_state.concentration_pct):
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Concentration above 40% cap"
            return

        if self._symbol_has_position(symbol, open_positions):
            logger.info("Already have open position on %s — skipping duplicate entry", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Open position already exists"
            return

        allocation = self.config.allocation_for(symbol)
        base_max_risk = phase_rules.get("max_risk_pct", self.config.max_risk_pct())
        max_risk_pct = base_max_risk * allocation

        win_rate = 0.55
        semantic = self.memory.get_semantic_context(
            primary_features.regime.value, symbol, session_name,
        )
        if semantic.get("best_agent"):
            perf = self.memory.agent_performance(semantic["best_agent"])
            if perf["sample_size"] >= 5:
                win_rate = perf["win_rate"]

        size = self.kelly_sizer.compute_size(
            equity=equity,
            win_rate=win_rate,
            reward_risk_ratio=1.5,
            atr_14=primary_features.atr_14,
            atr_50=primary_features.atr_50,
            confidence=decision.confidence,
            phase_multiplier=self.config.phase_multiplier,
            drawdown_multiplier=dd_state.size_multiplier,
            orchestrator_scale=decision.size_scale * combined_adj,
            allocation_cap=allocation,
            leverage_haircut=margin_state.leverage_haircut,
            margin_size_multiplier=margin_state.size_multiplier * self._size_multiplier,
            max_risk_override=max_risk_pct,
        )

        actionable = [s for s in signals if s.is_actionable and s.direction == decision.direction]
        if actionable:
            actionable.sort(key=lambda s: abs((s.stop_loss or primary_features.close) - primary_features.close))
        sl = actionable[0].stop_loss if actionable else None
        tp = actionable[0].take_profit if actionable else None
        agent_name = actionable[0].agent_name if actionable else "orchestrator"

        if not self.simulation:
            sl, tp = self._sanitize_stops(
                symbol,
                decision.direction.value,
                primary_features.close,
                sl,
                tp,
                primary_features.atr_14,
            )

        if not self.simulation:
            lots = self._risk_to_lots(symbol, size, primary_features.close, sl)
        else:
            lots = size  # simulation keeps legacy behaviour

        if lots <= 0:
            logger.info("Size below min lot for %s (risk=%.4f)", symbol, size)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Size below minimum lot"
            return

        specs = self._get_symbol_specs(symbol)
        contract = specs["contract_size"] if specs else 1.0
        trade_notional = position_notional(lots, contract, primary_features.close)
        heat_ok, heat_reason = self.portfolio_heat.pre_trade_check(
            equity,
            open_positions,
            float(self.connector.get_account_info().get("gross_exposure", 0)),
            symbol,
            decision.direction.value,
            trade_notional,
        )
        if not heat_ok:
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = heat_reason or "Portfolio heat cap"
            return

        result = self.connector.send_trade(
            symbol=symbol,
            direction=decision.direction.value,
            volume=lots,
            sl=sl,
            tp=tp,
        )

        exec_status = result.get("status", "executed")
        error_msg = result.get("message")
        if exec_status not in ("ok", "simulated"):
            logger.error("Trade failed for %s: %s", symbol, error_msg or exec_status)
            exec_status = "error"

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
            extra={"error": error_msg, "ticket": result.get("ticket")} if error_msg else {"ticket": result.get("ticket")},
        )

        decision_record["status"] = exec_status
        decision_record["size"] = lots
        if error_msg:
            decision_record["skip_reason"] = error_msg

        ticket = result.get("ticket")
        if ticket:
            self.position_manager.register_entry(
                ticket, symbol, decision.direction.value,
                result.get("price", primary_features.close), sl, lots,
                primary_features.regime.value,
            )
            self._open_trades[ticket] = {
                "symbol": symbol,
                "direction": decision.direction.value,
                "entry_price": result.get("price", primary_features.close),
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
                "reasoning": decision.reasoning,
                "entry_time": datetime.now(timezone.utc).isoformat(),
            }

        logger.info("Executed: %s", result)

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

        return self.connector.get_ohlcv(symbol, timeframe=timeframe, count=200)

    def run(self, cycle_minutes: int = 15) -> None:
        """Run the engine in a continuous loop."""
        import threading

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

        logger.info("Running decision loop every %d minutes", cycle_minutes)
        try:
            while True:
                cycle_start = datetime.now(timezone.utc)
                logger.info("--- Cycle start: %s ---", cycle_start.isoformat())
                self.run_cycle()
                elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
                sleep_secs = max(0, cycle_minutes * 60 - elapsed)
                logger.info("Cycle complete in %.1fs — sleeping %.0fs", elapsed, sleep_secs)
                time.sleep(sleep_secs)
        except KeyboardInterrupt:
            logger.info("Engine stopped by user")
        finally:
            self._running = False
            self.live_feed.stop()
            self._publish_state()
            self.compliance_heartbeat.stop()
            self.connector.close()
