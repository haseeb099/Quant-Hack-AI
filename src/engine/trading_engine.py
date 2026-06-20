"""Main trading engine — 15-minute decision loop."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import pandas as pd

from src.agents.breakout_hunter import BreakoutHunterAgent
from src.agents.context_builder import ContextBuilder
from src.agents.debate_orchestrator import DebateOrchestrator
from src.agents.mean_reversion import MeanReversionAgent
from src.agents.meta_orchestrator import MetaOrchestrator
from src.agents.momentum_pulse import MomentumPulseAgent
from src.agents.trend_surfer import TrendSurferAgent
from src.bridges.zeromq_connector import ZeroMQConnector
from src.data.feature_engine import FeatureEngine
from src.data.session_filter import SessionFilter
from src.engine.config import QuantAIConfig, load_yaml
from src.intelligence.peer_monitor import PeerMonitor
from src.learning.layered_memory import LayeredMemory, TradeRecord
from src.risk.compliance import ComplianceEngine
from src.risk.compliance_heartbeat import ComplianceHeartbeat
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.kelly_sizer import KellySizer
from src.risk.lot_sizer import risk_to_lots
from src.risk.margin_monitor import MarginMonitor
from src.risk.sharpe_guard import SharpeGuard
from src.utils.logger import log_trade_decision
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
        self.trade_logger = TradeLogger()
        self.sharpe_guard = SharpeGuard()
        self.compliance_heartbeat = ComplianceHeartbeat(config.risk)

        phases_cfg = load_yaml("phases.yaml")
        self.session_filter = SessionFilter(phases_cfg.get("sessions", {}))

        orch_cfg = dict(config.agent_config("meta_orchestrator"))
        orch_cfg["anthropic_api_key"] = orch_cfg.get("anthropic_api_key") or __import__("os").getenv("ANTHROPIC_API_KEY")

        self.agents = [
            TrendSurferAgent(config.agent_config("trend_surfer")),
            BreakoutHunterAgent(config.agent_config("breakout_hunter")),
            MomentumPulseAgent(config.agent_config("momentum_pulse")),
            MeanReversionAgent(config.agent_config("mean_reversion")),
        ]
        self.orchestrator = MetaOrchestrator(orch_cfg, config.regime_boosts)

        risk = config.risk
        self.drawdown_guard = DrawdownGuard(risk.get("drawdown", {}))
        self.kelly_sizer = KellySizer(risk.get("sizing", {}))
        self.margin_monitor = MarginMonitor(
            risk.get("margin", {}),
            risk.get("leverage", {}),
            risk.get("concentration", {}),
        )
        self.compliance = ComplianceEngine(risk.get("compliance", {}))
        self.state_publisher = StatePublisher()
        self._open_trades: dict[int, dict] = {}
        self._peak_equity: float = 0.0
        self._prev_dd_tier: str = "normal"
        self._cycle_decisions: list[dict] = []
        self._cycle_votes: list[dict] = []
        self._instrument_regimes: dict[str, str] = {}
        self._running = False
        self._last_cycle_at: str | None = None
        self._next_cycle_at: str | None = None

    def start(self) -> None:
        if not self.simulation:
            if not self.connector.connect():
                raise RuntimeError("ZeroMQ bridge not connected — start DWX_ZeroMQ_Server in MT5")
            time.sleep(1.5)  # ZMQ slow-joiner warmup
            self._init_mt5_session()
        self._running = True
        account = self.connector.get_account_info()
        equity = account.get("equity", 1_000_000)
        self.drawdown_guard.reset(equity)
        self._peak_equity = equity
        self._initial_equity = equity

        if not self.simulation:
            self.compliance_heartbeat.start(
                metrics_fn=self._compliance_metrics,
                action_callback=self._handle_compliance_actions,
            )

        logger.info("QuantAI engine started — phase=%s, equity=%.2f", self.config.current_phase, equity)
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
            logger.warning("ComplianceHeartbeat: REDUCE_MARGIN")
            self._sync_risk_event("REDUCE_MARGIN", "Sustained margin violation", "warning", actions)
        self._publish_state()

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
        snapshot = {
            "phase": self.config.current_phase,
            "mode": "simulate" if self.simulation else "live",
            "timestamp": now.isoformat(),
            "last_cycle_at": self._last_cycle_at,
            "next_cycle_at": next_cycle_at,
            "connected": mt5_connected or self.simulation,
            "engine_running": self._running,
            "mt5_connected": mt5_connected,
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
            "instruments": {
                symbol: {"last_regime": regime}
                for symbol, regime in self._instrument_regimes.items()
            },
        }
        self.state_publisher.publish(snapshot)

    def run_cycle(self) -> None:
        """Execute one 15-minute decision cycle across all active symbols."""
        cycle_start = datetime.now(timezone.utc)
        self._cycle_decisions = []
        self._cycle_votes = []
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

            self._manage_positions(equity, dd_state)

            peer_snapshot = self.peer_monitor.update({
                "peer_count": 100,
                "avg_return": 0.02,
                "avg_drawdown": 0.04,
                "top_performer_return": 0.06,
                "our_return": (equity - self._peak_equity) / max(self._peak_equity, 1),
                "our_rank": 55,
            })
            peer_adj = self.peer_monitor.sizing_adjustment()

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
                    peer_adj=peer_adj, peer_sentiment=peer_snapshot.crowd_bias,
                )
        finally:
            self._publish_state(cycle_start)

    def _manage_positions(self, equity: float, dd_state) -> None:
        positions = self.connector.get_positions()
        for pos in positions:
            ticket = pos.get("ticket")
            if not ticket:
                continue

            profit = pos.get("profit", 0)
            pos_value = pos.get("volume", 0) * pos.get("price_open", 0)
            pnl_pct = profit / max(pos_value, 1e-9)

            if self.sharpe_guard.should_close_for_sharpe(pnl_pct, equity):
                logger.info("SharpeGuard closing ticket %d", ticket)
                self.connector.close_position(ticket)
                self._finalize_trade(ticket, pos, equity)
            elif dd_state.tier == "critical" and profit < 0:
                logger.info("Critical tier closing losing position %d", ticket)
                self.connector.close_position(ticket)
                self._finalize_trade(ticket, pos, equity)

    def _finalize_trade(self, ticket: int, pos: dict, equity: float) -> None:
        tracked = self._open_trades.pop(ticket, None)
        if not tracked:
            return

        exit_price = pos.get("price_open", 0)
        entry_price = tracked.get("entry_price", exit_price)
        direction = tracked.get("direction", "BUY")
        sl_dist = abs(entry_price - tracked.get("sl", entry_price))
        pnl = pos.get("profit", 0)

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
    ) -> None:
        m15_df = self._get_ohlcv(symbol, "M15")
        if m15_df is None or len(m15_df) < 50:
            logger.debug("Insufficient data for %s", symbol)
            return

        multi_features = self.feature_engine.compute_multi(symbol, m15_df)
        if not multi_features:
            return

        signals = []
        for agent in self.agents:
            agent_cfg = agent.config
            timeframes = agent_cfg.get("timeframes", ["M15"])
            best_signal = None
            for tf in timeframes:
                features = multi_features.get(tf) or (multi_features.get("M15") if tf != "M15" else None)
                if features is None:
                    continue
                candidate = agent.analyze(features)
                if best_signal is None or candidate.confidence > best_signal.confidence:
                    best_signal = candidate
            if best_signal is not None:
                signals.append(best_signal)

        primary_features = multi_features.get("M15") or next(iter(multi_features.values()))
        open_positions = self.connector.get_positions()
        self._instrument_regimes[symbol] = primary_features.regime.value

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

        if decision.direction.value == "HOLD":
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "HOLD decision"
            return

        if not dd_state.allow_new_trades:
            logger.info("New trades blocked at tier %s", dd_state.tier)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = f"Blocked at tier {dd_state.tier}"
            return

        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        if is_crypto and not dd_state.allow_crypto:
            logger.info("Crypto blocked at drawdown tier %s — skipping %s", dd_state.tier, symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Crypto blocked at drawdown tier"
            return

        if margin_state.action.startswith("EMERGENCY") or "hard stop" in margin_state.action.lower():
            logger.info("Margin block — skipping %s", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Margin block"
            return

        if self._symbol_has_position(symbol, open_positions):
            logger.info("Already have open position on %s — skipping duplicate entry", symbol)
            decision_record["status"] = "skipped"
            decision_record["skip_reason"] = "Open position already exists"
            return

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
            orchestrator_scale=decision.size_scale * peer_adj,
        )

        actionable = [s for s in signals if s.is_actionable and s.direction == decision.direction]
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
            self._publish_state()
            self.compliance_heartbeat.stop()
            self.connector.close()
