#!/usr/bin/env bash
# Elite başarı formülü paper — port 8160, $800/saat hedef
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [[ ! -x "$PY" ]]; then
  echo "venv yok"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED

for pat in "elite_trader.scanner" "momentum_scanner" "dashboard.py"; do
  pids=$(pgrep -f "$pat" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
done
sleep 1

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_formula_800h.env
set +a

PORT="${DASHBOARD_PORT:-8160}"
export PAPER_DB_PATH="${PAPER_DB_PATH:-data/elite_formula.db}"
export DASHBOARD_PORT="$PORT"

echo "══════════════════════════════════════════════════════════"
echo " ELITE FORMULA — http://127.0.0.1:${PORT}"
echo "  Hedef: \$${ELITE_TARGET_HOURLY_USD}/saat (garanti değil)"
echo "  DB: ${PAPER_DB_PATH}"
echo "  İlk kurulum: ${PY} -m elite_trader.research"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f data/elite_success_formula.pkl ]]; then
  echo "  Formül yok — araştırma başlatılıyor..."
  "$PY" -m elite_trader.research
fi

"$PY" dashboard.py &
DPID=$!
trap 'kill $DPID 2>/dev/null || true' EXIT INT TERM
sleep 2
exec "$PY" -m elite_trader.scanner
