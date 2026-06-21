#!/usr/bin/env bash
# Between-round learning pipeline: ingest → regime library → adapt weights.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PHASE="${1:-round1}"
DATA_DIR="${2:-data/historical}"

echo "==> Phase: $PHASE"

if [[ -d "$DATA_DIR" ]] && ls "$DATA_DIR"/*.{parquet,csv} 1>/dev/null 2>&1; then
  echo "==> Ingesting historical data from $DATA_DIR"
  python3 scripts/ingest_historical.py --input "$DATA_DIR" --output data/historical
else
  echo "==> Skipping ingest (no files in $DATA_DIR)"
fi

if [[ -d data/historical ]]; then
  echo "==> Building regime library"
  python3 scripts/build_regime_library.py || echo "Regime library skipped"
fi

echo "==> Running round adaptation"
python3 scripts/adapt_round.py --phase "$PHASE"

echo "Done. Plan written to data/adaptation_plan.json"
