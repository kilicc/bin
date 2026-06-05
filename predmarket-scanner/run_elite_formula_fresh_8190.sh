#!/usr/bin/env bash
# Elite FORMULA 8160 klonu — port 8190, sıfır DB, $22k (8160/8170/8180 dokunulmaz)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8190
DB_FRESH="data/elite_formula_8190_fresh.db"
STATS_JSON="data/scan_stats_elite_formula_8190_fresh.json"

[[ -x "$PY" ]] || { echo "venv yok"; exit 1; }

unset POLYMARKET_LIVE_TRADING POLYMARKET_LIVE_CONFIRM POLYMARKET_LIVE_ARMED
unset SCENARIO_LABEL SCENARIO_NAME ELITE_DECISION_MODE
unset ELITE_CAL_PRIMARY_STACK ELITE_VELOCITY_STACK ELITE_GLOBAL_2X_STACK
unset PAPER_DB_PATH DASHBOARD_PORT

mkdir -p "$PID_DIR"
for pf in "$PID_DIR/elite_formula_8190_fresh.dash.pid" "$PID_DIR/elite_formula_8190_fresh.scanner.pid"; do
  [[ -f "$pf" ]] || continue
  pid=$(cat "$pf" 2>/dev/null || true)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && kill "$pid" 2>/dev/null || true
  rm -f "$pf"
done

if command -v lsof >/dev/null 2>&1; then
  pids=$(lsof -ti :"${PORT}" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  Port ${PORT} temizleniyor..."
    kill $pids 2>/dev/null || true
    sleep 1
  fi
fi

for pid in $(pgrep -f "elite_trader.scanner" 2>/dev/null || true); do
  if lsof -p "$pid" 2>/dev/null | grep -q "elite_formula_8190_fresh\.db"; then
    kill "$pid" 2>/dev/null || true
  fi
done
sleep 1

# DB korunur; yalnızca ELITE_8190_REFRESH_DB=1 ile sıfırlanır
if [[ "${ELITE_8190_REFRESH_DB:-0}" == "1" ]]; then
  BK_DIR="data/backups"
  mkdir -p "$BK_DIR"
  if [[ -f "$DB_FRESH" ]]; then
    cp "$DB_FRESH" "$BK_DIR/8190_manual_$(date -u +%Y%m%dT%H%M%SZ).db"
    echo "  Yedek alındı → $BK_DIR/"
  fi
  rm -f "$DB_FRESH" "$STATS_JSON"
  "$PY" -c "from pathlib import Path; from elite_trader.db import init_db; init_db(Path('${DB_FRESH}')).close(); print('  Sıfır DB:', '${DB_FRESH}')"
elif [[ ! -f "$DB_FRESH" ]]; then
  "$PY" -c "from pathlib import Path; from elite_trader.db import init_db; init_db(Path('${DB_FRESH}')).close(); print('  Yeni DB:', '${DB_FRESH}')"
else
  echo "  DB korunuyor: ${DB_FRESH}"
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_formula_8190_fresh.env
set +a

export PAPER_DB_PATH="${PAPER_DB_PATH:-$DB_FRESH}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-$PORT}"

echo "══════════════════════════════════════════════════════════"
echo " ELITE FORMULA FRESH — http://127.0.0.1:${DASHBOARD_PORT}"
echo "  8160 ile aynı ayarlar | Başlangıç: \$${STARTING_BALANCE}"
echo "  Stake: \$${ELITE_MIN_STAKE_USD} – \$${ELITE_MAX_STAKE_USD}"
if [[ "${ELITE_8190_REFRESH_DB:-0}" == "1" ]]; then
  echo "  DB: ${PAPER_DB_PATH} (sıfır — REFRESH)"
else
  echo "  DB: ${PAPER_DB_PATH} (geçmiş korunur)"
fi
echo "  8160/8170/8180 DOKUNULMAZ"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f data/elite_success_formula.pkl ]]; then
  echo "  Formül yok — araştırma başlatılıyor..."
  "$PY" -m elite_trader.research
fi

"$PY" dashboard.py &
echo $! >"$PID_DIR/elite_formula_8190_fresh.dash.pid"
sleep 2
"$PY" -m elite_trader.scanner &
echo $! >"$PID_DIR/elite_formula_8190_fresh.scanner.pid"
wait
