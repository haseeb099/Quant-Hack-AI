"""ML signal model — GradientBoosting on feature vectors."""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("data/models/signal_model.pkl")
DEFAULT_METRICS_PATH = Path("data/models/signal_model_metrics.json")
TRAIN_FRACTION = 0.70
MIN_BARS_PER_SYMBOL = 500

FEATURE_NAMES = [
    "adx",
    "rsi_14",
    "atr_14",
    "atr_50",
    "ema_9",
    "ema_21",
    "ema_50",
    "ema_200",
    "bb_width",
    "bb_width_percentile",
    "donchian_high",
    "donchian_low",
    "volume_ratio",
    "macd_histogram",
]

LABEL_MAP = {0: "HOLD", 1: "BUY", 2: "SELL"}
INV_LABEL_MAP = {"HOLD": 0, "BUY": 1, "SELL": 2}


def features_to_row(features: Any) -> np.ndarray:
    row = np.array([
        features.adx,
        features.rsi_14,
        features.atr_14,
        features.atr_50,
        features.ema_9,
        features.ema_21,
        features.ema_50,
        features.ema_200,
        features.bb_width,
        features.bb_width_percentile,
        features.donchian_high,
        features.donchian_low,
        features.volume_ratio,
        features.macd_histogram,
    ], dtype=float)
    return np.nan_to_num(row, nan=0.0, posinf=0.0, neginf=0.0)


