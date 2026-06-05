#!/usr/bin/env bash
# Sadece 8160 stack — 8150 (cal primary) ve diğer portlara dokunmaz
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PORT=8160

if [[ ! -x "$PY" ]]; then
  echo "venv yok"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED
unset SCENARIO_LABEL SCENARIO_NAME ELITE_DECISION_MODE ELITE_CAL_PRIMARY_STACK
unset PAPER_DB_PATH DASHBOARD_PORT

if command -v lsof >/dev/null 2>&1; then
  pids=$(lsof -ti :"${PORT}" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  Port ${PORT} temizleniyor..."
    kill $pids 2>/dev/null || true
    sleep 1
  fi
fi

# elite_formula.db kullanan tarayıcı (8150 cal DB kullanır)
for pid in $(pgrep -f "elite_trader.scanner" 2>/dev/null || true); do
  if lsof -p "$pid" 2>/dev/null | grep -q "elite_formula\.db"; then
    if ! lsof -p "$pid" 2>/dev/null | grep -q "elite_formula_cal\.db"; then
      kill "$pid" 2>/dev/null || true
    fi
  fi
done
sleep 1

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_formula_800h.env
set +a

export PAPER_DB_PATH="${PAPER_DB_PATH:-data/elite_formula.db}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-$PORT}"

echo "══════════════════════════════════════════════════════════"
echo " ELITE FORMULA 8160 — http://127.0.0.1:${DASHBOARD_PORT}"
echo "  Stake: \$${ELITE_MIN_STAKE_USD} – \$${ELITE_MAX_STAKE_USD} (4 basamak)"
echo "  DB: ${PAPER_DB_PATH}"
echo "══════════════════════════════════════════════════════════"

"$PY" dashboard.py &
DPID=$!
sleep 2
exec "$PY" -m elite_trader.scanner
