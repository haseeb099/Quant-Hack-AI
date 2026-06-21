"""Portfolio heat — net directional exposure and cluster caps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CRYPTO_SYMBOLS = frozenset({"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"})
FOREX_USD_LONG_CLUSTER = frozenset({"EUR/USD", "GBP/USD", "AUD/USD"})
FOREX_USD_SHORT_CLUSTER = frozenset({"USD/JPY", "USD/CAD", "USD/CHF"})


@dataclass
class HeatState:
    net_crypto_long_pct: float
    net_usd_long_pct: float
    projected_leverage: float
    block_reason: str | None
    allow_trade: bool


class PortfolioHeat:
    """Track net exposure clusters and pre-trade leverage projection."""

    CRYPTO_LONG_CAP = 0.60
    CLUSTER_CAP = 0.40

    def __init__(self, config: dict[str, Any] | float | None = None) -> None:
        if isinstance(config, (int, float)):
            cfg: dict[str, Any] = {"reference_equity": float(config)}
        else:
            cfg = config or {}
        self.crypto_long_cap = cfg.get("crypto_long_cap", self.CRYPTO_LONG_CAP)
        self.cluster_cap = cfg.get("cluster_cap", self.CLUSTER_CAP)

    def assess(
        self,
        equity: float,
        positions: list[dict[str, Any]],
        gross_exposure: float,
    ) -> HeatState:
        if equity <= 0:
            return HeatState(0, 0, 0, None, True)

        crypto_long = 0.0
        usd_long = 0.0
        for pos in positions:
            symbol = str(pos.get("symbol", ""))
            notional = abs(float(pos.get("volume", 0)) * float(pos.get("price_open", 0)))
            direction = str(pos.get("type", "BUY")).upper()
            is_long = "BUY" in direction or direction == "LONG"

            if symbol in CRYPTO_SYMBOLS and is_long:
                crypto_long += notional
            if symbol in FOREX_USD_LONG_CLUSTER and is_long:
                usd_long += notional
            if symbol in FOREX_USD_SHORT_CLUSTER and not is_long:
                usd_long += notional

        crypto_pct = crypto_long / equity
        usd_pct = usd_long / equity
        leverage = gross_exposure / equity

        block_reason = None
        if crypto_pct > self.crypto_long_cap:
            block_reason = f"Net crypto long {crypto_pct:.0%} > {self.crypto_long_cap:.0%}"
        elif usd_pct > self.cluster_cap:
            block_reason = f"USD cluster exposure {usd_pct:.0%} > {self.cluster_cap:.0%}"

        return HeatState(
            net_crypto_long_pct=crypto_pct,
            net_usd_long_pct=usd_pct,
            projected_leverage=leverage,
            block_reason=block_reason,
            allow_trade=block_reason is None,
        )

    def pre_trade_check(
        self,
        equity: float,
        positions: list[dict[str, Any]],
        gross_exposure: float,
        symbol: str,
        direction: str,
        trade_notional: float,
        max_leverage: float = 20.0,
    ) -> tuple[bool, str | None]:
        """Project leverage and cluster exposure after proposed trade."""
        projected_positions = list(positions)
        projected_positions.append({
            "symbol": symbol,
            "type": direction,
            "volume": 1.0,
            "price_open": trade_notional,
        })
        new_gross = gross_exposure + trade_notional
        projected_lev = new_gross / max(equity, 1e-9)
        if projected_lev > max_leverage:
            return False, f"Projected leverage {projected_lev:.1f}× > {max_leverage}×"

        heat = self.assess(equity, projected_positions, new_gross)
        if not heat.allow_trade:
            return False, heat.block_reason

        is_crypto = symbol in CRYPTO_SYMBOLS
        is_long = direction.upper() == "BUY"
        if is_crypto and is_long:
            current = self.assess(equity, positions, gross_exposure)
            added_pct = trade_notional / equity
            if current.net_crypto_long_pct + added_pct > self.crypto_long_cap:
                return False, "Would exceed crypto long cap"

        return True, None
