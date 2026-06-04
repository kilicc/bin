#!/usr/bin/env bash
# MEGA canlı emir — port 9006 (berserk2 yükünden ayrı process)
# Tercih: ./scripts/elite_9006_process_ctl.sh restart
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=9006
LOG="logs/binance_elite_mega_9006.log"
PID_FILE="$PID_DIR/binance_elite_mega_9006.pid"

[[ -x "$PY" ]] || { echo "venv yok: $PY"; exit 1; }
mkdir -p "$PID_DIR" logs

# shellcheck disable=SC1091
source scripts/elite_9006_process_ctl.sh
elite_9006_stop 0 || elite_9006_stop 1

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
source scenarios/binance_elite_mega_9006_mainnet.env
export BN_FUT_MODE=testnet
export BINANCE_FUTURES_TESTNET=1
export BINANCE_FUTURES_DEMO=1
export BINANCE_LIVE_ORDERS=0
export MEGA_LIVE_ORDERS=1
export BINANCE_RECV_WINDOW="${BINANCE_RECV_WINDOW:-15000}"
set +a
export PYTHONUNBUFFERED=1

echo "══════════════════════════════════════════════════════════"
echo " MEGA CANLI EMİR — http://127.0.0.1:${PORT}/paper"
echo "  Berserk2 scan → MEGA giriş | ayrı Binance hesabı"
echo "  REST: demo-fapi.binance.com (MEGA_BINANCE_* .env)"
echo "══════════════════════════════════════════════════════════"

nohup "$PY" binance_elite_pro_9006.py >>"$LOG" 2>&1 &
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
echo "   Durdur: ./scripts/elite_9006_process_ctl.sh stop"
