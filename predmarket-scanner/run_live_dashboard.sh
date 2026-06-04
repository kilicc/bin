#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PORT="${LIVE_DASHBOARD_PORT:-8002}"
echo "Canlı panel: http://127.0.0.1:${PORT}/"
exec "$PY" -m uvicorn live_dashboard:app --host 0.0.0.0 --port "$PORT" --reload
