#!/usr/bin/env bash
# Binance Futures DEMO — port 9100 (8210 elite ile çakışmaz)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=9100

[[ -x "$PY" ]] || { echo "venv yok"; exit 1; }

mkdir -p "$PID_DIR" data logs
for pf in "$PID_DIR/binance_futures_9100.dash.pid" "$PID_DIR/binance_futures_9100.scanner.pid"; do
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

if cert="$("$PY" -c "import certifi; print(certifi.where())" 2>/dev/null)"; then
  export SSL_CERT_FILE="$cert"
  export REQUESTS_CA_BUNDLE="$cert"
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/binance_futures_demo.env
export BN_FUT_DASHBOARD_PORT="${PORT}"
set +a

DB_FILE="${BN_FUT_DB_PATH:-data/binance_futures_demo.db}"
if [[ "${BN_FUT_FRESH_START:-0}" == "1" ]] && [[ -f "$DB_FILE" ]]; then
  rm -f "$DB_FILE" "${DB_FILE}-wal" "${DB_FILE}-shm" 2>/dev/null || true
  echo "  🆕 DB sıfırlandı: $DB_FILE"
fi
rm -f data/binance_futures.lock 2>/dev/null || true
"$PY" -c "from pathlib import Path; from binance_futures_trader.db import init_db; init_db(Path('$DB_FILE')).close(); print('  DB hazır:', '$DB_FILE')"

echo "══════════════════════════════════════════════════════════"
echo " BINANCE FUTURES DEMO — http://127.0.0.1:${BN_FUT_DASHBOARD_PORT}"
echo "  Mod: ${BN_FUT_MODE:-paper} | Strateji: ${BN_FUT_STRATEGY_PROFILE:-standard}"
echo "  DB: ${BN_FUT_DB_PATH:-data/binance_futures_demo.db}"
echo "══════════════════════════════════════════════════════════"

export PYTHONUNBUFFERED=1
nohup "$PY" -m binance_futures_trader.dashboard >"logs/binance_futures_9100.dash.log" 2>&1 &
echo $! >"$PID_DIR/binance_futures_9100.dash.pid"
sleep 2
nohup "$PY" -m binance_futures_trader.scanner >"logs/binance_futures_9100.scanner.log" 2>&1 &
echo $! >"$PID_DIR/binance_futures_9100.scanner.pid"
echo "✅ Dashboard PID $(cat "$PID_DIR/binance_futures_9100.dash.pid")"
echo "✅ Scanner PID $(cat "$PID_DIR/binance_futures_9100.scanner.pid")"
echo "   Panel: http://127.0.0.1:${BN_FUT_DASHBOARD_PORT}"
