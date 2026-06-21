#!/usr/bin/env bash
# Smoke-test dashboard Docker image: build (optional), run health checks.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="${QUANTAI_DASHBOARD_IMAGE:-quantai-dashboard}"
PORT="${SMOKE_PORT:-8080}"
BUILD="${SMOKE_BUILD:-1}"

if [[ "$BUILD" == "1" ]]; then
  echo "Building ${IMAGE} from Dockerfile.dashboard..."
  docker build -f Dockerfile.dashboard -t "$IMAGE" .
fi

mkdir -p data logs
if [[ ! -f data/runtime_state.json ]]; then
  python3 -c "from src.web.runtime_state import default_state, write_state; write_state(default_state())"
fi

CONTAINER="quantai-smoke-$$"
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Starting container on port ${PORT}..."
docker run -d --name "$CONTAINER" \
  -p "${PORT}:8080" \
  -v "${ROOT}/logs:/app/logs" \
  -v "${ROOT}/data:/app/data" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done

echo "GET /health"
curl -sf "http://127.0.0.1:${PORT}/health" | python3 -m json.tool

echo "GET /api/status"
curl -sf "http://127.0.0.1:${PORT}/api/status" | python3 -m json.tool | head -20

echo "GET /api/operator/runbook"
curl -sf "http://127.0.0.1:${PORT}/api/operator/runbook" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('phases:', len(d.get('phases', [])))
print('preflight:', d.get('preflight', {}).get('passed'), '/', d.get('preflight', {}).get('total'))
"

echo "Smoke test passed."
