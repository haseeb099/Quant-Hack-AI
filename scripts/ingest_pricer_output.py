#!/usr/bin/env python3
"""Ingest pricer tick parquet files into M15 OHLCV for historical learning."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)

DEFAULT_INPUT = "pricer-output-2026-05-11_2026-06-10"
DEFAULT_OUTPUT = "data/historical"

# Pricer folder uses compact symbols (EURUSD); output matches ingest_historical stem convention.
COMPETITION_SYMBOLS = frozenset({
    "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
    "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCHF",
})

FILE_PATTERN = re.compile(r"^([A-Z]{6})_(\d{4})_(\d{2})_(\d{2})\.parquet$")


def pricer_symbol_to_stem(pricer_sym: str) -> str:
    """EURUSD -> EUR_USD (matches build_regime_library symbol parsing)."""
    if len(pricer_sym) != 6:
        return pricer_sym
    return f"{pricer_sym[:3]}_{pricer_sym[3:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest pricer tick parquet to M15 OHLCV")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Pricer output directory")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output directory")
    return parser.parse_args()


def _parse_timestamp(series) -> "pd.Series":
    import pandas as pd

    ts = pd.to_datetime(series, utc=True, errors="coerce")
    if ts.isna().all():
        raise ValueError("No valid timestamps in time/received columns")
    return ts


def resample_ticks_to_m15(df) -> "pd.DataFrame":
    """Resample tick mid prices to M15 OHLCV; volume = tick count per bar."""
    import pandas as pd

    time_col = "received" if "received" in df.columns else "time"
    ts = _parse_timestamp(df[time_col])
    mid = (df["bid"].astype(float) + df["ask"].astype(float)) / 2.0

    ticks = pd.DataFrame({"mid": mid.values}, index=ts.values)
    ticks = ticks.dropna().sort_index()
    if ticks.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    ohlcv = ticks["mid"].resample("15min").agg(["first", "max", "min", "last", "count"])
    ohlcv.columns = ["open", "high", "low", "close", "volume"]
    ohlcv = ohlcv.dropna(subset=["open", "close"])
    ohlcv["volume"] = ohlcv["volume"].astype(float)
    return ohlcv.reset_index(drop=True)


def ingest_symbol_files(files: list[Path], output_dir: Path) -> int:
    """Ingest all daily files for one symbol in a single concat/write pass."""
    import pandas as pd

    if not files:
        return 0

    match = FILE_PATTERN.match(files[0].name)
    if not match:
        return 0

    pricer_sym = match.group(1)
    stem = pricer_symbol_to_stem(pricer_sym)
    out_path = output_dir / f"{stem}.parquet"

    chunks: list[pd.DataFrame] = []
    for fpath in files:
        try:
            df = pd.read_parquet(fpath)
            if "bid" not in df.columns or "ask" not in df.columns:
                logger.warning("Skipping %s - missing bid/ask columns", fpath)
                continue
            m15 = resample_ticks_to_m15(df)
            if not m15.empty:
                chunks.append(m15)
        except Exception:
            logger.warning("Failed to ingest %s", fpath, exc_info=True)

    if not chunks:
        return 0

    combined = pd.concat(chunks, ignore_index=True)
    combined = combined.drop_duplicates(subset=["open", "high", "low", "close"], keep="last")
    combined.to_parquet(out_path, index=False)
    logger.info("Ingested %d files -> %s (%d bars)", len(chunks), out_path, len(combined))
    return len(combined)


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        logger.error("Input directory not found: %s", input_dir)
        sys.exit(1)

    files = sorted(input_dir.glob("*.parquet"))
    if not files:
        logger.error("No parquet files in %s", input_dir)
        sys.exit(1)

    by_symbol: dict[str, list[Path]] = {}
    for fpath in files:
        match = FILE_PATTERN.match(fpath.name)
        if not match:
            continue
        pricer_sym = match.group(1)
        if pricer_sym not in COMPETITION_SYMBOLS:
            continue
        by_symbol.setdefault(pricer_sym, []).append(fpath)

    total_bars = 0
    processed = 0
    for pricer_sym in sorted(by_symbol):
        try:
            bars = ingest_symbol_files(by_symbol[pricer_sym], output_dir)
            if bars > 0:
                processed += len(by_symbol[pricer_sym])
                total_bars += bars
        except Exception:
            logger.warning("Failed symbol batch %s", pricer_sym, exc_info=True)

    logger.info(
        "Pricer ingest complete: %d files processed, %d total bars written to %s",
        processed,
        total_bars,
        output_dir,
    )


if __name__ == "__main__":
    main()
