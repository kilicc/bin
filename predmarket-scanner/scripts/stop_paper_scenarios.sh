#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PID_DIR="data/scenario_pids"

pkill -f "multi_paper_scanner.py" 2>/dev/null || true

if [[ -d "$PID_DIR" ]]; then
  for f in "$PID_DIR"/*.pid; do
    [[ -f "$f" ]] || continue
    pid=$(cat "$f" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  done
fi

for port in 8010 8020 8030; do
  if lsof -ti:"$port" >/dev/null 2>&1; then
    lsof -ti:"$port" | xargs kill 2>/dev/null || true
  fi
done

echo "Paper senaryoları durduruldu."
