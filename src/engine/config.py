"""Configuration loader for QuantAI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class QuantAIConfig:
    agents: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    phases: dict[str, Any] = field(default_factory=dict)
    instruments: list[dict[str, Any]] = field(default_factory=list)
    regime_boosts: dict[str, dict[str, float]] = field(default_factory=dict)
    current_phase: str = "round1"

    @classmethod
    def load(cls, phase: str = "round1") -> QuantAIConfig:
        agents_cfg = load_yaml("agents.yaml")
        risk_cfg = load_yaml("risk.yaml")
        phases_cfg = load_yaml("phases.yaml")
        instruments_cfg = load_yaml("instruments.yaml")

        return cls(
            agents=agents_cfg.get("agents", {}),
            risk=risk_cfg.get("risk", {}),
            phases=phases_cfg.get("phases", {}),
            instruments=instruments_cfg.get("instruments", []),
            regime_boosts=agents_cfg.get("regime_boosts", {}),
            current_phase=phase,
        )

    @property
    def phase_multiplier(self) -> float:
        phase = self.phases.get(self.current_phase, {})
        return phase.get("risk_multiplier", 1.0)

    @property
    def active_symbols(self) -> list[str]:
        return [i["symbol"] for i in self.instruments if i.get("active", True)]

    def agent_config(self, name: str) -> dict[str, Any]:
        return self.agents.get(name, {})
