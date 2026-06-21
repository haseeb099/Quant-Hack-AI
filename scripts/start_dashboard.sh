#!/usr/bin/env bash
# Start QuantAI dashboard (API + built React UI) on port 8080.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [[ ! -d frontend/dist ]] || [[ "${1:-}" == "--build" ]]; then
  echo "Building frontend..."
  (cd frontend && npm install && npm run build)
fi

if [[ ! -f data/runtime_state.json ]]; then
  python3 -c "from src.web.runtime_state import default_state, write_state; write_state(default_state())"
  echo "Seeded default runtime state"
fi

PORT="${DASHBOARD_PORT:-8080}"
echo "Starting QuantAI dashboard on http://0.0.0.0:${PORT}"
exec python3 -c "from src.web.dashboard import run_dashboard; run_dashboard(host='0.0.0.0', port=${PORT})"
