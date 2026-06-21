"""Unified pre-trade risk gate — shared by engine, manual orders, and copilot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.data.market_validator import MarketValidator
from src.engine.config import QuantAIConfig, load_yaml
from src.risk.drawdown_guard import DrawdownGuard
from src.risk.margin_monitor import MarginMonitor
from src.risk.portfolio_heat import CRYPTO_SYMBOLS, PortfolioHeat
from src.web.runtime_state import is_state_stale

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
        self.portfolio_heat = PortfolioHeat({"reference_equity": 1_000_000})
        self.market_validator = MarketValidator()

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
        equity = float(account.get("equity", 1_000_000))
        used_margin = float(account.get("margin", 0))
        gross_exposure = float(account.get("gross_exposure", 0))
        trade_notional = self._estimate_notional(symbol, volume, state, request.price)

        if state.get("engine_paused"):
            blockers.append(
                RiskBlocker(
                    "ENGINE_PAUSED",
                    "critical",
                    "Trading engine is paused — new entries blocked",
                ),
            )
            remediation.append("Resume the engine from the control bar")

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

        market = state.get("market", {})
        instruments = state.get("instruments", {})
        inst = instruments.get(symbol, {})
        tick_age = inst.get("tick_age_ms") or market.get("last_tick_age_ms")
        if mode == "live" and tick_age is not None and float(tick_age) > self.market_validator.max_tick_age_ms:
            blockers.append(
                RiskBlocker(
                    "STALE_TICKS",
                    "critical",
                    f"Stale market data ({float(tick_age) / 1000:.1f}s since last tick)",
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

        peak = equity / max(1.0 - drawdown_pct, 1e-9) if drawdown_pct < 1 else equity
        self.drawdown_guard.peak_equity = max(peak, equity)
        dd_state = self.drawdown_guard.update(equity)

        margin_state = self.margin_monitor.check(
            equity,
            used_margin,
            gross_exposure,
            float(account.get("largest_position_pct", risk.get("concentration_pct", 0))),
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
        if margin_state.concentration_pct >= conc_max or self.margin_monitor.concentration_blocks_symbol(
            symbol, margin_state.concentration_pct,
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

        self.portfolio_heat = PortfolioHeat(equity)
        heat_ok, heat_reason = self.portfolio_heat.pre_trade_check(
            equity,
            positions,
            gross_exposure,
            symbol,
            direction,
            trade_notional,
            max_leverage=float(self.config.risk.get("leverage", {}).get("max", 20)),
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
        )
        state["risk"]["concentration_pct"] = margin_state.concentration_pct

        if hasattr(engine, "live_feed") and engine.live_feed:
            tick = engine.live_feed.get_tick(request.symbol)
            if tick:
                state["market"]["last_tick_age_ms"] = tick.tick_age_ms
                state["instruments"][request.symbol] = {
                    "mid": tick.mid,
                    "tick_age_ms": tick.tick_age_ms,
                }

        return self.evaluate_from_state(state, request)

    def _estimate_notional(
        self,
        symbol: str,
        volume: float,
        state: dict[str, Any],
        price: float | None,
    ) -> float:
        if price and price > 0:
            return abs(volume * price)
        inst = state.get("instruments", {}).get(symbol, {})
        mid = inst.get("mid") or inst.get("bid") or inst.get("ask")
        if mid:
            return abs(volume * float(mid))
        defaults = {
            "BTC/USD": 95_000.0,
            "ETH/USD": 3_500.0,
            "XAU/USD": 2_350.0,
            "EUR/USD": 1.08,
        }
        return abs(volume * defaults.get(symbol, 100.0))

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
