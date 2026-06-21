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
    def phase_multiplier(self) -> float:
        phase = self.phases.get(self.current_phase, {})
        return phase.get("risk_multiplier", 1.0)

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
            # Round 3: forex + metals only unless configured otherwise
            if self.current_phase == "round3":
                cat = inst.get("category", "")
                if cat == "crypto":
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

    def is_agent_enabled(self, agent_name: str) -> bool:
        phase_cfg = self.phases.get(self.current_phase, {})
        disabled = phase_cfg.get("disabled_agents", [])
        if self.current_phase == "round3" and not disabled:
            disabled = ["breakout_hunter"]
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
                "max_risk_pct": 0.025,
                "enable_partial_takes": False,
                "enable_trailing": False,
                "time_stop_bars": 4,
            },
            "round2": {
                "disabled_agents": [],
                "low_allocation_symbols": {"BAR/USD", "XRP/USD"},
                "low_allocation_requires_a_plus": True,
                "min_confidence_a_plus": 0.80,
                "crypto_only_if_dd_normal": False,
                "discipline_halt_below": None,
                "ignore_session_agents": False,
                "max_risk_pct": 0.015,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "time_stop_bars": 3,
            },
            "round3": {
                "disabled_agents": ["breakout_hunter"],
                "low_allocation_symbols": set(),
                "low_allocation_requires_a_plus": False,
                "crypto_only_if_dd_normal": True,
                "discipline_halt_below": None,
                "ignore_session_agents": False,
                "max_risk_pct": 0.01,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "time_stop_bars": 3,
            },
            "finals": {
                "disabled_agents": [],
                "low_allocation_symbols": set(),
                "low_allocation_requires_a_plus": False,
                "crypto_only_if_dd_normal": False,
                "discipline_halt_below": 95,
                "ignore_session_agents": False,
                "max_risk_pct": 0.015,
                "enable_partial_takes": True,
                "enable_trailing": True,
                "time_stop_bars": 3,
            },
        }
        merged = {**defaults.get(self.current_phase, {}), **phase_cfg}
        low = merged.get("low_allocation_symbols", set())
        if isinstance(low, list):
            merged["low_allocation_symbols"] = set(low)
        return merged
