"""Configuration loader for QuantAI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
BST = ZoneInfo("Europe/London")

OBJECTIVE_PROFILES: dict[str, dict[str, Any]] = {
    "maximize_return": {
        "min_confidence_floor": 0.55,
        "max_new_entries_per_cycle": None,
        "risk_multiplier_scale": 1.0,
    },
    "avoid_elimination": {
        "min_confidence_floor": 0.62,
        "max_new_entries_per_cycle": 2,
        "risk_multiplier_scale": 0.75,
    },
    "optimize_composite": {
        "min_confidence_floor": 0.60,
        "max_new_entries_per_cycle": 3,
        "risk_multiplier_scale": 0.95,
    },
}


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_phase(phase: str | None = None, auto: bool = True) -> str:
    """Resolve competition phase; auto-switch by BST schedule when auto=True."""
    if phase and not auto:
        return phase
    if phase and phase != "auto":
        explicit = phase
    else:
        explicit = None

    phases_cfg = load_yaml("phases.yaml").get("phases", {})
    now = datetime.now(BST)

    for name, cfg in phases_cfg.items():
        start_s = cfg.get("start")
        end_s = cfg.get("end")
        if not start_s or not end_s:
            continue
        try:
            start = datetime.fromisoformat(start_s)
            end = datetime.fromisoformat(end_s)
            if start <= now < end:
                return name
        except ValueError:
            continue

    # After the last scheduled phase ends, hold on finals (do not revert to round1).
    last_named = explicit or "round1"
    latest_end: datetime | None = None
    for name, cfg in phases_cfg.items():
        end_s = cfg.get("end")
        if not end_s:
            continue
        try:
            end = datetime.fromisoformat(end_s)
        except ValueError:
            continue
        if latest_end is None or end > latest_end:
            latest_end = end
            last_named = name

    if latest_end is not None and now >= latest_end:
        return last_named

    return explicit or "round1"


@dataclass
class QuantAIConfig:
    agents: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    phases: dict[str, Any] = field(default_factory=dict)
    instruments: list[dict[str, Any]] = field(default_factory=list)
    regime_boosts: dict[str, dict[str, float]] = field(default_factory=dict)
    engine: dict[str, Any] = field(default_factory=dict)
    current_phase: str = "round1"

    @classmethod
    def load(cls, phase: str = "round1", auto_phase: bool = True) -> QuantAIConfig:
        agents_cfg = load_yaml("agents.yaml")
        risk_cfg = load_yaml("risk.yaml")
        phases_cfg = load_yaml("phases.yaml")
        instruments_cfg = load_yaml("instruments.yaml")

        resolved = resolve_phase(phase, auto=auto_phase)

        return cls(
            agents=agents_cfg.get("agents", {}),
            risk=risk_cfg.get("risk", {}),
            phases=phases_cfg.get("phases", {}),
            instruments=instruments_cfg.get("instruments", []),
            regime_boosts=agents_cfg.get("regime_boosts", {}),
            engine=phases_cfg.get("engine", {}),
            current_phase=resolved,
        )

    @property
    def objective(self) -> str:
        return str(self.phase_rules.get("objective", "maximize_return"))

    def objective_profile(self) -> dict[str, Any]:
        return dict(OBJECTIVE_PROFILES.get(self.objective, OBJECTIVE_PROFILES["maximize_return"]))

    @property
    def phase_multiplier(self) -> float:
        phase = self.phases.get(self.current_phase, {})
        base = float(phase.get("risk_multiplier", 1.0))
        scale = float(self.objective_profile().get("risk_multiplier_scale", 1.0))
        return base * scale

    @property
    def feature_update_seconds(self) -> int:
        return int(self.engine.get("feature_update_seconds", 60))

    @property
    def active_symbols(self) -> list[str]:
        phase_cfg = self.phases.get(self.current_phase, {})
        drop_symbols = set(phase_cfg.get("drop_symbols", []))
        disabled_agents = set(phase_cfg.get("disabled_agents", []))

        symbols = []
        for inst in self.instruments:
            if not inst.get("active", True):
                continue
            sym = inst["symbol"]
            if sym in drop_symbols:
                continue
            # Round 3: forex + metals by default; crypto when phase enables it
            if self.current_phase == "round3":
                cat = inst.get("category", "")
                phase_cfg = self.phases.get("round3", {})
                if cat == "crypto" and not phase_cfg.get("include_crypto", False):
                    continue
            symbols.append(sym)
        return symbols

    def agent_config(self, name: str) -> dict[str, Any]:
        return self.agents.get(name, {})

    def allocation_for(self, symbol: str) -> float:
        for inst in self.instruments:
            if inst.get("symbol") == symbol:
                return float(inst.get("allocation", 1.0))
        return 1.0

    def bias_for(self, symbol: str) -> str:
        for inst in self.instruments:
            if inst.get("symbol") == symbol:
                return str(inst.get("bias", "mixed"))
        return "mixed"

    def category_for(self, symbol: str) -> str:
        for inst in self.instruments:
            if inst.get("symbol") == symbol:
                return str(inst.get("category", ""))
        return ""

    def is_agent_enabled(self, agent_name: str) -> bool:
        phase_cfg = self.phases.get(self.current_phase, {})
        disabled = phase_cfg.get("disabled_agents", [])
        return agent_name not in disabled

    def max_risk_pct(self) -> float:
        phase_cfg = self.phases.get(self.current_phase, {})
        defaults = {"round1": 0.025, "round2": 0.015, "round3": 0.01, "finals": 0.015}
        return float(phase_cfg.get("max_risk_pct", defaults.get(self.current_phase, 0.02)))

    @property
    def phase_rules(self) -> dict[str, Any]:
        """Per-round playbook rules merged with sensible defaults."""
        phase_cfg = dict(self.phases.get(self.current_phase, {}))
        defaults: dict[str, dict[str, Any]] = {
            "round1": {
                "disabled_agents": [],
                "low_allocation_symbols": set(),
                "low_allocation_requires_a_plus": False,
                "crypto_only_if_dd_normal": False,
                "discipline_halt_below": None,
                "ignore_session_agents": True,
                "min_agent_confidence": 0.40,
                "max_new_entries_per_cycle": 8,
                "prioritize_by_opportunity": True,
                "session_symbol_filter": False,
                "orchestrator_cooldown_minutes": 5,
                "cycle_minutes": 8,
                "net_directional_enforce_min_gross_pct": 0.20,
                "max_risk_pct": 0.032,
                "return_focus": True,
                "min_orchestrator_size_scale": 0.90,
                "symbol_cooldown_minutes": 16,
                "macro_block_crypto_long_fear_below": 25,
                "min_consensus_agents": 2,
                "blocked_symbols": [],
                "enable_partial_takes": True,
                "enable_trailing": False,
                "enable_breakeven": True,
                "partial_take_r": 1.0,
                "partial_fraction": 0.33,
                "breakeven_r": 0.75,
                "time_stop_bars": 12,
                "time_stop_min_r": 0.25,
            },
            "round2": {
                "disabled_agents": [],
                "low_allocation_symbols": {"BAR/USD", "XRP/USD"},
                "low_allocation_requires_a_plus": True,
                "min_confidence_a_plus": 0.80,
                "crypto_only_if_dd_normal": False,
                "discipline_halt_below": None,
                "ignore_session_agents": True,
                "session_symbol_filter": False,
                "prioritize_by_opportunity": True,
                "return_focus": True,
                "max_risk_pct": 0.020,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "enable_breakeven": True,
                "partial_fraction": 0.40,
                "breakeven_r": 0.75,
                "time_stop_bars": 10,
                "time_stop_min_r": 0.25,
                "max_new_entries_per_cycle": 4,
                "symbol_cooldown_minutes": 30,
                "cycle_minutes": 8,
                "min_consensus_agents": 2,
                "blocked_symbols": ["XRP/USD", "BAR/USD"],
                "net_directional_enforce_min_gross_pct": 0.15,
            },
            "round3": {
                "disabled_agents": [],
                "low_allocation_symbols": set(),
                "low_allocation_requires_a_plus": False,
                "crypto_only_if_dd_normal": True,
                "include_crypto": True,
                "discipline_halt_below": None,
                "objective": "maximize_return",
                "return_focus": True,
                "ignore_session_agents": True,
                "session_symbol_filter": False,
                "prioritize_by_opportunity": True,
                "max_risk_pct": 0.018,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "enable_breakeven": True,
                "trail_after_r": 1.25,
                "regime_flip_enabled": True,
                "time_stop_bars": 10,
                "time_stop_m15_bars": 10,
                "time_stop_min_r": 0.15,
                "max_new_entries_per_cycle": 4,
                "symbol_cooldown_minutes": 20,
                "cycle_minutes": 10,
                "min_orchestrator_size_scale": 0.85,
                "blocked_symbols": ["XRP/USD", "BAR/USD", "EUR/GBP", "USD/CHF", "USD/JPY"],
            },
            "finals": {
                "disabled_agents": [],
                "low_allocation_symbols": set(),
                "low_allocation_requires_a_plus": False,
                "crypto_only_if_dd_normal": False,
                "include_crypto": True,
                "discipline_halt_below": 95,
                "objective": "maximize_return",
                "return_focus": True,
                "ignore_session_agents": True,
                "session_symbol_filter": False,
                "prioritize_by_opportunity": True,
                "max_risk_pct": 0.020,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "enable_breakeven": True,
                "trail_after_r": 1.5,
                "regime_flip_enabled": True,
                "time_stop_bars": 12,
                "time_stop_m15_bars": 12,
                "time_stop_min_r": 0.15,
                "max_new_entries_per_cycle": 4,
                "symbol_cooldown_minutes": 18,
                "cycle_minutes": 8,
                "min_orchestrator_size_scale": 0.88,
                "blocked_symbols": ["XRP/USD", "BAR/USD", "EUR/GBP", "USD/CHF", "USD/JPY"],
            },
        }
        merged = {**defaults.get(self.current_phase, {}), **phase_cfg}
        low = merged.get("low_allocation_symbols", set())
        if isinstance(low, list):
            merged["low_allocation_symbols"] = set(low)
        return merged

    def cycle_minutes(self) -> int:
        """Decision loop interval for the active competition phase."""
        rules = self.phase_rules
        raw = (
            rules.get("cycle_minutes")
            or self.phases.get(self.current_phase, {}).get("cycle_minutes")
            or self.engine.get("cycle_minutes", 15)
        )
        return int(raw)
