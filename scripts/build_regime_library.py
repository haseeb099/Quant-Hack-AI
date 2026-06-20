#!/usr/bin/env python3
"""Build historical regime library — label each bar with regime."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.data.feature_engine import FeatureEngine
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build regime library from historical data")
    parser.add_argument("--input", default="data/historical", help="Historical data directory")
    parser.add_argument("--output", default="data/regime_library", help="Output directory")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    import pandas as pd

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine = FeatureEngine()
    files = list(input_dir.glob("*.parquet")) + list(input_dir.glob("*.csv"))

    if not files:
        logger.error("No historical files in %s", input_dir)
        return

    for fpath in files:
        try:
            if fpath.suffix == ".parquet":
                df = pd.read_parquet(fpath)
            else:
                df = pd.read_csv(fpath)

            symbol = fpath.stem.replace("_", "/")
            regimes = []
            window = 50

            for i in range(window, len(df)):
                chunk = df.iloc[i - window:i + 1]
                features = engine.compute(symbol, "M15", chunk)
                regimes.append({
                    "index": i,
                    "regime": features.regime.value,
                    "adx": features.adx,
                    "atr_14": features.atr_14,
                    "bb_width_percentile": features.bb_width_percentile,
                })

            regime_df = pd.DataFrame(regimes)
            out_path = output_dir / f"{fpath.stem}_regimes.parquet"
            regime_df.to_parquet(out_path, index=False)
            logger.info("Regime library: %s → %s (%d labels)", fpath, out_path, len(regime_df))
        except Exception:
            logger.warning("Failed regime labeling for %s", fpath, exc_info=True)

    logger.info("Regime library build complete")


if __name__ == "__main__":
    main()
