"""Portfolio heat — net directional exposure and cluster caps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.risk.account_profile import position_notional_from_dict

CRYPTO_SYMBOLS = frozenset({"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"})
METALS_CLUSTER = frozenset({"XAU/USD", "XAG/USD"})
FOREX_USD_LONG_CLUSTER = frozenset({"EUR/USD", "GBP/USD", "AUD/USD"})
FOREX_USD_SHORT_CLUSTER = frozenset({"USD/JPY", "USD/CAD", "USD/CHF"})
FOREX_CHF_CLUSTER = frozenset({"USD/CHF", "EUR/CHF"})

_DEFAULT_CORRELATION_PAIRS: dict[frozenset[str], float] = {
    frozenset({"EUR/USD", "GBP/USD"}): 0.85,
    frozenset({"EUR/USD", "AUD/USD"}): 0.72,
    frozenset({"GBP/USD", "AUD/USD"}): 0.68,
    frozenset({"USD/JPY", "USD/CHF"}): 0.78,
    frozenset({"EUR/USD", "USD/CHF"}): -0.75,
    frozenset({"AUD/USD", "NZD/USD"}): 0.88,
    frozenset({"EUR/CHF", "USD/CHF"}): 0.88,
    frozenset({"EUR/CHF", "EUR/USD"}): 0.72,
}


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
    NET_DIRECTIONAL_PENALTY = 0.95
    NET_DIRECTIONAL_CAP = 0.85

    def __init__(self, config: dict[str, Any] | float | None = None) -> None:
        if isinstance(config, (int, float)):
            cfg: dict[str, Any] = {"reference_equity": float(config)}
        else:
            cfg = config or {}
        conc = cfg.get("concentration", {}) if isinstance(cfg.get("concentration"), dict) else {}
        self.crypto_long_cap = cfg.get("crypto_long_cap", self.CRYPTO_LONG_CAP)
        self.cluster_cap = cfg.get("cluster_cap", self.CLUSTER_CAP)
        self.metals_cluster_max_pct = float(
            cfg.get("metals_cluster_max_pct", conc.get("metals_cluster_max_pct", 0.50))
        )
        self.metals_single_max_pct = float(
            cfg.get("metals_single_max_pct", conc.get("metals_single_max_pct", 0.25))
        )
        self.chf_cluster_max_pct = float(
            cfg.get("chf_cluster_max_pct", conc.get("chf_cluster_max_pct", 0.35))
        )
        self.net_directional_cap = cfg.get("net_directional_cap", self.NET_DIRECTIONAL_CAP)
        self.net_directional_min_gross_pct = float(
            cfg.get("net_directional_min_gross_pct", 0.08)
        )
        self.correlation_threshold = float(cfg.get("correlation_threshold", 0.70))
        self._correlation_pairs = self._parse_correlation_pairs(cfg.get("correlation_pairs"))

    @staticmethod
    def _parse_correlation_pairs(raw: Any) -> dict[frozenset[str], float]:
        pairs = dict(_DEFAULT_CORRELATION_PAIRS)
        if not raw:
            return pairs
        for entry in raw:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                a, b, corr = str(entry[0]), str(entry[1]), float(entry[2])
                pairs[frozenset({a, b})] = corr
        return pairs

    @staticmethod
    def _position_direction(pos: dict[str, Any]) -> str:
        direction = str(pos.get("type", "BUY")).upper()
        is_long = "BUY" in direction or direction in ("LONG", "0")
        return "BUY" if is_long else "SELL"

    def _cluster_notional(
        self,
        positions: list[dict[str, Any]],
        cluster: frozenset[str],
        get_contract_size: Callable[[str], float] | None = None,
    ) -> float:
        total = 0.0
        for pos in positions:
            symbol = str(pos.get("symbol", ""))
            if symbol not in cluster:
                continue
            total += self._position_notional(pos, get_contract_size)
        return total

    def _correlated_exposure(
        self,
        positions: list[dict[str, Any]],
        symbol: str,
        direction: str,
        trade_notional: float,
        get_contract_size: Callable[[str], float] | None = None,
    ) -> tuple[float, str | None]:
        """Sum notional in positions correlated above threshold with proposed trade."""
        proposed_dir = direction.upper()
        correlated_notional = 0.0
        matched_pair = ""

        for pos in positions:
            pos_symbol = str(pos.get("symbol", ""))
            if pos_symbol == symbol:
                continue
            pair_key = frozenset({symbol, pos_symbol})
            corr = self._correlation_pairs.get(pair_key)
            if corr is None or abs(corr) < self.correlation_threshold:
                continue
            pos_dir = self._position_direction(pos)
            same_direction = pos_dir == proposed_dir
            if corr > 0 and not same_direction:
                continue
            if corr < 0 and same_direction:
                continue
            notional = self._position_notional(pos, get_contract_size)
            correlated_notional += notional
            matched_pair = f"{symbol}/{pos_symbol} ({corr:+.2f})"

        return correlated_notional + trade_notional, matched_pair

    @staticmethod
    def _position_notional(
        pos: dict[str, Any],
        get_contract_size: Callable[[str], float] | None = None,
    ) -> float:
        symbol = str(pos.get("symbol", ""))
        cs = float(pos.get("contract_size", 0)) or (
            get_contract_size(symbol) if get_contract_size else 1.0
        )
        return position_notional_from_dict(pos, cs)

    @staticmethod
    def net_directional_ratio(
        positions: list[dict[str, Any]],
        get_contract_size: Callable[[str], float] | None = None,
    ) -> float:
        """|long - short| / gross — competition net directional exposure metric."""
        long_notional = 0.0
        short_notional = 0.0
        for pos in positions:
            notional = PortfolioHeat._position_notional(pos, get_contract_size)
            direction = str(pos.get("type", "BUY")).upper()
            is_long = "BUY" in direction or direction in ("LONG", "0")
            if is_long:
                long_notional += notional
            else:
                short_notional += notional
        gross = long_notional + short_notional
        if gross <= 0:
            return 0.0
        return abs(long_notional - short_notional) / gross

    def assess(
        self,
        equity: float,
        positions: list[dict[str, Any]],
        gross_exposure: float,
        get_contract_size: Callable[[str], float] | None = None,
    ) -> HeatState:
        if equity <= 0:
            return HeatState(0, 0, 0, None, True)

        crypto_long = 0.0
        usd_long = 0.0
        metals_notional = 0.0
        chf_notional = 0.0
        for pos in positions:
            symbol = str(pos.get("symbol", ""))
            notional = self._position_notional(pos, get_contract_size)
            direction = str(pos.get("type", "BUY")).upper()
            is_long = "BUY" in direction or direction == "LONG"

            if symbol in CRYPTO_SYMBOLS and is_long:
                crypto_long += notional
            if symbol in FOREX_USD_LONG_CLUSTER and is_long:
                usd_long += notional
            if symbol in FOREX_USD_SHORT_CLUSTER and not is_long:
                usd_long += notional
            if symbol in METALS_CLUSTER:
                metals_notional += notional
            if symbol in FOREX_CHF_CLUSTER:
                chf_notional += notional

        crypto_pct = crypto_long / equity
        usd_pct = usd_long / equity
        metals_pct = metals_notional / equity
        chf_pct = chf_notional / equity
        leverage = gross_exposure / equity
        net_directional = self.net_directional_ratio(positions, get_contract_size)
        gross_pct = gross_exposure / equity

        block_reason = None
        if (
            len(positions) >= 2
            and net_directional > self.net_directional_cap
            and gross_pct >= self.net_directional_min_gross_pct
        ):
            block_reason = f"Net directional {net_directional:.0%} > {self.net_directional_cap:.0%}"
        elif crypto_pct > self.crypto_long_cap:
            block_reason = f"Net crypto long {crypto_pct:.0%} > {self.crypto_long_cap:.0%}"
        elif usd_pct > self.cluster_cap:
            block_reason = f"USD cluster exposure {usd_pct:.0%} > {self.cluster_cap:.0%}"
        elif metals_pct > self.metals_cluster_max_pct:
            block_reason = (
                f"Metals cluster exposure {metals_pct:.0%} > {self.metals_cluster_max_pct:.0%}"
            )
        elif chf_pct > self.chf_cluster_max_pct:
            block_reason = f"CHF cluster exposure {chf_pct:.0%} > {self.chf_cluster_max_pct:.0%}"

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
        volume: float = 0.0,
        price: float = 0.0,
        contract_size: float = 1.0,
        get_contract_size: Callable[[str], float] | None = None,
    ) -> tuple[bool, str | None]:
        """Project leverage and cluster exposure after proposed trade."""
        trade_price = price if price > 0 else (
            trade_notional / max(volume * contract_size, 1e-9) if volume > 0 else 0.0
        )
        projected_positions = list(positions)
        projected_positions.append({
            "symbol": symbol,
            "type": direction,
            "volume": volume if volume > 0 else trade_notional / max(trade_price * contract_size, 1e-9),
            "price_open": trade_price if trade_price > 0 else 1.0,
            "contract_size": contract_size,
        })
        new_gross = gross_exposure + trade_notional
        projected_lev = new_gross / max(equity, 1e-9)
        if projected_lev > max_leverage:
            return False, f"Projected leverage {projected_lev:.1f}× > {max_leverage}×"

        corr_notional, pair_label = self._correlated_exposure(
            positions, symbol, direction, trade_notional, get_contract_size,
        )
        if pair_label and corr_notional / equity > self.cluster_cap:
            return (
                False,
                f"Correlated exposure {corr_notional / equity:.0%} exceeds "
                f"{self.cluster_cap:.0%} cap ({pair_label})",
            )

        if symbol in METALS_CLUSTER:
            symbol_existing = sum(
                self._position_notional(p, get_contract_size)
                for p in positions
                if str(p.get("symbol", "")) == symbol
            )
            symbol_pct = (symbol_existing + trade_notional) / equity
            if symbol_pct > self.metals_single_max_pct:
                return (
                    False,
                    f"Metals single-symbol exposure {symbol_pct:.0%} exceeds "
                    f"{self.metals_single_max_pct:.0%} cap",
                )
            metals_existing = self._cluster_notional(positions, METALS_CLUSTER, get_contract_size)
            projected_metals_pct = (metals_existing + trade_notional) / equity
            if projected_metals_pct > self.metals_cluster_max_pct:
                return (
                    False,
                    f"Metals cluster exposure {projected_metals_pct:.0%} exceeds "
                    f"{self.metals_cluster_max_pct:.0%} cap",
                )

        if symbol in FOREX_CHF_CLUSTER:
            chf_existing = self._cluster_notional(positions, FOREX_CHF_CLUSTER, get_contract_size)
            projected_chf_pct = (chf_existing + trade_notional) / equity
            if projected_chf_pct > self.chf_cluster_max_pct:
                return (
                    False,
                    f"CHF cluster exposure {projected_chf_pct:.0%} exceeds "
                    f"{self.chf_cluster_max_pct:.0%} cap",
                )

        heat = self.assess(equity, projected_positions, new_gross, get_contract_size)
        if not heat.allow_trade:
            current_net = self.net_directional_ratio(positions, get_contract_size)
            projected_net = self.net_directional_ratio(projected_positions, get_contract_size)
            if projected_net < current_net:
                pass  # balancing trade — allow despite net directional cap
            else:
                return False, heat.block_reason

        is_crypto = symbol in CRYPTO_SYMBOLS
        is_long = direction.upper() == "BUY"
        if is_crypto and is_long:
            current = self.assess(equity, positions, gross_exposure, get_contract_size)
            added_pct = trade_notional / equity
            if current.net_crypto_long_pct + added_pct > self.crypto_long_cap:
                return False, "Would exceed crypto long cap"

        return True, None
