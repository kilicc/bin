#!/usr/bin/env bash
# Elite GLOBAL 2× — port 8180 (8160 / 8170 dokunulmaz)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8180
DB_SRC="data/elite_formula.db"
DB_G2X="data/elite_global_2x.db"

[[ -x "$PY" ]] || { echo "venv yok"; exit 1; }

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED
unset SCENARIO_LABEL SCENARIO_NAME ELITE_DECISION_MODE
unset ELITE_CAL_PRIMARY_STACK ELITE_VELOCITY_STACK PAPER_DB_PATH DASHBOARD_PORT

mkdir -p "$PID_DIR"
for pf in "$PID_DIR/elite_global_2x.dash.pid" "$PID_DIR/elite_global_2x.scanner.pid"; do
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

if [[ ! -f "$DB_G2X" ]] || [[ "${ELITE_G2X_REFRESH_DB:-0}" == "1" ]]; then
  [[ -f "$DB_SRC" ]] && cp "$DB_SRC" "$DB_G2X" && echo "  DB kopyalandı: $DB_SRC → $DB_G2X"
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_global_2x.env
set +a

export PAPER_DB_PATH="${PAPER_DB_PATH:-$DB_G2X}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-$PORT}"
export ELITE_GLOBAL_2X_STACK=1
export MAX_POSITION_USD="${MAX_POSITION_USD:-100000}"
export GAP_STAKE_CAP_80="${GAP_STAKE_CAP_80:-100000}"
export GAP_STAKE_CAP_70="${GAP_STAKE_CAP_70:-100000}"

_max_label="${ELITE_MAX_STAKE_USD}"
[[ "${ELITE_MAX_STAKE_USD:-0}" == "0" ]] && _max_label="sınırsız (WR ölçekli)"

echo "══════════════════════════════════════════════════════════"
echo " ELITE GLOBAL 2× — http://127.0.0.1:${DASHBOARD_PORT}"
echo "  Hedef: ${ELITE_TARGET_EQUITY_MULT}× / ${ELITE_TARGET_HOURS}h"
echo "  Stake: min \$${ELITE_MIN_STAKE_USD} max ${_max_label} | Aktif %${ELITE_ACTIVE_CAPITAL_PCT} | max açık ${ELITE_MAX_OPEN}"
echo "  DB: ${PAPER_DB_PATH}"
echo "  8160/8170 DOKUNULMAZ"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f data/elite_success_formula.pkl ]] || [[ "${ELITE_G2X_FORCE_RESEARCH:-0}" == "1" ]]; then
  echo "  Global elite araştırması (ilk kurulum ~5-15 dk)..."
  "$PY" -m elite_trader.research --global
fi

"$PY" dashboard.py &
echo $! >"$PID_DIR/elite_global_2x.dash.pid"
sleep 2
"$PY" -m elite_trader.scanner &
echo $! >"$PID_DIR/elite_global_2x.scanner.pid"
wait
