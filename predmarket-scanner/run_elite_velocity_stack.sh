#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8170
DB_SRC="data/elite_formula.db"
DB_VEL="data/elite_formula_velocity.db"

[[ -x "$PY" ]] || { echo "venv yok"; exit 1; }

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED
unset SCENARIO_LABEL SCENARIO_NAME ELITE_DECISION_MODE ELITE_CAL_PRIMARY_STACK
unset PAPER_DB_PATH DASHBOARD_PORT

mkdir -p "$PID_DIR"
for pf in "$PID_DIR/elite_velocity.dash.pid" "$PID_DIR/elite_velocity.scanner.pid"; do
  [[ -f "$pf" ]] || continue
  pid=$(cat "$pf" 2>/dev/null || true)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  rm -f "$pf"
done
if command -v lsof >/dev/null 2>&1; then
  pids=$(lsof -ti :"${PORT}" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
  sleep 1
fi
if [[ ! -f "$DB_VEL" ]] || [[ "${ELITE_VEL_REFRESH_DB:-0}" == "1" ]]; then
  [[ -f "$DB_SRC" ]] && cp "$DB_SRC" "$DB_VEL" && echo "  DB kopyalandı: $DB_SRC → $DB_VEL"
fi
set -a
source .env 2>/dev/null || true
source scenarios/elite_formula_velocity.env
set +a
export PAPER_DB_PATH="${PAPER_DB_PATH:-$DB_VEL}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-$PORT}"
export ELITE_VELOCITY_STACK=1
echo " ELITE VELOCITY — http://127.0.0.1:${DASHBOARD_PORT}"
echo "  stake \$${ELITE_MIN_STAKE_USD}-\$${ELITE_MAX_STAKE_USD} MAX_OPEN=${ELITE_MAX_OPEN}"
[[ -f data/elite_success_formula.pkl ]] || "$PY" -m elite_trader.research
"$PY" dashboard.py &
echo $! >"$PID_DIR/elite_velocity.dash.pid"
sleep 2
"$PY" -m elite_trader.scanner &
echo $! >"$PID_DIR/elite_velocity.scanner.pid"
wait
