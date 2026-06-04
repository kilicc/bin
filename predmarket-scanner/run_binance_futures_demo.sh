#!/usr/bin/env bash
# Binance Futures DEMO — port 8210 (8150–8190 elite stack dokunulmaz)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=8210

[[ -x "$PY" ]] || { echo "venv yok"; exit 1; }

mkdir -p "$PID_DIR" data
for pf in "$PID_DIR/binance_futures.dash.pid" "$PID_DIR/binance_futures.scanner.pid"; do
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

# macOS SSL: certifi CA bundle (CERTIFICATE_VERIFY_FAILED önlemi)
if cert="$("$PY" -c "import certifi; print(certifi.where())" 2>/dev/null)"; then
  export SSL_CERT_FILE="$cert"
  export REQUESTS_CA_BUNDLE="$cert"
fi

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/binance_futures_demo.env
set +a

if [[ ! -f "${BN_FUT_DB_PATH:-data/binance_futures_demo.db}" ]] || [[ "${BN_FUT_REFRESH_DB:-0}" == "1" ]]; then
  "$PY" -c "from pathlib import Path; from binance_futures_trader.db import init_db; init_db(Path('${BN_FUT_DB_PATH:-data/binance_futures_demo.db}')).close(); print('  DB:', '${BN_FUT_DB_PATH}')"
fi

echo "══════════════════════════════════════════════════════════"
echo " BINANCE FUTURES DEMO — http://127.0.0.1:${BN_FUT_DASHBOARD_PORT:-$PORT}"
echo "  Mod: ${BN_FUT_MODE:-paper} | Strateji: ${BN_FUT_STRATEGY_PROFILE:-standard}"
echo "  TP ${BN_FUT_TP_PCT:-0.03} / SL ${BN_FUT_SL_PCT:-0.05} | ${BN_FUT_CANDLE_INTERVAL:-15m} | Aktif %${BN_FUT_ACTIVE_CAPITAL_PCT:-0.5}"
echo "  Lev ${BN_FUT_LEVERAGE_MIN:-2}-${BN_FUT_LEVERAGE_MAX:-12}x | Margin ${BN_FUT_MARGIN_TYPE:-isolated} | Max açık ${BN_FUT_MAX_OPEN:-12}"
echo "  Stale TP ${BN_FUT_STALE_TP_MOVE_PCT:-0.02} | Runner ${BN_FUT_TIER_ROI_PCTS:-0.10,0.20,0.30}"
echo "  DB: ${BN_FUT_DB_PATH:-data/binance_futures_demo.db}"
echo "  Elite/Polymarket portları DOKUNULMAZ"
echo "══════════════════════════════════════════════════════════"

"$PY" -m binance_futures_trader.dashboard &
echo $! >"$PID_DIR/binance_futures.dash.pid"
sleep 2
"$PY" -m binance_futures_trader.scanner &
echo $! >"$PID_DIR/binance_futures.scanner.pid"
wait
