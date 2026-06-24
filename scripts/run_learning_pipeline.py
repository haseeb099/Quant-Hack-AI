#!/usr/bin/env python3
"""Full learning pipeline: backfill → audit → backtest → ML → adapt."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full learning pipeline")
    parser.add_argument("--phase", default="round1", help="Competition phase for adaptation")
    parser.add_argument("--pricer-input", default="pricer-output-2026-05-11_2026-06-10")
    parser.add_argument("--data-dir", default="data/historical")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-backfill", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-backtest", action="store_true")
    parser.add_argument("--skip-ml", action="store_true")
    return parser.parse_args()


def _run(cmd: list[str], *, allow_fail: bool = False) -> None:
    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    if proc.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def _fail_if_red_agents() -> None:
    health_path = ROOT / "data" / "agent_health.json"
    if not health_path.exists():
        return
    try:
        health = json.loads(health_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    red = set(health.get("red_agents") or [])
    critical = {"ml_signal", "sentiment_agent"} & red
    if critical and health.get("status") == "RED":
        raise RuntimeError(f"Agent health RED for critical agents: {sorted(critical)}")


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()
    py = sys.executable

    if not args.skip_backfill:
        _run([py, "scripts/backfill_trade_memory.py"], allow_fail=True)

    if not args.skip_audit:
        _run([py, "scripts/agent_audit.py"])

    _run([py, "scripts/competition_day_verify.py", "--quick"], allow_fail=True)

    if not args.skip_ingest:
        pricer_path = ROOT / args.pricer_input
        if pricer_path.exists():
            _run([
                py, "scripts/ingest_pricer_output.py",
                "--input", str(pricer_path),
                "--output", args.data_dir,
            ])
        else:
            logger.warning("Pricer input not found: %s — skipping ingest", pricer_path)

    data_path = ROOT / args.data_dir
    if data_path.exists() and any(data_path.glob("*.parquet")):
        _run([py, "scripts/build_regime_library.py", "--input", args.data_dir])
    else:
        logger.warning("No historical data in %s — skipping regime library", data_path)

    if not args.skip_backtest and data_path.exists():
        _run([
            py, "scripts/run_historical_backtest.py",
            "--data-dir", args.data_dir,
            "--round-id", "historical_backtest",
        ])

    if not args.skip_ml and data_path.exists():
        try:
            _run([py, "scripts/train_signal_model.py", "--data-dir", args.data_dir])
        except subprocess.CalledProcessError:
            logger.warning("ML training failed — continuing without model")

    _run([py, "scripts/adapt_round.py", "--phase", args.phase, "--data", args.data_dir])

    try:
        _fail_if_red_agents()
    except RuntimeError as exc:
        logger.error("%s", exc)

    _print_summary(args.data_dir)


def _print_summary(data_dir: str) -> None:
    from src.learning.signal_model import DEFAULT_METRICS_PATH

    plan_path = ROOT / "data" / "adaptation_plan.json"
    audit_path = ROOT / "data" / "agent_audit.json"
    metrics_path = ROOT / DEFAULT_METRICS_PATH
    hist_path = ROOT / data_dir

    symbols = sorted(p.stem for p in hist_path.glob("*.parquet")) if hist_path.exists() else []
    logger.info("=== Learning pipeline summary ===")
    logger.info("Historical symbols (%d): %s", len(symbols), ", ".join(symbols[:10]) or "none")

    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            logger.info(
                "Agent audit: %d trades, %d recommendations",
                audit.get("trade_count", 0),
                len(audit.get("recommendations", [])),
            )
        except (json.JSONDecodeError, OSError):
            pass

    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            pooled = metrics.get("pooled", {})
            logger.info(
                "ML model: acc=%.3f f1=%.3f promoted=%s",
                pooled.get("accuracy", 0),
                pooled.get("f1", 0),
                metrics.get("promoted", True),
            )
            if metrics.get("blocked_reason"):
                logger.info("ML blocked: %s", metrics["blocked_reason"])
        except (json.JSONDecodeError, OSError):
            logger.info("ML model: metrics file unreadable")

    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            promoted = plan.get("promoted", False)
            wf = plan.get("walk_forward", {})
            logger.info(
                "Adaptation: promoted=%s sharpe_delta=%.3f symbols=%s",
                promoted,
                wf.get("sharpe_delta", 0),
                wf.get("symbol_count", 0),
            )
            if plan.get("blocked_reason"):
                logger.info("Adaptation blocked: %s", plan["blocked_reason"])
            if promoted:
                logger.info("New weights: %s", plan.get("new_weights"))
        except (json.JSONDecodeError, OSError):
            pass

    logger.info("Plan: data/adaptation_plan.json — restart engine to load promoted weights")


if __name__ == "__main__":
    main()
