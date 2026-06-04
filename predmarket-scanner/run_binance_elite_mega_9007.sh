#!/usr/bin/env bash
# MEGA canlı emir — port 9007 (berserk2 yükünden ayrı process)
# Tercih: ./scripts/elite_9007_process_ctl.sh restart
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=9007
LOG="logs/binance_elite_mega_9007.log"
PID_FILE="$PID_DIR/binance_elite_mega_9007.pid"

[[ -x "$PY" ]] || { echo "venv yok: $PY"; exit 1; }
mkdir -p "$PID_DIR" logs

# shellcheck disable=SC1091
source scripts/elite_9007_process_ctl.sh
elite_9007_stop 0 || elite_9007_stop 1

if cert="$("$PY" -c "import certifi; print(certifi.where())" 2>/dev/null)"; then
  export SSL_CERT_FILE="$cert"
  export REQUESTS_CA_BUNDLE="$cert"
fi

unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy \
      SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy \
      GIT_HTTP_PROXY GIT_HTTPS_PROXY 2>/dev/null || true
export NO_PROXY="*"
export no_proxy="*"

set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
# shellcheck disable=SC1091
source scenarios/binance_elite_mega_9007.env
export BN_FUT_MODE=testnet
export BINANCE_FUTURES_TESTNET=1
export BINANCE_FUTURES_DEMO=1
export BINANCE_LIVE_ORDERS=0
export MEGA_LIVE_ORDERS=1
export MEGA_SIM_ENABLED=0
export MEGA_INSTANCE_ID=9007
export BINANCE_RECV_WINDOW="${BINANCE_RECV_WINDOW:-15000}"
set +a
export PYTHONUNBUFFERED=1

echo "══════════════════════════════════════════════════════════"
echo " MEGA CANLI DESK 9007 — http://127.0.0.1:${PORT}/paper"
echo "  Ayrı API (MEGA_9007_*) · demo-fapi canlı emir"
echo "══════════════════════════════════════════════════════════"

nohup "$PY" binance_elite_pro_9007.py >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"
sleep 3
new_pid=$(cat "$PID_FILE")
if ! kill -0 "$new_pid" 2>/dev/null; then
  echo "✗ MEGA bot başlamadı — log: $LOG" >&2
  tail -20 "$LOG" >&2 || true
  exit 1
fi
echo "✅ PID $new_pid | log: $LOG"
echo "   Panel: http://127.0.0.1:${PORT}/paper"
echo "   Durdur: ./scripts/elite_9007_process_ctl.sh stop"
