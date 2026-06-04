#!/usr/bin/env bash
# Elite 9005 MAINNET — GCP prod (fapi.binance.com)
# Tercih: ./scripts/elite_9005_mainnet_process_ctl.sh restart
set -euo pipefail
cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
PID_DIR=".pids"
PORT=9005
LOG="logs/binance_elite_9005_mainnet.log"
PID_FILE="$PID_DIR/binance_elite_9005_mainnet.pid"

[[ -x "$PY" ]] || { echo "venv yok: $PY"; exit 1; }
mkdir -p "$PID_DIR" logs

# shellcheck disable=SC1091
source scripts/elite_9005_mainnet_process_ctl.sh
elite_9005_mainnet_stop 0 || elite_9005_mainnet_stop 1

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
source scenarios/binance_elite_8300_9005_mainnet.env
export ELITE_MAINNET=1
export BINANCE_LIVE_ORDERS=1
export BINANCE_FUTURES_DEMO=0
export BINANCE_FUTURES_TESTNET=0
export BN_FUT_MODE=live
export ELITE_DEMO_ONLY_DATA=0
export ELITE_BIND_HOST="${ELITE_BIND_HOST:-127.0.0.1}"
set +a
export PYTHONUNBUFFERED=1

echo "══════════════════════════════════════════════════════════"
echo " ELITE 9005 MAINNET — http://${ELITE_BIND_HOST}:${PORT}"
echo "  REST: fapi.binance.com"
echo "  Stake min \$${ELITE_MIN_STAKE_USD} | max open ${ELITE_MAX_OPEN}"
echo "══════════════════════════════════════════════════════════"

nohup "$PY" binance_elite_pro_9005_mainnet.py >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"
sleep 3
new_pid=$(cat "$PID_FILE")
if ! kill -0 "$new_pid" 2>/dev/null; then
  echo "✗ Bot başlamadı — log: $LOG" >&2
  tail -20 "$LOG" >&2 || true
  exit 1
fi
echo "✅ PID $new_pid | log: $LOG"
