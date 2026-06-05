#!/usr/bin/env bash
# Elite CAL PRIMARY — port 8150 (8160 stack'e dokunmaz)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8150
DB_SRC="data/elite_formula.db"
DB_CAL="data/elite_formula_cal.db"

if [[ ! -x "$PY" ]]; then
  echo "venv yok"
  exit 1
fi

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED

mkdir -p "$PID_DIR"

# Sadece bu stack'in PID'leri (8160 tarayıcılarına dokunma)
for pf in "$PID_DIR/elite_cal_primary.dash.pid" "$PID_DIR/elite_cal_primary.scanner.pid"; do
  if [[ -f "$pf" ]]; then
    pid=$(cat "$pf" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pf"
  fi
done

if command -v lsof >/dev/null 2>&1; then
  pids=$(lsof -ti :"${PORT}" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  Port ${PORT} temizleniyor..."
    kill $pids 2>/dev/null || true
    sleep 1
  fi
fi

if [[ ! -f "$DB_CAL" ]] || [[ "${ELITE_CAL_REFRESH_DB:-0}" == "1" ]]; then
  if [[ -f "$DB_SRC" ]]; then
    cp "$DB_SRC" "$DB_CAL"
    echo "  DB kopyalandı: $DB_SRC → $DB_CAL"
  fi
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_formula_cal_primary.env
set +a

export PAPER_DB_PATH="${PAPER_DB_PATH:-$DB_CAL}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-$PORT}"
export ELITE_CAL_PRIMARY_STACK=1

echo "══════════════════════════════════════════════════════════"
echo " ELITE CAL PRIMARY — http://127.0.0.1:${DASHBOARD_PORT}"
echo "  Mod: kalibrasyon edge ana (Yol B), whale sadece stake"
echo "  DB: ${PAPER_DB_PATH}"
echo "  8160 DOKUNULMAZ"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f data/elite_success_formula.pkl ]]; then
  echo "  Formül yok — araştırma..."
  "$PY" -m elite_trader.research
fi

"$PY" dashboard.py &
echo $! >"$PID_DIR/elite_cal_primary.dash.pid"
sleep 2
"$PY" -m elite_trader.scanner &
echo $! >"$PID_DIR/elite_cal_primary.scanner.pid"
wait
