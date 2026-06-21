"""Technical feature computation from OHLCV bars."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.agents.base_agent import FeatureVector, Regime
from src.data.regime_detector import RegimeDetector

TIMEFRAME_FACTORS: dict[str, int] = {
    "M15": 1,
    "H1": 4,
    "H4": 16,
}


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _atr(high, low, close, period)
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.rolling(period).mean()


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    line = ema12 - ema26
    signal = _ema(line, 9)
    hist = line - signal
    return line, signal, hist


def _percentile_rank(series: pd.Series, window: int = 100) -> pd.Series:
    return series.rolling(window).apply(
        lambda x: float(np.searchsorted(np.sort(x), x.iloc[-1], side="right")) / len(x) * 100
        if len(x) > 0
        else 50.0,
        raw=False,
    )


class FeatureEngine:
    """Compute multi-indicator feature vectors from OHLCV data."""

    def __init__(self) -> None:
        self.regime_detector = RegimeDetector()

    @staticmethod
    def resample_ohlcv(df: pd.DataFrame, factor: int) -> pd.DataFrame:
        if factor <= 1:
            return df.copy()
        n = len(df) // factor * factor
        trimmed = df.iloc[-n:].copy()
        groups = np.arange(len(trimmed)) // factor
        out = trimmed.groupby(groups).agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        return out.reset_index(drop=True)

    def compute(self, symbol: str, timeframe: str, ohlcv: pd.DataFrame) -> FeatureVector:
        df = ohlcv.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = df[col].astype(float)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        atr_14_s = _atr(high, low, close, 14)
        atr_50_s = _atr(high, low, close, 50)
        rsi_14_s = _rsi(close, 14)
        adx_s = _adx(high, low, close, 14)
        ema_9 = _ema(close, 9)
        ema_21 = _ema(close, 21)
        ema_50 = _ema(close, 50)
        ema_200 = _ema(close, 200)

        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        bb_width_pct = _percentile_rank(bb_width.fillna(0))

        donchian_high = high.rolling(20).max()
        donchian_low = low.rolling(20).min()

        vol_avg = volume.rolling(20).mean()
        volume_ratio = (volume / vol_avg.replace(0, np.nan)).fillna(1.0)

        macd_line, macd_signal, macd_hist = _macd(close)
        atr_pct = _percentile_rank(atr_14_s.fillna(0))

        atr_14 = float(atr_14_s.iloc[-1]) if len(atr_14_s) else 0.0
        atr_50 = float(atr_50_s.iloc[-1]) if len(atr_50_s) else atr_14
        rsi_14 = float(rsi_14_s.iloc[-1]) if len(rsi_14_s) else 50.0
        adx = float(adx_s.iloc[-1]) if len(adx_s) else 0.0
        bb_width_val = float(bb_width.iloc[-1]) if len(bb_width) else 0.0
        bb_width_percentile = float(bb_width_pct.iloc[-1]) if len(bb_width_pct) else 50.0
        atr_percentile = float(atr_pct.iloc[-1]) if len(atr_pct) else 50.0

        regime = self.regime_detector.classify(adx, atr_percentile, bb_width_percentile)

        return FeatureVector(
            symbol=symbol,
            timeframe=timeframe,
            close=float(close.iloc[-1]),
            atr_14=max(atr_14, 1e-9),
            atr_50=max(atr_50, 1e-9),
            rsi_14=max(0.0, min(100.0, rsi_14)),
            adx=max(adx, 0.0),
            ema_9=float(ema_9.iloc[-1]),
            ema_21=float(ema_21.iloc[-1]),
            ema_50=float(ema_50.iloc[-1]),
            ema_200=float(ema_200.iloc[-1]),
            bb_width=bb_width_val,
            bb_width_percentile=bb_width_percentile,
            donchian_high=float(donchian_high.iloc[-1]),
            donchian_low=float(donchian_low.iloc[-1]),
            volume_ratio=float(volume_ratio.iloc[-1]),
            macd_histogram=float(macd_hist.iloc[-1]),
            regime=regime,
            extras={
                "bb_middle": float(bb_mid.iloc[-1]),
                "bb_upper": float(bb_upper.iloc[-1]),
                "bb_lower": float(bb_lower.iloc[-1]),
                "atr_percentile": atr_percentile,
                "macd_line": float(macd_line.iloc[-1]),
                "macd_signal": float(macd_signal.iloc[-1]),
                "macd_histogram_prev": float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else 0.0,
            },
        )

    def compute_multi(
        self,
        symbol: str,
        m15_ohlcv: pd.DataFrame,
        donchian_period: int = 20,
    ) -> dict[str, FeatureVector]:
        _ = donchian_period  # used when computing donchian extras in engine
        out: dict[str, FeatureVector] = {}
        out["M15"] = self.compute(symbol, "M15", m15_ohlcv)
        h1 = self.resample_ohlcv(m15_ohlcv, TIMEFRAME_FACTORS["H1"])
        h4 = self.resample_ohlcv(m15_ohlcv, TIMEFRAME_FACTORS["H4"])
        min_bars = 20
        if len(h1) >= min_bars:
            out["H1"] = self.compute(symbol, "H1", h1)
        if len(h4) >= min_bars:
            out["H4"] = self.compute(symbol, "H4", h4)
        return out
