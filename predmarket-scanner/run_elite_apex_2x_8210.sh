#!/usr/bin/env bash
# Elite APEX 2×24H FRESH — port 8210 (sıfırdan başlangıç)
#   ./run_elite_apex_2x_8210.sh          → ön plan
#   ./run_elite_apex_2x_8210.sh --bg     → arka plan + logs/elite_apex_2x_8210.scanner.log
#   ./run_elite_apex_2x_8210.sh --fresh  → DB sıfırla + başlat
#   ./run_elite_apex_2x_8210.sh --stop   → durdur
#   ./run_elite_apex_2x_8210.sh --status → durum
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8210
DB_APEX="data/elite_apex_2x_24h_8210.db"
STATS_JSON="data/scan_stats_elite_apex_2x_24h_8210.json"
LOG_DASH="logs/elite_apex_2x_8210.dash.log"
LOG_SCAN="logs/elite_apex_2x_8210.scanner.log"
MODE="fg"
FRESH=0

for arg in "$@"; do
  case "$arg" in
    --bg|--background) MODE="bg" ;;
    --fresh) FRESH=1 ;;
    --stop)
      echo "  APEX 8210 durduruluyor..."
      for pf in "$PID_DIR/elite_apex_2x_8210.dash.pid" "$PID_DIR/elite_apex_2x_8210.scanner.pid"; do
        [[ -f "$pf" ]] || continue
        pid=$(cat "$pf" 2>/dev/null || true)
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f "$pf"
      done
      lsof -ti :"${PORT}" 2>/dev/null | xargs kill 2>/dev/null || true
      for pid in $(pgrep -f "elite_trader.scanner" 2>/dev/null || true); do
        lsof -p "$pid" 2>/dev/null | grep -q "elite_apex_2x_24h\.db" && kill "$pid" 2>/dev/null || true
      done
      echo "  Durduruldu."
      exit 0
      ;;
    --status)
      dash_pid=""; scan_pid=""
      [[ -f "$PID_DIR/elite_apex_2x_8210.dash.pid" ]] && dash_pid=$(cat "$PID_DIR/elite_apex_2x_8210.dash.pid")
      [[ -f "$PID_DIR/elite_apex_2x_8210.scanner.pid" ]] && scan_pid=$(cat "$PID_DIR/elite_apex_2x_8210.scanner.pid")
      http=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:${PORT}/" 2>/dev/null || echo "---")
      echo "  Panel :${PORT} HTTP ${http}"
      _alive() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null && echo '(çalışıyor)' || echo '(kapalı)'; }
      echo "  Dashboard PID: ${dash_pid:-yok} $(_alive "$dash_pid")"
      echo "  Scanner PID:   ${scan_pid:-yok} $(_alive "$scan_pid")"
      exit 0
      ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

[[ "${ELITE_APEX_REFRESH_DB:-0}" == "1" ]] && FRESH=1
[[ -x "$PY" ]] || { echo "venv yok: $PY"; exit 1; }

mkdir -p "$PID_DIR" logs

if [[ "$FRESH" -eq 0 ]] && [[ "$MODE" == "fg" ]] && lsof -ti :"${PORT}" >/dev/null 2>&1; then
  echo "  ⚠ Port ${PORT} zaten dinliyor."
  echo "  Yeniden başlat: $0 --stop && $0"
  echo "  Arka plan:      $0 --bg"
  exit 0
fi

for pf in "$PID_DIR/elite_apex_2x_8210.dash.pid" "$PID_DIR/elite_apex_2x_8210.scanner.pid"; do
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
for pid in $(pgrep -f "elite_trader.scanner" 2>/dev/null || true); do
  lsof -p "$pid" 2>/dev/null | grep -q "elite_apex_2x_24h\.db" && kill "$pid" 2>/dev/null || true
done
sleep 1

if [[ "$FRESH" -eq 1 ]] || [[ ! -f "$DB_APEX" ]]; then
  rm -f "$DB_APEX" "$STATS_JSON"
  "$PY" -c "from pathlib import Path; from elite_trader.db import init_db; init_db(Path('${DB_APEX}')).close()"
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/elite_apex_2x_24h.env
set +a

export PAPER_DB_PATH="$DB_APEX"
export DASHBOARD_PORT="$PORT"
export ELITE_APEX_2X_STACK=1
export PYTHONUNBUFFERED=1

_max_label="${ELITE_MAX_STAKE_USD}"
[[ "${ELITE_MAX_STAKE_USD:-0}" == "0" ]] && _max_label="WR ölçekli"

echo "══════════════════════════════════════════════════════════"
echo " 🆕 ELITE APEX 2×24H FRESH — http://127.0.0.1:${PORT}"
echo "  Stake: min \$${ELITE_MIN_STAKE_USD} max ${_max_label}"
echo "  DB: ${PAPER_DB_PATH}"
echo "  STATUS: SIFIRDAN BAŞLANGIÇ (Fresh Start)"
echo "══════════════════════════════════════════════════════════"

if [[ ! -f data/elite_success_formula.pkl ]] || [[ "${ELITE_APEX_FORCE_RESEARCH:-0}" == "1" ]]; then
  "$PY" -m elite_trader.research --global
fi

if [[ "$MODE" == "bg" ]]; then
  nohup "$PY" dashboard.py >>"$LOG_DASH" 2>&1 &
  echo $! >"$PID_DIR/elite_apex_2x_8210.dash.pid"
  sleep 2
  nohup "$PY" -m elite_trader.scanner >>"$LOG_SCAN" 2>&1 &
  echo $! >"$PID_DIR/elite_apex_2x_8210.scanner.pid"
  echo "  Arka plan — tail -f ${LOG_SCAN}"
  exit 0
fi

# 8160 ile aynı: panel arka planda, tarayıcı terminalde
"$PY" dashboard.py >>"$LOG_DASH" 2>&1 &
sleep 2
exec "$PY" -m elite_trader.scanner
