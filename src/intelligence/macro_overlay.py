"""Macro regime overlay — risk-on/off and USD strength proxy."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from src.intelligence.models import MacroRegime
from src.intelligence.rapidapi_client import (
    cash_flow_macro_notes,
    fetch_company_cash_flow,
    rapidapi_key,
)

logger = logging.getLogger(__name__)


class MacroOverlay:
    """Computes macro regime from Fear & Greed and optional indicators."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        macro_cfg = config.get("macro", {})
        self.fear_greed_enabled = macro_cfg.get("fear_greed_enabled", True)
        self.fear_greed_url = macro_cfg.get(
            "fear_greed_url", "https://api.alternative.me/fng/",
        )
        self.rapidapi_cash_flow_enabled = macro_cfg.get("rapidapi_cash_flow_enabled", True)
        self._regime: MacroRegime | None = None
        self._last_refresh: datetime | None = None

    def _fetch_rapidapi_cash_flow_note(self) -> str | None:
        enabled = os.getenv("RAPIDAPI_FINANCE_ENABLED", "").strip().lower()
        if enabled in ("0", "false", "no"):
            return None
        if not self.rapidapi_cash_flow_enabled or not rapidapi_key():
            return None
        payload = fetch_company_cash_flow()
        if not payload:
            return None
        note = cash_flow_macro_notes(payload)
        return note or None

    def _fetch_fear_greed(self) -> int | None:
        if not self.fear_greed_enabled:
            return None
        try:
            with urllib.request.urlopen(self.fear_greed_url, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            items = data.get("data", [])
            if items:
                return int(items[0].get("value", 50))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            logger.debug("Fear & Greed fetch failed: %s", exc)
        return None

    def refresh(self, force: bool = False) -> MacroRegime:
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._last_refresh
            and self._regime
            and (now - self._last_refresh).total_seconds() < 600
        ):
            return self._regime

        fg = self._fetch_fear_greed()
        cash_flow_note = self._fetch_rapidapi_cash_flow_note()
        if fg is not None:
            if fg >= 60:
                bias, usd = "risk_on", "weak"
                notes = f"Fear & Greed {fg} — risk-on environment"
            elif fg <= 40:
                bias, usd = "risk_off", "strong"
                notes = f"Fear & Greed {fg} — risk-off, USD bid"
            else:
                bias, usd = "neutral", "neutral"
                notes = f"Fear & Greed {fg} — neutral macro"
        else:
            bias, usd, notes = "neutral", "neutral", "Macro data unavailable — neutral default"
            fg = None
        if cash_flow_note:
            notes = f"{notes}; {cash_flow_note}"

        self._regime = MacroRegime(bias=bias, usd_strength=usd, fear_greed=fg, notes=notes)
        self._last_refresh = now
        return self._regime

    @property
    def regime(self) -> MacroRegime:
        if self._regime is None:
            return self.refresh(force=True)
        return self._regime

    def size_adjustment(self, symbol: str, direction: str) -> float:
        """Return sizing multiplier based on macro alignment."""
        r = self.regime
        is_crypto = symbol in {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
        is_metal = symbol in {"XAU/USD", "XAG/USD"}
        is_usd_quote = symbol.endswith("/USD") or symbol.startswith("USD/")

        if r.bias == "risk_off" and r.usd_strength == "strong":
            if is_crypto and direction == "BUY":
                return 0.65
            if is_crypto and direction == "SELL":
                return 1.18
            if is_metal and direction == "BUY":
                return 1.12
            if is_usd_quote and direction == "BUY" and symbol.startswith("USD/"):
                return 1.08
        if r.bias == "risk_on" and r.usd_strength == "weak":
            if is_crypto and direction == "BUY":
                return 1.12
            if is_crypto and direction == "SELL":
                return 0.88
        return 1.0