class SignalModel:
    """GradientBoosting classifier for BUY/SELL/HOLD from feature vectors."""

    def __init__(self, model_path: str | Path = DEFAULT_MODEL_PATH) -> None:
        self.model_path = Path(model_path)
        self._model: Any = None
        if self.model_path.exists():
            self.load()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        try:
            with open(self.model_path, "rb") as f:
                self._model = pickle.load(f)
            logger.info("Loaded signal model from %s", self.model_path)
            return True
        except Exception:
            logger.warning("Failed to load signal model from %s", self.model_path, exc_info=True)
            self._model = None
            return False

    def save(self) -> None:
        if self._model is None:
            raise RuntimeError("No model to save")
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump(self._model, f)
        logger.info("Saved signal model to %s", self.model_path)

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        from sklearn.ensemble import GradientBoostingClassifier

        self._model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )
        self._model.fit(X, y)

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> dict[str, Any]:
        """Return accuracy, precision, and F1 on a held-out set."""
        from sklearn.metrics import accuracy_score, f1_score, precision_score

        if self._model is None or len(X) == 0:
            return {"accuracy": 0.0, "precision": 0.0, "f1": 0.0, "samples": 0}

        y_pred = self._model.predict(X)
        return {
            "accuracy": float(accuracy_score(y, y_pred)),
            "precision": float(precision_score(y, y_pred, average="weighted", zero_division=0)),
            "f1": float(f1_score(y, y_pred, average="weighted", zero_division=0)),
            "samples": int(len(y)),
        }

    def save_metrics(self, metrics: dict[str, Any], path: str | Path | None = None) -> Path:
        out = Path(path or DEFAULT_METRICS_PATH)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        logger.info("Saved signal model metrics to %s", out)
        return out

    def predict(self, features: Any) -> tuple[str, float]:
        if self._model is None:
            return "HOLD", 0.0
        row = features_to_row(features)
        proba = self._model.predict_proba(row.reshape(1, -1))[0]
        classes = self._model.classes_
        best_idx = int(np.argmax(proba))
        label = LABEL_MAP.get(int(classes[best_idx]), "HOLD")
        confidence = float(proba[best_idx])
        return label, confidence

    @staticmethod
    def build_training_matrix(
        ohlcv_df: Any,
        symbol: str,
        feature_engine: Any,
        lookahead_bars: int = 4,
        min_return_atr: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Label bars by forward return vs ATR threshold."""
        import pandas as pd

        from src.data.feature_engine import FeatureEngine

        engine = feature_engine or FeatureEngine()
        window = 200
        X_rows: list[np.ndarray] = []
        y_rows: list[int] = []

        df = ohlcv_df.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)

        for i in range(window, len(df) - lookahead_bars):
            chunk = df.iloc[i - window : i + 1]
            features = engine.compute(symbol, "M15", chunk)
            close_now = float(df.iloc[i]["close"])
            close_fwd = float(df.iloc[i + lookahead_bars]["close"])
            atr = max(features.atr_14, 1e-9)
            ret = (close_fwd - close_now) / atr

            if ret >= min_return_atr:
                label = INV_LABEL_MAP["BUY"]
            elif ret <= -min_return_atr:
                label = INV_LABEL_MAP["SELL"]
            else:
                label = INV_LABEL_MAP["HOLD"]

            X_rows.append(features_to_row(features))
            y_rows.append(label)

        if not X_rows:
            return np.empty((0, len(FEATURE_NAMES))), np.empty(0, dtype=int)
        X = np.vstack(X_rows)
        y = np.array(y_rows, dtype=int)
        valid = np.isfinite(X).all(axis=1)
        return X[valid], y[valid]

    def train_from_directory(
        self,
        data_dir: str | Path,
        feature_engine: Any = None,
        metrics_path: str | Path | None = None,
    ) -> int:
        from src.data.feature_engine import FeatureEngine

        engine = feature_engine or FeatureEngine()
        path = Path(data_dir)
        all_X: list[np.ndarray] = []
        all_y: list[np.ndarray] = []
        per_symbol: dict[str, dict[str, Any]] = {}
        skipped_symbols: dict[str, str] = {}

        baseline_metrics: dict[str, Any] | None = None
        if DEFAULT_METRICS_PATH.exists():
            try:
                baseline_metrics = json.loads(DEFAULT_METRICS_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                baseline_metrics = None

        for fpath in sorted(path.glob("*.parquet")) + sorted(path.glob("*.csv")):
            import pandas as pd

            if fpath.suffix == ".parquet":
                df = pd.read_parquet(fpath)
            else:
                df = pd.read_csv(fpath)
            symbol = fpath.stem.replace("_", "/")
            if len(df) < MIN_BARS_PER_SYMBOL:
                skipped_symbols[symbol] = f"insufficient bars ({len(df)}<{MIN_BARS_PER_SYMBOL})"
                continue
            X, y = self.build_training_matrix(df, symbol, engine)
            if len(X) < 20:
                skipped_symbols[symbol] = f"insufficient samples ({len(X)})"
                continue
            split = max(int(len(X) * TRAIN_FRACTION), 1)
            if split >= len(X):
                split = len(X) - 1
            self.fit(X[:split], y[:split])
            per_symbol[symbol] = self.evaluate(X[split:], y[split:])
            all_X.append(X)
            all_y.append(y)

        if not all_X:
            blocked = "no symbols passed min bar gate"
            self.save_metrics(
                {
                    "train_samples": 0,
                    "test_samples": 0,
                    "symbols": [],
                    "skipped_symbols": skipped_symbols,
                    "blocked_reason": blocked,
                    "pooled": {"accuracy": 0.0, "precision": 0.0, "f1": 0.0, "samples": 0},
                    "per_symbol": per_symbol,
                },
                path=metrics_path,
            )
            logger.warning("No training samples from %s (%s)", data_dir, blocked)
            return 0

        X_full = np.vstack(all_X)
        y_full = np.concatenate(all_y)
        split_idx = max(int(len(X_full) * TRAIN_FRACTION), 1)
        if split_idx >= len(X_full):
            split_idx = len(X_full) - 1

        self.fit(X_full[:split_idx], y_full[:split_idx])
        pooled_metrics = self.evaluate(X_full[split_idx:], y_full[split_idx:])

        baseline_f1 = (
            (baseline_metrics or {}).get("pooled", {}).get("f1", 0.0)
        )
        blocked_reason: str | None = None
        if pooled_metrics["f1"] < baseline_f1 and baseline_metrics:
            blocked_reason = (
                f"OOS f1 {pooled_metrics['f1']:.3f} below baseline {baseline_f1:.3f}"
            )
            logger.warning("Model promotion blocked: %s", blocked_reason)
        else:
            self.save()

        metrics_payload = {
            "train_samples": int(split_idx),
            "test_samples": int(len(X_full) - split_idx),
            "symbols": sorted(per_symbol.keys()),
            "skipped_symbols": skipped_symbols,
            "min_bars_per_symbol": MIN_BARS_PER_SYMBOL,
            "pooled": pooled_metrics,
            "per_symbol": per_symbol,
            "blocked_reason": blocked_reason,
            "promoted": blocked_reason is None,
        }
        self.save_metrics(metrics_payload, path=metrics_path)
        logger.info(
            "Trained on %d samples (test acc=%.3f f1=%.3f promoted=%s)",
            len(y_full),
            pooled_metrics["accuracy"],
            pooled_metrics["f1"],
            blocked_reason is None,
        )
        return len(y_full)
