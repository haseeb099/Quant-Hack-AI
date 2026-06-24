"""Unified pre-trade risk gate — shared by engine, manual orders, and copilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.data.market_validator import MarketValidator
from src.engine.config import QuantAIConfig, load_yaml
from src.bridges.zeromq_connector import account_equity
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.margin_monitor import MarginMonitor
from src.risk.account_profile import position_notional
from src.risk.portfolio_heat import CRYPTO_SYMBOLS, PortfolioHeat

CONTRACT_SIZE_DEFAULTS: dict[str, float] = {
    "BTC/USD": 1.0,
    "ETH/USD": 1.0,
    "EUR/USD": 100_000.0,
    "GBP/USD": 100_000.0,
    "USD/JPY": 100_000.0,
    "XAU/USD": 100.0,
}

ALLOWED_SYMBOLS: set[str] | None = None


def _allowed_symbols() -> set[str]:
    global ALLOWED_SYMBOLS
    if ALLOWED_SYMBOLS is None:
        instruments = load_yaml("instruments.yaml").get("instruments", [])
        ALLOWED_SYMBOLS = {str(i.get("symbol", "")) for i in instruments if i.get("symbol")}
    return ALLOWED_SYMBOLS


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").upper()


@dataclass
class TradeCheckRequest:
    symbol: str
    direction: str
    volume: float
    sl: float | None = None
    tp: float | None = None
    price: float | None = None
    atr_14: float | None = None


@dataclass
class RiskBlocker:
    code: str
    severity: str
    message: str
    discipline_risk: int | None = None
    penalty_in_min: float | None = None


@dataclass
class TradeCheckResult:
    allowed: bool
    blockers: list[RiskBlocker] = field(default_factory=list)
    warnings: list[RiskBlocker] = field(default_factory=list)
    remediation: list[str] = field(default_factory=list)
    projected: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blockers": [asdict(b) for b in self.blockers],
            "warnings": [asdict(w) for w in self.warnings],
            "remediation": self.remediation,
            "projected": self.projected,
        }


class PreTradeRiskGate:
    """Evaluate proposed trades against the frozen risk constitution."""

    def __init__(self, config: QuantAIConfig | None = None) -> None:
        self.config = config or QuantAIConfig.load()
        risk = self.config.risk
        self.drawdown_guard = DrawdownGuard(risk.get("drawdown", {}))
        self.margin_monitor = MarginMonitor(
            risk.get("margin", {}),
            risk.get("leverage", {}),
            risk.get("concentration", {}),
            risk.get("drawdown", {}),
        )
        self.portfolio_heat = PortfolioHeat(self._portfolio_heat_config(1_000_000))
        self.market_validator = MarketValidator()

    def _portfolio_heat_config(self, equity: float) -> dict[str, Any]:
        risk = self.config.risk
        net_dir = risk.get("net_directional", {})
        phase_rules = self.config.phase_rules
        return {
            "reference_equity": equity,
            "correlation_threshold": float(risk.get("sizing", {}).get("correlation_threshold", 0.70)),
            "correlation_pairs": risk.get("correlation_pairs", []),
            "cluster_cap": float(risk.get("concentration", {}).get("max_pct", 0.40)),
            "net_directional_cap": float(net_dir.get("internal_cap", 0.85)),
            "net_directional_min_gross_pct": float(
                phase_rules.get(
                    "net_directional_enforce_min_gross_pct",
                    net_dir.get("enforce_min_gross_pct", 0.08),
                )
            ),
        }

    def evaluate_from_state(
        self,
        state: dict[str, Any],
        request: TradeCheckRequest,
    ) -> TradeCheckResult:
        blockers: list[RiskBlocker] = []
        warnings: list[RiskBlocker] = []
        remediation: list[str] = []

        symbol = request.symbol.strip()
        direction = request.direction.upper()
        volume = float(request.volume)

        if volume <= 0:
            blockers.append(RiskBlocker("INVALID_VOLUME", "critical", "Volume must be greater than zero"))
            return self._finalize(blockers, warnings, remediation, state, request, 0.0)

        if symbol not in _allowed_symbols():
            blockers.append(
                RiskBlocker(
                    "INVALID_SYMBOL",
                    "critical",
                    f"{symbol} is not a competition instrument",
                ),
            )
            return self._finalize(blockers, warnings, remediation, state, request, 0.0)

        if direction not in ("BUY", "SELL"):
            blockers.append(RiskBlocker("INVALID_DIRECTION", "critical", "Direction must be BUY or SELL"))
            return self._finalize(blockers, warnings, remediation, state, request, 0.0)

        account = state.get("account", {})
        risk = state.get("risk", {})
        positions = state.get("positions", [])
        mode = str(state.get("mode", "simulate"))
        equity_val = account_equity(account, simulation=(mode != "live"))
        if mode == "live" and equity_val is None:
            blockers.append(
                RiskBlocker(
                    "BRIDGE_OFFLINE",
                    "critical",
                    "Account equity unavailable — ZMQ bridge offline or error",
                ),
            )
            remediation.append("Reconnect MT5 bridge from the control bar")
            return self._finalize(blockers, warnings, remediation, state, request, 0.0)
        raw_equity = account.get("equity")
        if equity_val is not None:
            equity = equity_val
        elif raw_equity is not None:
            equity = float(raw_equity)
        elif mode != "live":
            equity = 1_000_000.0
        else:
            equity = 0.0
        used_margin = float(account.get("margin", 0))
        gross_exposure = float(account.get("gross_exposure", 0))
        trade_notional = self._estimate_notional(symbol, volume, state, request.price)

        def _contract_size(sym: str) -> float:
            inst = state.get("instruments", {}).get(sym, {})
            cs = inst.get("contract_size")
            if cs:
                return float(cs)
            return CONTRACT_SIZE_DEFAULTS.get(sym, 100.0)

        get_contract_size = _contract_size

        if state.get("engine_paused"):
            blockers.append(
                RiskBlocker(
                    "ENGINE_PAUSED",
                    "critical",
                    "Trading engine is paused — new entries blocked",
                ),
            )
            remediation.append("Resume the engine from the control bar")

        from src.web.runtime_state import is_state_stale

        if is_state_stale(state):
            blockers.append(
                RiskBlocker(
                    "STALE_STATE",
                    "critical",
                    "Dashboard state is stale — engine may have stopped",
                ),
            )
            remediation.append("Restart engine or refresh connection")

        if mode == "live" and not state.get("mt5_connected"):
            blockers.append(
                RiskBlocker(
                    "MT5_OFFLINE",
                    "critical",
                    "MT5 / ZeroMQ bridge is offline",
                ),
            )
            remediation.append("Reconnect MT5 bridge from the control bar")

        max_spread_atr = self.config.risk.get("sizing", {}).get("max_spread_atr_ratio")
        if (
            mode == "live"
            and max_spread_atr
            and request.atr_14
            and request.atr_14 > 0
        ):
            inst = state.get("instruments", {}).get(symbol, {})
            bid = inst.get("bid")
            ask = inst.get("ask")
            if bid is not None and ask is not None:
                spread = float(ask) - float(bid)
                if spread > float(max_spread_atr) * request.atr_14:
                    blockers.append(
                        RiskBlocker(
                            "WIDE_SPREAD",
                            "critical",
                            f"Spread {spread:.5f} exceeds {max_spread_atr:.2f}× ATR "
                            f"({request.atr_14:.5f})",
                        ),
                    )
                    remediation.append("Wait for tighter spread or skip entry")

        market = state.get("market", {})
        instruments = state.get("instruments", {})
        inst = instruments.get(symbol, {})
        tick_age = inst.get("tick_age_ms") if inst.get("tick_age_ms") is not None else market.get("last_tick_age_ms")
        if mode == "live" and (tick_age is None or float(tick_age) > self.market_validator.max_tick_age_ms):
            blockers.append(
                RiskBlocker(
                    "STALE_TICKS",
                    "critical",
                    f"Stale or missing market data ({(float(tick_age) / 1000 if tick_age is not None else 0):.1f}s since last tick)",
                ),
            )
            remediation.append("Wait for fresh ticks or reconnect MT5")

        dd_tier = str(risk.get("dd_tier", "normal"))
        drawdown_pct = float(risk.get("drawdown_pct", 0))
        if dd_tier in ("critical", "emergency"):
            blockers.append(
                RiskBlocker(
                    "DRAWDOWN_TIER",
                    "critical",
                    f"Drawdown tier {dd_tier.upper()} — new entries blocked ({drawdown_pct:.1%} DD)",
                ),
            )
            remediation.append("Reduce exposure or wait for equity recovery")
        elif dd_tier in ("warning", "elevated"):
            warnings.append(
                RiskBlocker(
                    "DRAWDOWN_TIER",
                    "warning",
                    f"Drawdown tier {dd_tier.upper()} — position size reduced ({drawdown_pct:.1%} DD)",
                ),
            )

        is_crypto = symbol in CRYPTO_SYMBOLS
        crypto_blocked_at = self.config.risk.get("drawdown", {}).get("crypto_blocked_at", "warning")
        tier_order = DrawdownGuard.TIERS
        if is_crypto and dd_tier in tier_order:
            blocked_idx = tier_order.index(crypto_blocked_at) if crypto_blocked_at in tier_order else 2
            if tier_order.index(dd_tier) >= blocked_idx:
                blockers.append(
                    RiskBlocker(
                        "CRYPTO_BLOCKED",
                        "critical",
                        f"Crypto entries blocked at drawdown tier {dd_tier}",
                    ),
                )

        phase_rules = self.config.phase_rules
        if phase_rules.get("crypto_only_if_dd_normal") and is_crypto and dd_tier != "normal":
            blockers.append(
                RiskBlocker(
                    "PHASE_RULE",
                    "critical",
                    "Round 3 — crypto only allowed at Normal drawdown tier",
                ),
            )

        discipline = float(risk.get("discipline", 100))
        discipline_halt = phase_rules.get("discipline_halt_below")
        if discipline_halt is not None and discipline < float(discipline_halt):
            blockers.append(
                RiskBlocker(
                    "DISCIPLINE_HALT",
                    "critical",
                    f"Risk discipline {discipline:.0f} below halt threshold {discipline_halt}",
                    discipline_risk=-5,
                ),
            )

        if self._symbol_has_position(symbol, positions):
            blockers.append(
                RiskBlocker(
                    "DUPLICATE_POSITION",
                    "critical",
                    f"Open position already exists on {symbol}",
                ),
            )
            remediation.append("Close or modify the existing position first")

        peak = self.drawdown_guard.peak_equity
        if equity > 0 and peak > equity * 10:
            implied_dd = (peak - equity) / peak
            if implied_dd >= 0.50:
                self.drawdown_guard.reset(equity)
        elif equity > 0 and state.get("account_profile") == "micro":
            bound = max(equity * 2, 1000)
            if peak > bound:
                self.drawdown_guard.reset(equity)
        dd_state = self.drawdown_guard.update(equity)

        margin_state = self.margin_monitor.check(
            equity,
            used_margin,
            gross_exposure,
            float(account.get("largest_position_pct", risk.get("concentration_pct", 0))),
            margin_level_pct=account.get("margin_level"),
        )

        net_directional_cap = self.config.risk.get("net_directional", {}).get("internal_cap", 0.85)
        net_directional = PortfolioHeat.net_directional_ratio(positions, get_contract_size)
        inst = state.get("instruments", {}).get(symbol, {})
        contract_size = get_contract_size(symbol)
        trade_price = request.price
        if not trade_price or trade_price <= 0:
            for key in ("mid", "bid", "ask"):
                val = inst.get(key)
                if val and float(val) > 0:
                    trade_price = float(val)
                    break
        if not trade_price or trade_price <= 0:
            trade_price = trade_notional / max(volume * contract_size, 1e-9)
        projected_positions = list(positions) + [{
            "symbol": symbol,
            "type": direction,
            "volume": volume,
            "price_open": trade_price,
            "contract_size": get_contract_size(symbol),
        }]
        projected_net = PortfolioHeat.net_directional_ratio(projected_positions, get_contract_size)

        if margin_state.stop_out_risk:
            blockers.append(
                RiskBlocker(
                    "STOP_OUT_RISK",
                    "critical",
                    f"Margin level {margin_state.margin_level_pct:.0f}% approaching 30% stop-out — entries blocked",
                ),
            )
            remediation.append("Reduce exposure immediately to avoid forced liquidation")

        net_penalty = self.config.risk.get("net_directional", {}).get("competition_penalty_pct", 0.95)
        min_gross = float(
            self.config.phase_rules.get(
                "net_directional_enforce_min_gross_pct",
                self.config.risk.get("net_directional", {}).get("enforce_min_gross_pct", 0.08),
            )
        )
        projected_gross = gross_exposure + trade_notional
        gross_pct = projected_gross / max(equity, 1e-9)
        balancing_trade = projected_net < net_directional
        if (
            positions
            and projected_net > net_directional_cap
            and gross_pct >= min_gross
            and not balancing_trade
        ):
            blockers.append(
                RiskBlocker(
                    "NET_DIRECTIONAL",
                    "critical",
                    f"Projected net directional exposure {projected_net:.0%} exceeds {net_directional_cap:.0%} cap",
                    discipline_risk=-10,
                ),
            )
            remediation.append("Balance long/short exposure before adding")
        elif positions and projected_net > net_penalty and gross_pct >= min_gross:
            warnings.append(
                RiskBlocker(
                    "NET_DIRECTIONAL",
                    "warning",
                    f"Projected net directional {projected_net:.0%} near competition penalty ({net_penalty:.0%})",
                    discipline_risk=-10,
                    penalty_in_min=30,
                ),
            )

        if margin_state.block_new_trades or "EMERGENCY" in margin_state.action.upper():
            blockers.append(
                RiskBlocker(
                    "MARGIN_USAGE",
                    "critical",
                    margin_state.message or "Margin usage blocks new entries",
                    discipline_risk=-20 if margin_state.margin_usage_pct > 0.9 else None,
                ),
            )
            remediation.append("Close positions to free margin")

        margin_penalty_pct = self.config.risk.get("margin", {}).get("competition_penalty_pct", 0.90)
        if margin_state.margin_usage_pct > margin_penalty_pct:
            warnings.append(
                RiskBlocker(
                    "MARGIN_USAGE",
                    "warning",
                    f"Margin usage {margin_state.margin_usage_pct:.0%} approaching competition penalty zone",
                    discipline_risk=-20,
                    penalty_in_min=30,
                ),
            )

        lev_max = self.config.risk.get("leverage", {}).get("max", 20)
        projected_gross = gross_exposure + trade_notional
        projected_leverage = projected_gross / max(equity, 1e-9)
        if projected_leverage > lev_max:
            blockers.append(
                RiskBlocker(
                    "LEVERAGE",
                    "critical",
                    f"Projected leverage {projected_leverage:.1f}× exceeds {lev_max}× cap",
                ),
            )
            remediation.append("Reduce trade size or close other positions")

        lev_penalty = self.config.risk.get("leverage", {}).get("competition_penalty", 28)
        if projected_leverage > lev_penalty:
            warnings.append(
                RiskBlocker(
                    "LEVERAGE",
                    "warning",
                    f"Projected leverage {projected_leverage:.1f}× near competition penalty ({lev_penalty}×)",
                    discipline_risk=-20,
                    penalty_in_min=30,
                ),
            )

        conc_max = self.config.risk.get("concentration", {}).get("max_pct", 0.40)
        trade_conc_pct = trade_notional / max(equity, 1e-9)
        projected_conc_pct = max(margin_state.concentration_pct, trade_conc_pct)

        if margin_state.concentration_pct >= conc_max or self.margin_monitor.concentration_blocks_entries(
            margin_state.concentration_pct,
        ):
            blockers.append(
                RiskBlocker(
                    "CONCENTRATION",
                    "critical",
                    f"Concentration {margin_state.concentration_pct:.0%} at or above {conc_max:.0%} cap",
                    discipline_risk=-10,
                ),
            )
            remediation.append("Diversify — reduce largest position before adding")
        elif projected_conc_pct > conc_max:
            blockers.append(
                RiskBlocker(
                    "CONCENTRATION_PROJECTED",
                    "critical",
                    f"Projected concentration {projected_conc_pct:.0%} exceeds {conc_max:.0%} cap",
                    discipline_risk=-10,
                ),
            )
            remediation.append("Reduce trade size or diversify before adding")

        heat_cfg = self.config.risk
        self.portfolio_heat = PortfolioHeat(self._portfolio_heat_config(equity))
        heat_ok, heat_reason = self.portfolio_heat.pre_trade_check(
            equity,
            positions,
            gross_exposure,
            symbol,
            direction,
            trade_notional,
            max_leverage=float(self.config.risk.get("leverage", {}).get("max", 20)),
            volume=volume,
            price=trade_price,
            contract_size=get_contract_size(symbol),
            get_contract_size=get_contract_size,
        )
        if not heat_ok:
            blockers.append(
                RiskBlocker(
                    "PORTFOLIO_HEAT",
                    "critical",
                    heat_reason or "Portfolio heat cap exceeded",
                ),
            )

        if not dd_state.allow_new_trades and not any(b.code == "DRAWDOWN_TIER" for b in blockers):
            blockers.append(
                RiskBlocker(
                    "DRAWDOWN_TIER",
                    "critical",
                    dd_state.message,
                ),
            )

        return self._finalize(blockers, warnings, remediation, state, request, trade_notional, {
            "equity": equity,
            "trade_notional": trade_notional,
            "projected_gross_exposure": projected_gross,
            "projected_leverage": round(projected_leverage, 2),
            "margin_usage_pct": round(margin_state.margin_usage_pct, 4),
            "concentration_pct": round(margin_state.concentration_pct, 4),
            "projected_concentration_pct": round(projected_conc_pct, 4),
            "net_directional_pct": round(net_directional, 4),
            "projected_net_directional_pct": round(projected_net, 4),
            "margin_level_pct": round(margin_state.margin_level_pct, 2),
            "dd_tier": dd_tier,
            "discipline": discipline,
        })

    def evaluate_from_engine(
        self,
        engine: Any,
        request: TradeCheckRequest,
    ) -> TradeCheckResult:
        state = {
            "phase": engine.config.current_phase,
            "mode": "simulate" if engine.simulation else "live",
            "engine_paused": engine.is_paused,
            "engine_running": engine._running,
            "mt5_connected": engine.connector.is_connected,
            "account": engine.connector.get_account_info(),
            "positions": engine.connector.get_positions(),
            "risk": {
                "dd_tier": engine.drawdown_guard.current_tier,
                "drawdown_pct": (
                    (engine.drawdown_guard.peak_equity - engine.connector.get_account_info().get("equity", 0))
                    / max(engine.drawdown_guard.peak_equity, 1e-9)
                ),
                "discipline": engine.compliance_heartbeat.state.risk_discipline_score,
                "concentration_pct": 0.0,
            },
            "market": {},
            "instruments": {},
        }
        account = state["account"]
        if engine.drawdown_guard.peak_equity > 0:
            state["risk"]["drawdown_pct"] = (
                engine.drawdown_guard.peak_equity - float(account.get("equity", 0))
            ) / engine.drawdown_guard.peak_equity

        margin_state = engine.margin_monitor.check(
            float(account.get("equity", 0)),
            float(account.get("margin", 0)),
            float(account.get("gross_exposure", 0)),
            float(account.get("largest_position_pct", 0)),
            margin_level_pct=account.get("margin_level"),
        )
        state["risk"]["concentration_pct"] = margin_state.concentration_pct
        state["account"]["margin_level"] = account.get("margin_level")

        if hasattr(engine, "live_feed") and engine.live_feed:
            tick = engine.live_feed.get_tick(request.symbol)
            if tick:
                state["market"]["last_tick_age_ms"] = tick.tick_age_ms
                state["instruments"][request.symbol] = {
                    "mid": tick.mid,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "tick_age_ms": tick.tick_age_ms,
                }

        specs = engine._get_symbol_specs(request.symbol) if hasattr(engine, "_get_symbol_specs") else None
        if specs:
            state.setdefault("instruments", {}).setdefault(request.symbol, {})["contract_size"] = specs["contract_size"]

        return self.evaluate_from_state(state, request)

    def _estimate_notional(
        self,
        symbol: str,
        volume: float,
        state: dict[str, Any],
        price: float | None,
    ) -> float:
        inst = state.get("instruments", {}).get(symbol, {})
        contract_size = float(inst.get("contract_size", 0)) or CONTRACT_SIZE_DEFAULTS.get(symbol, 100.0)
        if price and price > 0:
            return position_notional(volume, contract_size, price)
        mid = inst.get("mid") or inst.get("bid") or inst.get("ask")
        if mid:
            return position_notional(volume, contract_size, float(mid))
        defaults = {
            "BTC/USD": 95_000.0,
            "ETH/USD": 3_500.0,
            "XAU/USD": 2_350.0,
            "EUR/USD": 1.08,
        }
        ref_price = defaults.get(symbol, 100.0)
        return position_notional(volume, contract_size, ref_price)

    @staticmethod
    def _symbol_has_position(symbol: str, positions: list[dict[str, Any]]) -> bool:
        target = _normalize_symbol(symbol)
        for pos in positions:
            if _normalize_symbol(str(pos.get("symbol", ""))) == target:
                return True
        return False

    def _finalize(
        self,
        blockers: list[RiskBlocker],
        warnings: list[RiskBlocker],
        remediation: list[str],
        state: dict[str, Any],
        request: TradeCheckRequest,
        trade_notional: float,
        projected: dict[str, Any] | None = None,
    ) -> TradeCheckResult:
        allowed = len(blockers) == 0
        if not allowed and not remediation:
            remediation = self._default_remediation(blockers)
        proj = projected or {
            "trade_notional": trade_notional,
            "symbol": request.symbol,
            "direction": request.direction.upper(),
            "volume": request.volume,
        }
        return TradeCheckResult(
            allowed=allowed,
            blockers=blockers,
            warnings=warnings,
            remediation=list(dict.fromkeys(remediation)),
            projected=proj,
        )

    @staticmethod
    def _default_remediation(blockers: list[RiskBlocker]) -> list[str]:
        codes = {b.code for b in blockers}
        steps: list[str] = []
        if "MARGIN_USAGE" in codes or "LEVERAGE" in codes:
            steps.append("Reduce trade size or close other positions")
        if "DRAWDOWN_TIER" in codes:
            steps.append("Wait for drawdown tier to improve before new entries")
        if "STALE_TICKS" in codes or "MT5_OFFLINE" in codes:
            steps.append("Reconnect MT5 and confirm Algorithmic Trading is enabled")
        if "DUPLICATE_POSITION" in codes:
            steps.append("Close the existing position on this symbol first")
        if "ENGINE_PAUSED" in codes:
            steps.append("Resume the trading engine")
        return steps


_default_gate: PreTradeRiskGate | None = None


def get_pre_trade_gate() -> PreTradeRiskGate:
    global _default_gate
    if _default_gate is None:
        _default_gate = PreTradeRiskGate()
    return _default_gate


def check_trade(state: dict[str, Any], request: TradeCheckRequest) -> TradeCheckResult:
    return get_pre_trade_gate().evaluate_from_state(state, request)
