#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/stop_paper_scenarios.sh 2>/dev/null || true
for port in 8000 8040 8050; do
  lsof -ti:"$port" 2>/dev/null | xargs kill 2>/dev/null || true
done
pkill -f "momentum_scanner.py" 2>/dev/null || true
pkill -f "multi_paper_scanner.py" 2>/dev/null || true
echo "Tüm INSANE paper süreçleri durduruldu."
