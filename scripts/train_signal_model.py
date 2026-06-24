#!/usr/bin/env python3
"""Train ML signal model from historical OHLCV."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.learning.signal_model import DEFAULT_MODEL_PATH, SignalModel
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train ML signal model")
    parser.add_argument("--data-dir", default="data/historical", help="OHLCV data directory")
    parser.add_argument("--output", default=str(DEFAULT_MODEL_PATH), help="Model output path")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    model = SignalModel(args.output)
    n = model.train_from_directory(args.data_dir)
    if n == 0:
        logger.error("Training failed — no samples")
        sys.exit(1)
    logger.info("Model saved to %s (%d samples)", args.output, n)


if __name__ == "__main__":
    main()
