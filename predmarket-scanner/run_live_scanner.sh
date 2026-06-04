#!/usr/bin/env bash
# Gerçek CLOB emirleri — live.db; paper paneli ayrı terminalde kalsın.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -f live.scanner.env ]]; then
  echo "live.scanner.env bulunamadı"
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
# shellcheck disable=SC1091
source live.scanner.env
set +a

echo "LIVE CLOB | MAX_POSITION_USD=${MAX_POSITION_USD:-?} | MAX_OPEN=${MAX_OPEN_POSITIONS:-?} | DB=${LIVE_DB_PATH:-data/live.db}"
echo "Paper panel: ayrı terminalde ./run_paper_stack.sh veya dashboard.py"
echo "Tek örnek: ikinci ./run_live_scanner.sh başlamaz (data/polymarket_scanner.lock)."
exec "$PY" momentum_scanner.py
