"""ML signal agent — uses trained GradientBoosting model when available."""

from __future__ import annotations

import os
from pathlib import Path

from src.agents.base_agent import AgentSignal, BaseTradingAgent, Direction, FeatureVector
from src.learning.signal_model import DEFAULT_MODEL_PATH, SignalModel


class MLSignalAgent(BaseTradingAgent):
    name = "ml_signal"
    base_weight = 0.10

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        model_path = config.get("model_path") or os.getenv("ML_SIGNAL_MODEL_PATH", str(DEFAULT_MODEL_PATH))
        self._model = SignalModel(model_path)
        self._stop_mult = float(config.get("stop_atr_mult", 1.5))
        self._target_mult = float(config.get("target_atr_mult", 2.5))
        self._min_confidence = float(config.get("min_confidence", 0.55))

    @property
    def is_active(self) -> bool:
        return self._model.is_loaded

    def analyze(self, features: FeatureVector) -> AgentSignal:
        if not self.is_active:
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning="ML model not loaded",
            )

        label, confidence = self._model.predict(features)
        if confidence < self._min_confidence or label == "HOLD":
            return AgentSignal(
                agent_name=self.name,
                symbol=features.symbol,
                direction=Direction.HOLD,
                confidence=0.0,
                reasoning=f"ML signal below threshold ({label} conf={confidence:.2f})",
            )

        direction = Direction.BUY if label == "BUY" else Direction.SELL
        atr = features.atr_14
        if direction == Direction.BUY:
            sl = features.close - atr * self._stop_mult
            tp = features.close + atr * self._target_mult
        else:
            sl = features.close + atr * self._stop_mult
            tp = features.close - atr * self._target_mult

        return AgentSignal(
            agent_name=self.name,
            symbol=features.symbol,
            direction=direction,
            confidence=confidence,
            stop_loss=sl,
            take_profit=tp,
            reasoning=f"ML {label} conf={confidence:.2f}",
            metadata={"ml_label": label, "ml_confidence": confidence},
        )
