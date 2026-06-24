"""Account profile detection — competition vs practice vs micro."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ProfileKind = Literal["competition", "practice", "micro"]

COMPETITION_EQUITY_MIN = 500_000.0
COMPETITION_EQUITY_MAX = 2_000_000.0
MICRO_EQUITY_MAX = 100.0
PRACTICE_EQUITY_MAX = 500_000.0


@dataclass(frozen=True)
class AccountProfile:
    kind: ProfileKind
    initial_equity: float
    concentration_reference: float
    leverage_reference: float
    display_scale: float
    chart_base: float

    @property
    def is_competition(self) -> bool:
        return self.kind == "competition"

    @property
    def name(self) -> ProfileKind:
        """Alias for kind (preflight / legacy callers)."""
        return self.kind


def detect_profile(equity: float, override: str | None = None) -> AccountProfile:
    """Detect account profile from equity; env ACCOUNT_PROFILE overrides auto."""
    env_override = (override or os.getenv("ACCOUNT_PROFILE", "auto")).strip().lower()

    if env_override in ("competition", "practice", "micro"):
        kind: ProfileKind = env_override  # type: ignore[assignment]
    elif equity < MICRO_EQUITY_MAX:
        kind = "micro"
    elif COMPETITION_EQUITY_MIN <= equity <= COMPETITION_EQUITY_MAX:
        kind = "competition"
    else:
        kind = "practice"

    if kind == "competition":
        ref_equity = max(equity, 1_000_000.0)
        display_scale = 1.0
    elif kind == "micro":
        ref_equity = max(equity, 1.0)
        display_scale = 0.001
    else:
        ref_equity = max(equity, 10_000.0)
        display_scale = 0.01

    return AccountProfile(
        kind=kind,
        initial_equity=equity,
        concentration_reference=ref_equity,
        leverage_reference=ref_equity,
        display_scale=display_scale,
        chart_base=ref_equity,
    )


def position_notional(volume: float, contract_size: float, price: float) -> float:
    """Compute position notional using contract size (not vol × price alone)."""
    if volume <= 0 or contract_size <= 0 or price <= 0:
        return 0.0
    return abs(volume * contract_size * price)


def position_notional_from_dict(
    pos: dict,
    contract_size: float,
    price_key: str = "price_open",
) -> float:
    """Notional for an MT5 position dict using contract size."""
    volume = float(pos.get("volume", 0))
    price = float(pos.get(price_key, 0) or pos.get("price_current", 0))
    cs = float(pos.get("contract_size", 0)) or contract_size
    return position_notional(volume, cs, price)


def normalize_concentration(
    position_notional_value: float,
    equity: float,
    profile: AccountProfile,
) -> float:
    """Normalize concentration pct against account profile reference equity."""
    ref = max(profile.concentration_reference, equity, 1e-9)
    return position_notional_value / ref
