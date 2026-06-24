#!/usr/bin/env python3

"""Report between-round adaptation readiness — historical data, regime library, plan."""



from __future__ import annotations



import json

import sys

from pathlib import Path



import yaml



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from scripts.ingest_pricer_output import COMPETITION_SYMBOLS, pricer_symbol_to_stem

PRICER_STEMS = frozenset(pricer_symbol_to_stem(s) for s in COMPETITION_SYMBOLS)

HISTORICAL_DIR = ROOT / "data" / "historical"

REGIME_DIR = ROOT / "data" / "regime_library"

PLAN_PATH = ROOT / "data" / "adaptation_plan.json"

INSTRUMENTS = ROOT / "config" / "instruments.yaml"





def _count_data_files(directory: Path, extensions: tuple[str, ...]) -> tuple[int, list[str]]:

    if not directory.exists():

        return 0, []

    files = [p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in extensions]

    return len(files), sorted({p.stem for p in files})[:20]





def _expected_symbol_stems() -> list[str]:

    """Instrument stems expected from ingest (EUR/USD -> EUR_USD)."""

    if not INSTRUMENTS.exists():

        return []

    with open(INSTRUMENTS, encoding="utf-8") as f:

        cfg = yaml.safe_load(f) or {}

    stems = []

    for inst in cfg.get("instruments", []):

        sym = inst.get("symbol", "")

        if sym:

            stems.append(sym.replace("/", "_"))

    return sorted(stems)





def main() -> int:

    print("QuantAI adaptation readiness\n")



    hist_count, hist_symbols = _count_data_files(HISTORICAL_DIR, (".parquet", ".csv"))

    regime_count, _ = _count_data_files(REGIME_DIR, (".parquet", ".csv", ".json"))

    expected = _expected_symbol_stems()

    present = set(hist_symbols)

    missing = [s for s in expected if s not in present]

    covered = [s for s in expected if s in present]



    print(f"Historical data ({HISTORICAL_DIR})")

    if hist_count == 0:

        print("  [FAIL] No Parquet/CSV files — walk-forward adaptation will skip (promoted=false)")

        print("\n  Ingest steps:")

        print("    1. python scripts/ingest_pricer_output.py  # pricer tick data → M15 OHLCV")

        print("    2. python scripts/ingest_historical.py --input <dataset_dir> --output data/historical")

        print("    3. python scripts/build_regime_library.py   # optional but recommended")

        print("    4. python scripts/run_learning_pipeline.py    # full pipeline")

    else:

        print(f"  [PASS] {hist_count} file(s)" + (f" — sample: {', '.join(hist_symbols[:8])}" if hist_symbols else ""))

        if expected:

            print(f"  Symbol coverage vs instruments.yaml: {len(covered)}/{len(expected)}")

            if missing:

                print(f"  [WARN] Missing: {', '.join(missing[:12])}" + (" ..." if len(missing) > 12 else ""))

            else:

                print("  [PASS] All configured instruments have historical files")

        pricer_present = sorted(s for s in hist_symbols if s in PRICER_STEMS)
        if pricer_present:
            print(
                f"  Pricer-ingested symbols: {len(pricer_present)}/{len(PRICER_STEMS)}"
                f" — {', '.join(pricer_present[:8])}"
                + (" ..." if len(pricer_present) > 8 else "")
            )
            crypto_missing = [s for s in expected if s not in PRICER_STEMS and s not in present]
            if crypto_missing:
                print(f"  [info] No pricer data for crypto/other: {', '.join(crypto_missing[:8])}")



    print(f"\nRegime library ({REGIME_DIR})")

    if regime_count == 0:

        print("  [WARN] Empty — run scripts/build_regime_library.py after ingest")

    else:

        print(f"  [PASS] {regime_count} file(s)")



    print(f"\nAdaptation plan ({PLAN_PATH})")

    if PLAN_PATH.exists():

        try:

            plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

            promoted = plan.get("promoted", False)

            print(f"  [info] promoted={promoted}, round={plan.get('round', plan.get('phase', '?'))}")

            if promoted:

                print("  [info] Restart engine after promotion — weights load at startup only")

        except (json.JSONDecodeError, OSError) as exc:

            print(f"  [WARN] Could not read plan: {exc}")

    else:

        print("  [info] No plan yet — run adapt_round after historical ingest")



    print("\nBetween-round window (22:00–23:00 BST):")

    print("  python scripts/adapt_round.py")

    print("  # or dashboard POST /api/adaptation/run?confirm=true")



    ready = hist_count > 0

    print(f"\nOverall: {'READY' if ready else 'NOT READY — ingest historical data first'}")

    return 0 if ready else 1





if __name__ == "__main__":

    raise SystemExit(main())

