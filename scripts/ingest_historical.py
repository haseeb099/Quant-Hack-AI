#!/usr/bin/env python3
"""Ingest competition historical dataset to Parquet/SQLite."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest historical competition data")
    parser.add_argument("--input", required=True, help="Input directory or file")
    parser.add_argument("--output", default="data/historical", help="Output directory")
    parser.add_argument("--format", choices=["parquet", "csv"], default="parquet")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    import pandas as pd

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    if input_path.is_file():
        files = [input_path]
    else:
        files = list(input_path.glob("**/*.csv")) + list(input_path.glob("**/*.json"))

    if not files:
        logger.error("No input files found in %s", input_path)
        return

    total_rows = 0
    for fpath in files:
        try:
            if fpath.suffix == ".csv":
                df = pd.read_csv(fpath)
            else:
                df = pd.read_json(fpath)

            required = {"open", "high", "low", "close"}
            if not required.issubset(df.columns):
                logger.warning("Skipping %s — missing OHLC columns", fpath)
                continue

            if "volume" not in df.columns:
                df["volume"] = 0.0

            symbol = fpath.stem.replace("_", "/")
            out_name = fpath.stem
            if args.format == "parquet":
                out_path = output_dir / f"{out_name}.parquet"
                df.to_parquet(out_path, index=False)
            else:
                out_path = output_dir / f"{out_name}.csv"
                df.to_csv(out_path, index=False)

            total_rows += len(df)
            logger.info("Ingested %s → %s (%d rows)", fpath, out_path, len(df))
        except Exception:
            logger.warning("Failed to ingest %s", fpath, exc_info=True)

    logger.info("Ingestion complete: %d files, %d total rows", len(files), total_rows)


if __name__ == "__main__":
    main()
